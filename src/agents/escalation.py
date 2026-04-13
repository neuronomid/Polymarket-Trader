"""Escalation policy engine — enforces Tier A escalation rules.

Tier A (Opus) escalation is the most expensive operation in the system.
This engine enforces all gating conditions from spec Section 8.10:

ESCALATE only when ALL of:
- Candidate survived deterministic filtering
- Meaningful net-edge above minimum AFTER entry impact deduction
- Ambiguity unresolved by Tier B
- Position size/consequence meaningful
- Cost Governor pre-approved Tier A
- Daily Tier A budget not exhausted
- Cost-of-selectivity ratio not above target (or candidate justifies)

DO NOT escalate when:
- Contract fails hard rules
- Market quality poor
- Expected net edge thin/negative
- Task is only summarization/extraction
- Position tiny
- Cost Governor denied
- Entry impact > 25% of gross edge
- Cumulative review cost exceeded cap
- Position review completed deterministically

Every escalation logged with all required fields.
"""

from __future__ import annotations

from typing import Any

import structlog

from agents.types import EscalationRecord, RegimeContext
from cost.types import CostApproval, ReviewCostStatus

_log = structlog.get_logger(component="escalation_policy")


# --- Escalation Conditions ---


class EscalationRequest:
    """Input to the escalation policy engine."""

    def __init__(
        self,
        *,
        workflow_run_id: str,
        agent_role: str,
        reason: str,
        triggering_rule: str,
        # Candidate state
        survived_deterministic_filtering: bool = False,
        net_edge_after_impact: float | None = None,
        min_net_edge_threshold: float = 0.02,
        ambiguity_resolved_by_tier_b: bool = True,
        position_size_meaningful: bool = True,
        is_summarization_only: bool = False,
        # Cost state
        cost_governor_approval: CostApproval | None = None,
        daily_opus_budget_remaining: float | None = None,
        cost_selectivity_ratio: float | None = None,
        cost_selectivity_target: float = 0.20,
        # Entry impact
        entry_impact_pct_of_edge: float | None = None,
        max_entry_impact_pct: float = 0.25,
        # Review cost
        review_cost_status: ReviewCostStatus | None = None,
        review_completed_deterministically: bool = False,
        # Regime
        regime: RegimeContext | None = None,
    ) -> None:
        self.workflow_run_id = workflow_run_id
        self.agent_role = agent_role
        self.reason = reason
        self.triggering_rule = triggering_rule

        self.survived_deterministic_filtering = survived_deterministic_filtering
        self.net_edge_after_impact = net_edge_after_impact
        self.min_net_edge_threshold = min_net_edge_threshold
        self.ambiguity_resolved_by_tier_b = ambiguity_resolved_by_tier_b
        self.position_size_meaningful = position_size_meaningful
        self.is_summarization_only = is_summarization_only

        self.cost_governor_approval = cost_governor_approval
        self.daily_opus_budget_remaining = daily_opus_budget_remaining
        self.cost_selectivity_ratio = cost_selectivity_ratio
        self.cost_selectivity_target = cost_selectivity_target

        self.entry_impact_pct_of_edge = entry_impact_pct_of_edge
        self.max_entry_impact_pct = max_entry_impact_pct

        self.review_cost_status = review_cost_status
        self.review_completed_deterministically = review_completed_deterministically

        self.regime = regime


class EscalationDenial:
    """Reason for denying a Tier A escalation."""

    def __init__(self, reason: str, rule: str) -> None:
        self.reason = reason
        self.rule = rule


