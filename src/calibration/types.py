"""Calibration system runtime types.

Pydantic models for shadow forecast collection, Brier score computation,
segment state tracking, cross-category pooling, accumulation projections,
and friction model calibration feedback.

All calibration computation is deterministic (Tier D).
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from core.enums import CalibrationRegime, Category


# --- Enums ---


class SegmentType(str, Enum):
    """Types of calibration segments."""

    OVERALL = "overall"
    CATEGORY = "category"
    HORIZON = "horizon"
    MARKET_TYPE = "market_type"
    AMBIGUITY = "ambiguity"
    EVIDENCE_QUALITY = "evidence_quality"


class HorizonBucket(str, Enum):
    """Time horizon buckets for calibration segmentation."""

    SHORT = "short"        # < 3 days
    MEDIUM = "medium"      # 3-14 days
    LONG = "long"          # 14-60 days
    EXTENDED = "extended"  # > 60 days


class CalibrationSourceStatus(str, Enum):
    """Calibration data status per segment."""

    NO_DATA = "no_data"
    INSUFFICIENT = "insufficient"
    PRELIMINARY = "preliminary"
    RELIABLE = "reliable"


# --- Shadow Forecast ---


class ShadowForecastInput(BaseModel):
    """Input for recording a shadow forecast.

    Every investigated market produces a shadow forecast from day one,
    regardless of whether a trade is placed.
    """

    market_id: str
    workflow_run_id: str | None = None

    # Probabilities
    system_probability: float
    market_implied_probability: float
    base_rate_probability: float | None = None

    # Segment classification
    category: str
    horizon_bucket: HorizonBucket | None = None
    market_type: str | None = None
    ambiguity_band: str | None = None
    evidence_quality_class: str | None = None

    # Full thesis context (stored for future reference)
    thesis_context: dict[str, Any] = Field(default_factory=dict)

    forecast_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))


class ShadowForecastResolution(BaseModel):
    """Resolution data for updating a shadow forecast."""

    market_id: str
    resolution_outcome: float  # 1.0 for Yes, 0.0 for No
    resolved_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))


# --- Brier Scores ---


class BrierScoreResult(BaseModel):
    """Result of a Brier score computation for a single forecast."""

    forecast_id: str
    system_brier: float
    market_brier: float
    base_rate_brier: float | None = None
    system_advantage: float  # market_brier - system_brier (positive = system better)


class BrierComparison(BaseModel):
    """Aggregated Brier comparison for a scope (weekly)."""

    scope: str  # overall, category, horizon, period
    scope_label: str
    period_start: datetime
    period_end: datetime

    system_brier: float
    market_brier: float
    base_rate_brier: float | None = None
    system_advantage: float  # market_brier - system_brier

    resolved_count: int
    compared_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))

    @property
    def system_is_better(self) -> bool:
        """System outperforms market (lower Brier is better)."""
        return self.system_advantage > 0.0


# --- Segment State ---


class SegmentState(BaseModel):
    """Current calibration state for a single segment."""

    segment_type: SegmentType
    segment_label: str

    regime: CalibrationRegime = CalibrationRegime.INSUFFICIENT
    resolved_count: int = 0
    total_forecasts: int = 0
    min_threshold: int = 20

    # Brier metrics
    system_brier: float | None = None
    market_brier: float | None = None
    base_rate_brier: float | None = None
    system_advantage: float | None = None

    threshold_met: bool = False
    updated_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))

    @property
    def source_status(self) -> CalibrationSourceStatus:
        """Derive calibration source status from data availability."""
        if self.resolved_count == 0:
            return CalibrationSourceStatus.NO_DATA
        if not self.threshold_met:
            return CalibrationSourceStatus.INSUFFICIENT
        if self.resolved_count < self.min_threshold * 2:
            return CalibrationSourceStatus.PRELIMINARY
        return CalibrationSourceStatus.RELIABLE

    @property
    def needs_more_data(self) -> bool:
        return self.resolved_count < self.min_threshold


class SegmentThresholdConfig(BaseModel):
    """Threshold configuration for a calibration segment type."""

    segment_type: SegmentType
    segment_label: str
    min_trades: int


# --- Cross-Category Pooling ---


class PooledSegment(BaseModel):
    """Result of cross-category pooling for structurally similar segments."""

    pool_label: str
    contributing_segments: list[str] = Field(default_factory=list)
    individual_counts: dict[str, int] = Field(default_factory=dict)

    # Pooled metrics (with penalty)
    combined_resolved: int = 0
    combined_forecasts: int = 0
    penalty_factor: float = 0.30  # conservative 30%
    pooled_system_brier: float | None = None
    pooled_market_brier: float | None = None
    pooled_advantage: float | None = None

    # Validation
    pool_minimum_met: bool = False  # combined >= 15
    individual_minimums_met: bool = False  # each segment >= 5

    @property
    def is_valid(self) -> bool:
        """Pool is valid when both minimums are met."""
        return self.pool_minimum_met and self.individual_minimums_met


# --- Accumulation Tracking ---


class AccumulationProjection(BaseModel):
    """Projected timeline for reaching calibration threshold in a segment."""

    segment_type: SegmentType
    segment_label: str

    current_resolved: int
    target_threshold: int
    resolved_per_week: float
    weeks_to_threshold: float | None = None
    projected_threshold_date: datetime | None = None
    is_bottleneck: bool = False

    projected_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))


class AccumulationReport(BaseModel):
    """Summary of calibration accumulation across all segments."""

    projections: list[AccumulationProjection] = Field(default_factory=list)
    bottleneck_segments: list[str] = Field(default_factory=list)
    overall_pace: str = "unknown"  # on_track, slow, critical
    recommendation: str | None = None  # e.g., "focus on shorter-horizon markets"
    generated_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))

    @property
    def majority_beyond_patience(self) -> bool:
        """Whether majority of segments project beyond patience budget."""
        if not self.projections:
            return False
        beyond = sum(
            1 for p in self.projections
            if p.projected_threshold_date is None  # no data to project
            or p.is_bottleneck
        )
        return beyond > len(self.projections) / 2


# --- Friction Model Feedback ---


class FrictionFeedback(BaseModel):
    """Friction model calibration feedback result.

    Compares realized vs estimated slippage over a window of trades.
    """

    mean_slippage_ratio: float  # realized / estimated
    trades_in_window: int
    window_size: int = 20

    needs_tightening: bool = False    # ratio > 1.5
    can_relax: bool = False           # ratio < 0.7 (below by > 30%)
    adjustment_factor: float = 1.0    # multiplier to apply

    # Current parameters
    current_spread_estimate: float = 0.0
    current_depth_assumption: float = 0.0
    current_impact_coefficient: float = 0.0

    # Proposed adjustments
    proposed_spread_estimate: float | None = None
    proposed_depth_assumption: float | None = None
    proposed_impact_coefficient: float | None = None

    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))


# --- Sizing Under Calibration ---


class CalibrationSizingResult(BaseModel):
    """Position sizing adjustment based on calibration regime.

    In insufficient calibration: hard size caps, conservative penalties.
    In sufficient calibration: calibrated estimates replace raw model.
    """

    regime: CalibrationRegime
    base_size_usd: float
    adjusted_size_usd: float
    size_cap_multiplier: float = 1.0

    # Adjustments applied
    calibration_adjustment: float = 1.0
    sports_adjustment: float = 1.0
    category_adjustment: float = 1.0

    # Source probabilities
    raw_model_probability: float | None = None
    calibrated_probability: float | None = None
    used_calibrated: bool = False

    reason: str = ""
