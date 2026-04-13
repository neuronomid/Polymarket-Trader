"""Degraded mode manager — time-based escalation ladder.

Manages the scanner's degraded mode state when the CLOB API becomes
unavailable. Implements the four-level ladder from Phase 5 spec:

  Level 0: Normal operation — live data flowing.
  Level 1: Cache stale (> freshness threshold) — no new discovery triggers.
  Level 2: 4+ hours — position sizes reduced 15%, review frequency up.
  Level 3: 8+ hours — graceful position reduction begins.

Recovery: API back → refill cache → return to normal.

All logic is Tier D (deterministic). No LLM calls.
"""

from __future__ import annotations

from datetime import UTC, datetime

from config.settings import ScannerConfig
from logging_.logger import get_logger
from scanner.types import DegradedModeLevel, ScannerHealthEvent


class DegradedModeManager:
    """Manages degraded mode escalation and recovery.

    Tracks API outage duration and escalates through levels.
    Provides restriction policies that downstream systems must honour.
    """

    def __init__(self, config: ScannerConfig | None = None) -> None:
        self._config = config or ScannerConfig()
        self._current_level = DegradedModeLevel.NORMAL
        self._degraded_since: datetime | None = None
        self._last_successful_poll: datetime | None = None
        self._consecutive_failures: int = 0
        self._log = get_logger(component="degraded_mode_manager")

    @property
    def current_level(self) -> DegradedModeLevel:
        return self._current_level

    @property
    def is_degraded(self) -> bool:
        return self._current_level != DegradedModeLevel.NORMAL

    @property
    def degraded_since(self) -> datetime | None:
        return self._degraded_since

    @property
    def degraded_duration_seconds(self) -> float:
        if self._degraded_since is None:
            return 0.0
        return (datetime.now(tz=UTC) - self._degraded_since).total_seconds()

    @property
    def last_successful_poll(self) -> datetime | None:
        return self._last_successful_poll

    @property
    def consecutive_failures(self) -> int:
        return self._consecutive_failures

    # --- Restriction policies ---

    @property
    def discovery_triggers_allowed(self) -> bool:
        """Whether new discovery triggers should be emitted."""
        return self._current_level == DegradedModeLevel.NORMAL

    @property
    def size_reduction_pct(self) -> float:
        """Position size reduction percentage (0.0 = no reduction)."""
        if self._current_level >= DegradedModeLevel.SIZE_REDUCTION:
            return 0.15  # 15% reduction at level 2+
        return 0.0

    @property
    def position_reduction_active(self) -> bool:
        """Whether graceful position reduction should begin."""
        return self._current_level >= DegradedModeLevel.POSITION_REDUCTION

    @property
    def stale_data_flag(self) -> bool:
        """Whether data should be flagged as stale."""
        return self._current_level >= DegradedModeLevel.STALE_CACHE

    # --- State transitions ---

    def record_success(self) -> ScannerHealthEvent | None:
        """Record a successful API poll.

        If recovering from degraded mode, emits a recovery health event.
        Returns a health event if a transition occurred, else None.
        """
        self._last_successful_poll = datetime.now(tz=UTC)
        self._consecutive_failures = 0

        if self._current_level == DegradedModeLevel.NORMAL:
            return None

        # Recovery transition
        previous_level = self._current_level
        self._current_level = DegradedModeLevel.NORMAL
        degraded_duration = self.degraded_duration_seconds
        self._degraded_since = None

        self._log.info(
            "degraded_mode_recovery",
            previous_level=previous_level.value,
            degraded_duration_seconds=degraded_duration,
        )

        return ScannerHealthEvent(
            event_type="recovery",
            severity="info",
            api_available=True,
            cache_state="healthy",
            degraded_mode_level=DegradedModeLevel.NORMAL,
            consecutive_failures=0,
            last_successful_poll=self._last_successful_poll,
            details=f"Recovered from level {previous_level.value} after {degraded_duration:.0f}s",
        )

    def record_failure(self) -> ScannerHealthEvent | None:
        """Record an API poll failure.

        Evaluates degraded mode level based on time since first failure.
        Returns a health event if a transition occurred, else None.
        """
        self._consecutive_failures += 1
        now = datetime.now(tz=UTC)

        if self._degraded_since is None:
            self._degraded_since = now

        previous_level = self._current_level
        new_level = self._compute_level(now)

        if new_level != previous_level:
            self._current_level = new_level
            return self._emit_transition_event(previous_level, new_level, now)

        return None

    def _compute_level(self, now: datetime) -> DegradedModeLevel:
        """Compute the degraded mode level based on duration."""
        if self._degraded_since is None:
            return DegradedModeLevel.NORMAL

        elapsed_hours = (now - self._degraded_since).total_seconds() / 3600.0

        if elapsed_hours >= self._config.degraded_level3_hours:
            return DegradedModeLevel.POSITION_REDUCTION
        if elapsed_hours >= self._config.degraded_level2_hours:
            return DegradedModeLevel.SIZE_REDUCTION
        if elapsed_hours >= self._config.degraded_level1_minutes / 60.0:
            return DegradedModeLevel.STALE_CACHE

        return DegradedModeLevel.NORMAL

    def _emit_transition_event(
        self,
        previous: DegradedModeLevel,
        current: DegradedModeLevel,
        now: datetime,
    ) -> ScannerHealthEvent:
        """Emit a health event for a degraded mode transition."""
        if current > previous:
            event_type = "degraded_level_change" if previous != DegradedModeLevel.NORMAL else "degraded_enter"
        else:
            event_type = "degraded_exit"

        severity_map = {
            DegradedModeLevel.NORMAL: "info",
            DegradedModeLevel.STALE_CACHE: "warning",
            DegradedModeLevel.SIZE_REDUCTION: "warning",
            DegradedModeLevel.POSITION_REDUCTION: "critical",
        }

        self._log.warning(
            "degraded_mode_transition",
            previous_level=previous.value,
            new_level=current.value,
            consecutive_failures=self._consecutive_failures,
            elapsed_hours=(now - self._degraded_since).total_seconds() / 3600.0
            if self._degraded_since
            else 0,
        )

        return ScannerHealthEvent(
            event_type=event_type,
            severity=severity_map.get(current, "warning"),
            api_available=False,
            cache_state="stale" if current >= DegradedModeLevel.STALE_CACHE else "healthy",
            degraded_mode_level=current,
            consecutive_failures=self._consecutive_failures,
            last_successful_poll=self._last_successful_poll,
            details=(
                f"Degraded mode: {previous.name} → {current.name} "
                f"({self._consecutive_failures} failures)"
            ),
            event_at=now,
        )

    def get_restrictions_summary(self) -> dict:
        """Get a summary of current degraded mode restrictions."""
        return {
            "level": self._current_level.value,
            "level_name": self._current_level.name,
            "is_degraded": self.is_degraded,
            "discovery_triggers_allowed": self.discovery_triggers_allowed,
            "size_reduction_pct": self.size_reduction_pct,
            "position_reduction_active": self.position_reduction_active,
            "stale_data_flag": self.stale_data_flag,
            "degraded_duration_seconds": self.degraded_duration_seconds,
            "consecutive_failures": self._consecutive_failures,
        }
