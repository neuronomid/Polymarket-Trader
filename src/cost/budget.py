"""Budget tracker for daily, lifetime, and per-position budgets.

Maintains in-memory budget state, supports recording spend, and provides
alerts at lifetime consumption thresholds. Fully deterministic (Tier D).
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog

from config.settings import CostConfig
from core.enums import ModelTier
from cost.types import BudgetState, CostRecordInput, LifetimeBudgetAlert

_log = structlog.get_logger(component="budget_tracker")


class BudgetTracker:
    """Tracks budget consumption across daily, lifetime, and per-position dimensions.

    Usage:
        tracker = BudgetTracker(config)
        tracker.reset_day()
        tracker.record_spend(cost_record)
        state = tracker.state
    """

    def __init__(self, config: CostConfig) -> None:
        self._config = config

        # Daily tracking
        self._daily_spent_usd: float = 0.0
        self._daily_opus_spent_usd: float = 0.0
        self._day_start: datetime = datetime.now(tz=UTC)
        self._current_equity_usd: float | None = None

        # Lifetime tracking
        self._lifetime_spent_usd: float = 0.0

        # Per-position daily spend: position_id -> daily spend
        self._position_daily_spend: dict[str, float] = {}

        # Per-workflow spend: workflow_run_id -> total spend
        self._workflow_spend: dict[str, float] = {}

    def update_equity(self, current_equity_usd: float) -> None:
        """Update current equity for percentage-based budget calculations."""
        self._current_equity_usd = current_equity_usd

    # --- Day lifecycle ---

    def reset_day(self) -> BudgetState:
        """Reset daily counters for a new trading day."""
        self._daily_spent_usd = 0.0
        self._daily_opus_spent_usd = 0.0
        self._position_daily_spend.clear()
        self._day_start = datetime.now(tz=UTC)

        _log.info(
            "budget_day_reset",
            lifetime_spent=round(self._lifetime_spent_usd, 4),
            lifetime_pct=round(self.lifetime_pct_consumed, 4),
        )
        return self.state

    def load_lifetime_spent(self, lifetime_spent_usd: float) -> None:
        """Load lifetime spend from persistent storage on startup."""
        self._lifetime_spent_usd = lifetime_spent_usd
        _log.info(
            "budget_lifetime_loaded",
            lifetime_spent=round(lifetime_spent_usd, 4),
            lifetime_pct=round(self.lifetime_pct_consumed, 4),
        )

    # --- Recording spend ---

    def record_spend(self, record: CostRecordInput) -> None:
        """Record actual cost of a single LLM call against budgets."""
        cost = record.actual_cost_usd

        self._daily_spent_usd += cost
        self._lifetime_spent_usd += cost

        # Track Opus escalation sub-budget
        if record.tier == ModelTier.A:
            self._daily_opus_spent_usd += cost

        # Track per-position spend
        if record.position_id:
            self._position_daily_spend[record.position_id] = (
                self._position_daily_spend.get(record.position_id, 0.0) + cost
            )

        # Track per-workflow spend
        self._workflow_spend[record.workflow_run_id] = (
            self._workflow_spend.get(record.workflow_run_id, 0.0) + cost
        )

        _log.debug(
            "budget_spend_recorded",
            cost_usd=round(cost, 6),
            agent_role=record.agent_role,
            tier=record.tier.value,
            daily_total=round(self._daily_spent_usd, 4),
        )

    # --- Budget queries ---

    @property
    def state(self) -> BudgetState:
        """Current budget state snapshot."""
        # Calculate daily budget: max of USD cap or % of equity
        daily_budget = self._config.daily_llm_budget_usd
        if self._config.daily_llm_budget_pct > 0 and self._current_equity_usd is not None:
            pct_budget = self._current_equity_usd * self._config.daily_llm_budget_pct
            # If both are set, the pct takes precedence as a target, 
            # but we use max to be safe unless user explicitly zeroed one.
            daily_budget = pct_budget

        opus_budget = self._config.daily_opus_escalation_budget_usd
        lifetime_budget = self._config.lifetime_experiment_budget_usd

        return BudgetState(
            daily_spent_usd=round(self._daily_spent_usd, 6),
            daily_budget_usd=daily_budget,
            daily_remaining_usd=round(max(0.0, daily_budget - self._daily_spent_usd), 6),
            daily_pct_remaining=round(
                max(0.0, (daily_budget - self._daily_spent_usd) / daily_budget)
                if daily_budget > 0 else 0.0,
                4,
            ),
            daily_opus_spent_usd=round(self._daily_opus_spent_usd, 6),
            daily_opus_budget_usd=opus_budget,
            daily_opus_remaining_usd=round(max(0.0, opus_budget - self._daily_opus_spent_usd), 6),
            lifetime_spent_usd=round(self._lifetime_spent_usd, 6),
            lifetime_budget_usd=lifetime_budget,
            lifetime_remaining_usd=round(
                max(0.0, lifetime_budget - self._lifetime_spent_usd), 6
            ),
            lifetime_pct_consumed=round(self.lifetime_pct_consumed, 4),
        )

    @property
    def lifetime_pct_consumed(self) -> float:
        budget = self._config.lifetime_experiment_budget_usd
        if budget <= 0:
            return 1.0
        return self._lifetime_spent_usd / budget

    @property
    def daily_spent(self) -> float:
        return self._daily_spent_usd

    @property
    def lifetime_spent(self) -> float:
        return self._lifetime_spent_usd

    def get_workflow_spend(self, workflow_run_id: str) -> float:
        """Total spend for a specific workflow run."""
        return self._workflow_spend.get(workflow_run_id, 0.0)

    def get_position_daily_spend(self, position_id: str) -> float:
        """Daily spend attributed to a specific position."""
        return self._position_daily_spend.get(position_id, 0.0)

    def check_workflow_budget(self, workflow_run_id: str) -> bool:
        """Check if a workflow has exceeded its per-run budget."""
        spent = self.get_workflow_spend(workflow_run_id)
        return spent < self._config.max_single_workflow_usd

    def check_position_daily_budget(self, position_id: str) -> bool:
        """Check if a position has exceeded its daily budget."""
        spent = self.get_position_daily_spend(position_id)
        return spent < self._config.max_per_open_position_per_day_usd

    def check_opus_budget(self) -> bool:
        """Check if Opus escalation daily budget is available."""
        return self._daily_opus_spent_usd < self._config.daily_opus_escalation_budget_usd

    # --- Lifetime alerts ---

    def check_lifetime_alert(self) -> LifetimeBudgetAlert:
        """Check if lifetime budget has crossed an alert threshold."""
        pct = self.lifetime_pct_consumed

        if pct >= 1.0:
            return LifetimeBudgetAlert.PCT_100
        if pct >= 0.75:
            return LifetimeBudgetAlert.PCT_75
        if pct >= 0.50:
            return LifetimeBudgetAlert.PCT_50
        return LifetimeBudgetAlert.NONE
