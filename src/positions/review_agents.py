"""LLM-escalated position review agents.

Sub-agents invoked when deterministic checks flag issues that require
LLM judgment. The Position Review Orchestration Agent (Tier B) coordinates:

- Update Evidence Agent (Tier C)
- Thesis Integrity Agent (Tier B)
- Opposing Signal Agent (Tier C, escalates to B for complex cases)
- Liquidity Deterioration Agent (Tier D metrics + Tier C explanation)
- Catalyst Shift Agent (Tier C)

Premium (Opus) escalation only when:
- Large position
- Near invalidation
- Conflicting evidence
- Interpretation risk
- Remaining value justifies cost
- Cumulative review cost below cap
"""

from __future__ import annotations

import json
from typing import Any

import structlog

from agents.base import BaseAgent
from agents.types import AgentInput, AgentResult, RegimeContext
from core.enums import ExitClass, ModelTier, ReviewTier
from positions.types import (
    DeterministicCheckName,
    LLMReviewInput,
    LLMReviewResult,
    PositionAction,
    SubAgentResult,
)

_log = structlog.get_logger(component="position_review_agents")


# --- Sub-agents ---


class UpdateEvidenceAgent(BaseAgent):
    """Update Evidence Agent (Tier C) — position review sub-agent.

    Identifies new evidence relevant to an existing position.
    Structures and compresses findings for review.
    """

    role_name = "update_evidence"

    async def _execute(
        self,
        agent_input: AgentInput,
        regime: RegimeContext | None,
    ) -> dict[str, Any]:
        result = AgentResult(agent_role=self.role_name)
        user_prompt = self._build_review_prompt(agent_input)

        response = await self.call_llm(
            agent_input,
            user_prompt=user_prompt,
            regime=regime,
            result=result,
        )
        return self._parse_response(response)

    def _build_review_prompt(self, agent_input: AgentInput) -> str:
        ctx = agent_input.context
        return (
            f"Review evidence for position in market: {ctx.get('market_id', 'unknown')}\n\n"
            f"Core thesis: {ctx.get('core_thesis', 'N/A')}\n"
            f"Flagged issues: {', '.join(ctx.get('flagged_issues', []))}\n\n"
            f"Current price: {ctx.get('current_price', 'N/A')}\n"
            f"Entry price: {ctx.get('entry_price', 'N/A')}\n\n"
            "Identify any new evidence that affects the thesis. Structure findings as:\n"
            "1. New supporting evidence (if any)\n"
            "2. New opposing evidence (if any)\n"
            "3. Evidence quality assessment\n"
            "4. Recommendation for thesis validity\n\n"
            "Return structured JSON with keys: new_supporting, new_opposing, "
            "evidence_quality_change, recommendation"
        )


class ThesisIntegrityAgent(BaseAgent):
    """Thesis Integrity Agent (Tier B) — invoked on LLM-escalated review.

    Assesses whether the original thesis remains valid given new evidence.
    Flags thesis invalidation triggers and confidence degradation.
    """

    role_name = "thesis_integrity"

    async def _execute(
        self,
        agent_input: AgentInput,
        regime: RegimeContext | None,
    ) -> dict[str, Any]:
        result = AgentResult(agent_role=self.role_name)
        user_prompt = self._build_integrity_prompt(agent_input)

        response = await self.call_llm(
            agent_input,
            user_prompt=user_prompt,
            regime=regime,
            result=result,
        )
        return self._parse_response(response)

    def _build_integrity_prompt(self, agent_input: AgentInput) -> str:
        ctx = agent_input.context
        invalidation_conditions = ctx.get("invalidation_conditions", [])
        return (
            f"Assess thesis integrity for position: {ctx.get('position_id', 'unknown')}\n\n"
            f"Core thesis: {ctx.get('core_thesis', 'N/A')}\n"
            f"Original confidence: {ctx.get('confidence_estimate', 'N/A')}\n"
            f"Flagged issues: {', '.join(ctx.get('flagged_issues', []))}\n\n"
            f"Invalidation conditions:\n"
            + "\n".join(f"  - {c}" for c in invalidation_conditions) + "\n\n"
            f"Current price: {ctx.get('current_price', 'N/A')} "
            f"(entry: {ctx.get('entry_price', 'N/A')})\n"
            f"Price change: {ctx.get('price_change_pct', 'N/A')}\n\n"
            "Assess:\n"
            "1. Has any invalidation condition been triggered?\n"
            "2. Has the core thesis logic been undermined?\n"
            "3. What is the updated confidence level?\n"
            "4. Recommended action: hold, trim, partial_close, or full_close\n\n"
            "Return structured JSON with keys: invalidation_triggered, "
            "thesis_still_valid, updated_confidence, recommended_action, reasoning"
        )


