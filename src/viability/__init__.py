"""Strategy viability system — deterministic viability checkpoints.

Evaluates strategy viability at scheduled checkpoints (weeks 4, 8, 12)
and budget thresholds (50%, 75%, 100%). All determination is by
deterministic threshold comparison (Tier D), not LLM.

Components:
- ViabilityProcessor: checkpoint evaluation and budget tracking
- types: runtime Pydantic models for viability analysis
"""

from viability.processor import ViabilityProcessor
from viability.types import (
    LifetimeBudgetState,
    ViabilityAlert,
    ViabilityAlertType,
    ViabilityCheckpointInput,
    ViabilityCheckpointResult,
    ViabilityCheckpointType,
    ViabilityMetrics,
    ViabilityStatus,
)

__all__ = [
    "ViabilityProcessor",
    "LifetimeBudgetState",
    "ViabilityAlert",
    "ViabilityAlertType",
    "ViabilityCheckpointInput",
    "ViabilityCheckpointResult",
    "ViabilityCheckpointType",
    "ViabilityMetrics",
    "ViabilityStatus",
]
