"""Calibration & Learning System — Phase 12.

Shadow forecast collection, Brier score computation, segment management,
cross-category pooling, accumulation projections, friction model feedback,
and calibration-aware sizing.

All calibration computation is deterministic (Tier D).
"""

from calibration.types import (
    AccumulationProjection,
    AccumulationReport,
    BrierComparison,
    BrierScoreResult,
    CalibrationSizingResult,
    CalibrationSourceStatus,
    FrictionFeedback,
    HorizonBucket,
    PooledSegment,
    SegmentState,
    SegmentType,
    ShadowForecastInput,
    ShadowForecastResolution,
)
from calibration.store import CalibrationStore
from calibration.brier import BrierEngine
from calibration.segments import SegmentManager
from calibration.accumulation import AccumulationTracker
from calibration.friction import FrictionCalibrator
from calibration.sizing import CalibrationSizer

__all__ = [
    # Types
    "AccumulationProjection",
    "AccumulationReport",
    "BrierComparison",
    "BrierScoreResult",
    "CalibrationSizingResult",
    "CalibrationSourceStatus",
    "FrictionFeedback",
    "HorizonBucket",
    "PooledSegment",
    "SegmentState",
    "SegmentType",
    "ShadowForecastInput",
    "ShadowForecastResolution",
    # Components
    "CalibrationStore",
    "BrierEngine",
    "SegmentManager",
    "AccumulationTracker",
    "FrictionCalibrator",
    "CalibrationSizer",
]