class OpposingSignalAgent(BaseAgent):
    """Opposing Signal Agent (Tier C) — monitors for signals opposing thesis.

    Simple updates only — escalates complex analysis to Tier B.
    """

    role_name = "opposing_signal"

    async def _execute(
        self,
        agent_input: AgentInput,
        regime: RegimeContext | None,
    ) -> dict[str, Any]:
        result = AgentResult(agent_role=self.role_name)
        user_prompt = self._build_signal_prompt(agent_input)

        response = await self.call_llm(
            agent_input,
            user_prompt=user_prompt,
            regime=regime,
            result=result,
        )
        return self._parse_response(response)

    def _build_signal_prompt(self, agent_input: AgentInput) -> str:
        ctx = agent_input.context
        return (
            f"Scan for opposing signals against position thesis.\n\n"
            f"Market: {ctx.get('market_id', 'unknown')}\n"
            f"Thesis side: {ctx.get('proposed_side', 'N/A')}\n"
            f"Core thesis: {ctx.get('core_thesis', 'N/A')}\n\n"
            f"Flagged issues: {', '.join(ctx.get('flagged_issues', []))}\n\n"
            "Identify any signals that oppose the current thesis:\n"
            "1. Price-action signals\n"
            "2. Information/news signals\n"
            "3. Market structure signals\n\n"
            "If complex analysis is needed, flag for Tier B escalation.\n\n"
            "Return structured JSON with keys: opposing_signals, "
            "signal_severity, needs_escalation, summary"
        )


class CatalystShiftAgent(BaseAgent):
    """Catalyst Shift Agent (Tier C) — position review sub-agent.

    Assesses whether catalyst timing or nature has shifted
    for a held position.
    """

    role_name = "catalyst_shift"

    async def _execute(
        self,
        agent_input: AgentInput,
        regime: RegimeContext | None,
    ) -> dict[str, Any]:
        result = AgentResult(agent_role=self.role_name)
        user_prompt = self._build_catalyst_prompt(agent_input)

        response = await self.call_llm(
            agent_input,
            user_prompt=user_prompt,
            regime=regime,
            result=result,
        )
        return self._parse_response(response)

    def _build_catalyst_prompt(self, agent_input: AgentInput) -> str:
        ctx = agent_input.context
        return (
            f"Assess catalyst timing for position.\n\n"
            f"Market: {ctx.get('market_id', 'unknown')}\n"
            f"Expected catalyst: {ctx.get('expected_catalyst', 'N/A')}\n"
            f"Expected date: {ctx.get('expected_catalyst_date', 'N/A')}\n"
            f"Hours until catalyst: {ctx.get('hours_until_catalyst', 'N/A')}\n\n"
            "Assess:\n"
            "1. Has the catalyst timing shifted?\n"
            "2. Has the catalyst nature changed?\n"
            "3. Is the catalyst still expected to drive resolution?\n"
            "4. Time pressure assessment\n\n"
            "Return structured JSON with keys: timing_shifted, "
            "nature_changed, still_relevant, urgency_level, summary"
        )


