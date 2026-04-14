"""Execution Engine — Phase 10.

Translates approved, validated trade decisions into actual Polymarket
orders. Fully deterministic (Tier D). Records realized slippage for
friction model calibration.

Components:
- ExecutionEngine: Pre-execution revalidation + order placement
- SlippageTracker: Realized vs estimated slippage recording
- FrictionModelCalibrator: Statistical parameter adjustment

No LLM calls in any execution component.
"""

from execution.engine import ExecutionEngine
from execution.friction import FrictionModelCalibrator
from execution.slippage import SlippageTracker
from execution.types import (
    EntryMode,
    ExecutionLogEntry,
    ExecutionOutcome,
    ExecutionRequest,
    ExecutionResult,
    FrictionModelState,
    RevalidationCheck,
    RevalidationCheckName,
    RevalidationResult,
    SlippageRecord,
)

__all__ = [
    "ExecutionEngine",
    "FrictionModelCalibrator",
    "SlippageTracker",
    "EntryMode",
    "ExecutionLogEntry",
    "ExecutionOutcome",
    "ExecutionRequest",
    "ExecutionResult",
    "FrictionModelState",
    "RevalidationCheck",
    "RevalidationCheckName",
    "RevalidationResult",
    "SlippageRecord",
]
