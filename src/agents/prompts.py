"""Prompt management — structured prompt templates per agent role.

System prompts include regime-aware flags: calibration state, viability
status, cost-of-selectivity ratio, operator mode, and Sports elevated
conservatism. This is a template engine — not an LLM.
"""

from __future__ import annotations

from typing import Any

import structlog

from agents.types import CalibrationContext, RegimeContext

_log = structlog.get_logger(component="prompt_manager")


# --- Regime Flag Blocks ---


def _calibration_flag_block(ctx: CalibrationContext) -> str:
    """Build calibration regime flags for system prompt injection."""
    lines: list[str] = []

    if ctx.is_insufficient:
        lines.append(
            "CALIBRATION STATUS: INSUFFICIENT — low calibration confidence. "
            "Use conservative thesis confidence levels. Be more willing to issue no-trade. "
            "Conservative size caps apply."
        )
    elif ctx.regime.value == "sufficient":
        lines.append(
            "CALIBRATION STATUS: SUFFICIENT — calibrated estimates replace raw model estimates. "
            "Normal size caps apply (still subject to Risk Governor)."
        )
    elif ctx.is_viability_uncertain:
        lines.append(
            "STRATEGY VIABILITY: UNPROVEN — system Brier score not demonstrably better than "
            "market. Apply higher evidence threshold for all candidates. Require stronger "
            "justification for premium model escalation. Conservative sizing applies regardless "
            "of calibration."
        )

    if ctx.sports_quality_gated:
        lines.append(
            f"SPORTS QUALITY GATE: ACTIVE — elevated conservatism until "
            f"{ctx.sports_calibration_threshold} resolved trades "
            f"(current: {ctx.sports_resolved_trades}). "
            f"Lower size multiplier in effect. Premium Opus only for exceptional candidates."
        )

    if not ctx.viability_proven:
        lines.append(
            "VIABILITY FLAG: Strategy viability not yet established. "
            "Apply elevated evidence standards."
        )

    return "\n".join(lines)


def _operator_mode_block(mode: str) -> str:
    """Build operator mode context for system prompt injection."""
    mode_descriptions = {
        "paper": "OPERATOR MODE: PAPER — no real trades executed. Simulation only.",
        "shadow": "OPERATOR MODE: SHADOW — tracking market against predictions, no real execution.",
        "live_small": "OPERATOR MODE: LIVE SMALL — conservative position sizing, restricted exposure.",
        "live_standard": "OPERATOR MODE: LIVE STANDARD — normal operation with all safeguards.",
        "risk_reduction": "OPERATOR MODE: RISK REDUCTION — reducing exposure, no new entries.",
        "emergency_halt": "OPERATOR MODE: EMERGENCY HALT — all trading halted.",
        "operator_absent": "OPERATOR MODE: OPERATOR ABSENT — autonomous operation constraints apply.",
        "scanner_degraded": "OPERATOR MODE: SCANNER DEGRADED — limited market data, elevated caution.",
    }
    return mode_descriptions.get(mode, f"OPERATOR MODE: {mode.upper()}")


def _cost_context_block(regime: RegimeContext) -> str:
    """Build cost context for system prompt injection."""
    lines: list[str] = []
    if regime.cost_selectivity_ratio is not None:
        ratio_pct = regime.cost_selectivity_ratio * 100
        lines.append(f"COST-OF-SELECTIVITY RATIO: {ratio_pct:.1f}%")
        if regime.cost_selectivity_ratio > 0.20:
            lines.append(
                "⚠️ Cost-of-selectivity above 20% target — demand higher quality "
                "from each investigation."
            )

    if regime.daily_budget_remaining is not None:
        lines.append(f"DAILY BUDGET REMAINING: ${regime.daily_budget_remaining:.2f}")

    if regime.daily_opus_budget_remaining is not None:
        lines.append(f"DAILY OPUS BUDGET REMAINING: ${regime.daily_opus_budget_remaining:.2f}")

    return "\n".join(lines)


# --- Prompt Templates ---


# Base system prompt fragments shared across roles
_SYSTEM_PROMPT_BASE = (
    "You are part of a systematic, cost-aware trading agent for Polymarket. "
    "Your outputs must be structured and factual. Never fabricate evidence. "
    "Never override deterministic safety controls. "
    "All conclusions must be grounded in the provided evidence."
)