class LiquidityDeteriorationAgent(BaseAgent):
    """Liquidity Deterioration Summary Agent (Tier C).

    Describes liquidity changes in narrative form given deterministic
    metric data. Metrics are Tier D — this agent only narrates.
    """

    role_name = "liquidity_deterioration_summary"

    async def _execute(
        self,
        agent_input: AgentInput,
        regime: RegimeContext | None,
    ) -> dict[str, Any]:
        result = AgentResult(agent_role=self.role_name)
        user_prompt = self._build_liquidity_prompt(agent_input)

        response = await self.call_llm(
            agent_input,
            user_prompt=user_prompt,
            regime=regime,
            result=result,
        )
        return self._parse_response(response)

    def _build_liquidity_prompt(self, agent_input: AgentInput) -> str:
        ctx = agent_input.context
        return (
            f"Describe liquidity situation for position.\n\n"
            f"Current depth: ${ctx.get('current_depth_usd', 0):.2f}\n"
            f"Current spread: {ctx.get('current_spread', 0):.4f}\n"
            f"Position size: ${ctx.get('current_size_usd', 0):.2f}\n"
            f"Exit capability: {ctx.get('exit_capability', 'unknown')}\n\n"
            "Describe the liquidity situation and its implications for "
            "position management. Keep factual — metrics have been computed.\n\n"
            "Return structured JSON with keys: liquidity_assessment, "
            "exit_risk_level, recommended_action, summary"
        )


# --- Orchestrator ---


