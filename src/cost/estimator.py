"""Pre-run cost estimator.

Estimates expected cost (min/max) before any workflow starts.
Uses agent specs, run type classification, and the effective cost profile
for position reviews. Fully deterministic (Tier D).
"""

from __future__ import annotations

import structlog

from config.settings import CostConfig
from core.constants import COST_CLASS_RANGES, POSITION_REVIEW_COST_PROFILE, TIER_COST_CLASS
from core.enums import CostClass, ModelTier
from cost.types import (
    AgentCostSpec,
    BudgetState,
    CostEstimate,
    CostEstimateRequest,
    RunType,
)

_log = structlog.get_logger(component="pre_run_cost_estimator")


class PreRunCostEstimator:
    """Estimates cost of a workflow run before it starts.

    Uses agent specifications to compute min/max cost bounds.
    For position reviews, applies the effective cost profile (65% deterministic).
    """

    def __init__(self, config: CostConfig) -> None:
        self._config = config

    def estimate(
        self,
        request: CostEstimateRequest,
        budget_state: BudgetState,
    ) -> CostEstimate:
        """Compute pre-run cost estimate for a workflow.

        Args:
            request: Workflow specification with agent breakdown.
            budget_state: Current budget state for context.

        Returns:
            CostEstimate with min/max bounds and per-agent budgets.
        """
        if request.run_type == RunType.POSITION_REVIEW:
            return self._estimate_position_review(request, budget_state)

        return self._estimate_standard(request, budget_state)

    def _estimate_standard(
        self,
        request: CostEstimateRequest,
        budget_state: BudgetState,
    ) -> CostEstimate:
        """Estimate for investigation or operator-forced runs."""
        total_min = 0.0
        total_max = 0.0
        agent_budgets: dict[str, dict] = {}

        for spec in request.agent_specs:
            agent_min, agent_max = self._agent_cost_bounds(spec)
            # Scale by candidate count for multi-candidate workflows
            scaled_min = agent_min * request.candidate_count
            scaled_max = agent_max * request.candidate_count

            total_min += scaled_min
            total_max += scaled_max

            agent_budgets[spec.agent_role] = {
                "tier": spec.tier.value,
                "cost_class": spec.cost_class.value,
                "estimated_min_usd": round(scaled_min, 6),
                "estimated_max_usd": round(scaled_max, 6),
                "candidates": request.candidate_count,
            }

        _log.info(
            "cost_estimate_computed",
            workflow_run_id=request.workflow_run_id,
            run_type=request.run_type.value,
            cost_min=round(total_min, 4),
            cost_max=round(total_max, 4),
            agent_count=len(request.agent_specs),
            candidate_count=request.candidate_count,
        )

        return CostEstimate(
            workflow_run_id=request.workflow_run_id,
            run_type=request.run_type,
            expected_cost_min_usd=round(total_min, 6),
            expected_cost_max_usd=round(total_max, 6),
            agent_budgets=agent_budgets,
            budget_state=budget_state,
        )

    def _estimate_position_review(
        self,
        request: CostEstimateRequest,
        budget_state: BudgetState,
    ) -> CostEstimate:
        """Estimate using effective cost profile for position reviews.

        ~65% of reviews are deterministic ($0), ~25% Tier B, ~10% Tier A.
        The estimate reflects the expected (weighted average) cost, not worst-case.
        """
        det_pct = POSITION_REVIEW_COST_PROFILE["deterministic_only_pct"]
        workhorse_pct = POSITION_REVIEW_COST_PROFILE["workhorse_escalation_pct"]
        premium_pct = POSITION_REVIEW_COST_PROFILE["premium_escalation_pct"]

        tier_b_range = COST_CLASS_RANGES[CostClass.M]
        tier_a_range = COST_CLASS_RANGES[CostClass.H]

        # Weighted expected cost (min uses low end, max uses high end)
        # Deterministic portion is $0
        expected_min = (
            det_pct * 0.0
            + workhorse_pct * tier_b_range[0]
            + premium_pct * tier_a_range[0]
        )
        expected_max = (
            det_pct * 0.0
            + workhorse_pct * tier_b_range[1]
            + premium_pct * tier_a_range[1]
        )

        agent_budgets = {
            "position_review_weighted": {
                "tier": "effective_profile",
                "cost_class": "weighted",
                "deterministic_pct": det_pct,
                "workhorse_pct": workhorse_pct,
                "premium_pct": premium_pct,
                "estimated_min_usd": round(expected_min, 6),
                "estimated_max_usd": round(expected_max, 6),
            }
        }

        _log.info(
            "cost_estimate_position_review",
            workflow_run_id=request.workflow_run_id,
            cost_min=round(expected_min, 6),
            cost_max=round(expected_max, 6),
        )

        return CostEstimate(
            workflow_run_id=request.workflow_run_id,
            run_type=request.run_type,
            expected_cost_min_usd=round(expected_min, 6),
            expected_cost_max_usd=round(expected_max, 6),
            agent_budgets=agent_budgets,
            budget_state=budget_state,
        )

    def _agent_cost_bounds(self, spec: AgentCostSpec) -> tuple[float, float]:
        """Compute min/max cost for a single agent.

        Uses explicit estimates from spec if provided, otherwise falls
        back to cost class ranges.
        """
        if spec.estimated_cost_min_usd > 0 or spec.estimated_cost_max_usd > 0:
            return spec.estimated_cost_min_usd, spec.estimated_cost_max_usd

        cost_class = TIER_COST_CLASS.get(spec.tier, CostClass.Z)
        cost_range = COST_CLASS_RANGES.get(cost_class, (0.0, 0.0))
        return cost_range
