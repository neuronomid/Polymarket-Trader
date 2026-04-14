"""Weekly bias audit report writer.

Orchestrates a complete bias audit cycle:
1. Collects forecast data from the calibration store
2. Runs the five statistical checks via BiasDetector
3. Updates pattern persistence state
4. Generates alerts

The optional Tier C summary writer is a separate concern — this module
produces the statistical facts; a Tier C agent may later describe them
in human-readable form for the audit report.

Fully deterministic (Tier D) except for the optional summary text.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import structlog

from bias.detector import BiasDetector
from bias.types import (
    BiasAuditResult,
    BiasDetectionInput,
    BiasPatternType,
    ForecastDataPoint,
)
from calibration.store import CalibrationStore

_log = structlog.get_logger(component="bias_audit")


class BiasAuditRunner:
    """Orchestrates weekly bias audit reports.

    Usage:
        runner = BiasAuditRunner(
            detector=BiasDetector(),
            calibration_store=calibration_store,
        )
        result = runner.run_weekly_audit()
    """

    DEFAULT_LOOKBACK_WEEKS = 4

    def __init__(
        self,
        detector: BiasDetector,
        calibration_store: CalibrationStore,
        lookback_weeks: int = DEFAULT_LOOKBACK_WEEKS,
    ) -> None:
        self._detector = detector
        self._store = calibration_store
        self._lookback_weeks = lookback_weeks

        # Persistent state across audits
        self._previous_pattern_weeks: dict[str, int] = {
            pt.value: 0 for pt in BiasPatternType
        }

    def run_weekly_audit(
        self,
        period_end: datetime | None = None,
    ) -> BiasAuditResult:
        """Execute a weekly bias audit.

        Collects resolved forecasts over the lookback window,
        runs all five statistical checks, and updates pattern tracking.

        Args:
            period_end: End of the audit period. Defaults to now.

        Returns:
            Complete BiasAuditResult.
        """
        if period_end is None:
            period_end = datetime.now(tz=UTC)

        period_start = period_end - timedelta(weeks=self._lookback_weeks)

        # Collect resolved forecasts from the calibration store
        forecasts = self._collect_forecast_data(period_start, period_end)

        _log.info(
            "bias_audit_starting",
            period_start=period_start.isoformat(),
            period_end=period_end.isoformat(),
            forecasts_collected=len(forecasts),
            lookback_weeks=self._lookback_weeks,
        )

        # Build detection input
        inp = BiasDetectionInput(
            forecasts=forecasts,
            period_start=period_start,
            period_end=period_end,
            previous_patterns=dict(self._previous_pattern_weeks),
        )

        # Run the detector
        result = self._detector.run_audit(inp)

        # Update persistent state
        self._previous_pattern_weeks = dict(result.pattern_weeks)

        _log.info(
            "bias_audit_complete",
            any_detected=result.any_bias_detected,
            patterns=sorted(p.value for p in result.detected_patterns),
            alerts=len(result.alerts),
            persistent_patterns=[
                k for k, v in result.pattern_weeks.items() if v >= 3
            ],
        )

        return result

    def load_pattern_state(self, pattern_weeks: dict[str, int]) -> None:
        """Load pattern persistence state from persistent storage.

        Call on startup to restore tracking across restarts.
        """
        self._previous_pattern_weeks = dict(pattern_weeks)
        _log.info(
            "bias_pattern_state_loaded",
            patterns=pattern_weeks,
        )

    def get_pattern_state(self) -> dict[str, int]:
        """Return current pattern persistence state for storage."""
        return dict(self._previous_pattern_weeks)

    def _collect_forecast_data(
        self,
        period_start: datetime,
        period_end: datetime,
    ) -> list[ForecastDataPoint]:
        """Collect resolved forecasts from calibration store.

        Converts in-memory forecast entries to ForecastDataPoint for analysis.
        """
        resolved = self._store.get_resolved()
        data_points: list[ForecastDataPoint] = []

        for entry in resolved:
            # Time filter
            if entry.resolved_at is None:
                continue
            if entry.resolved_at < period_start or entry.resolved_at > period_end:
                continue

            # Compute forecast accuracy (absolute error)
            accuracy = None
            if entry.resolution_outcome is not None:
                accuracy = abs(entry.system_probability - entry.resolution_outcome)

            # Extract evidence quality from thesis context
            eq_score = entry.thesis_context.get("evidence_quality_score") if entry.thesis_context else None

            data_points.append(
                ForecastDataPoint(
                    forecast_id=entry.forecast_id,
                    market_id=entry.market_id,
                    category=entry.category,
                    system_probability=entry.system_probability,
                    market_implied_probability=entry.market_implied_probability,
                    base_rate_probability=entry.base_rate_probability,
                    resolution_outcome=entry.resolution_outcome,
                    evidence_quality_score=eq_score,
                    forecast_accuracy=accuracy,
                    forecast_at=entry.forecast_at,
                    resolved_at=entry.resolved_at,
                )
            )

        return data_points
