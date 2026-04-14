"""Patience budget tracker.

Tracks the experiment patience budget (default 9 months from shadow mode start).
At expiry, operator must explicitly decide whether to continue, adjust, or terminate.
Operator silence does NOT extend the budget.

Fully deterministic (Tier D).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import structlog

from learning.types import PatienceBudgetState, PatienceDecision

_log = structlog.get_logger(component="patience_budget")


class PatienceBudgetTracker:
    """Tracks the experiment patience budget.

    Per spec Section 15.13:
    - Default 9 months from shadow mode start
    - At expiry: comprehensive viability report required
    - Operator must explicitly decide (continue/adjust/terminate)
    - Operator silence does NOT extend the budget

    Usage:
        tracker = PatienceBudgetTracker(start_date, budget_months=9)
        state = tracker.compute_state()
        if state.needs_decision:
            # prompt operator for decision
            tracker.record_decision(PatienceDecision.CONTINUE)
    """

    def __init__(
        self,
        start_date: datetime,
        budget_months: int = 9,
    ) -> None:
        self._start_date = start_date
        self._budget_months = budget_months
        self._expiry_date = self._compute_expiry(start_date, budget_months)
        self._decision: PatienceDecision | None = None
        self._decision_at: datetime | None = None

    def compute_state(
        self,
        as_of: datetime | None = None,
    ) -> PatienceBudgetState:
        """Compute the current patience budget state."""
        now = as_of or datetime.now(tz=UTC)

        elapsed = now - self._start_date
        total = self._expiry_date - self._start_date

        elapsed_days = max(0, int(elapsed.total_seconds() / 86400))
        total_days = max(1, int(total.total_seconds() / 86400))
        remaining_days = max(0, total_days - elapsed_days)
        elapsed_pct = min(1.0, elapsed_days / total_days)

        is_expired = now >= self._expiry_date

        state = PatienceBudgetState(
            start_date=self._start_date,
            expiry_date=self._expiry_date,
            budget_months=self._budget_months,
            elapsed_days=elapsed_days,
            remaining_days=remaining_days,
            elapsed_pct=round(elapsed_pct, 4),
            is_expired=is_expired,
            operator_decision=self._decision,
            decision_at=self._decision_at,
        )

        if is_expired and self._decision is None:
            _log.warning(
                "patience_budget_expired_no_decision",
                elapsed_days=elapsed_days,
                expiry_date=self._expiry_date.isoformat(),
            )

        return state

    def record_decision(
        self,
        decision: PatienceDecision,
        decided_at: datetime | None = None,
    ) -> None:
        """Record operator's decision at patience budget expiry.

        Args:
            decision: Operator's explicit choice.
            decided_at: When the decision was made.
        """
        self._decision = decision
        self._decision_at = decided_at or datetime.now(tz=UTC)

        _log.info(
            "patience_budget_decision_recorded",
            decision=decision.value,
            decided_at=self._decision_at.isoformat(),
        )

        if decision == PatienceDecision.CONTINUE:
            # Extend budget by the same duration
            self._expiry_date = self._compute_expiry(
                self._decision_at, self._budget_months
            )
            _log.info(
                "patience_budget_extended",
                new_expiry=self._expiry_date.isoformat(),
            )

    def is_expired(self, as_of: datetime | None = None) -> bool:
        """Check if patience budget is expired."""
        now = as_of or datetime.now(tz=UTC)
        return now >= self._expiry_date

    def needs_decision(self, as_of: datetime | None = None) -> bool:
        """Check if expired and no decision has been made."""
        return self.is_expired(as_of) and self._decision is None

    @property
    def expiry_date(self) -> datetime:
        return self._expiry_date

    @property
    def start_date(self) -> datetime:
        return self._start_date

    @staticmethod
    def _compute_expiry(start: datetime, months: int) -> datetime:
        """Compute expiry date from start + months."""
        # Approximate month as 30.44 days
        return start + timedelta(days=months * 30.44)
