"""Calibration segment management with thresholds and cross-category pooling.

Manages per-segment calibration state, enforces hard minimum sample thresholds,
and implements cross-category pooling with conservative penalty.

Fully deterministic (Tier D).
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog

from calibration.store import CalibrationStore
from calibration.types import (
    PooledSegment,
    SegmentState,
    SegmentThresholdConfig,
    SegmentType,
)
from config.settings import CalibrationConfig

_log = structlog.get_logger(component="calibration_segments")

# Hard minimum sample thresholds (spec Section 15.6)
DEFAULT_THRESHOLDS: list[SegmentThresholdConfig] = [
    SegmentThresholdConfig(
        segment_type=SegmentType.OVERALL,
        segment_label="initial_correction",
        min_trades=20,
    ),
    SegmentThresholdConfig(
        segment_type=SegmentType.CATEGORY,
        segment_label="*",  # all categories
        min_trades=30,
    ),
    SegmentThresholdConfig(
        segment_type=SegmentType.HORIZON,
        segment_label="*",  # all horizons
        min_trades=25,
    ),
    SegmentThresholdConfig(
        segment_type=SegmentType.CATEGORY,
        segment_label="sports",
        min_trades=40,
    ),
]

# Cross-category pooling constraints
POOL_MINIMUM_COMBINED = 15
POOL_MINIMUM_INDIVIDUAL = 5
POOL_PENALTY_FACTOR = 0.30

# Structurally incompatible categories (never pool together)
_INCOMPATIBLE_POOLS: set[frozenset[str]] = {
    frozenset({"politics", "sports"}),
    frozenset({"geopolitics", "sports"}),
}


class SegmentManager:
    """Manages calibration segments and cross-category pooling.

    Usage:
        manager = SegmentManager(store, config)
        state = manager.compute_segment_state(SegmentType.CATEGORY, "politics")
        pool = manager.attempt_cross_category_pool("technology", "macro_policy", "medium")
    """

    def __init__(
        self,
        store: CalibrationStore,
        config: CalibrationConfig | None = None,
    ) -> None:
        self._store = store
        self._config = config or CalibrationConfig()
        self._threshold_map = self._build_threshold_map()

    def compute_segment_state(
        self,
        segment_type: SegmentType,
        segment_label: str,
    ) -> SegmentState:
        """Compute the current calibration state for a segment.

        Returns segment state including Brier metrics, regime, and threshold status.
        """
        entries = self._store.get_resolved_by_segment(segment_type, segment_label)
        total = len(self._store.get_all_forecasts())  # approximate
        threshold = self._get_threshold(segment_type, segment_label)

        # Compute aggregate Brier scores
        system_brier = None
        market_brier = None
        base_rate_brier = None
        advantage = None

        if entries:
            sys_scores = [e.system_brier for e in entries if e.system_brier is not None]
            mkt_scores = [e.market_brier for e in entries if e.market_brier is not None]
            br_scores = [e.base_rate_brier for e in entries if e.base_rate_brier is not None]

            if sys_scores:
                system_brier = round(sum(sys_scores) / len(sys_scores), 6)
            if mkt_scores:
                market_brier = round(sum(mkt_scores) / len(mkt_scores), 6)
            if br_scores:
                base_rate_brier = round(sum(br_scores) / len(br_scores), 6)

            if system_brier is not None and market_brier is not None:
                advantage = round(market_brier - system_brier, 6)

        resolved_count = len(entries)
        threshold_met = resolved_count >= threshold
        regime = self._determine_regime(resolved_count, threshold, advantage)

        state = SegmentState(
            segment_type=segment_type,
            segment_label=segment_label,
            regime=regime,
            resolved_count=resolved_count,
            total_forecasts=total,
            min_threshold=threshold,
            system_brier=system_brier,
            market_brier=market_brier,
            base_rate_brier=base_rate_brier,
            system_advantage=advantage,
            threshold_met=threshold_met,
        )

        _log.debug(
            "segment_state_computed",
            segment_type=segment_type.value,
            segment_label=segment_label,
            resolved_count=resolved_count,
            threshold=threshold,
            threshold_met=threshold_met,
            regime=regime.value,
        )

        return state

    def compute_all_segment_states(self) -> list[SegmentState]:
        """Compute state for all active segments.

        Returns states for overall, each category, and each horizon bucket.
        """
        states: list[SegmentState] = []

        # Overall
        states.append(self.compute_segment_state(SegmentType.OVERALL, "all"))

        # Per category
        categories = ["politics", "geopolitics", "technology", "science_health", "macro_policy", "sports"]
        for cat in categories:
            states.append(self.compute_segment_state(SegmentType.CATEGORY, cat))

        # Per horizon
        horizons = ["short", "medium", "long", "extended"]
        for hz in horizons:
            states.append(self.compute_segment_state(SegmentType.HORIZON, hz))

        return states

    def attempt_cross_category_pool(
        self,
        category_a: str,
        category_b: str,
        shared_attribute: str,
    ) -> PooledSegment | None:
        """Attempt cross-category pooling for structurally similar segments.

        Per spec Section 15.5:
        - Conservative 30% penalty factor applied to pooled calibration
        - Combined pool minimum: 15 trades
        - Individual segment minimum within pool: 5 trades
        - Never across structurally different categories

        Args:
            category_a: First category to pool.
            category_b: Second category to pool.
            shared_attribute: Shared structural attribute (e.g., horizon bucket).

        Returns:
            PooledSegment if pooling is valid, None if incompatible.
        """
        # Check structural compatibility
        pair = frozenset({category_a, category_b})
        if pair in _INCOMPATIBLE_POOLS:
            _log.debug(
                "cross_category_pool_rejected_incompatible",
                category_a=category_a,
                category_b=category_b,
            )
            return None

        entries_a = [
            entry
            for entry in self._store.get_resolved_by_segment(SegmentType.CATEGORY, category_a)
            if entry.horizon_bucket == shared_attribute
        ]
        entries_b = [
            entry
            for entry in self._store.get_resolved_by_segment(SegmentType.CATEGORY, category_b)
            if entry.horizon_bucket == shared_attribute
        ]

        count_a = len(entries_a)
        count_b = len(entries_b)
        combined = count_a + count_b

        pool_min_met = combined >= POOL_MINIMUM_COMBINED
        individual_min_met = count_a >= POOL_MINIMUM_INDIVIDUAL and count_b >= POOL_MINIMUM_INDIVIDUAL

        # Compute pooled Brier (with penalty)
        pooled_system = None
        pooled_market = None
        pooled_advantage = None

        all_entries = entries_a + entries_b
        if all_entries:
            sys_scores = [e.system_brier for e in all_entries if e.system_brier is not None]
            mkt_scores = [e.market_brier for e in all_entries if e.market_brier is not None]

            if sys_scores and mkt_scores:
                raw_system = sum(sys_scores) / len(sys_scores)
                raw_market = sum(mkt_scores) / len(mkt_scores)

                # Apply conservative penalty: worsen system Brier by penalty factor
                pooled_system = round(raw_system * (1.0 + POOL_PENALTY_FACTOR), 6)
                pooled_market = round(raw_market, 6)
                pooled_advantage = round(pooled_market - pooled_system, 6)

        pool = PooledSegment(
            pool_label=f"{category_a}+{category_b}:{shared_attribute}",
            contributing_segments=[category_a, category_b],
            individual_counts={category_a: count_a, category_b: count_b},
            combined_resolved=combined,
            combined_forecasts=combined,
            penalty_factor=POOL_PENALTY_FACTOR,
            pooled_system_brier=pooled_system,
            pooled_market_brier=pooled_market,
            pooled_advantage=pooled_advantage,
            pool_minimum_met=pool_min_met,
            individual_minimums_met=individual_min_met,
        )

        _log.info(
            "cross_category_pool_attempted",
            pool_label=pool.pool_label,
            combined_resolved=combined,
            pool_valid=pool.is_valid,
            penalty_factor=POOL_PENALTY_FACTOR,
        )

        return pool

    def get_size_penalty_eligible(
        self,
        segment_type: SegmentType,
        segment_label: str,
    ) -> bool:
        """Check if a segment is eligible to reduce size penalties.

        Per spec: 30 resolved trades AND Brier improvement vs base rate.
        """
        state = self.compute_segment_state(segment_type, segment_label)

        if state.resolved_count < self._config.size_penalty_reduction_min_trades:
            return False

        # Must show improvement over base rate
        if state.system_brier is None or state.base_rate_brier is None:
            return False

        return state.system_brier < state.base_rate_brier

    # --- Private helpers ---

    def _build_threshold_map(self) -> dict[tuple[str, str], int]:
        """Build lookup map from config."""
        return {
            ("overall", "initial_correction"): self._config.initial_correction_min_trades,
            ("category", "*"): self._config.category_min_trades,
            ("category", "sports"): self._config.sports_min_trades,
            ("horizon", "*"): self._config.horizon_bucket_min_trades,
        }

    def _get_threshold(self, segment_type: SegmentType, segment_label: str) -> int:
        """Get the minimum sample threshold for a segment."""
        # Specific label first
        key = (segment_type.value, segment_label)
        if key in self._threshold_map:
            return self._threshold_map[key]

        # Wildcard
        wildcard_key = (segment_type.value, "*")
        if wildcard_key in self._threshold_map:
            return self._threshold_map[wildcard_key]

        # Default fallback
        return self._config.initial_correction_min_trades

    def _determine_regime(
        self,
        resolved_count: int,
        threshold: int,
        system_advantage: float | None,
    ) -> str:
        """Determine calibration regime from segment state.

        Uses CalibrationRegime values as strings for flexibility.
        """
        from core.enums import CalibrationRegime

        if resolved_count < threshold:
            return CalibrationRegime.INSUFFICIENT

        # Sufficient data but system not demonstrably better
        if system_advantage is not None and system_advantage <= 0:
            return CalibrationRegime.VIABILITY_UNCERTAIN

        return CalibrationRegime.SUFFICIENT
