"""Cost Governor — deterministic cost control authority.

Orchestrates pre-run cost estimation, budget enforcement, cost-of-selectivity
monitoring, cumulative review cost tracking, and estimate accuracy feedback.

Fully deterministic (Tier D). No LLM may override the Cost Governor.
"""

from __future__ import annotations

import structlog

from config.settings import CostConfig
from core.enums import ModelTier
from cost.budget import BudgetTracker
from cost.estimator import PreRunCostEstimator
from cost.feedback import EstimateAccuracyTracker
from cost.review_costs import CumulativeReviewTracker
from cost.selectivity import SelectivityMonitor
from cost.types import (
    CostApproval,
    CostDecision,
    CostEstimate,
    CostEstimateRequest,
    CostRecordInput,
    EstimateAccuracy,
    ReviewCostStatus,
    RunType,
    SelectivitySnapshot,
)

_log = structlog.get_logger(component="cost_governor")


class CostGovernor:
    """Top-level cost authority for the trading system.

    Prevents inference cost from consuming expected edge. Every workflow
    must obtain Cost Governor pre-approval before starting.

    Usage:
        governor = CostGovernor(config)
        governor.reset_day()

        estimate = governor.estimate(request)
        approval = governor.approve(estimate, expected_net_edge=0.05)
        if approval.is_approved:
            # proceed with workflow
            pass

        # After workflow completes:
        governor.record_spend(cost_record)
        governor.record_estimate_accuracy(workflow_run_id, run_type, est_min, est_max, actual)
    """

    def __init__(self, config: CostConfig) -> None:
        self._config = config
        self._estimator = PreRunCostEstimator(config)
        self._budget = BudgetTracker(config)
        self._selectivity = SelectivityMonitor(config)
        self._review_costs = CumulativeReviewTracker(config)
        self._feedback = EstimateAccuracyTracker()
        self._log = structlog.get_logger(component="cost_governor")

    # --- Accessors ---

    @property
    def budget_tracker(self) -> BudgetTracker:
        return self._budget

    @property
    def selectivity_monitor(self) -> SelectivityMonitor:
        return self._selectivity

    @property
    def review_tracker(self) -> CumulativeReviewTracker:
        return self._review_costs

    @property
    def feedback_tracker(self) -> EstimateAccuracyTracker:
        return self._feedback

    # --- Day lifecycle ---

    def reset_day(self) -> None:
        """Reset daily counters for a new trading day."""
        self._budget.reset_day()
        self._selectivity.start_day()
        self._log.info("cost_governor_day_reset")

    def update_equity(self, current_equity_usd: float) -> None:
        """Update current equity for dynamic budget calculations."""
        self._budget.update_equity(current_equity_usd)

    # --- Core workflow: estimate → approve → record ---

    def estimate(self, request: CostEstimateRequest) -> CostEstimate:
        """Compute pre-run cost estimate for a workflow.

        This must be called before every investigation or review workflow.
        """
        budget_state = self._budget.state
        return self._estimator.estimate(request, budget_state)

    def approve(
        self,
        estimate: CostEstimate,
        expected_net_edge: float | None = None,
    ) -> CostApproval:
        """Make approval decision based on estimate and current budget state.

        Decision logic (from spec Section 11.3):
        1. expected_max within budget → approve at full tier
        2. expected_max breaches daily but min does not → approve at reduced tier
        3. even min breaches daily budget → defer (Level D never deferred)
        4. estimated cost exceeds configured fraction of net edge → reject
        5. daily < 10% AND lifetime > 75% consumed → restrict to Tier B max
        """
        budget = self._budget.state
        selectivity = self._selectivity.compute_snapshot()

        cost_min = estimate.expected_cost_min_usd
        cost_max = estimate.expected_cost_max_usd

        # Rule 4: Cost-inefficiency check (if net edge provided)
        if expected_net_edge is not None and expected_net_edge > 0:
            cost_edge_fraction = cost_max / expected_net_edge
            if cost_edge_fraction > self._config.cost_inefficient_edge_fraction:
                return self._decision(
                    CostDecision.REJECT,
                    f"Estimated cost ${cost_max:.4f} exceeds "
                    f"{self._config.cost_inefficient_edge_fraction:.0%} of net edge ${expected_net_edge:.4f}",
                    selectivity=selectivity,
                )

        # Rule: Lifetime budget exhausted → pause new investigations (Level D never blocked)
        if budget.lifetime_remaining_usd <= 0:
            return self._decision(
                CostDecision.REJECT,
                "Lifetime experiment budget exhausted",
                selectivity=selectivity,
            )

        # Rule 3: Even min breaches daily budget → defer
        if cost_min > budget.daily_remaining_usd:
            return self._decision(
                CostDecision.DEFER,
                f"Even minimum cost ${cost_min:.4f} exceeds daily remaining ${budget.daily_remaining_usd:.4f}",
                selectivity=selectivity,
            )

        # Rule 5: Daily < 10% AND lifetime > 75% → restrict to Tier B max
        if budget.daily_budget_critically_low and budget.lifetime_heavily_consumed:
            return self._decision(
                CostDecision.APPROVE_REDUCED,
                "Daily budget critically low and lifetime heavily consumed — restricted to Tier B maximum",
                max_tier=ModelTier.B,
                max_cost=budget.daily_remaining_usd,
                selectivity=selectivity,
            )

        # Rule 2: Max breaches daily but min does not → approve reduced
        if cost_max > budget.daily_remaining_usd:
            return self._decision(
                CostDecision.APPROVE_REDUCED,
                f"Max cost ${cost_max:.4f} exceeds daily remaining — approved at reduced tier/scope",
                max_tier=ModelTier.B,
                max_cost=budget.daily_remaining_usd,
                selectivity=selectivity,
            )

        # Rule: Check Opus sub-budget if workflow includes Tier A agents
        if not self._budget.check_opus_budget():
            return self._decision(
                CostDecision.APPROVE_REDUCED,
                "Daily Opus escalation budget exhausted — restricted to Tier B maximum",
                max_tier=ModelTier.B,
                max_cost=cost_max,
                selectivity=selectivity,
            )

        # Rule 1: All within budget → approve full
        return self._decision(
            CostDecision.APPROVE_FULL,
            "Within all budget constraints",
            max_tier=ModelTier.A,
            max_cost=cost_max,
            selectivity=selectivity,
        )

    # --- Post-run recording ---

    def record_spend(self, record: CostRecordInput) -> None:
        """Record actual cost of a single LLM call.

        Updates budget tracker and selectivity monitor.
        """
        self._budget.record_spend(record)
        self._selectivity.record_daily_spend(record.actual_cost_usd)

    def record_estimate_accuracy(
        self,
        workflow_run_id: str,
        run_type: RunType,
        estimated_min_usd: float,
        estimated_max_usd: float,
        actual_usd: float,
    ) -> EstimateAccuracy:
        """Record estimate vs actual for the feedback loop."""
        return self._feedback.record(
            workflow_run_id=workflow_run_id,
            run_type=run_type,
            estimated_min_usd=estimated_min_usd,
            estimated_max_usd=estimated_max_usd,
            actual_usd=actual_usd,
        )

    # --- Selectivity ---

    def record_trade_entered(self, count: int = 1) -> None:
        """Record trades entered for selectivity tracking."""
        self._selectivity.record_trade_entered(count)

    def record_gross_edge(self, edge_usd: float) -> None:
        """Record realized gross edge for selectivity tracking."""
        self._selectivity.record_gross_edge(edge_usd)

    def get_selectivity_snapshot(self) -> SelectivitySnapshot:
        """Get current cost-of-selectivity metrics."""
        return self._selectivity.compute_snapshot()

    def get_opus_escalation_threshold(self, standard_minimum: float) -> float:
        """Get adjusted Opus escalation threshold based on selectivity."""
        return self._selectivity.compute_opus_escalation_threshold(standard_minimum)

    # --- Review costs ---

    def register_position(self, position_id: str, position_value_usd: float) -> None:
        """Register a position for review cost tracking."""
        self._review_costs.register_position(position_id, position_value_usd)

    def record_review(
        self,
        position_id: str,
        cost_usd: float,
        is_deterministic: bool,
    ) -> ReviewCostStatus:
        """Record a position review and get updated cost status."""
        return self._review_costs.record_review(position_id, cost_usd, is_deterministic)

    def should_force_deterministic_review(self, position_id: str) -> bool:
        """Check if position should be forced to deterministic-only reviews."""
        return self._review_costs.should_force_deterministic(position_id)

    def should_flag_exit_review(self, position_id: str) -> bool:
        """Check if position should be flagged for cost-inefficiency exit review."""
        return self._review_costs.should_flag_for_exit_review(position_id)

    def get_review_status(self, position_id: str) -> ReviewCostStatus | None:
        """Get review cost status for a position."""
        return self._review_costs.get_status(position_id)

    # --- Quick checks ---

    def can_start_workflow(self) -> tuple[bool, str]:
        """Quick check: is there budget to start any workflow?"""
        budget = self._budget.state

        if budget.lifetime_remaining_usd <= 0:
            return False, "Lifetime experiment budget exhausted"

        if budget.daily_remaining_usd <= 0:
            return False, "Daily budget exhausted"

        return True, "Budget available"

    # --- Private ---

    def _decision(
        self,
        decision: CostDecision,
        reason: str,
        max_tier: ModelTier | None = None,
        max_cost: float | None = None,
        selectivity: SelectivitySnapshot | None = None,
    ) -> CostApproval:
        """Build a CostApproval with logging."""
        selectivity_ratio = (
            selectivity.cost_to_edge_ratio if selectivity else None
        )
        opus_threshold = None
        if selectivity_ratio is not None and selectivity_ratio > self._config.cost_of_selectivity_target_ratio:
            opus_threshold = self._selectivity.compute_opus_escalation_threshold(0.0)

        approval = CostApproval(
            decision=decision,
            reason=reason,
            approved_max_tier=max_tier,
            approved_max_cost_usd=round(max_cost, 6) if max_cost is not None else None,
            cost_selectivity_ratio=round(selectivity_ratio, 6) if selectivity_ratio is not None else None,
            opus_escalation_threshold=round(opus_threshold, 6) if opus_threshold is not None else None,
        )

        self._log.info(
            "cost_governor_decision",
            decision=decision.value,
            reason=reason,
            max_tier=max_tier.value if max_tier else None,
            max_cost=max_cost,
        )

        return approval
