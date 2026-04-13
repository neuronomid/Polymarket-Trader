"""Scanner health monitor — tracks and reports scanner subsystem health.

Integrates with degraded mode manager to provide a unified health view.
Emits ScannerHealthEvent records on infrastructure failures and transitions.

All logic is Tier D (deterministic). No LLM calls.
"""

from __future__ import annotations

from datetime import UTC, datetime

from logging_.logger import get_logger
from scanner.degraded_mode import DegradedModeManager
from scanner.types import DegradedModeLevel, ScannerHealthEvent, ScannerHealthStatus


class ScannerHealthMonitor:
    """Tracks scanner health metrics and emits health events.

    Aggregates data from the degraded mode manager, cache state,
    and poll metrics into a unified health status.
    """

    def __init__(self, degraded_mode: DegradedModeManager) -> None:
        self._degraded_mode = degraded_mode
        self._total_polls: int = 0
        self._successful_polls: int = 0
        self._failed_polls: int = 0
        self._total_triggers: int = 0
        self._health_events: list[ScannerHealthEvent] = []
        self._max_stored_events: int = 100
        self._log = get_logger(component="scanner_health_monitor")

    def record_poll_success(self, triggers_detected: int = 0) -> ScannerHealthEvent | None:
        """Record a successful poll cycle.

        Returns a health event if degraded mode recovered.
        """
        self._total_polls += 1
        self._successful_polls += 1
        self._total_triggers += triggers_detected

        event = self._degraded_mode.record_success()
        if event:
            self._store_event(event)
        return event

    def record_poll_failure(self, error: str = "") -> ScannerHealthEvent | None:
        """Record a failed poll cycle.

        Returns a health event if a degraded mode transition occurred.
        """
        self._total_polls += 1
        self._failed_polls += 1

        event = self._degraded_mode.record_failure()
        if event:
            self._store_event(event)

        # Also emit an api_failure event for tracking
        failure_event = ScannerHealthEvent(
            event_type="api_failure",
            severity="warning",
            api_available=False,
            cache_state="stale" if self._degraded_mode.is_degraded else "healthy",
            degraded_mode_level=self._degraded_mode.current_level,
            consecutive_failures=self._degraded_mode.consecutive_failures,
            last_successful_poll=self._degraded_mode.last_successful_poll,
            details=error,
        )
        self._store_event(failure_event)

        return event

    def get_health_status(self) -> ScannerHealthStatus:
        """Get the current health status snapshot."""
        dm = self._degraded_mode
        return ScannerHealthStatus(
            api_available=not dm.is_degraded,
            cache_state=self._infer_cache_state(),
            degraded_mode_level=dm.current_level,
            last_successful_poll=dm.last_successful_poll,
            consecutive_global_failures=dm.consecutive_failures,
            total_polls=self._total_polls,
            total_triggers_detected=self._total_triggers,
            degraded_since=dm.degraded_since,
            degraded_duration_seconds=dm.degraded_duration_seconds,
            size_reduction_active=dm.size_reduction_pct > 0,
            size_reduction_pct=dm.size_reduction_pct,
            position_reduction_active=dm.position_reduction_active,
        )

    def get_recent_health_events(
        self, limit: int = 20
    ) -> list[ScannerHealthEvent]:
        """Get recent health events for dashboard / logging."""
        return list(reversed(self._health_events[-limit:]))

    def _infer_cache_state(self) -> str:
        """Infer cache state description from degraded mode level."""
        level = self._degraded_mode.current_level
        if level == DegradedModeLevel.NORMAL:
            return "healthy"
        if level == DegradedModeLevel.STALE_CACHE:
            return "stale"
        return "degraded"

    def _store_event(self, event: ScannerHealthEvent) -> None:
        """Store a health event, trimming old events if needed."""
        self._health_events.append(event)
        if len(self._health_events) > self._max_stored_events:
            self._health_events = self._health_events[-self._max_stored_events:]

        self._log.info(
            "scanner_health_event",
            event_type=event.event_type,
            severity=event.severity,
            degraded_level=event.degraded_mode_level.value,
            details=event.details,
        )
