"""Shadow forecast calibration store.

Manages shadow forecast collection from day one. Every investigated market
produces a shadow forecast entry. Handles recording, resolution updates,
and querying by segment.

Fully deterministic (Tier D).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Sequence

import structlog

from calibration.types import (
    BrierScoreResult,
    ShadowForecastInput,
    ShadowForecastResolution,
    SegmentType,
)

_log = structlog.get_logger(component="calibration_store")


class _ForecastEntry:
    """In-memory shadow forecast record."""

    __slots__ = (
        "forecast_id",
        "market_id",
        "workflow_run_id",
        "system_probability",
        "market_implied_probability",
        "base_rate_probability",
        "category",
        "horizon_bucket",
        "market_type",
        "ambiguity_band",
        "evidence_quality_class",
        "thesis_context",
        "forecast_at",
        "resolution_outcome",
        "resolved_at",
        "is_resolved",
        "system_brier",
        "market_brier",
        "base_rate_brier",
    )

    def __init__(self, forecast_id: str, inp: ShadowForecastInput) -> None:
        self.forecast_id = forecast_id
        self.market_id = inp.market_id
        self.workflow_run_id = inp.workflow_run_id
        self.system_probability = inp.system_probability
        self.market_implied_probability = inp.market_implied_probability
        self.base_rate_probability = inp.base_rate_probability
        self.category = inp.category
        self.horizon_bucket = inp.horizon_bucket.value if inp.horizon_bucket else None
        self.market_type = inp.market_type
        self.ambiguity_band = inp.ambiguity_band
        self.evidence_quality_class = inp.evidence_quality_class
        self.thesis_context = inp.thesis_context
        self.forecast_at = inp.forecast_at
        self.resolution_outcome: float | None = None
        self.resolved_at: datetime | None = None
        self.is_resolved = False
        self.system_brier: float | None = None
        self.market_brier: float | None = None
        self.base_rate_brier: float | None = None


class CalibrationStore:
    """Shadow forecast store for calibration data collection.

    Maintains forecasts in memory and provides segment-aware querying.
    In production, this wraps the ShadowForecastRecord repository.

    Usage:
        store = CalibrationStore()
        forecast_id = store.record_forecast(input)
        store.resolve_forecast(resolution)
        resolved = store.get_resolved_by_category("politics")
    """

    def __init__(self) -> None:
        self._forecasts: dict[str, _ForecastEntry] = {}
        self._market_index: dict[str, list[str]] = {}  # market_id -> [forecast_ids]
        self._counter = 0

    # --- Recording ---

    def record_forecast(self, inp: ShadowForecastInput) -> str:
        """Record a new shadow forecast. Returns forecast_id."""
        self._counter += 1
        forecast_id = f"sf_{self._counter:06d}"
        entry = _ForecastEntry(forecast_id, inp)
        self._forecasts[forecast_id] = entry

        if inp.market_id not in self._market_index:
            self._market_index[inp.market_id] = []
        self._market_index[inp.market_id].append(forecast_id)

        _log.info(
            "shadow_forecast_recorded",
            forecast_id=forecast_id,
            market_id=inp.market_id,
            system_prob=round(inp.system_probability, 4),
            market_prob=round(inp.market_implied_probability, 4),
            category=inp.category,
        )
        return forecast_id

    def resolve_forecast(self, resolution: ShadowForecastResolution) -> list[BrierScoreResult]:
        """Resolve all forecasts for a market and compute Brier scores.

        Returns Brier results for each resolved forecast.
        """
        forecast_ids = self._market_index.get(resolution.market_id, [])
        results: list[BrierScoreResult] = []

        for fid in forecast_ids:
            entry = self._forecasts.get(fid)
            if entry is None or entry.is_resolved:
                continue

            entry.resolution_outcome = resolution.resolution_outcome
            entry.resolved_at = resolution.resolved_at
            entry.is_resolved = True

            # Compute Brier scores
            outcome = resolution.resolution_outcome
            entry.system_brier = (entry.system_probability - outcome) ** 2
            entry.market_brier = (entry.market_implied_probability - outcome) ** 2

            if entry.base_rate_probability is not None:
                entry.base_rate_brier = (entry.base_rate_probability - outcome) ** 2

            system_advantage = entry.market_brier - entry.system_brier

            result = BrierScoreResult(
                forecast_id=fid,
                system_brier=round(entry.system_brier, 6),
                market_brier=round(entry.market_brier, 6),
                base_rate_brier=round(entry.base_rate_brier, 6) if entry.base_rate_brier is not None else None,
                system_advantage=round(system_advantage, 6),
            )
            results.append(result)

            _log.info(
                "shadow_forecast_resolved",
                forecast_id=fid,
                market_id=resolution.market_id,
                outcome=outcome,
                system_brier=result.system_brier,
                market_brier=result.market_brier,
                system_advantage=result.system_advantage,
            )

        return results

    # --- Querying ---

    def get_all_forecasts(self) -> list[_ForecastEntry]:
        """Return all forecasts."""
        return list(self._forecasts.values())

    def get_resolved(self) -> list[_ForecastEntry]:
        """Return all resolved forecasts."""
        return [e for e in self._forecasts.values() if e.is_resolved]

    def get_unresolved(self) -> list[_ForecastEntry]:
        """Return all unresolved forecasts."""
        return [e for e in self._forecasts.values() if not e.is_resolved]

    def get_resolved_by_segment(
        self,
        segment_type: SegmentType,
        segment_label: str,
    ) -> list[_ForecastEntry]:
        """Return resolved forecasts matching a segment filter.

        Maintained separately per segment: category, horizon bucket,
        market type, ambiguity band, evidence quality class.
        """
        resolved = self.get_resolved()

        if segment_type == SegmentType.OVERALL:
            return resolved

        attr_map = {
            SegmentType.CATEGORY: "category",
            SegmentType.HORIZON: "horizon_bucket",
            SegmentType.MARKET_TYPE: "market_type",
            SegmentType.AMBIGUITY: "ambiguity_band",
            SegmentType.EVIDENCE_QUALITY: "evidence_quality_class",
        }

        attr = attr_map.get(segment_type)
        if attr is None:
            return resolved

        return [e for e in resolved if getattr(e, attr, None) == segment_label]

    def get_forecasts_by_market(self, market_id: str) -> list[_ForecastEntry]:
        """Return all forecasts for a specific market."""
        forecast_ids = self._market_index.get(market_id, [])
        return [self._forecasts[fid] for fid in forecast_ids if fid in self._forecasts]

    def get_total_count(self) -> int:
        """Total number of forecasts recorded."""
        return len(self._forecasts)

    def get_resolved_count(self) -> int:
        """Number of resolved forecasts."""
        return sum(1 for e in self._forecasts.values() if e.is_resolved)

    def get_resolved_count_by_category(self, category: str) -> int:
        """Number of resolved forecasts for a specific category."""
        return sum(
            1 for e in self._forecasts.values()
            if e.is_resolved and e.category == category
        )
