"""Tradeability Synthesizer — Tier B agent-assisted assessment.

For surviving candidates with non-trivial residual ambiguity, the
Tradeability Synthesizer provides an agent-assisted interpretation.

From spec Section 9.5:
Output: Reject (reason code), Watch, Tradable Reduced Size
        (with liquidity-adjusted max), Tradable Normal
        (with liquidity-adjusted max).

Deterministic checks run first. Agent-assisted interpretation runs
only for candidates with non-trivial residual ambiguity.
"""

from __future__ import annotations

import json
from typing import Any

import structlog

from agents.base import BaseAgent
from agents.types import AgentInput, AgentResult, RegimeContext
from agents.providers import LLMResponse
from core.enums import ModelTier

from tradeability.types import (
    HardRejectionReason,
    ResolutionClarity,
    ResolutionParseOutput,
    TradeabilityInput,
    TradeabilityOutcome,
    TradeabilityResult,
)

_log = structlog.get_logger(component="tradeability_synthesizer")


class TradeabilitySynthesizer(BaseAgent):
    """Tradeability assessment combining deterministic checks and Tier B synthesis.

    For most candidates, the deterministic resolution parser provides
    sufficient clarity. The LLM-assisted synthesizer is invoked only
    when the parser detects marginal residual ambiguity that requires
    interpretive judgment.

    Usage:
        synthesizer = TradeabilitySynthesizer(
            router=router,
            prompt_manager=prompt_manager,
        )
        result = await synthesizer.assess(
            input_data=tradeability_input,
            regime=regime_context,
        )
        if result.is_tradable:
            # forward to Risk Governor
            pass
    """

    role_name = "tradeability_synthesizer"

    async def assess(
        self,
        input_data: TradeabilityInput,
        *,
        regime: RegimeContext | None = None,
    ) -> TradeabilityResult:
        """Run full tradeability assessment.

        1. First applies deterministic hard rejection patterns
        2. If resolution parse was clear → approve
        3. If residual ambiguity exists → invoke Tier B synthesis
        """
        parse_result = input_data.resolution_parse

        # Step 1: Check for hard rejections from the parser
        if parse_result.is_rejected:
            return self._hard_reject(input_data, parse_result)

        # Step 2: Compute liquidity-adjusted max size
        liquidity_max = self._compute_liquidity_max(input_data)

        # Step 3: Check additional spread/depth requirements
        hard_rejection = self._check_hard_limits(input_data)
        if hard_rejection is not None:
            return hard_rejection

        # Step 4: If resolution is clear → approve at normal
        if parse_result.clarity == ResolutionClarity.CLEAR:
            return TradeabilityResult(
                market_id=input_data.market_id,
                outcome=TradeabilityOutcome.TRADABLE_NORMAL,
                reason="Resolution clear, all checks passed",
                reason_code="clear_resolution",
                liquidity_adjusted_max_size_usd=liquidity_max,
                resolution_clarity=ResolutionClarity.CLEAR,
            )

        # Step 5: If ambiguous beyond marginal → reject
        if parse_result.clarity == ResolutionClarity.AMBIGUOUS:
            return TradeabilityResult(
                market_id=input_data.market_id,
                outcome=TradeabilityOutcome.REJECT,
                reason="Resolution ambiguity too severe for trading",
                reason_code="severe_ambiguity",
                liquidity_adjusted_max_size_usd=0.0,
                resolution_clarity=ResolutionClarity.AMBIGUOUS,
                residual_ambiguity_issues=parse_result.flagged_items,
            )

        # Step 6: Marginal ambiguity → invoke Tier B synthesis
        return await self._synthesize(input_data, parse_result, liquidity_max, regime)

    async def _synthesize(
        self,
        input_data: TradeabilityInput,
        parse_result: ResolutionParseOutput,
        liquidity_max: float,
        regime: RegimeContext | None,
    ) -> TradeabilityResult:
        """Invoke Tier B agent for borderline ambiguity assessment."""
        agent_input = AgentInput(
            workflow_run_id=input_data.workflow_run_id,
            market_id=input_data.market_id,
            context={
                "market_title": input_data.title,
                "market_description": input_data.description or "",
                "resolution_checks": [
                    {
                        "check": c.check_name,
                        "passed": c.passed,
                        "detail": c.detail,
                    }
                    for c in parse_result.checks
                    if not c.passed
                ],
                "ambiguous_phrases": [
                    {"phrase": ap.phrase, "context": ap.context}
                    for ap in parse_result.ambiguous_phrases
                ],
                "undefined_terms": parse_result.undefined_terms,
                "flagged_items": parse_result.flagged_items,
                "has_named_source": parse_result.has_named_source,
                "has_explicit_deadline": parse_result.has_explicit_deadline,
                "gross_edge": input_data.gross_edge,
                "entry_impact_bps": input_data.entry_impact_bps,
            },
        )

        try:
            result = await self.run(agent_input, regime=regime)

            if result.success and result.result:
                return self._interpret_synthesis(
                    input_data, parse_result, result.result, liquidity_max,
                    synthesizer_cost=result.total_cost_usd,
                )
        except Exception as exc:
            _log.warning(
                "tradeability_synthesis_failed",
                market_id=input_data.market_id,
                error=str(exc),
            )

        # Fallback: treat marginal as tradable with reduced size
        return TradeabilityResult(
            market_id=input_data.market_id,
            outcome=TradeabilityOutcome.TRADABLE_REDUCED,
            reason="Marginal ambiguity — synthesis unavailable, defaulting to reduced size",
            reason_code="synthesis_fallback",
            liquidity_adjusted_max_size_usd=liquidity_max * 0.5,
            resolution_clarity=ResolutionClarity.MARGINAL,
            residual_ambiguity_issues=parse_result.flagged_items,
        )

    async def _execute(
        self,
        agent_input: AgentInput,
        regime: RegimeContext | None,
    ) -> dict[str, Any]:
        """Execute the Tier B synthesis call."""
        user_prompt = self._build_synthesis_prompt(agent_input)
        result = AgentResult(agent_role=self.role_name)

        response = await self.call_llm(
            agent_input,
            user_prompt=user_prompt,
            regime=regime,
            result=result,
            max_tokens=2048,
            temperature=0.0,
        )

        return self._parse_response(response)

    def _build_synthesis_prompt(self, agent_input: AgentInput) -> str:
        """Build structured prompt for tradeability synthesis."""
        context = agent_input.context or {}
        parts = [
            "Assess the tradeability of this market contract based on the following resolution analysis:\n",
            f"Market: {context.get('market_title', 'Unknown')}",
            f"Description: {context.get('market_description', 'N/A')}",
            "",
            "## Flagged Resolution Issues:",
        ]

        for item in context.get("flagged_items", []):
            parts.append(f"- {item}")

        parts.extend([
            "",
            "## Ambiguous Phrases Found:",
        ])

        for ap in context.get("ambiguous_phrases", []):
            parts.append(f'- "{ap["phrase"]}" in context: "{ap["context"]}"')

        parts.extend([
            "",
            f"Has Named Resolution Source: {context.get('has_named_source', False)}",
            f"Has Explicit Deadline: {context.get('has_explicit_deadline', False)}",
            f"Expected Gross Edge: {context.get('gross_edge', 'Unknown')}",
            f"Entry Impact (bps): {context.get('entry_impact_bps', 'Unknown')}",
            "",
            "## Required Output (JSON):",
            "Respond with a JSON object containing:",
            '- "tradable": boolean — whether the contract is tradable despite ambiguity',
            '- "confidence": "low" | "medium" | "high"',
            '- "size_recommendation": "normal" | "reduced" | "reject"',
            '- "residual_risks": list of strings describing remaining risks',
            '- "reasoning": string explaining the assessment',
        ])

        return "\n".join(parts)

    def _interpret_synthesis(
        self,
        input_data: TradeabilityInput,
        parse_result: ResolutionParseOutput,
        synthesis_result: dict[str, Any],
        liquidity_max: float,
        synthesizer_cost: float = 0.0,
    ) -> TradeabilityResult:
        """Interpret the Tier B synthesis output into a TradeabilityResult."""
        tradable = synthesis_result.get("tradable", False)
        size_rec = synthesis_result.get("size_recommendation", "reduced")
        confidence = synthesis_result.get("confidence", "low")
        residual_risks = synthesis_result.get("residual_risks", [])
        reasoning = synthesis_result.get("reasoning", "")

        if not tradable or size_rec == "reject":
            return TradeabilityResult(
                market_id=input_data.market_id,
                outcome=TradeabilityOutcome.REJECT,
                reason=f"Synthesizer rejected: {reasoning}",
                reason_code="synthesizer_reject",
                liquidity_adjusted_max_size_usd=0.0,
                resolution_clarity=parse_result.clarity,
                residual_ambiguity_issues=residual_risks,
                synthesizer_output=synthesis_result,
                synthesizer_cost_usd=synthesizer_cost,
            )

        if size_rec == "reduced" or confidence == "low":
            return TradeabilityResult(
                market_id=input_data.market_id,
                outcome=TradeabilityOutcome.TRADABLE_REDUCED,
                reason=f"Tradable with reduced size: {reasoning}",
                reason_code="synthesizer_reduced",
                liquidity_adjusted_max_size_usd=liquidity_max * 0.5,
                resolution_clarity=parse_result.clarity,
                residual_ambiguity_issues=residual_risks,
                synthesizer_output=synthesis_result,
                synthesizer_cost_usd=synthesizer_cost,
            )

        return TradeabilityResult(
            market_id=input_data.market_id,
            outcome=TradeabilityOutcome.TRADABLE_NORMAL,
            reason=f"Tradable at normal size: {reasoning}",
            reason_code="synthesizer_normal",
            liquidity_adjusted_max_size_usd=liquidity_max,
            resolution_clarity=parse_result.clarity,
            residual_ambiguity_issues=residual_risks,
            synthesizer_output=synthesis_result,
            synthesizer_cost_usd=synthesizer_cost,
        )

    # --- Deterministic helpers ---

    def _hard_reject(
        self,
        input_data: TradeabilityInput,
        parse_result: ResolutionParseOutput,
    ) -> TradeabilityResult:
        """Build a hard rejection result from the resolution parser."""
        rejection_reasons: list[HardRejectionReason] = []
        if parse_result.rejection_reason:
            rejection_reasons.append(parse_result.rejection_reason)

        return TradeabilityResult(
            market_id=input_data.market_id,
            outcome=TradeabilityOutcome.REJECT,
            reason=parse_result.rejection_detail or "Hard rejection from resolution parser",
            reason_code=parse_result.rejection_reason.value if parse_result.rejection_reason else "parser_reject",
            liquidity_adjusted_max_size_usd=0.0,
            resolution_clarity=parse_result.clarity,
            hard_rejection_reasons=rejection_reasons,
        )

    def _check_hard_limits(
        self,
        input_data: TradeabilityInput,
    ) -> TradeabilityResult | None:
        """Additional hard limit checks beyond the resolution parser."""
        # Spread fails hard limit
        if input_data.spread is not None and input_data.spread > 0.15:
            return TradeabilityResult(
                market_id=input_data.market_id,
                outcome=TradeabilityOutcome.REJECT,
                reason=f"Spread {input_data.spread:.4f} exceeds hard limit 0.15",
                reason_code="spread_hard_limit",
                hard_rejection_reasons=[HardRejectionReason.SPREAD_DEPTH_HARD_LIMIT],
            )

        # Depth below minimum
        if input_data.visible_depth_usd > 0 and input_data.visible_depth_usd < input_data.min_position_size_usd:
            return TradeabilityResult(
                market_id=input_data.market_id,
                outcome=TradeabilityOutcome.REJECT,
                reason="Visible depth below minimum for minimum position size",
                reason_code="depth_below_min",
                hard_rejection_reasons=[HardRejectionReason.DEPTH_BELOW_MINIMUM],
            )

        return None

    def _compute_liquidity_max(self, input_data: TradeabilityInput) -> float:
        """Compute liquidity-adjusted maximum position size.

        Hard cap: no order > depth_fraction_limit of visible depth
        at the top 3 levels.
        """
        if input_data.visible_depth_usd <= 0:
            return 0.0

        return input_data.visible_depth_usd * input_data.depth_fraction_limit