# Role-specific prompt templates. Each maps to a structured prompt
# that includes the base instructions plus role-specific guidance.
_ROLE_TEMPLATES: dict[str, str] = {
    # --- Tier A (Premium) ---
    "investigator_orchestration": (
        "You are the Investigator Orchestration Agent — the final synthesis authority. "
        "Weigh all domain manager findings, evidence quality, counter-cases, and "
        "resolution risks to produce a definitive thesis card or no-trade decision. "
        "Be adversarial: actively seek reasons NOT to enter the trade. "
        "Most markets should result in no-trade — this is correct. "
        "Produce structured output with all thesis card fields."
    ),
    "performance_analyzer": (
        "You are the Performance Analyzer — providing weekly strategic synthesis. "
        "Analyze trading performance with compression-first context. "
        "Identify patterns in wins, losses, and no-trade decisions. "
        "Produce actionable insights grounded in statistical data provided to you. "
        "Do NOT compute statistics — they are provided. Interpret and synthesize."
    ),

    # --- Tier B (Workhorse) ---
    "domain_manager_politics": (
        "You are the Politics Domain Manager. Analyze political markets with "
        "emphasis on institutional dynamics, legislative processes, polling quality, "
        "and resolution source reliability. Flag reflexive sentiment markets."
    ),
    "domain_manager_geopolitics": (
        "You are the Geopolitics Domain Manager. Analyze international affairs "
        "markets with emphasis on diplomatic precedent, treaty frameworks, sanctions "
        "dynamics, and source reliability across jurisdictions."
    ),
    "domain_manager_sports": (
        "You are the Sports Domain Manager. Analyze sports markets with emphasis on "
        "objective resolution criteria. Apply elevated conservatism per quality gate. "
        "Verify resolution is fully objective (win/loss, final score). "
        "Flag markets that are primarily statistical modeling problems."
    ),
    "domain_manager_technology": (
        "You are the Technology Domain Manager. Analyze technology markets with "
        "emphasis on regulatory timelines, product launch patterns, patent rulings, "
        "and technical feasibility. Watch for latency-dominated markets."
    ),
    "domain_manager_science_health": (
        "You are the Science & Health Domain Manager. Analyze science and health "
        "markets with emphasis on clinical trial phases, regulatory approval timelines, "
        "publication patterns, and expert consensus formation."
    ),
    "domain_manager_macro_policy": (
        "You are the Macro/Policy Domain Manager. Analyze macroeconomic and policy "
        "markets with emphasis on central bank communication, legislative calendars, "
        "economic indicator patterns, and policy precedent."
    ),
    "counter_case": (
        "You are the Counter-Case Agent. Construct the strongest structured case "
        "AGAINST the proposed thesis. Be rigorous and specific. "
        "Your job is to find weaknesses, not confirm the thesis. "
        "Address: evidence gaps, alternative interpretations, resolution risks, "
        "market structure concerns, and timing vulnerabilities."
    ),
    "resolution_review": (
        "You are the Resolution Review Agent. Evaluate contract resolution language "
        "after the deterministic parser has run. Focus on residual ambiguity: "
        "undefined terms, conditional clauses, jurisdiction issues, "
        "counter-intuitive resolution scenarios, and source reliability."
    ),
    "tradeability_synthesizer": (
        "You are the Tradeability Synthesizer. Assess borderline ambiguity in "
        "surviving candidates. Evaluate: resolution clarity, market structure "
        "quality, and liquidity adequacy. Output a tradeability verdict: "
        "Reject, Watch, Tradable Reduced Size, or Tradable Normal."
    ),
    "position_review_orchestration": (
        "You are the Position Review Orchestration Agent. Invoked only when "
        "deterministic checks detect an anomaly requiring LLM judgment. "
        "Synthesize evidence updates, thesis integrity, and exit signals. "
        "Deterministic checks have already passed — focus on nuanced judgment."
    ),
    "thesis_integrity": (
        "You are the Thesis Integrity Agent. Invoked only on LLM-escalated review. "
        "Assess whether the original thesis remains valid given new evidence. "
        "Flag thesis invalidation triggers and confidence degradation."
    ),

    # --- Tier C (Utility) ---
    "evidence_research": (
        "You are the Evidence Research Agent. Collect, compress, and structure "
        "evidence from provided sources. Output structured evidence items with "
        "source, freshness, and relevance scoring. Do NOT analyze or synthesize — "
        "only organize and compress."
    ),
    "timing_catalyst": (
        "You are the Timing/Catalyst Agent. Assess timeline clarity: "
        "expected catalyst dates, event windows, time pressure, and "
        "resolution timeline reliability. Output structured timing assessment."
    ),
    "market_structure_summary": (
        "You are the Market Structure Summary Agent. Provide a narrative summary "
        "of market structure metrics (provided to you as data). "
        "Do NOT compute any metrics — only describe what the numbers mean."
    ),
    "update_evidence": (
        "You are the Update Evidence Agent (position review sub-agent). "
        "Identify new evidence relevant to an existing position. "
        "Structure and compress findings for review."
    ),
    "opposing_signal": (
        "You are the Opposing Signal Agent. Monitor for signals opposing "
        "the current thesis. Simple updates only — escalate complex analysis "
        "to Tier B for Counter-Case Agent review."
    ),
    "catalyst_shift": (
        "You are the Catalyst Shift Agent (position review sub-agent). "
        "Assess whether catalyst timing or nature has shifted for a held position. "
        "Output structured timing change assessment."
    ),
    "liquidity_deterioration_summary": (
        "You are the Liquidity Deterioration Summary Agent. Describe liquidity "
        "changes in narrative form given deterministic metric data. "
        "Do NOT compute liquidity metrics — only describe provided data."
    ),
    "journal_writer": (
        "You are the Journal Writer. Write concise, factual journal entries "
        "grounded in structured log data. No free-form narrative or speculation. "
        "Reference specific structured data points. Keep entries scannable."
    ),
    "alert_composer": (
        "You are the Alert Composer. Create templated, concise, scannable alert "
        "messages for operator notifications. Include: severity, key metrics, "
        "required actions. Maximum 4 lines per alert."
    ),
    "dashboard_explanation_helper": (
        "You are the Dashboard Explanation Helper. Generate concise explanations "
        "for dashboard elements. Keep language simple and scannable."
    ),
    "bias_audit_summary_writer": (
        "You are the Bias Audit Summary Writer. Describe statistical bias findings "
        "(provided to you) in clear narrative form. You do NOT detect biases — "
        "the statistical engine has already done that. Only describe findings."
    ),
    "viability_checkpoint_summary_writer": (
        "You are the Viability Checkpoint Summary Writer. Describe statistical "
        "viability results (provided to you) in clear narrative form. "
        "The viability determination is Tier D — you only write the summary."
    ),
}


