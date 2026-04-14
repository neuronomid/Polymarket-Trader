"""Review scheduler — tiered frequency scheduling for position reviews.

Manages review timing for all open positions based on their review tier:
- Tier 1 (New, first 48hr): every 2-4 hours
- Tier 2 (Stable): every 6-8 hours
- Tier 3 (Low-value): every 12 hours

Tier override: Level C/D triggers promote to Tier 1 immediately.

Fully deterministic (Tier D). No LLM calls.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import structlog

from config.settings import PositionReviewConfig
from core.enums import ReviewTier, TriggerLevel
from positions.types import (
    PositionSnapshot,
    ReviewMode,
    ReviewScheduleEntry,
    ReviewScheduleState,
    TriggerPromotionEvent,
)

_log = structlog.get_logger(component="review_scheduler")


# --- Tier classification logic ---


def classify_review_tier(
    position: PositionSnapshot,
    *,
    all_position_values: list[float] | None = None,
    config: PositionReviewConfig,
) -> ReviewTier:
    """Classify a position into its review tier.

    Per spec Section 11.1:
    - Tier 1 (New): first 48 hours
    - Tier 2 (Stable): no triggers in 24hr, price in thesis range, held > 48hr
    - Tier 3 (Low-value): bottom 20th percentile size, low remaining expected value

    Args:
        position: Current position snapshot.
        all_position_values: All position values for percentile computation.
        config: Review configuration thresholds.

    Returns:
        ReviewTier classification.
    """
    now = datetime.now(tz=UTC)
    hours_held = (now - position.entered_at).total_seconds() / 3600

    # Tier 1: first 48 hours
    if hours_held < config.new_position_hours:
        return ReviewTier.NEW

    # Check stability criteria for Tier 2
    is_stable = True

    # No triggers in last 24 hours
    if position.last_trigger_at is not None:
        hours_since_trigger = (now - position.last_trigger_at).total_seconds() / 3600
        if hours_since_trigger < config.stable_no_trigger_hours:
            is_stable = False

    # Price within thesis range
    if position.thesis_price_target is not None and position.thesis_price_floor is not None:
        if not (position.thesis_price_floor <= position.current_price <= position.thesis_price_target):
            is_stable = False

    # Check for low-value tier (Tier 3)
    if is_stable and all_position_values:
        sorted_values = sorted(all_position_values)
        percentile_20_idx = max(0, int(len(sorted_values) * config.low_value_percentile) - 1)
        threshold = sorted_values[percentile_20_idx]
        if position.current_value_usd <= threshold:
            return ReviewTier.LOW_VALUE

    if is_stable:
        return ReviewTier.STABLE

    # Default to NEW if not stable yet
    return ReviewTier.NEW


class ReviewScheduler:
    """Manages review scheduling for all open positions.

    Determines when each position needs its next review based on
    review tier and handles trigger-based promotions to Tier 1.

    Usage:
        scheduler = ReviewScheduler(config)
        scheduler.register_position(position_snapshot)
        due = scheduler.get_due_reviews()
        scheduler.record_review_completed(position_id)
    """

    def __init__(self, config: PositionReviewConfig) -> None:
        self._config = config
        self._positions: dict[str, _PositionScheduleState] = {}

    # --- Tier interval mapping ---

    def _interval_hours(self, tier: ReviewTier) -> float:
        """Get review interval in hours for a tier."""
        if tier == ReviewTier.NEW:
            return self._config.new_review_interval_hours
        if tier == ReviewTier.STABLE:
            return self._config.stable_review_interval_hours
        if tier == ReviewTier.LOW_VALUE:
            return self._config.low_value_review_interval_hours
        return self._config.new_review_interval_hours

    # --- Position lifecycle ---

    def register_position(self, position: PositionSnapshot) -> ReviewScheduleEntry:
        """Register a position for review scheduling.

        New positions start in Tier 1 with immediate first review scheduled.
        """
        now = datetime.now(tz=UTC)
        tier = classify_review_tier(
            position,
            config=self._config,
        )
        interval = self._interval_hours(tier)
        next_review = now + timedelta(hours=interval)

        state = _PositionScheduleState(
            position_id=position.position_id,
            market_id=position.market_id,
            review_tier=tier,
            next_review_at=next_review,
            last_review_at=None,
            entered_at=position.entered_at,
            promoted_review_mode=ReviewMode.SCHEDULED,
        )
        self._positions[position.position_id] = state

        entry = ReviewScheduleEntry(
            position_id=position.position_id,
            review_tier=tier,
            scheduled_at=next_review,
        )

        _log.info(
            "position_registered_for_review",
            position_id=position.position_id,
            tier=tier.value,
            next_review=next_review.isoformat(),
        )

        return entry

    def remove_position(self, position_id: str) -> None:
        """Remove a closed position from the scheduler."""
        self._positions.pop(position_id, None)
        _log.info("position_removed_from_schedule", position_id=position_id)

    # --- Review completion ---

    def record_review_completed(
        self,
        position_id: str,
        *,
        new_tier: ReviewTier | None = None,
        all_position_values: list[float] | None = None,
        position: PositionSnapshot | None = None,
    ) -> ReviewScheduleEntry | None:
        """Record a completed review and schedule the next one.

        Optionally reclassifies the review tier if a position snapshot
        is provided for re-evaluation.

        Returns:
            Next scheduled review entry, or None if position not tracked.
        """
        state = self._positions.get(position_id)
        if state is None:
            return None

        now = datetime.now(tz=UTC)
        state.last_review_at = now

        # Reclassify tier if requested or if position data available
        if new_tier is not None:
            state.review_tier = new_tier
        elif position is not None:
            state.review_tier = classify_review_tier(
                position,
                all_position_values=all_position_values,
                config=self._config,
            )

        # Reset trigger promotion
        state.promoted_by_trigger = False
        state.promoted_review_mode = ReviewMode.SCHEDULED

        # Schedule next review
        interval = self._interval_hours(state.review_tier)
        state.next_review_at = now + timedelta(hours=interval)

        _log.info(
            "review_completed_next_scheduled",
            position_id=position_id,
            tier=state.review_tier.value,
            next_review=state.next_review_at.isoformat(),
        )

        return ReviewScheduleEntry(
            position_id=position_id,
            review_tier=state.review_tier,
            scheduled_at=state.next_review_at,
        )

    # --- Trigger promotion ---

    def promote_to_tier_1(self, event: TriggerPromotionEvent) -> ReviewScheduleEntry | None:
        """Promote a position to Tier 1 immediately on Level C/D trigger.

        Per spec Section 11.1: Level C/D triggers promote to Tier 1 immediately.

        Returns:
            Updated schedule entry, or None if position not tracked.
        """
        if event.trigger_level not in (TriggerLevel.C, TriggerLevel.D):
            _log.debug(
                "trigger_promotion_skipped_low_level",
                position_id=event.position_id,
                trigger_level=event.trigger_level.value,
            )
            return None

        state = self._positions.get(event.position_id)
        if state is None:
            return None

        now = datetime.now(tz=UTC)
        state.review_tier = ReviewTier.NEW
        state.next_review_at = now  # immediate
        state.promoted_by_trigger = True

        _log.warning(
            "position_promoted_to_tier_1",
            position_id=event.position_id,
            trigger_class=event.trigger_class.value,
            trigger_level=event.trigger_level.value,
            reason=event.reason,
        )

        review_mode = ReviewMode.SCHEDULED
        if event.trigger_class.value == "position_stress":
            review_mode = ReviewMode.STRESS
        elif event.trigger_class.value == "profit_protection":
            review_mode = ReviewMode.PROFIT_PROTECTION
        elif event.trigger_class.value == "catalyst_window":
            review_mode = ReviewMode.CATALYST
        state.promoted_review_mode = review_mode

        return ReviewScheduleEntry(
            position_id=event.position_id,
            review_tier=ReviewTier.NEW,
            scheduled_at=now,
            review_mode=review_mode,
            promoted_by_trigger=True,
        )

    # --- Queries ---

    def get_due_reviews(self) -> list[ReviewScheduleEntry]:
        """Get all positions due for review now.

        Returns positions sorted by priority: promoted first, then by
        scheduled time.
        """
        now = datetime.now(tz=UTC)
        due: list[ReviewScheduleEntry] = []

        for state in self._positions.values():
            if state.next_review_at <= now:
                due.append(ReviewScheduleEntry(
                    position_id=state.position_id,
                    review_tier=state.review_tier,
                    scheduled_at=state.next_review_at,
                    review_mode=state.promoted_review_mode,
                    promoted_by_trigger=state.promoted_by_trigger,
                ))

        # Sort: promoted first, then by scheduled time (oldest first)
        due.sort(key=lambda e: (not e.promoted_by_trigger, e.scheduled_at))
        return due

    def get_state(self) -> ReviewScheduleState:
        """Get overall scheduler state snapshot."""
        now = datetime.now(tz=UTC)
        pending: list[ReviewScheduleEntry] = []
        overdue: list[ReviewScheduleEntry] = []

        tier_dist: dict[str, int] = {}

        for state in self._positions.values():
            tier_dist[state.review_tier.value] = tier_dist.get(state.review_tier.value, 0) + 1

            entry = ReviewScheduleEntry(
                position_id=state.position_id,
                review_tier=state.review_tier,
                scheduled_at=state.next_review_at,
                review_mode=state.promoted_review_mode,
                promoted_by_trigger=state.promoted_by_trigger,
            )

            if state.next_review_at <= now:
                overdue.append(entry)
            else:
                pending.append(entry)

        next_review = min(
            (s.next_review_at for s in self._positions.values()),
            default=None,
        )

        return ReviewScheduleState(
            pending_reviews=sorted(pending, key=lambda e: e.scheduled_at),
            overdue_reviews=sorted(overdue, key=lambda e: e.scheduled_at),
            next_review_at=next_review,
            total_positions_tracked=len(self._positions),
            tier_distribution=tier_dist,
        )

    def get_position_tier(self, position_id: str) -> ReviewTier | None:
        """Get current review tier for a position."""
        state = self._positions.get(position_id)
        return state.review_tier if state else None


class _PositionScheduleState:
    """Internal mutable state for a scheduled position."""

    __slots__ = (
        "position_id",
        "market_id",
        "review_tier",
        "next_review_at",
        "last_review_at",
        "entered_at",
        "promoted_by_trigger",
        "promoted_review_mode",
    )

    def __init__(
        self,
        position_id: str,
        market_id: str,
        review_tier: ReviewTier,
        next_review_at: datetime,
        last_review_at: datetime | None,
        entered_at: datetime,
        promoted_review_mode: ReviewMode,
    ) -> None:
        self.position_id = position_id
        self.market_id = market_id
        self.review_tier = review_tier
        self.next_review_at = next_review_at
        self.last_review_at = last_review_at
        self.entered_at = entered_at
        self.promoted_by_trigger: bool = False
        self.promoted_review_mode = promoted_review_mode
