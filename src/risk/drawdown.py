"""Drawdown defense ladder — state machine for capital protection.

Tracks current drawdown percentage against start-of-day equity and
escalates through 5 stages: Normal → SoftWarning → RiskReduction →
EntriesDisabled → HardKillSwitch.

Fully deterministic (Tier D). No LLM calls.
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog

from config.settings import RiskConfig
from core.enums import DrawdownLevel
from risk.types import DrawdownState


# Ordered ladder for threshold comparison (ascending severity).
_LADDER: list[tuple[DrawdownLevel, str]] = [
    (DrawdownLevel.HARD_KILL_SWITCH, "hard_kill_switch_pct"),
    (DrawdownLevel.ENTRIES_DISABLED, "entries_disabled_pct"),
    (DrawdownLevel.RISK_REDUCTION, "risk_reduction_pct"),
    (DrawdownLevel.SOFT_WARNING, "soft_warning_pct"),
]


class DrawdownTracker:
    """Stateful drawdown defense ladder.

    Call update() with current equity to recalculate drawdown level.
    The tracker remembers state across calls and logs level transitions.
    """

    def __init__(self, config: RiskConfig) -> None:
        self._config = config
        self._state = DrawdownState()
        self._log = structlog.get_logger(component="drawdown_tracker")

    @property
    def state(self) -> DrawdownState:
        return self._state

    @property
    def level(self) -> DrawdownLevel:
        return self._state.level

    def reset_day(self, start_of_day_equity: float) -> DrawdownState:
        """Reset for a new trading day with fresh start-of-day equity."""
        self._state = DrawdownState(
            level=DrawdownLevel.NORMAL,
            current_drawdown_pct=0.0,
            start_of_day_equity=start_of_day_equity,
            current_equity=start_of_day_equity,
            entries_allowed=True,
            size_multiplier=1.0,
            min_evidence_score=0.0,
        )
        self._log.info(
            "drawdown_day_reset",
            start_of_day_equity=start_of_day_equity,
        )
        return self._state

    def update(self, current_equity: float) -> DrawdownState:
        """Recalculate drawdown level from current equity.

        Returns the updated DrawdownState. Logs any level transitions.
        """
        sod = self._state.start_of_day_equity
        if sod <= 0:
            return self._state

        drawdown_pct = max(0.0, (sod - current_equity) / sod)
        previous_level = self._state.level
        new_level = self._compute_level(drawdown_pct)

        entries_allowed = new_level not in (
            DrawdownLevel.ENTRIES_DISABLED,
            DrawdownLevel.HARD_KILL_SWITCH,
        )
        size_multiplier = self._compute_size_multiplier(new_level)
        min_evidence = self._compute_min_evidence(new_level)

        self._state = DrawdownState(
            level=new_level,
            current_drawdown_pct=drawdown_pct,
            start_of_day_equity=sod,
            current_equity=current_equity,
            entries_allowed=entries_allowed,
            size_multiplier=size_multiplier,
            min_evidence_score=min_evidence,
            changed_at=datetime.now(tz=UTC) if new_level != previous_level else self._state.changed_at,
        )

        if new_level != previous_level:
            self._log.warning(
                "drawdown_level_change",
                previous_level=previous_level.value,
                new_level=new_level.value,
                drawdown_pct=round(drawdown_pct, 4),
                current_equity=current_equity,
                start_of_day_equity=sod,
            )

        return self._state

    def _compute_level(self, drawdown_pct: float) -> DrawdownLevel:
        """Determine drawdown level from percentage. Check from most severe down."""
        if drawdown_pct >= self._config.hard_kill_switch_pct:
            return DrawdownLevel.HARD_KILL_SWITCH
        if drawdown_pct >= self._config.entries_disabled_pct:
            return DrawdownLevel.ENTRIES_DISABLED
        if drawdown_pct >= self._config.risk_reduction_pct:
            return DrawdownLevel.RISK_REDUCTION
        if drawdown_pct >= self._config.soft_warning_pct:
            return DrawdownLevel.SOFT_WARNING
        return DrawdownLevel.NORMAL

    def _compute_size_multiplier(self, level: DrawdownLevel) -> float:
        """Sizing multiplier for the current drawdown level."""
        if level == DrawdownLevel.HARD_KILL_SWITCH:
            return 0.0
        if level == DrawdownLevel.ENTRIES_DISABLED:
            return 0.0
        if level == DrawdownLevel.RISK_REDUCTION:
            return self._config.risk_reduction_size_multiplier
        if level == DrawdownLevel.SOFT_WARNING:
            return self._config.soft_warning_size_multiplier
        return 1.0

    def _compute_min_evidence(self, level: DrawdownLevel) -> float:
        """Minimum evidence quality score required at this drawdown level."""
        if level in (DrawdownLevel.SOFT_WARNING, DrawdownLevel.RISK_REDUCTION):
            return self._config.min_evidence_score_soft_warning
        return 0.0