class PositionReviewOrchestrator(BaseAgent):
    """Position Review Orchestration Agent (Tier B).

    Invoked only when deterministic checks detect an anomaly requiring
    LLM judgment. Coordinates sub-agents and synthesizes their output
    into a final position action recommendation.

    Per spec Section 11.3:
    - Runs sub-agents focused on flagged issues
    - Synthesizes evidence, thesis integrity, and exit signals
    - May escalate to Opus for large positions near invalidation

    Premium (Opus) escalation criteria per spec Section 11.4:
    - Large position
    - Near invalidation
    - Conflicting evidence
    - Interpretation risk
    - Remaining value justifies cost
    - Cumulative review cost below cap
    """

    role_name = "position_review_orchestration"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._update_evidence = UpdateEvidenceAgent(
            router=self._router,
            prompt_manager=self._prompt_manager,
        )
        self._thesis_integrity = ThesisIntegrityAgent(
            router=self._router,
            prompt_manager=self._prompt_manager,
        )
        self._opposing_signal = OpposingSignalAgent(
            router=self._router,
            prompt_manager=self._prompt_manager,
        )
        self._catalyst_shift = CatalystShiftAgent(
            router=self._router,
            prompt_manager=self._prompt_manager,
        )
        self._liquidity_deterioration = LiquidityDeteriorationAgent(
            router=self._router,
            prompt_manager=self._prompt_manager,
        )

    async def run_review(
        self,
        review_input: LLMReviewInput,
        *,
        regime: RegimeContext | None = None,
    ) -> LLMReviewResult:
        """Execute the full LLM-escalated review pipeline.

        Runs relevant sub-agents based on flagged issues, then
        synthesizes results into a final recommendation.

        Args:
            review_input: LLM review input with position and flagged checks.
            regime: Regime context for agent prompts.

        Returns:
            LLMReviewResult with action recommendation.
        """
        position = review_input.position
        flagged = review_input.deterministic_result.flagged_checks
        result = LLMReviewResult(
            position_id=position.position_id,
            workflow_run_id=review_input.workflow_run_id,
        )

        # Build shared agent input context
        base_context = self._build_context(review_input)

        # Run sub-agents based on flagged issues
        await self._run_sub_agents(
            result=result,
            flagged=flagged,
            base_context=base_context,
            review_input=review_input,
            regime=regime,
        )

        # Synthesize results
        synthesis = await self._synthesize(
            result=result,
            review_input=review_input,
            regime=regime,
        )

        result.synthesis = synthesis
        result.recommended_action = self._determine_action(synthesis, review_input)
        result.recommended_exit_class = self._determine_exit_class(
            synthesis, result.recommended_action,
        )

        _log.info(
            "llm_review_complete",
            position_id=position.position_id,
            recommended_action=result.recommended_action.value,
            exit_class=result.recommended_exit_class.value if result.recommended_exit_class else None,
            agents_invoked=result.agents_invoked,
            total_cost=round(result.total_review_cost_usd, 4),
            opus_escalated=result.opus_escalated,
        )

        return result

    def _build_context(self, review_input: LLMReviewInput) -> dict[str, Any]:
        """Build shared context dict for all sub-agents."""
        position = review_input.position
        return {
            "position_id": position.position_id,
            "market_id": position.market_id,
            "current_price": position.current_price,
            "entry_price": position.entry_price,
            "entry_side": position.entry_side,
            "current_size_usd": position.current_size_usd,
            "current_value_usd": position.current_value_usd,
            "unrealized_pnl_pct": position.unrealized_pnl_pct,
            "proposed_side": position.proposed_side,
            "core_thesis": position.core_thesis,
            "invalidation_conditions": position.invalidation_conditions,
            "expected_catalyst": position.expected_catalyst,
            "expected_catalyst_date": (
                position.expected_catalyst_date.isoformat()
                if position.expected_catalyst_date else None
            ),
            "current_spread": position.current_spread,
            "current_depth_usd": position.current_depth_usd,
            "category": position.category,
            "flagged_issues": review_input.flagged_issues,
            "review_mode": review_input.review_mode.value,
            "confidence_estimate": None,  # populated from thesis card if available
            "price_change_pct": position.unrealized_pnl_pct,
        }

    async def _run_sub_agents(
        self,
        result: LLMReviewResult,
        flagged: list[DeterministicCheckName],
        base_context: dict[str, Any],
        review_input: LLMReviewInput,
        regime: RegimeContext | None,
    ) -> None:
        """Run relevant sub-agents based on flagged checks."""
        position = review_input.position
        flagged_set = set(flagged)

        # Always run evidence update on LLM escalation
        evidence_result = await self._run_agent(
            self._update_evidence,
            base_context,
            review_input,
            regime,
        )
        result.evidence_update = evidence_result
        result.agents_invoked.append("update_evidence")
        result.total_review_cost_usd += evidence_result.cost_usd

        # Run thesis integrity if price or age flagged
        if flagged_set & {
            DeterministicCheckName.PRICE_VS_THESIS,
            DeterministicCheckName.POSITION_AGE_VS_HORIZON,
        }:
            integrity_result = await self._run_agent(
                self._thesis_integrity,
                base_context,
                review_input,
                regime,
            )
            result.thesis_integrity = integrity_result
            result.agents_invoked.append("thesis_integrity")
            result.total_review_cost_usd += integrity_result.cost_usd

        # Run opposing signal for any escalation
        opposing_result = await self._run_agent(
            self._opposing_signal,
            base_context,
            review_input,
            regime,
        )
        result.opposing_signals = opposing_result
        result.agents_invoked.append("opposing_signal")
        result.total_review_cost_usd += opposing_result.cost_usd

        # Run liquidity deterioration if spread or depth flagged
        if flagged_set & {
            DeterministicCheckName.SPREAD_VS_LIMITS,
            DeterministicCheckName.DEPTH_VS_MINIMUMS,
        }:
            ctx = dict(base_context)
            ctx["exit_capability"] = (
                "limited" if position.current_depth_usd < position.current_size_usd * 0.5
                else "adequate"
            )
            liquidity_result = await self._run_agent(
                self._liquidity_deterioration,
                ctx,
                review_input,
                regime,
            )
            result.liquidity_assessment = liquidity_result
            result.agents_invoked.append("liquidity_deterioration_summary")
            result.total_review_cost_usd += liquidity_result.cost_usd

        # Run catalyst shift if catalyst flagged
        if DeterministicCheckName.CATALYST_PROXIMITY in flagged_set:
            catalyst_ctx = dict(base_context)
            if position.expected_catalyst_date:
                from datetime import UTC, datetime as dt
                now = dt.now(tz=UTC)
                hours_until = (position.expected_catalyst_date - now).total_seconds() / 3600
                catalyst_ctx["hours_until_catalyst"] = round(hours_until, 1)

            catalyst_result = await self._run_agent(
                self._catalyst_shift,
                catalyst_ctx,
                review_input,
                regime,
            )
            result.catalyst_shift = catalyst_result
            result.agents_invoked.append("catalyst_shift")
            result.total_review_cost_usd += catalyst_result.cost_usd

    async def _run_agent(
        self,
        agent: BaseAgent,
        context: dict[str, Any],
        review_input: LLMReviewInput,
        regime: RegimeContext | None,
    ) -> SubAgentResult:
        """Run a single sub-agent and wrap its result."""
        agent_input = AgentInput(
            workflow_run_id=review_input.workflow_run_id,
            market_id=review_input.position.market_id,
            position_id=review_input.position.position_id,
            agent_role=agent.role_name,
            context=context,
        )

        try:
            agent_result = await agent.run(agent_input, regime=regime)
            return SubAgentResult(
                agent_role=agent.role_name,
                success=agent_result.success,
                findings=agent_result.result,
                cost_usd=agent_result.total_cost_usd,
                error=agent_result.error,
            )
        except Exception as exc:
            _log.error(
                "sub_agent_failed",
                agent_role=agent.role_name,
                position_id=review_input.position.position_id,
                error=str(exc),
            )
            return SubAgentResult(
                agent_role=agent.role_name,
                success=False,
                error=str(exc),
            )

    async def _synthesize(
        self,
        result: LLMReviewResult,
        review_input: LLMReviewInput,
        regime: RegimeContext | None,
    ) -> dict[str, Any]:
        """Synthesize sub-agent results into a final recommendation.

        Uses the Position Review Orchestration Agent (Tier B) to combine
        all findings into a cohesive action recommendation.

        May escalate to Opus per spec Section 11.4 criteria.
        """
        # Build synthesis context from sub-agent results
        synthesis_context: dict[str, Any] = {
            "position_id": review_input.position.position_id,
            "market_id": review_input.position.market_id,
            "review_mode": review_input.review_mode.value,
            "flagged_issues": review_input.flagged_issues,
            "deterministic_suggestion": review_input.deterministic_result.suggested_action.value,
        }

        if result.evidence_update and result.evidence_update.success:
            synthesis_context["evidence_update"] = result.evidence_update.findings
        if result.thesis_integrity and result.thesis_integrity.success:
            synthesis_context["thesis_integrity"] = result.thesis_integrity.findings
        if result.opposing_signals and result.opposing_signals.success:
            synthesis_context["opposing_signals"] = result.opposing_signals.findings
        if result.liquidity_assessment and result.liquidity_assessment.success:
            synthesis_context["liquidity_assessment"] = result.liquidity_assessment.findings
        if result.catalyst_shift and result.catalyst_shift.success:
            synthesis_context["catalyst_shift"] = result.catalyst_shift.findings

        # Check Opus escalation criteria
        should_escalate_to_opus = self._should_escalate_to_opus(
            review_input, result, synthesis_context,
        )

        tier = ModelTier.B
        if should_escalate_to_opus:
            tier = ModelTier.A
            result.opus_escalated = True
            result.opus_escalation_reason = self._opus_escalation_reason(review_input)
            _log.info(
                "opus_escalation_for_review",
                position_id=review_input.position.position_id,
                reason=result.opus_escalation_reason,
            )

        # Make the synthesis call
        agent_input = AgentInput(
            workflow_run_id=review_input.workflow_run_id,
            market_id=review_input.position.market_id,
            position_id=review_input.position.position_id,
            agent_role=self.role_name,
            context=synthesis_context,
        )

        synthesis_prompt = (
            "Synthesize the following sub-agent findings into a position action.\n\n"
            f"Context:\n{json.dumps(synthesis_context, indent=2, default=str)}\n\n"
            "Determine the appropriate action:\n"
            "- hold: thesis intact, no action needed\n"
            "- trim: reduce position size\n"
            "- partial_close: close some of the position\n"
            "- full_close: exit entirely\n"
            "- watch_and_review: schedule earlier next review\n"
            "- forced_risk_reduction: risk-mandated reduction\n\n"
            "If closing, specify exit class:\n"
            "thesis_invalidated, resolution_risk, time_decay, news_shock, "
            "profit_protection, liquidity_collapse, correlation_risk, "
            "portfolio_defense, cost_inefficiency\n\n"
            "Return structured JSON with keys: action, exit_class (if closing), "
            "confidence, reasoning, key_factors"
        )

        try:
            agent_result = AgentResult(agent_role=self.role_name)
            response = await self.call_llm(
                agent_input,
                user_prompt=synthesis_prompt,
                tier=tier,
                regime=regime,
                result=agent_result,
            )
            result.total_review_cost_usd += agent_result.total_cost_usd
            return self._parse_response(response)

        except Exception as exc:
            _log.error(
                "synthesis_failed",
                position_id=review_input.position.position_id,
                error=str(exc),
            )
            return {
                "action": "watch_and_review",
                "reasoning": f"Synthesis failed: {exc}",
                "confidence": 0.3,
            }

    def _should_escalate_to_opus(
        self,
        review_input: LLMReviewInput,
        result: LLMReviewResult,
        synthesis_context: dict[str, Any],
    ) -> bool:
        """Check Opus escalation criteria per spec Section 11.4.

        Premium escalation only when:
        - Large position
        - Near invalidation
        - Conflicting evidence
        - Interpretation risk
        - Remaining value justifies cost
        - Cumulative review cost below cap
        """
        position = review_input.position

        # Must be allowed by cost cap
        if not review_input.allows_opus_escalation:
            return False

        # Position must be large enough to justify premium cost
        min_value_for_opus = 200.0  # minimum position value for Opus escalation
        if position.current_value_usd < min_value_for_opus:
            return False

        # Check for conflicting or high-risk signals
        has_invalidation_risk = False
        has_conflicting_evidence = False

        if result.thesis_integrity and result.thesis_integrity.success:
            findings = result.thesis_integrity.findings
            has_invalidation_risk = findings.get("invalidation_triggered", False)
            confidence = findings.get("updated_confidence", 1.0)
            if isinstance(confidence, (int, float)) and confidence < 0.4:
                has_invalidation_risk = True

        if result.opposing_signals and result.opposing_signals.success:
            findings = result.opposing_signals.findings
            severity = findings.get("signal_severity", "low")
            if severity in ("high", "critical"):
                has_conflicting_evidence = True

        # Escalate if high-risk conditions met
        return has_invalidation_risk or has_conflicting_evidence

    def _opus_escalation_reason(self, review_input: LLMReviewInput) -> str:
        """Build a human-readable reason for Opus escalation."""
        position = review_input.position
        reasons: list[str] = []

        if position.current_value_usd >= 200.0:
            reasons.append(f"Large position (${position.current_value_usd:.2f})")

        flagged = review_input.deterministic_result.flagged_checks
        if DeterministicCheckName.PRICE_VS_THESIS in flagged:
            reasons.append("Near thesis invalidation")
        if DeterministicCheckName.CATALYST_PROXIMITY in flagged:
            reasons.append("Catalyst proximity concerns")

        return "; ".join(reasons) if reasons else "Complex review requiring premium synthesis"

    def _determine_action(
        self,
        synthesis: dict[str, Any],
        review_input: LLMReviewInput,
    ) -> PositionAction:
        """Extract action from synthesis result, with fallback logic."""
        action_str = synthesis.get("action", "hold")
        action_map = {
            "hold": PositionAction.HOLD,
            "trim": PositionAction.TRIM,
            "partial_close": PositionAction.PARTIAL_CLOSE,
            "full_close": PositionAction.FULL_CLOSE,
            "forced_risk_reduction": PositionAction.FORCED_RISK_REDUCTION,
            "watch_and_review": PositionAction.WATCH_AND_REVIEW,
            "reduce_to_minimum": PositionAction.REDUCE_TO_MINIMUM,
        }
        return action_map.get(action_str, PositionAction.WATCH_AND_REVIEW)

    def _determine_exit_class(
        self,
        synthesis: dict[str, Any],
        action: PositionAction,
    ) -> ExitClass | None:
        """Extract exit class from synthesis result if closing."""
        if action not in (
            PositionAction.FULL_CLOSE,
            PositionAction.PARTIAL_CLOSE,
            PositionAction.FORCED_RISK_REDUCTION,
        ):
            return None

        exit_str = synthesis.get("exit_class", "")
        exit_map = {
            "thesis_invalidated": ExitClass.THESIS_INVALIDATED,
            "resolution_risk": ExitClass.RESOLUTION_RISK,
            "time_decay": ExitClass.TIME_DECAY,
            "news_shock": ExitClass.NEWS_SHOCK,
            "profit_protection": ExitClass.PROFIT_PROTECTION,
            "liquidity_collapse": ExitClass.LIQUIDITY_COLLAPSE,
            "correlation_risk": ExitClass.CORRELATION_RISK,
            "portfolio_defense": ExitClass.PORTFOLIO_DEFENSE,
            "cost_inefficiency": ExitClass.COST_INEFFICIENCY,
            "operator_absence": ExitClass.OPERATOR_ABSENCE,
            "scanner_degradation": ExitClass.SCANNER_DEGRADATION,
        }
        return exit_map.get(exit_str, ExitClass.THESIS_INVALIDATED)
