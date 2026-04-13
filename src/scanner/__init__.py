"""Trigger scanner — event-driven scanning with degraded-mode handling.

Phase 5 implementation.

Key components:
  - TriggerScanner: async polling loop (scanner.py)
  - TriggerDetector: deterministic signal detection (trigger_detector.py)
  - DegradedModeManager: time-based escalation ladder (degraded_mode.py)
  - ScannerHealthMonitor: health tracking and event emission (health_monitor.py)

All logic is Tier D (deterministic). No LLM calls in the scanner.
"""

from scanner.degraded_mode import DegradedModeManager
from scanner.health_monitor import ScannerHealthMonitor
from scanner.scanner import TriggerScanner
from scanner.trigger_detector import TriggerDetector
from scanner.types import (
    DegradedModeLevel,
    MarketWatchEntry,
    ScannerHealthEvent,
    ScannerHealthStatus,
    TriggerBatch,
    TriggerEvent,
    TriggerThresholds,
)

__all__ = [
    "DegradedModeLevel",
    "DegradedModeManager",
    "MarketWatchEntry",
    "ScannerHealthEvent",
    "ScannerHealthMonitor",
    "ScannerHealthStatus",
    "TriggerBatch",
    "TriggerDetector",
    "TriggerEvent",
    "TriggerScanner",
    "TriggerThresholds",
]
