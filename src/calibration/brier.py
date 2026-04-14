"""Brier score computation engine.

Computes shadow-vs-market Brier comparison weekly.
Supports system, market, and parallel base-rate benchmarks.
Aggregates at: strategy level, per category, per horizon, per time period.

Fully deterministic (Tier D).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import structlog

from calibration.store import CalibrationStore
from calibration.types import BrierComparison, SegmentType

_log = structlog.get_logger(component="brier_engine")


class BrierEngine:
    """Computes aggregated Brier score comparisons across segments.

    Usage:
        engine = BrierEngine(store)
        comparisons = engine.compute_weekly_comparison(period_end)
        cat_comparison = engine.compute_segment_comparison(
            SegmentType.CATEGORY, "politics", period_start, period_end
        )
    """

    def __init__(self, store: CalibrationStore) -> None:
        self._store = store

    def compute_weekly_comparison(
        self,
        period_end: datetime | None = None,
    ) -> list[BrierComparison]:
        """Compute weekly shadow-vs-market Brier comparison.

        Produces comparisons at: overall, per category, per horizon, per period.
        Returns list of BrierComparison for each scope.
        """
        if period_end is None:
            period_end = datetime.now(tz=UTC)

        period_start = period_end - timedelta(days=7)
        comparisons: list[BrierComparison] = []

        # Overall
        overall = self._compute_for_scope(
            scope="overall",
            scope_label="all",
            segment_type=SegmentType.OVERALL,
            segment_label="all",
            period_start=period_start,
            period_end=period_end,
        )
        if overall is not None:
            comparisons.append(overall)

        # Per category
        categories = self._get_distinct_values("category")
        for cat in categories:
            comp = self._compute_for_scope(
                scope="category",
                scope_label=cat,
                segment_type=SegmentType.CATEGORY,
                segment_label=cat,
                period_start=period_start,
                period_end=period_end,
            )
            if comp is not None:
                comparisons.append(comp)

        # Per horizon
        horizons = self._get_distinct_values("horizon_bucket")
        for hz in horizons:
            comp = self._compute_for_scope(
                scope="horizon",
                scope_label=hz,
                segment_type=SegmentType.HORIZON,
                segment_label=hz,
                period_start=period_start,
                period_end=period_end,
            )
            if comp is not None:
                comparisons.append(comp)

        _log.info(
            "weekly_brier_comparison_complete",
            period_start=period_start.isoformat(),
            period_end=period_end.isoformat(),
            comparisons_count=len(comparisons),
        )

        return comparisons

    def compute_segment_comparison(
        self,
        segment_type: SegmentType,
        segment_label: str,
        period_start: datetime | None = None,
        period_end: datetime | None = None,
    ) -> BrierComparison | None:
        """Compute Brier comparison for a specific segment and time range.

        If no time range given, uses all resolved forecasts in segment.
        """
        if period_end is None:
            period_end = datetime.now(tz=UTC)
        if period_start is None:
            period_start = datetime.min.replace(tzinfo=UTC)

        return self._compute_for_scope(
            scope=segment_type.value,
            scope_label=segment_label,
            segment_type=segment_type,
            segment_label=segment_label,
            period_start=period_start,
            period_end=period_end,
        )

    def compute_cumulative_comparison(self) -> BrierComparison | None:
        """Compute cumulative (all-time) Brier comparison."""
        return self._compute_for_scope(
            scope="cumulative",
            scope_label="all_time",
            segment_type=SegmentType.OVERALL,
            segment_label="all",
            period_start=datetime.min.replace(tzinfo=UTC),
            period_end=datetime.now(tz=UTC),
        )

    # --- Private helpers ---

    def _compute_for_scope(
        self,
        *,
        scope: str,
        scope_label: str,
        segment_type: SegmentType,
        segment_label: str,
        period_start: datetime,
        period_end: datetime,
    ) -> BrierComparison | None:
        """Compute Brier comparison for a scope/segment with time filter."""
        entries = self._store.get_resolved_by_segment(segment_type, segment_label)

        # Time filter
        filtered = [
            e for e in entries
            if e.resolved_at is not None
            and period_start <= e.resolved_at <= period_end
        ]

        if not filtered:
            return None

        total_system = 0.0
        total_market = 0.0
        total_base = 0.0
        base_count = 0

        for e in filtered:
            if e.system_brier is not None:
                total_system += e.system_brier
            if e.market_brier is not None:
                total_market += e.market_brier
            if e.base_rate_brier is not None:
                total_base += e.base_rate_brier
                base_count += 1

        count = len(filtered)
        avg_system = total_system / count
        avg_market = total_market / count
        avg_base = total_base / base_count if base_count > 0 else None
        advantage = avg_market - avg_system

        return BrierComparison(
            scope=scope,
            scope_label=scope_label,
            period_start=period_start,
            period_end=period_end,
            system_brier=round(avg_system, 6),
            market_brier=round(avg_market, 6),
            base_rate_brier=round(avg_base, 6) if avg_base is not None else None,
            system_advantage=round(advantage, 6),
            resolved_count=count,
        )

    def _get_distinct_values(self, attr: str) -> list[str]:
        """Get distinct non-None values of an attribute from resolved forecasts."""
        resolved = self._store.get_resolved()
        values = set()
        for e in resolved:
            val = getattr(e, attr, None)
            if val is not None:
                values.add(val)
        return sorted(values)
