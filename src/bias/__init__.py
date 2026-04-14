"""Bias detection system — statistical bias checks for LLM forecasts.

All detection is statistical (Tier D). LLM involvement is limited to
a Tier C summary writer that describes statistical findings — the LLM
does NOT detect biases or interpret whether they are problematic.

Components:
- BiasDetector: five statistical checks (directional, clustering,
  anchoring, narrative overweighting, base-rate neglect)
- BiasAuditRunner: orchestrates weekly audit cycle with pattern tracking
- types: runtime Pydantic models for all bias analysis
"""

from bias.audit import BiasAuditRunner
from bias.detector import BiasDetector
from bias.types import (
    AnchoringResult,
    BaseRateNeglectResult,
    BiasAlertLevel,
    BiasAlertType,
    BiasAuditResult,
    BiasDetectionInput,
    BiasPatternAlert,
    BiasPatternType,
    ConfidenceClusteringResult,
    DirectionalBiasResult,
    ForecastDataPoint,
    NarrativeOverweightingResult,
)

__all__ = [
    "BiasAuditRunner",
    "BiasDetector",
    "AnchoringResult",
    "BaseRateNeglectResult",
    "BiasAlertLevel",
    "BiasAlertType",
    "BiasAuditResult",
    "BiasDetectionInput",
    "BiasPatternAlert",
    "BiasPatternType",
    "ConfidenceClusteringResult",
    "DirectionalBiasResult",
    "ForecastDataPoint",
    "NarrativeOverweightingResult",
]
