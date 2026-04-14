"""Investigation orchestrator — full investigation workflow.

Implements the three-mode investigation engine (spec Section 8.6):
1. Scheduled broad sweep (2-3x daily)
2. Trigger-based single candidate (immediate on Level C)
3. Operator-forced (manual)

Candidate volume constraint: 0-3 per run (0 is correct most of the time).

Investigation sequence:
1. Receive trigger or scheduled scope
2. Pre-run cost estimate → Cost Governor approval
3. Fetch candidates from eligible pool
4. Rank by trigger urgency and fit profile
5. Filter by edge discovery focus (deprioritize heavily covered markets)
6. Assign domain manager for top candidates only
7. Run compact sub-agent pack (5 default agents)
8. Build structured domain memo
9. Adversarial synthesis (Orchestration Agent — Opus)
10. Attach base-rate comparison and deviation
11. Compute entry impact estimate
12. Compute net edge after friction AND impact
13. Decide no-trade vs. surviving candidate
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import structlog

from agents.base import BaseAgent
from agents.escalation import EscalationPolicyEngine, EscalationRequest
from agents.providers import ProviderRouter
from agents.prompts import PromptManager
from agents.regime import RegimeAdapter
from agents.types import AgentInput, AgentResult, RegimeContext
from core.enums import CostClass, ModelTier
from cost.types import (
    AgentCostSpec,
    CostApproval,
    CostEstimateRequest,
    RunType,
)
from investigation.base_rate import BaseRateSystem
from investigation.domain_managers import get_domain_manager_class
from investigation.entry_impact import EntryImpactCalculator
from investigation.research_agents import (
    CounterCaseAgent,
    DataCrossCheckAgent,
    EvidenceResearchAgent,
    MarketStructureAgent,
    ResolutionReviewAgent,
    SentimentDriftAgent,
    SourceReliabilityAgent,
    TimingCatalystAgent,
)
from investigation.rubric import (
    CandidateRubric,
    MIN_COMPOSITE_FOR_ACCEPTANCE,
    MIN_COMPOSITE_FOR_OPUS,
)
from investigation.thesis_builder import ThesisCardBuilder
from investigation.types import (
    BaseRateResult,
    CandidateContext,
    DomainMemo,
    EntryImpactResult,
    EvidenceItem,
    InvestigationMode,
    InvestigationOutcome,
    InvestigationRequest,
    InvestigationResult,
    NetEdgeCalculation,
    NoTradeResult,
    ResearchPackResult,
    ThesisCardData,
)
from market_data.types import OrderBookLevel

_log = structlog.get_logger(component="investigation_orchestrator")


class InvestigationOrchestrator:
    """Orchestrates the full investigation workflow.

    Three modes: scheduled sweep, trigger-based, operator-forced.
    Each run evaluates 0-3 candidates and produces thesis cards
    or structured no-trade decisions.

    Usage:
        orchestrator = InvestigationOrchestrator(
            router=router,
            cost_governor=cost_governor,
            regime_adapter=regime_adapter,
        )
        result = await orchestrator.run(request)
    """

    def __init__(
        self,
        *,
        router: ProviderRouter,
        cost_governor: Any = None,
        regime_adapter: RegimeAdapter | None = None,
        prompt_manager: PromptManager | None = None,
        escalation_engine: EscalationPolicyEngine | None = None,
        base_rate_system: BaseRateSystem | None = None,
        entry_impact_calculator: EntryImpactCalculator | None = None,
        rubric: CandidateRubric | None = None,
        thesis_builder: ThesisCardBuilder | None = None,
        min_net_edge: float = 0.02,
        max_entry_impact_edge_fraction: float = 0.25,
    ) -> None:
        self._router = router
        self._cost_governor = cost_governor
        self._regime_adapter = regime_adapter or RegimeAdapter()
        self._prompt_manager = prompt_manager or PromptManager()
        self._escalation_engine = escalation_engine or EscalationPolicyEngine()
        self._base_rate = base_rate_system or BaseRateSystem()
        self._impact_calc = entry_impact_calculator or EntryImpactCalculator()
        self._rubric = rubric or CandidateRubric()
        self._thesis_builder = thesis_builder or ThesisCardBuilder()
        self._min_net_edge = min_net_edge
        self._max_impact_fraction = max_entry_impact_edge_fraction

    async def run(
        self,
        request: InvestigationRequest,
        *,
        regime: RegimeContext | None = None,
        ask_levels_by_market: dict[str, list[OrderBookLevel]] | None = None,
    ) -> InvestigationResult:
        """Execute the full investigation workflow.

        Args:
            request: Investigation request with candidates and mode.
            regime: Regime context for agent behavior.
            ask_levels_by_market: Order book data per market for impact calc.

        Returns:
            InvestigationResult with thesis cards and/or no-trade records.
        """
        started_at = datetime.now(tz=UTC)
        models_used: set[str] = set()
        max_tier = "D"

        _log.info(
            "investigation_started",
            workflow_run_id=request.workflow_run_id,
            mode=request.mode.value,
            candidate_count=len(request.candidates),
            max_candidates=request.max_candidates,
        )

        result = InvestigationResult(
            workflow_run_id=request.workflow_run_id,
            mode=request.mode,
            outcome=InvestigationOutcome.NO_TRADE,
            started_at=started_at,
        )

        # --- Step 1: Pre-run cost estimate → Cost Governor approval ---
        cost_approval = await self._get_cost_approval(request)
        if cost_approval is not None and not cost_approval.is_approved:
            result.outcome = InvestigationOutcome.COST_REJECTED
            result.no_trade_results.append(NoTradeResult(
                reason=f"Cost Governor rejected: {cost_approval.reason}",
                reason_code="cost_governor_rejected",
                stage="pre_run_cost_check",
            ))
            result.completed_at = datetime.now(tz=UTC)
            _log.info(
                "investigation_cost_rejected",
                workflow_run_id=request.workflow_run_id,
                reason=cost_approval.reason,
            )
            return result

        # Determine max tier allowed by cost approval
        max_approved_tier = ModelTier.A
        if cost_approval and cost_approval.approved_max_tier:
            max_approved_tier = cost_approval.approved_max_tier

        # --- Step 2: Rank and limit candidates ---
        candidates = self._rank_candidates(request.candidates)
        candidates = candidates[: request.max_candidates]

        if not candidates:
            result.outcome = InvestigationOutcome.NO_TRADE
            result.no_trade_results.append(NoTradeResult(
                reason="No candidates available for investigation",
                reason_code="no_candidates",
                stage="candidate_selection",
            ))
            result.completed_at = datetime.now(tz=UTC)
            return result

        result.candidates_evaluated = len(candidates)

        # --- Step 3: Investigate each candidate ---
        for candidate in candidates:
            try:
                thesis_card = await self._investigate_candidate(
                    candidate=candidate,
                    regime=regime,
                    max_approved_tier=max_approved_tier,
                    cost_approval=cost_approval,
                    ask_levels=(ask_levels_by_market or {}).get(candidate.market_id, []),
                    models_used=models_used,
                    agent_costs=result.agent_costs,
                )

                if thesis_card is not None:
                    result.thesis_cards.append(thesis_card)
                else:
                    result.no_trade_results.append(NoTradeResult(
                        market_id=candidate.market_id,
                        reason="Candidate did not survive investigation",
                        reason_code="investigation_rejected",
                        stage="investigation_complete",
                    ))

            except Exception as exc:
                _log.error(
                    "candidate_investigation_failed",
                    market_id=candidate.market_id,
                    error=str(exc),
                )
                result.no_trade_results.append(NoTradeResult(
                    market_id=candidate.market_id,
                    reason=f"Investigation error: {str(exc)}",
                    reason_code="investigation_error",
                    stage="investigation_execution",
                ))

        # --- Finalize result ---
        if result.thesis_cards:
            result.outcome = InvestigationOutcome.CANDIDATE_ACCEPTED
            result.candidates_accepted = len(result.thesis_cards)

        result.actual_cost_usd = round(sum(result.agent_costs.values()), 6)
        result.models_used = sorted(models_used)
        result.max_tier_used = max_tier
        result.completed_at = datetime.now(tz=UTC)

        _log.info(
            "investigation_completed",
            workflow_run_id=request.workflow_run_id,
            outcome=result.outcome.value,
            candidates_evaluated=result.candidates_evaluated,
            candidates_accepted=result.candidates_accepted,
            no_trade_count=len(result.no_trade_results),
            actual_cost_usd=result.actual_cost_usd,
        )

        return result

    # --- Candidate investigation pipeline ---

    async def _investigate_candidate(
        self,
        *,
        candidate: CandidateContext,
        regime: RegimeContext | None,
        max_approved_tier: ModelTier,
        cost_approval: CostApproval | None,
        ask_levels: list[OrderBookLevel],
        models_used: set[str],
        agent_costs: dict[str, float],
    ) -> ThesisCardData | None:
        """Run the full investigation pipeline for a single candidate.

        Returns ThesisCardData if the candidate survives, None for no-trade.
        """
        workflow_run_id = f"inv-{candidate.market_id}-{uuid.uuid4().hex[:8]}"

        _log.info(
            "candidate_investigation_started",
            market_id=candidate.market_id,
            category=candidate.category,
            trigger_class=candidate.trigger_class,
        )

        # --- Step 4: Assign domain manager ---
        domain_memo, domain_role, domain_cost = await self._run_domain_manager(
            candidate, regime, workflow_run_id, models_used,
        )
        agent_costs[domain_role] = agent_costs.get(domain_role, 0.0) + domain_cost

        if domain_memo is None or not domain_memo.recommended_proceed:
            _log.info(
                "candidate_rejected_by_domain_manager",
                market_id=candidate.market_id,
                reason="Domain manager did not recommend proceeding",
            )
            return None

        # --- Step 5: Run research pack (5 default agents) ---
        research = await self._run_research_pack(
            candidate, domain_memo, regime, workflow_run_id, models_used,
        )

        # --- Step 6: Run optional sub-agents (if justified by domain manager) ---
        if domain_memo.optional_agents_justified:
            await self._run_optional_agents(
                candidate, domain_memo, research, regime, workflow_run_id, models_used,
            )

        # Merge all per-agent costs (pack + optional) into the run-level accumulator
        for role, cost in research.per_agent_costs.items():
            agent_costs[role] = agent_costs.get(role, 0.0) + cost

        # --- Step 7: Compute entry impact (Tier D) ---
        entry_impact = self._impact_calc.compute(
            ask_levels=ask_levels,
            order_size_usd=candidate.visible_depth_usd * 0.12,
        )

        # --- Step 8: Base-rate lookup (Tier D) ---
        subcategory = self._base_rate.infer_subcategory(
            candidate.title, candidate.category,
        )
        base_rate = self._base_rate.lookup(
            candidate.category, subcategory,
        )

        # --- Step 9: Score candidate with rubric (Tier D) ---
        # Compute preliminary gross edge from market implied probability
        market_implied = candidate.mid_price or candidate.price or 0.5
        # Use domain memo confidence to estimate probability
        domain_prob = self._estimate_probability_from_domain(domain_memo, market_implied)
        gross_edge = abs(domain_prob - market_implied)

        # Update base rate with system estimate
        base_rate = self._base_rate.lookup(
            candidate.category, subcategory, system_estimate=domain_prob,
        )

        rubric_score = self._rubric.score(
            candidate=candidate,
            domain_memo=domain_memo,
            research=research,
            entry_impact=entry_impact,
            base_rate=base_rate,
            gross_edge=gross_edge,
            market_implied_probability=market_implied,
        )

        # --- Step 10: Check rubric threshold ---
        if rubric_score.composite_score < MIN_COMPOSITE_FOR_ACCEPTANCE:
            _log.info(
                "candidate_rejected_by_rubric",
                market_id=candidate.market_id,
                composite_score=rubric_score.composite_score,
                threshold=MIN_COMPOSITE_FOR_ACCEPTANCE,
            )
            return None

        # --- Step 11: Compute net edge (Tier D) ---
        spread_friction = candidate.spread or 0.0
        slippage_fraction = entry_impact.estimated_impact_bps / 10_000
        inference_cost_as_edge = (research.total_research_cost_usd / 100) if gross_edge > 0 else 0.0

        net_edge = NetEdgeCalculation(
            gross_edge=round(gross_edge, 6),
            friction_adjusted_edge=round(gross_edge - spread_friction / 2, 6),
            impact_adjusted_edge=round(gross_edge - spread_friction / 2 - slippage_fraction, 6),
            net_edge_after_cost=round(
                gross_edge - spread_friction / 2 - slippage_fraction - inference_cost_as_edge, 6
            ),
        )

        # Check: positive gross edge but non-viable impact-adjusted edge
        if not net_edge.is_viable:
            _log.info(
                "candidate_rejected_negative_net_edge",
                market_id=candidate.market_id,
                gross_edge=net_edge.gross_edge,
                impact_adjusted_edge=net_edge.impact_adjusted_edge,
            )
            return None

        # --- Step 12: Entry impact check (25% of gross edge max) ---
        if gross_edge > 0:
            impact_fraction = self._impact_calc.impact_as_edge_fraction(
                entry_impact.estimated_impact_bps, gross_edge,
            )
            if impact_fraction > self._max_impact_fraction:
                _log.info(
                    "candidate_rejected_excessive_impact",
                    market_id=candidate.market_id,
                    impact_fraction=impact_fraction,
                    max_fraction=self._max_impact_fraction,
                )
                return None

        # --- Step 13: Adversarial synthesis (Opus, if qualified) ---
        orchestrator_output, synthesis_cost = await self._run_orchestrator_synthesis(
            candidate=candidate,
            domain_memo=domain_memo,
            research=research,
            entry_impact=entry_impact,
            base_rate=base_rate,
            rubric_score=rubric_score,
            net_edge=net_edge,
            regime=regime,
            max_approved_tier=max_approved_tier,
            cost_approval=cost_approval,
            workflow_run_id=workflow_run_id,
            models_used=models_used,
        )
        agent_costs["investigator_orchestration"] = agent_costs.get("investigator_orchestration", 0.0) + synthesis_cost

        if orchestrator_output is None:
            return None

        # Check if orchestrator decided no-trade
        if orchestrator_output.get("decision") == "no_trade":
            _log.info(
                "candidate_rejected_by_orchestrator",
                market_id=candidate.market_id,
                reason=orchestrator_output.get("no_trade_reason", ""),
            )
            return None

        # --- Step 14: Build thesis card ---
        card = self._thesis_builder.build(
            candidate=candidate,
            domain_memo=domain_memo,
            research=research,
            entry_impact=entry_impact,
            base_rate=base_rate,
            rubric=rubric_score,
            net_edge=net_edge,
            orchestrator_output=orchestrator_output,
            workflow_run_id=workflow_run_id,
            inference_cost_usd=research.total_research_cost_usd,
        )

        return card

    # --- Sub-component runners ---

    async def _run_domain_manager(
        self,
        candidate: CandidateContext,
        regime: RegimeContext | None,
        workflow_run_id: str,
        models_used: set[str],
    ) -> tuple[DomainMemo | None, str, float]:
        """Run the appropriate domain manager for the candidate's category.

        Returns (memo, role_name, cost_usd).
        """
        manager_class = get_domain_manager_class(candidate.category)
        if manager_class is None:
            _log.warning(
                "no_domain_manager_for_category",
                category=candidate.category,
            )
            return None, "domain_manager_unknown", 0.0

        manager = manager_class(
            router=self._router,
            prompt_manager=self._prompt_manager,
        )

        agent_input = AgentInput(
            workflow_run_id=workflow_run_id,
            market_id=candidate.market_id,
            agent_role=manager.role_name,
            context={"candidate": candidate.model_dump(mode="json")},
        )

        result = await manager.run(agent_input, regime=regime)
        models_used.add(self._router.model_for_tier(ModelTier.B))
        cost = result.total_cost_usd if result.success else 0.0

        if result.success and result.result:
            return DomainMemo(**result.result), manager.role_name, cost
        return None, manager.role_name, cost

    async def _run_research_pack(
        self,
        candidate: CandidateContext,
        domain_memo: DomainMemo,
        regime: RegimeContext | None,
        workflow_run_id: str,
        models_used: set[str],
    ) -> ResearchPackResult:
        """Run the five default research agents."""
        candidate_data = candidate.model_dump(mode="json")
        memo_data = domain_memo.model_dump(mode="json")

        base_context: dict[str, Any] = {
            "candidate": candidate_data,
            "domain_memo": memo_data,
        }

        pack = ResearchPackResult()

        # 1. Evidence Research (Tier C)
        evidence_agent = EvidenceResearchAgent(
            router=self._router,
            prompt_manager=self._prompt_manager,
        )
        evidence_input = AgentInput(
            workflow_run_id=workflow_run_id,
            market_id=candidate.market_id,
            agent_role="evidence_research",
            context=base_context,
        )
        evidence_result = await evidence_agent.run(evidence_input, regime=regime)
        models_used.add(self._router.model_for_tier(ModelTier.C))

        if evidence_result.success:
            raw_items = evidence_result.result.get("evidence", [])
            pack.evidence = [
                EvidenceItem(**item) if isinstance(item, dict) else item
                for item in raw_items
            ]
            pack.total_research_cost_usd += evidence_result.total_cost_usd
        pack.per_agent_costs["evidence_research"] = pack.per_agent_costs.get("evidence_research", 0.0) + evidence_result.total_cost_usd
        pack.agents_invoked.append("evidence_research")

        # Update context with evidence
        evidence_data = [e.model_dump() for e in pack.evidence] if pack.evidence else []
        ctx_with_evidence = {**base_context, "evidence": evidence_data}

        # 2. Counter-Case Agent (Tier B)
        counter_agent = CounterCaseAgent(
            router=self._router,
            prompt_manager=self._prompt_manager,
        )
        counter_input = AgentInput(
            workflow_run_id=workflow_run_id,
            market_id=candidate.market_id,
            agent_role="counter_case",
            context=ctx_with_evidence,
        )
        counter_result = await counter_agent.run(counter_input, regime=regime)
        models_used.add(self._router.model_for_tier(ModelTier.B))

        if counter_result.success:
            pack.counter_case = counter_result.result
            pack.total_research_cost_usd += counter_result.total_cost_usd
        pack.per_agent_costs["counter_case"] = pack.per_agent_costs.get("counter_case", 0.0) + counter_result.total_cost_usd
        pack.agents_invoked.append("counter_case")

        # 3. Resolution Review Agent (Tier B)
        resolution_agent = ResolutionReviewAgent(
            router=self._router,
            prompt_manager=self._prompt_manager,
        )
        resolution_input = AgentInput(
            workflow_run_id=workflow_run_id,
            market_id=candidate.market_id,
            agent_role="resolution_review",
            context=base_context,
        )
        resolution_result = await resolution_agent.run(resolution_input, regime=regime)

        if resolution_result.success:
            pack.resolution_review = resolution_result.result
            pack.total_research_cost_usd += resolution_result.total_cost_usd
        pack.per_agent_costs["resolution_review"] = pack.per_agent_costs.get("resolution_review", 0.0) + resolution_result.total_cost_usd
        pack.agents_invoked.append("resolution_review")

        # 4. Timing/Catalyst Agent (Tier C)
        timing_agent = TimingCatalystAgent(
            router=self._router,
            prompt_manager=self._prompt_manager,
        )
        timing_input = AgentInput(
            workflow_run_id=workflow_run_id,
            market_id=candidate.market_id,
            agent_role="timing_catalyst",
            context=base_context,
        )
        timing_result = await timing_agent.run(timing_input, regime=regime)

        if timing_result.success:
            pack.timing_assessment = timing_result.result
            pack.total_research_cost_usd += timing_result.total_cost_usd
        pack.per_agent_costs["timing_catalyst"] = pack.per_agent_costs.get("timing_catalyst", 0.0) + timing_result.total_cost_usd
        pack.agents_invoked.append("timing_catalyst")

        # 5. Market Structure Agent (Tier D metrics + Tier C summary)
        structure_agent = MarketStructureAgent(
            router=self._router,
            prompt_manager=self._prompt_manager,
        )
        structure_input = AgentInput(
            workflow_run_id=workflow_run_id,
            market_id=candidate.market_id,
            agent_role="market_structure_summary",
            context=base_context,
        )
        structure_result = await structure_agent.run(structure_input, regime=regime)

        if structure_result.success:
            pack.market_structure = structure_result.result
            pack.total_research_cost_usd += structure_result.total_cost_usd
        pack.per_agent_costs["market_structure_summary"] = pack.per_agent_costs.get("market_structure_summary", 0.0) + structure_result.total_cost_usd
        pack.agents_invoked.append("market_structure_summary")

        _log.info(
            "research_pack_completed",
            market_id=candidate.market_id,
            agents=pack.agents_invoked,
            evidence_count=len(pack.evidence),
            total_cost=pack.total_research_cost_usd,
        )

        return pack

    async def _run_optional_agents(
        self,
        candidate: CandidateContext,
        domain_memo: DomainMemo,
        research: ResearchPackResult,
        regime: RegimeContext | None,
        workflow_run_id: str,
        models_used: set[str],
    ) -> None:
        """Run optional sub-agents when domain manager justifies cost.

        Requires: domain manager provides written justification,
        Cost Governor approves additional cost within run budget.
        """
        justified = set(domain_memo.optional_agents_justified)
        evidence_data = [e.model_dump() for e in research.evidence]

        context: dict[str, Any] = {
            "candidate": candidate.model_dump(mode="json"),
            "evidence": evidence_data,
        }

        if "data_cross_check" in justified:
            agent = DataCrossCheckAgent(
                router=self._router,
                prompt_manager=self._prompt_manager,
            )
            agent_input = AgentInput(
                workflow_run_id=workflow_run_id,
                market_id=candidate.market_id,
                context=context,
            )
            result = await agent.run(agent_input, regime=regime)
            if result.success:
                research.data_cross_check = result.result
                research.total_research_cost_usd += result.total_cost_usd
            research.per_agent_costs["data_cross_check"] = research.per_agent_costs.get("data_cross_check", 0.0) + result.total_cost_usd
            research.agents_invoked.append("data_cross_check")

        if "sentiment_drift" in justified:
            agent = SentimentDriftAgent(
                router=self._router,
                prompt_manager=self._prompt_manager,
            )
            agent_input = AgentInput(
                workflow_run_id=workflow_run_id,
                market_id=candidate.market_id,
                context=context,
            )
            result = await agent.run(agent_input, regime=regime)
            if result.success:
                research.sentiment_drift = result.result
                research.total_research_cost_usd += result.total_cost_usd
            research.per_agent_costs["sentiment_drift"] = research.per_agent_costs.get("sentiment_drift", 0.0) + result.total_cost_usd
            research.agents_invoked.append("sentiment_drift")

        if "source_reliability" in justified:
            agent = SourceReliabilityAgent(
                router=self._router,
                prompt_manager=self._prompt_manager,
            )
            agent_input = AgentInput(
                workflow_run_id=workflow_run_id,
                market_id=candidate.market_id,
                context=context,
            )
            result = await agent.run(agent_input, regime=regime)
            if result.success:
                research.source_reliability = result.result
                research.total_research_cost_usd += result.total_cost_usd
            research.per_agent_costs["source_reliability"] = research.per_agent_costs.get("source_reliability", 0.0) + result.total_cost_usd
            research.agents_invoked.append("source_reliability")

    async def _run_orchestrator_synthesis(
        self,
        *,
        candidate: CandidateContext,
        domain_memo: DomainMemo,
        research: ResearchPackResult,
        entry_impact: EntryImpactResult,
        base_rate: BaseRateResult,
        rubric_score: CandidateRubricScore,
        net_edge: NetEdgeCalculation,
        regime: RegimeContext | None,
        max_approved_tier: ModelTier,
        cost_approval: CostApproval | None,
        workflow_run_id: str,
        models_used: set[str],
    ) -> tuple[dict[str, Any] | None, float]:
        """Run the Investigator Orchestration Agent (Tier A or B fallback).

        Uses Opus only when all escalation conditions are met.
        Falls back to Tier B (Sonnet) when Opus is not justified.
        Returns (output_dict, cost_usd).
        """
        # Determine tier: Opus if qualified, else Sonnet
        use_opus = False
        if (
            max_approved_tier == ModelTier.A
            and rubric_score.composite_score >= MIN_COMPOSITE_FOR_OPUS
            and net_edge.is_viable
        ):
            # Check escalation policy
            escalation_request = EscalationRequest(
                workflow_run_id=workflow_run_id,
                agent_role="investigator_orchestration",
                reason="Final adversarial synthesis for surviving candidate",
                triggering_rule="investigation_synthesis",
                survived_deterministic_filtering=True,
                net_edge_after_impact=net_edge.impact_adjusted_edge,
                min_net_edge_threshold=self._min_net_edge,
                ambiguity_resolved_by_tier_b=False,
                position_size_meaningful=True,
                cost_governor_approval=cost_approval,
                cost_selectivity_ratio=regime.cost_selectivity_ratio if regime else None,
                regime=regime,
            )
            approved, escalation_record = self._escalation_engine.evaluate(escalation_request)
            use_opus = approved

        effective_tier = ModelTier.A if use_opus else ModelTier.B
        models_used.add(self._router.model_for_tier(effective_tier))

        # Build synthesis prompt
        synthesis_context = {
            "candidate": candidate.model_dump(mode="json"),
            "domain_memo": domain_memo.model_dump(mode="json"),
            "evidence_summary": [e.model_dump() for e in research.evidence[:5]],
            "counter_case": research.counter_case,
            "resolution_review": research.resolution_review,
            "timing": research.timing_assessment,
            "market_structure": research.market_structure,
            "entry_impact_bps": entry_impact.estimated_impact_bps,
            "base_rate": base_rate.model_dump(),
            "rubric_score": rubric_score.model_dump(),
            "net_edge": net_edge.model_dump(),
        }

        orchestrator = _OrchestratorAgent(
            router=self._router,
            prompt_manager=self._prompt_manager,
            tier_override=effective_tier,
        )

        agent_input = AgentInput(
            workflow_run_id=workflow_run_id,
            market_id=candidate.market_id,
            agent_role="investigator_orchestration",
            context=synthesis_context,
        )

        result = await orchestrator.run(agent_input, regime=regime)

        if not result.success:
            _log.error(
                "orchestrator_synthesis_failed",
                market_id=candidate.market_id,
                error=result.error,
            )
            return None, 0.0

        return result.result, result.total_cost_usd

    # --- Private helpers ---

    async def _get_cost_approval(
        self,
        request: InvestigationRequest,
    ) -> CostApproval | None:
        """Get Cost Governor pre-approval for the investigation run."""
        if self._cost_governor is None:
            return None

        run_type_map = {
            InvestigationMode.SCHEDULED_SWEEP: RunType.SCHEDULED_SWEEP,
            InvestigationMode.TRIGGER_BASED: RunType.TRIGGER_BASED,
            InvestigationMode.OPERATOR_FORCED: RunType.OPERATOR_FORCED,
        }

        cost_request = CostEstimateRequest(
            workflow_run_id=request.workflow_run_id,
            run_type=run_type_map.get(request.mode, RunType.SCHEDULED_SWEEP),
            candidate_count=min(len(request.candidates), request.max_candidates),
            agent_specs=[
                AgentCostSpec(agent_role="domain_manager", tier=ModelTier.B, cost_class=CostClass.M),
                AgentCostSpec(agent_role="evidence_research", tier=ModelTier.C, cost_class=CostClass.L),
                AgentCostSpec(agent_role="counter_case", tier=ModelTier.B, cost_class=CostClass.M),
                AgentCostSpec(agent_role="resolution_review", tier=ModelTier.B, cost_class=CostClass.M),
                AgentCostSpec(agent_role="timing_catalyst", tier=ModelTier.C, cost_class=CostClass.L),
                AgentCostSpec(agent_role="market_structure", tier=ModelTier.C, cost_class=CostClass.L),
                AgentCostSpec(agent_role="orchestrator", tier=ModelTier.A, cost_class=CostClass.H),
            ],
        )

        estimate = self._cost_governor.estimate(cost_request)
        return self._cost_governor.approve(estimate)

    def _rank_candidates(
        self,
        candidates: list[CandidateContext],
    ) -> list[CandidateContext]:
        """Rank candidates by trigger urgency and edge discovery focus.

        Deprioritizes heavily covered markets where mispricing is unlikely.
        """
        trigger_priority = {
            "D": 0, "C": 1, "B": 2, "A": 3,
        }

        def sort_key(c: CandidateContext) -> tuple[int, float]:
            level_priority = trigger_priority.get(c.trigger_level or "A", 3)
            edge_score = c.edge_discovery_score
            return (level_priority, -edge_score)

        return sorted(candidates, key=sort_key)

    def _estimate_probability_from_domain(
        self,
        domain_memo: DomainMemo,
        market_implied: float,
    ) -> float:
        """Derive a preliminary probability estimate from domain memo.

        In the full system, this would use the orchestrator's output.
        For the initial pipeline, we use a simple heuristic.
        """
        confidence_map = {"high": 0.15, "medium": 0.08, "low": 0.03}
        adjustment = confidence_map.get(domain_memo.confidence_level, 0.03)

        # If domain manager recommends proceeding, assume slight mispricing
        if domain_memo.recommended_proceed:
            # We don't know the direction yet, so use a small offset
            return min(0.95, max(0.05, market_implied + adjustment))
        return market_implied


class _OrchestratorAgent(BaseAgent):
    """Internal orchestrator agent with configurable tier override."""

    role_name = "investigator_orchestration"

    def __init__(
        self,
        *,
        router: ProviderRouter,
        prompt_manager: PromptManager | None = None,
        tier_override: ModelTier = ModelTier.A,
    ) -> None:
        super().__init__(router=router, prompt_manager=prompt_manager)
        self._tier_override = tier_override

    @property
    def tier(self) -> ModelTier:
        return self._tier_override

    async def _execute(
        self,
        agent_input: AgentInput,
        regime: RegimeContext | None,
    ) -> dict[str, Any]:
        result = AgentResult(agent_role=self.role_name)

        ctx = agent_input.context
        user_prompt = (
            "You are performing final adversarial synthesis for a market candidate.\n\n"
            f"Market: {ctx.get('candidate', {}).get('title', 'Unknown')}\n"
            f"Category: {ctx.get('candidate', {}).get('category', 'Unknown')}\n\n"
            f"Domain Analysis Summary:\n{ctx.get('domain_memo', {}).get('summary', 'N/A')}\n\n"
            f"Evidence ({len(ctx.get('evidence_summary', []))} items):\n"
            f"{json.dumps(ctx.get('evidence_summary', [])[:3], indent=2, default=str)}\n\n"
            f"Counter-Case:\n{json.dumps(ctx.get('counter_case', {}), indent=2, default=str)}\n\n"
            f"Resolution Review:\n{json.dumps(ctx.get('resolution_review', {}), indent=2, default=str)}\n\n"
            f"Net Edge: {json.dumps(ctx.get('net_edge', {}), indent=2)}\n"
            f"Entry Impact: {ctx.get('entry_impact_bps', 0):.1f} bps\n"
            f"Base Rate: {ctx.get('base_rate', {}).get('base_rate', 0.5)}\n"
            f"Rubric Score: {ctx.get('rubric_score', {}).get('composite_score', 0)}\n\n"
            "Weigh ALL evidence and produce ONE of:\n"
            '1. {"decision": "accept", "proposed_side": "yes"|"no", '
            '"core_thesis": "...", "why_mispriced": "...", '
            '"probability_estimate": 0.0-1.0, "confidence_estimate": 0.0-1.0, '
            '"calibration_confidence": 0.0-1.0, "confidence_note": "...", '
            '"invalidation_conditions": ["..."], '
            '"supporting_evidence": [...], "opposing_evidence": [...], '
            '"resolution_risk_summary": "..."}\n\n'
            '2. {"decision": "no_trade", "no_trade_reason": "..."}\n\n'
            "Remember: most markets should result in no-trade. Be adversarial."
        )

        response = await self.call_llm(
            agent_input,
            user_prompt=user_prompt,
            tier=self._tier_override,
            regime=regime,
            result=result,
            max_tokens=3072,
        )

        try:
            output = json.loads(response.content)
        except (json.JSONDecodeError, TypeError):
            output = {"decision": "no_trade", "no_trade_reason": "Failed to parse synthesis output"}

        return output
