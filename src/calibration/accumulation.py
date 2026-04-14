"""Calibration accumulation rate tracking and projections.

Tracks resolved trades per week per segment, projects threshold dates,
and identifies bottleneck segments.

Fully deterministic (Tier D).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import structlog

from calibration.segments import SegmentManager
from calibration.store import CalibrationStore
from calibration.types import (
    AccumulationProjection,
    AccumulationReport,
    SegmentType,
)

_log = structlog.get_logger(component="calibration_accumulation")


class AccumulationTracker:
    """Tracks calibration accumulation rates and projects threshold timelines.

    Per spec Section 15.6:
    - Resolved trades per week per segment
    - Projected threshold date per segment
    - Bottleneck segment identification
    - Recommendations when majority of segments project beyond patience budget

    Usage:
        tracker = AccumulationTracker(store, segment_manager, patience_months=9)
        report = tracker.compute_weekly_projections()
    """

    def __init__(
        self,
        store: CalibrationStore,
        segment_manager: SegmentManager,
        *,
        patience_months: int = 9,
        lookback_weeks: int = 4,
    ) -> None:
        self._store = store
        self._segments = segment_manager
        self._patience_months = patience_months
        self._lookback_weeks = lookback_weeks

    def compute_weekly_projections(
        self,
        as_of: datetime | None = None,
    ) -> AccumulationReport:
        """Compute accumulation projections for all segments.

        Returns an AccumulationReport with per-segment projections
        and bottleneck identification.
        """
        if as_of is None:
            as_of = datetime.now(tz=UTC)

        states = self._segments.compute_all_segment_states()
        projections: list[AccumulationProjection] = []
        bottlenecks: list[str] = []

        for state in states:
            rate = self._compute_resolution_rate(
                state.segment_type,
                state.segment_label,
                as_of,
            )

            remaining = max(0, state.min_threshold - state.resolved_count)

            weeks_to_threshold: float | None = None
            projected_date: datetime | None = None

            if state.threshold_met:
                weeks_to_threshold = 0.0
                projected_date = as_of
            elif rate > 0:
                weeks_to_threshold = remaining / rate
                projected_date = as_of + timedelta(weeks=weeks_to_threshold)
            # If rate is 0 and threshold not met, projection is None (indeterminate)

            is_bottleneck = self._is_bottleneck(weeks_to_threshold, as_of)

            proj = AccumulationProjection(
                segment_type=state.segment_type,
                segment_label=state.segment_label,
                current_resolved=state.resolved_count,
                target_threshold=state.min_threshold,
                resolved_per_week=round(rate, 4),
                weeks_to_threshold=round(weeks_to_threshold, 2) if weeks_to_threshold is not None else None,
                projected_threshold_date=projected_date,
                is_bottleneck=is_bottleneck,
                projected_at=as_of,
            )
            projections.append(proj)

            if is_bottleneck:
                bottlenecks.append(f"{state.segment_type.value}:{state.segment_label}")

        # Determine overall pace
        pace = self._determine_pace(projections, as_of)

        # Generate recommendation
        recommendation = None
        report = AccumulationReport(
            projections=projections,
            bottleneck_segments=bottlenecks,
            overall_pace=pace,
            generated_at=as_of,
        )

        if report.majority_beyond_patience:
            recommendation = (
                "Majority of segments project beyond patience budget. "
                "Consider focusing on shorter-horizon markets, "
                "enable cross-category pooling, or adjust thresholds."
            )
            report.recommendation = recommendation

        _log.info(
            "accumulation_projections_computed",
            total_segments=len(projections),
            bottleneck_count=len(bottlenecks),
            overall_pace=pace,
            has_recommendation=recommendation is not None,
        )

        return report

    # --- Private helpers ---

    def _compute_resolution_rate(
        self,
        segment_type: SegmentType,
        segment_label: str,
        as_of: datetime,
    ) -> float:
        """Compute resolved trades per week for a segment over lookback window."""
        entries = self._store.get_resolved_by_segment(segment_type, segment_label)
        lookback_start = as_of - timedelta(weeks=self._lookback_weeks)

        recent = [
            e for e in entries
            if e.resolved_at is not None and e.resolved_at >= lookback_start
        ]

        if not recent or self._lookback_weeks <= 0:
            # Fall back to overall rate
            if entries and entries[0].resolved_at is not None:
                first_resolved = min(e.resolved_at for e in entries if e.resolved_at is not None)
                weeks_elapsed = max(1.0, (as_of - first_resolved).total_seconds() / (7 * 86400))
                return len(entries) / weeks_elapsed
            return 0.0

        return len(recent) / self._lookback_weeks

    def _is_bottleneck(
        self,
        weeks_to_threshold: float | None,
        as_of: datetime,
    ) -> bool:
        """Determine if a segment is a bottleneck (slowest to accumulate)."""
        if weeks_to_threshold is None:
            return True  # No data to project = bottleneck

        patience_weeks = self._patience_months * 4.33  # approximate
        return weeks_to_threshold > patience_weeks

    def _determine_pace(
        self,
        projections: list[AccumulationProjection],
        as_of: datetime,
    ) -> str:
        """Determine overall accumulation pace."""
        if not projections:
            return "unknown"

        patience_weeks = self._patience_months * 4.33
        bottleneck_count = sum(1 for p in projections if p.is_bottleneck)
        total = len(projections)

        if bottleneck_count == 0:
            return "on_track"
        if bottleneck_count < total / 3:
            return "slow"
        return "critical"
