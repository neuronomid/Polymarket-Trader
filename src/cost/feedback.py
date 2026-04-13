"""Estimate accuracy feedback loop.

Compares pre-run cost estimates to actual run costs and tracks accuracy
metrics separately for investigation runs, position reviews, and full
lifecycle estimates. Fully deterministic (Tier D).
"""

from __future__ import annotations

from collections import defaultdict

import structlog

from cost.types import EstimateAccuracy, RunType

_log = structlog.get_logger(component="estimate_accuracy_tracker")


class EstimateAccuracyTracker:
    """Tracks accuracy of pre-run cost estimates vs actual costs.

    Maintains separate accuracy histories for different run types to allow
    targeted recalibration.

    Usage:
        tracker = EstimateAccuracyTracker()
        accuracy = tracker.record(workflow_run_id, run_type, est_min, est_max, actual)
        stats = tracker.get_stats(RunType.TRIGGER_BASED)
    """

    def __init__(self, history_limit: int = 100) -> None:
        self._history_limit = history_limit
        # Separate histories per run type
        self._records: dict[RunType, list[EstimateAccuracy]] = defaultdict(list)

    def record(
        self,
        workflow_run_id: str,
        run_type: RunType,
        estimated_min_usd: float,
        estimated_max_usd: float,
        actual_usd: float,
    ) -> EstimateAccuracy:
        """Record an estimate vs actual comparison.

        Returns the accuracy record for this comparison.
        """
        midpoint = (estimated_min_usd + estimated_max_usd) / 2.0
        accuracy_ratio = actual_usd / midpoint if midpoint > 0 else 0.0
        within_bounds = estimated_min_usd <= actual_usd <= estimated_max_usd

        record = EstimateAccuracy(
            workflow_run_id=workflow_run_id,
            run_type=run_type,
            estimated_min_usd=estimated_min_usd,
            estimated_max_usd=estimated_max_usd,
            actual_usd=actual_usd,
            accuracy_ratio=round(accuracy_ratio, 4),
            within_bounds=within_bounds,
        )

        records = self._records[run_type]
        records.append(record)
        # Trim to limit
        if len(records) > self._history_limit:
            self._records[run_type] = records[-self._history_limit:]

        if not within_bounds:
            _log.warning(
                "cost_estimate_miss",
                workflow_run_id=workflow_run_id,
                run_type=run_type.value,
                estimated_min=round(estimated_min_usd, 4),
                estimated_max=round(estimated_max_usd, 4),
                actual=round(actual_usd, 4),
                accuracy_ratio=record.accuracy_ratio,
            )
        else:
            _log.debug(
                "cost_estimate_hit",
                workflow_run_id=workflow_run_id,
                run_type=run_type.value,
                accuracy_ratio=record.accuracy_ratio,
            )

        return record

    def get_stats(self, run_type: RunType) -> dict[str, float | int]:
        """Get accuracy statistics for a run type.

        Returns dict with: count, within_bounds_pct, mean_accuracy_ratio,
        mean_overestimate_pct, mean_underestimate_pct.
        """
        records = self._records.get(run_type, [])
        if not records:
            return {
                "count": 0,
                "within_bounds_pct": 0.0,
                "mean_accuracy_ratio": 0.0,
            }

        count = len(records)
        within = sum(1 for r in records if r.within_bounds)
        ratios = [r.accuracy_ratio for r in records]
        overestimates = [r for r in records if r.actual_usd < r.estimated_min_usd]
        underestimates = [r for r in records if r.actual_usd > r.estimated_max_usd]

        return {
            "count": count,
            "within_bounds_pct": round(within / count, 4),
            "mean_accuracy_ratio": round(sum(ratios) / count, 4),
            "overestimate_count": len(overestimates),
            "underestimate_count": len(underestimates),
        }

    def get_all_stats(self) -> dict[str, dict[str, float | int]]:
        """Get accuracy statistics across all run types."""
        return {rt.value: self.get_stats(rt) for rt in RunType}
