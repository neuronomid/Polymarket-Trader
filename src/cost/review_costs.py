"""Cumulative review cost tracker per position.

Tracks total inference cost attributed to reviewing each position,
enforces warning (8%) and cap (15%) thresholds relative to position value.
Fully deterministic (Tier D).
"""

from __future__ import annotations

import structlog

from config.settings import CostConfig
from cost.types import ReviewCostStatus

_log = structlog.get_logger(component="cumulative_review_tracker")


class PositionReviewState:
    """In-memory state for a single position's review costs."""

    __slots__ = (
        "position_id",
        "total_review_cost_usd",
        "position_value_usd",
        "total_reviews",
        "deterministic_reviews",
        "llm_reviews",
    )

    def __init__(self, position_id: str, position_value_usd: float) -> None:
        self.position_id = position_id
        self.position_value_usd = position_value_usd
        self.total_review_cost_usd: float = 0.0
        self.total_reviews: int = 0
        self.deterministic_reviews: int = 0
        self.llm_reviews: int = 0


class CumulativeReviewTracker:
    """Tracks cumulative review cost per position and enforces caps.

    Usage:
        tracker = CumulativeReviewTracker(config)
        tracker.register_position("pos-1", position_value_usd=500.0)
        tracker.record_review("pos-1", cost_usd=0.03, is_deterministic=False)
        status = tracker.get_status("pos-1")
    """

    def __init__(self, config: CostConfig) -> None:
        self._config = config
        self._positions: dict[str, PositionReviewState] = {}

    def register_position(
        self,
        position_id: str,
        position_value_usd: float,
    ) -> None:
        """Register a position for review cost tracking."""
        if position_id not in self._positions:
            self._positions[position_id] = PositionReviewState(
                position_id=position_id,
                position_value_usd=position_value_usd,
            )

    def load_position(
        self,
        position_id: str,
        position_value_usd: float,
        total_review_cost_usd: float,
        total_reviews: int,
        deterministic_reviews: int,
        llm_reviews: int,
    ) -> None:
        """Load position state from persistent storage."""
        state = PositionReviewState(
            position_id=position_id,
            position_value_usd=position_value_usd,
        )
        state.total_review_cost_usd = total_review_cost_usd
        state.total_reviews = total_reviews
        state.deterministic_reviews = deterministic_reviews
        state.llm_reviews = llm_reviews
        self._positions[position_id] = state

    def update_position_value(self, position_id: str, new_value_usd: float) -> None:
        """Update position value (e.g., after price change)."""
        if position_id in self._positions:
            self._positions[position_id].position_value_usd = new_value_usd

    def record_review(
        self,
        position_id: str,
        cost_usd: float,
        is_deterministic: bool,
    ) -> ReviewCostStatus:
        """Record a review and return updated status.

        Args:
            position_id: Position being reviewed.
            cost_usd: Actual LLM cost (0.0 for deterministic reviews).
            is_deterministic: Whether this review was deterministic-only.

        Returns:
            Updated ReviewCostStatus with threshold flags.
        """
        if position_id not in self._positions:
            raise ValueError(f"Position {position_id} not registered for review tracking")

        state = self._positions[position_id]
        state.total_review_cost_usd += cost_usd
        state.total_reviews += 1

        if is_deterministic:
            state.deterministic_reviews += 1
        else:
            state.llm_reviews += 1

        status = self._compute_status(state)

        if status.warning_threshold_hit and not status.cap_threshold_hit:
            _log.warning(
                "review_cost_warning",
                position_id=position_id,
                cost_pct=round(status.cost_pct_of_value, 4),
                threshold=self._config.cumulative_review_cost_warning_pct,
                total_cost=round(status.total_review_cost_usd, 4),
            )
        elif status.cap_threshold_hit:
            _log.warning(
                "review_cost_cap_hit",
                position_id=position_id,
                cost_pct=round(status.cost_pct_of_value, 4),
                threshold=self._config.cumulative_review_cost_cap_pct,
                total_cost=round(status.total_review_cost_usd, 4),
            )

        return status

    def get_status(self, position_id: str) -> ReviewCostStatus | None:
        """Get current review cost status for a position."""
        state = self._positions.get(position_id)
        if state is None:
            return None
        return self._compute_status(state)

    def should_force_deterministic(self, position_id: str) -> bool:
        """Check if a position should be forced to deterministic-only reviews.

        Returns True when cumulative review cost exceeds the cap threshold (15%).
        """
        status = self.get_status(position_id)
        if status is None:
            return False
        return status.cap_threshold_hit

    def should_flag_for_exit_review(self, position_id: str) -> bool:
        """Check if a position should be flagged for cost-inefficiency exit review.

        Returns True when cumulative review cost exceeds the warning threshold (8%).
        """
        status = self.get_status(position_id)
        if status is None:
            return False
        return status.warning_threshold_hit

    def remove_position(self, position_id: str) -> None:
        """Remove a closed position from tracking."""
        self._positions.pop(position_id, None)

    def _compute_status(self, state: PositionReviewState) -> ReviewCostStatus:
        """Compute current status with threshold checks."""
        cost_pct = (
            state.total_review_cost_usd / state.position_value_usd
            if state.position_value_usd > 0
            else 0.0
        )

        return ReviewCostStatus(
            position_id=state.position_id,
            total_review_cost_usd=round(state.total_review_cost_usd, 6),
            position_value_usd=state.position_value_usd,
            cost_pct_of_value=round(cost_pct, 6),
            total_reviews=state.total_reviews,
            deterministic_reviews=state.deterministic_reviews,
            llm_reviews=state.llm_reviews,
            warning_threshold_hit=cost_pct >= self._config.cumulative_review_cost_warning_pct,
            cap_threshold_hit=cost_pct >= self._config.cumulative_review_cost_cap_pct,
        )