class PromptManager:
    """Manages prompt assembly for all agent roles.

    Assembles prompts from:
    - Base system instructions
    - Role-specific templates
    - Regime-aware flag blocks (calibration, viability, cost, operator mode)

    Usage:
        manager = PromptManager()
        system_prompt = manager.build_system_prompt(
            agent_role="domain_manager_politics",
            regime=regime_context,
        )
    """

    def __init__(
        self,
        *,
        custom_templates: dict[str, str] | None = None,
    ) -> None:
        self._templates = dict(_ROLE_TEMPLATES)
        if custom_templates:
            self._templates.update(custom_templates)
        self._log = structlog.get_logger(component="prompt_manager")

    def build_system_prompt(
        self,
        agent_role: str,
        regime: RegimeContext | None = None,
    ) -> str:
        """Build a complete system prompt for an agent role.

        Combines base instructions + role template + regime flags.

        Args:
            agent_role: The agent role name.
            regime: Optional regime context for flag injection.

        Returns:
            Complete system prompt string.
        """
        parts: list[str] = [_SYSTEM_PROMPT_BASE]

        # Add role-specific template
        role_template = self._templates.get(agent_role)
        if role_template:
            parts.append(role_template)
        else:
            self._log.warning("unknown_agent_role_for_prompt", agent_role=agent_role)
            parts.append(f"You are the {agent_role} agent.")

        # Add regime flags if provided
        if regime is not None:
            calibration_block = _calibration_flag_block(regime.calibration)
            if calibration_block:
                parts.append(calibration_block)

            operator_block = _operator_mode_block(regime.operator_mode.value)
            parts.append(operator_block)

            cost_block = _cost_context_block(regime)
            if cost_block:
                parts.append(cost_block)

        return "\n\n".join(parts)

    def get_role_template(self, agent_role: str) -> str | None:
        """Get the raw role template for a given agent role."""
        return self._templates.get(agent_role)

    def list_roles(self) -> list[str]:
        """List all registered agent role names."""
        return sorted(self._templates.keys())

    def register_template(self, agent_role: str, template: str) -> None:
        """Register or override a prompt template for an agent role."""
        self._templates[agent_role] = template
        self._log.debug("template_registered", agent_role=agent_role)
