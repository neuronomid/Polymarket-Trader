"""Scanner runtime types — Pydantic models for trigger events and health.

These are runtime types used within the scanner module.
ORM persistence targets are in data/models/scanner.py and data/models/workflow.py.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, Field

from core.enums import TriggerClass, TriggerLevel


class DegradedModeLevel(int, Enum):
    """Degraded mode escalation levels.

    Level 0: Normal operation — cache served, live data coming in.
    Level 1: Cache stale — no new discovery triggers, stale flags set.
    Level 2: 4+ hours — position sizes reduced 15%, review frequency up.
    Level 3: 8+ hours — graceful position reduction begins.
    """

    NORMAL = 0
    STALE_CACHE = 1
    SIZE_REDUCTION = 2
    POSITION_REDUCTION = 3


class TriggerEvent(BaseModel):
    """A single trigger event detected by the scanner.

    Every detected signal is wrapped in this model with full context:
    classification, snapshot data, data source, and escalation status.
    """

    market_id: str
    token_id: str

    # Classification
    trigger_class: TriggerClass
    trigger_level: TriggerLevel

    # Snapshot at trigger time
    price: float | None = None
    spread: float | None = None
    depth_snapshot: dict | None = None

    # Change data (what caused the trigger)
    previous_value: float | None = None
    current_value: float | None = None
    change_pct: float | None = None

    # Context
    reason: str = ""
    data_source: str = "live"  # live, cache, secondary
    escalation_status: str | None = None

    # Timing
    detected_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))

    @property
    def is_actionable(self) -> bool:
        """Whether this trigger warrants downstream action (B+ level)."""
        return self.trigger_level in (TriggerLevel.B, TriggerLevel.C, TriggerLevel.D)

    @property
    def requires_immediate_action(self) -> bool:
        """Whether this is a Level D immediate risk intervention."""
        return self.trigger_level == TriggerLevel.D


class TriggerBatch(BaseModel):
    """Result of a single scan cycle across all monitored markets."""

    batch_id: str
    triggers: list[TriggerEvent] = Field(default_factory=list)
    markets_scanned: int = 0
    data_source: str = "live"
    degraded_mode_level: DegradedModeLevel = DegradedModeLevel.NORMAL
    scanned_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))

    @property
    def trigger_count(self) -> int:
        return len(self.triggers)

    @property
    def actionable_triggers(self) -> list[TriggerEvent]:
        return [t for t in self.triggers if t.is_actionable]

    @property
    def has_immediate_actions(self) -> bool:
        return any(t.requires_immediate_action for t in self.triggers)

    def triggers_by_level(self) -> dict[TriggerLevel, list[TriggerEvent]]:
        """Group triggers by level for processing priority."""
        result: dict[TriggerLevel, list[TriggerEvent]] = {}
        for t in self.triggers:
            result.setdefault(t.trigger_level, []).append(t)
        return result

    def trigger_summary(self) -> dict[str, int]:
        """Summary counts by class and level."""
        summary: dict[str, int] = {}
        for t in self.triggers:
            key = f"{t.trigger_class.value}_{t.trigger_level.value}"
            summary[key] = summary.get(key, 0) + 1
        return summary


class ScannerHealthStatus(BaseModel):
    """Current health state of the scanner subsystem."""

    api_available: bool = True
    cache_state: str = "healthy"  # healthy, stale, expired, empty
    degraded_mode_level: DegradedModeLevel = DegradedModeLevel.NORMAL
    last_successful_poll: datetime | None = None
    consecutive_global_failures: int = 0
    total_polls: int = 0
    total_triggers_detected: int = 0

    # Degraded mode timing
    degraded_since: datetime | None = None
    degraded_duration_seconds: float = 0.0

    # Position impact (from degraded mode)
    size_reduction_active: bool = False
    size_reduction_pct: float = 0.0
    position_reduction_active: bool = False

    last_updated: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))


class ScannerHealthEvent(BaseModel):
    """A health event emitted by the scanner.

    Covers API failures, degraded mode transitions, and recoveries.
    """

    event_type: str  # api_failure, degraded_enter, degraded_level_change, degraded_exit, recovery
    severity: str  # info, warning, critical
    api_available: bool
    cache_state: str
    degraded_mode_level: DegradedModeLevel
    consecutive_failures: int = 0
    last_successful_poll: datetime | None = None
    details: str = ""
    event_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))


class MarketWatchEntry(BaseModel):
    """A market being actively monitored by the scanner.

    Tracks both eligible markets and held position markets.
    """

    market_id: str
    token_id: str
    is_held_position: bool = False
    position_id: str | None = None
    category: str | None = None
    last_price: float | None = None
    last_spread: float | None = None
    last_depth_top3: float | None = None
    last_scanned_at: datetime | None = None
    catalyst_dates: list[datetime] = Field(default_factory=list)


class TriggerThresholds(BaseModel):
    """Configurable thresholds for trigger detection.

    All thresholds are deterministic — no LLM involvement.
    """

    # Price movement thresholds (as fraction, e.g. 0.05 = 5%)
    price_move_level_a: float = 0.02  # 2% — log only
    price_move_level_b: float = 0.05  # 5% — lightweight review
    price_move_level_c: float = 0.10  # 10% — full investigation
    price_move_level_d: float = 0.20  # 20% — immediate risk intervention

    # Spread thresholds (absolute values)
    spread_widen_warning: float = 0.10
    spread_widen_critical: float = 0.20
    spread_narrow_opportunity: float = 0.03

    # Depth change thresholds (as fraction of previous depth)
    depth_change_warning: float = 0.30  # 30% change
    depth_change_critical: float = 0.50  # 50% change

    # Position-specific thresholds
    position_adverse_move_b: float = 0.05
    position_adverse_move_c: float = 0.10
    position_adverse_move_d: float = 0.15
    position_favorable_move_b: float = 0.08
    position_favorable_move_c: float = 0.15

    # Catalyst window approach (hours before catalyst)
    catalyst_window_hours: float = 48.0
    catalyst_imminent_hours: float = 12.0