class EscalationPolicyEngine:
    """Enforces Tier A escalation rules.

    Every escalation must pass ALL gating conditions. Any single
    failure results in denial.

    Usage:
        engine = EscalationPolicyEngine()
        approved, record = engine.evaluate(request)
        if approved:
            # proceed with Tier A call
    """

    def __init__(
        self,
        *,
        min_net_edge_default: float = 0.02,
        max_entry_impact_default: float = 0.25,
        cost_selectivity_default_target: float = 0.20,
    ) -> None:
        self._min_net_edge = min_net_edge_default
        self._max_entry_impact = max_entry_impact_default
        self._cost_selectivity_target = cost_selectivity_default_target
        self._log = structlog.get_logger(component="escalation_policy")

    def evaluate(self, request: EscalationRequest) -> tuple[bool, EscalationRecord]:
        """Evaluate a Tier A escalation request.

        Returns:
            Tuple of (approved: bool, record: EscalationRecord).
        """
        denials: list[EscalationDenial] = []

        # Check all denial conditions
        self._check_denial_conditions(request, denials)

        approved = len(denials) == 0

        # Build record
        cost_approval = request.cost_governor_approval
        record = EscalationRecord(
            workflow_run_id=request.workflow_run_id,
            agent_role=request.agent_role,
            reason=request.reason if approved else denials[0].reason,
            triggering_rule=request.triggering_rule if approved else denials[0].rule,
            cost_governor_approved=cost_approval.is_approved if cost_approval else False,
            cost_governor_approval_reason=cost_approval.reason if cost_approval else None,
            cost_selectivity_ratio_at_decision=request.cost_selectivity_ratio,
            cumulative_position_review_cost=(
                request.review_cost_status.total_review_cost_usd
                if request.review_cost_status else None
            ),
            escalation_approved=approved,
        )

        # Log the decision
        if approved:
            self._log.info(
                "tier_a_escalation_approved",
                workflow_run_id=request.workflow_run_id,
                agent_role=request.agent_role,
                reason=request.reason,
                rule=request.triggering_rule,
                cost_selectivity_ratio=request.cost_selectivity_ratio,
            )
        else:
            denial_reasons = [d.reason for d in denials]
            self._log.info(
                "tier_a_escalation_denied",
                workflow_run_id=request.workflow_run_id,
                agent_role=request.agent_role,
                denial_count=len(denials),
                denials=denial_reasons,
            )

        return approved, record

    def _check_denial_conditions(
        self,
        request: EscalationRequest,
        denials: list[EscalationDenial],
    ) -> None:
        """Check all denial conditions and accumulate denials."""

        # 1. Must have survived deterministic filtering
        if not request.survived_deterministic_filtering:
            denials.append(EscalationDenial(
                "Candidate did not survive deterministic filtering",
                "deterministic_filter_required",
            ))

        # 2. Summarization-only tasks do not need Opus
        if request.is_summarization_only:
            denials.append(EscalationDenial(
                "Task is summarization/extraction only — Tier C sufficient",
                "no_opus_for_summarization",
            ))

        # 3. Net edge must be meaningful after impact
        min_edge = request.min_net_edge_threshold or self._min_net_edge
        # Adjust threshold based on cost-of-selectivity
        if request.cost_selectivity_ratio is not None:
            target = request.cost_selectivity_target or self._cost_selectivity_target
            if request.cost_selectivity_ratio > target:
                excess = request.cost_selectivity_ratio - target
                min_edge = min_edge * (1 + excess / target)

        if request.net_edge_after_impact is not None:
            if request.net_edge_after_impact < min_edge:
                denials.append(EscalationDenial(
                    f"Net edge after impact ({request.net_edge_after_impact:.4f}) "
                    f"below minimum ({min_edge:.4f})",
                    "insufficient_net_edge",
                ))

        # 4. Ambiguity should NOT be resolved by Tier B
        #    (if already resolved, no need for Opus)
        if request.ambiguity_resolved_by_tier_b:
            denials.append(EscalationDenial(
                "Ambiguity already resolved by Tier B",
                "ambiguity_resolved",
            ))

        # 5. Position size must be meaningful
        if not request.position_size_meaningful:
            denials.append(EscalationDenial(
                "Position size too small to justify Opus cost",
                "position_too_small",
            ))

        # 6. Cost Governor must have approved
        if request.cost_governor_approval is not None:
            if not request.cost_governor_approval.is_approved:
                denials.append(EscalationDenial(
                    f"Cost Governor denied: {request.cost_governor_approval.reason}",
                    "cost_governor_denied",
                ))

        # 7. Daily Opus budget must not be exhausted
        if request.daily_opus_budget_remaining is not None:
            if request.daily_opus_budget_remaining <= 0:
                denials.append(EscalationDenial(
                    "Daily Opus escalation budget exhausted",
                    "opus_budget_exhausted",
                ))

        # 8. Entry impact check
        if request.entry_impact_pct_of_edge is not None:
            max_impact = request.max_entry_impact_pct or self._max_entry_impact
            if request.entry_impact_pct_of_edge > max_impact:
                denials.append(EscalationDenial(
                    f"Entry impact ({request.entry_impact_pct_of_edge:.2%}) "
                    f"exceeds {max_impact:.0%} of gross edge",
                    "excessive_entry_impact",
                ))

        # 9. Cumulative review cost check
        if request.review_cost_status is not None:
            if request.review_cost_status.cap_threshold_hit:
                denials.append(EscalationDenial(
                    "Cumulative review cost cap exceeded",
                    "review_cost_cap_exceeded",
                ))

        # 10. If review was completed deterministically, no Opus needed
        if request.review_completed_deterministically:
            denials.append(EscalationDenial(
                "Position review completed deterministically",
                "review_deterministic_complete",
            ))

        # 11. Viability-uncertain regime — require stronger justification
        if request.regime is not None:
            cal = request.regime.calibration
            if cal.is_viability_uncertain:
                # In viability-uncertain regime, net edge threshold is higher
                if request.net_edge_after_impact is not None:
                    viability_min = min_edge * 1.5
                    if request.net_edge_after_impact < viability_min:
                        denials.append(EscalationDenial(
                            f"Viability uncertain: net edge ({request.net_edge_after_impact:.4f}) "
                            f"below elevated threshold ({viability_min:.4f})",
                            "viability_uncertain_higher_threshold",
                        ))
