"""Operator absence manager.

Deterministic (Tier D) system that tracks operator interactions,
computes absence level via timestamp comparison, enforces escalation
ladder restrictions, and manages the return workflow.

Escalation ladder:
- 0-48hr: Normal
- 48-72hr: Absent Level 1 — no new positions, increased review, alerts
- 72-96hr: Absent Level 2 — 25% size reduction, escalated alert
- 96-120hr: Absent Level 3 — additional 25% reduction, wind-down prep
- 120hr+: Graceful Wind-Down — close targets → break-even → scheduled

May NEVER during absence:
- Enter new positions
- Increase sizes
- Change parameters
- Override Risk/Cost Governor
- Delay Level D interventions

May ONLY:
- Maintain or reduce positions
- Increase review frequency
- Close at targets/expiry
- Execute Risk Governor forced reductions
- Send alerts

Critical alerts via at least two independent channels.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import structlog

from absence.types import (
    AbsenceAction,
    AbsenceActionRecord,
    AbsenceAlert,
    AbsenceAlertType,
    AbsenceLevel,
    AbsenceRestriction,
    AbsenceState,
    ABSENCE_LEVEL_NAMES,
    InteractionType,
    OperatorInteraction,
    OperatorReturnSummary,
)
from config.settings import AbsenceConfig

_log = structlog.get_logger(component="absence_manager")

# All restrictions enforced from Level 1 onward
_ABSENCE_RESTRICTIONS: list[AbsenceRestriction] = [
    AbsenceRestriction.NO_NEW_POSITIONS,
    AbsenceRestriction.NO_SIZE_INCREASES,
    AbsenceRestriction.NO_PARAMETER_CHANGES,
    AbsenceRestriction.NO_GOVERNOR_OVERRIDE,
    AbsenceRestriction.NO_DELAY_LEVEL_D,
]

# Actions allowed during absence
_ALLOWED_ACTIONS: list[AbsenceAction] = [
    AbsenceAction.MAINTAIN_POSITIONS,
    AbsenceAction.REDUCE_POSITIONS,
    AbsenceAction.INCREASE_REVIEW_FREQUENCY,
    AbsenceAction.CLOSE_AT_TARGETS,
    AbsenceAction.CLOSE_AT_EXPIRY,
    AbsenceAction.EXECUTE_RISK_FORCED_REDUCTIONS,
    AbsenceAction.SEND_ALERTS,
]

# Channels for critical alerts (minimum two independent)
DEFAULT_ALERT_CHANNELS = ["telegram", "email"]

# Wind-down target: zero positions in 72 hours
WINDDOWN_TARGET_HOURS = 72


class AbsenceManager:
    """Operator absence manager with full escalation ladder.

    Tracks operator interactions, computes absence level, enforces
    restrictions, records autonomous actions, and manages the return workflow.

    Usage:
        manager = AbsenceManager(config)
        manager.record_interaction(OperatorInteraction(...))
        state = manager.compute_state()
        if manager.is_restricted(AbsenceRestriction.NO_NEW_POSITIONS):
            # block new entries
    """

    def __init__(self, config: AbsenceConfig) -> None:
        self._config = config
        self._last_interaction: OperatorInteraction | None = None
        self._peak_absence_level = AbsenceLevel.NORMAL
        self._actions_taken: list[AbsenceActionRecord] = []
        self._alerts_sent: list[AbsenceAlert] = []
        self._winddown_started_at: datetime | None = None
        self._size_reductions_applied: dict[int, float] = {}  # level -> pct applied
        self._previously_escalated_to: AbsenceLevel = AbsenceLevel.NORMAL
        self._return_ack_pending = False
        self._return_duration_hours: float | None = None

    # --- Interaction Recording ---

    def record_interaction(self, interaction: OperatorInteraction) -> AbsenceState:
        """Record an operator interaction and recompute state.

        Any interaction resets the absence timer.
        """
        prior_level = AbsenceLevel.NORMAL
        prior_hours = 0.0
        if self._last_interaction is not None:
            prior_hours = (
                interaction.interacted_at - self._last_interaction.interacted_at
            ).total_seconds() / 3600.0
            prior_level = self._compute_level(prior_hours)

        self._last_interaction = interaction

        _log.info(
            "operator_interaction_recorded",
            interaction_type=interaction.interaction_type.value,
            interaction_at=interaction.interacted_at.isoformat(),
        )

        if prior_level >= AbsenceLevel.ABSENT_LEVEL_1:
            self._return_ack_pending = True
            self._return_duration_hours = round(max(prior_hours, 0.0), 2)

        state = self.compute_state(now=interaction.interacted_at)

        # If returning from absence, initiate return workflow
        if prior_level >= AbsenceLevel.ABSENT_LEVEL_1 and state.absence_level == AbsenceLevel.NORMAL:
            _log.info(
                "operator_returned_from_absence",
                peak_level=self._peak_absence_level.value,
                actions_during_absence=len(self._actions_taken),
            )

        return state

    def set_last_interaction_time(self, at: datetime) -> None:
        """Set the last interaction time (for startup/persistence loading)."""
        self._last_interaction = OperatorInteraction(
            interaction_type=InteractionType.LOGIN,
            interacted_at=at,
        )

    # --- State Computation ---

    def compute_state(self, now: datetime | None = None) -> AbsenceState:
        """Compute current absence state from timestamps.

        This is pure timestamp comparison — no LLM, no external calls.
        """
        if now is None:
            now = datetime.now(tz=UTC)

        if self._last_interaction is None:
            # No interaction recorded — treat as just started
            return AbsenceState(
                absence_level=AbsenceLevel.NORMAL,
                absence_level_name="normal",
                hours_since_last_interaction=0.0,
                computed_at=now,
                allowed_actions=list(_ALLOWED_ACTIONS),
            )

        hours = (now - self._last_interaction.interacted_at).total_seconds() / 3600.0
        level = self._compute_level(hours)

        # Track peak level for return summary
        if level.value > self._peak_absence_level.value:
            self._peak_absence_level = level

        return_ack_pending = self._return_ack_pending and level == AbsenceLevel.NORMAL

        # Compute size reduction
        total_reduction = self._compute_total_reduction(level)
        if return_ack_pending:
            total_reduction = self._compute_total_reduction(self._peak_absence_level)

        # Determine restrictions and allowed actions
        restrictions: list[AbsenceRestriction] = []
        allowed_actions = list(_ALLOWED_ACTIONS)
        winddown_active = False
        winddown_target_zero: datetime | None = None

        if level >= AbsenceLevel.ABSENT_LEVEL_1 or return_ack_pending:
            restrictions = list(_ABSENCE_RESTRICTIONS)

        if level >= AbsenceLevel.GRACEFUL_WINDDOWN:
            winddown_active = True
            if self._winddown_started_at is None:
                self._winddown_started_at = now
            winddown_target_zero = self._winddown_started_at + timedelta(hours=WINDDOWN_TARGET_HOURS)

        state = AbsenceState(
            absence_level=level,
            absence_level_name=ABSENCE_LEVEL_NAMES[level],
            hours_since_last_interaction=round(hours, 2),
            last_interaction_at=self._last_interaction.interacted_at,
            last_interaction_type=self._last_interaction.interaction_type,
            total_size_reduction_pct=round(total_reduction, 4),
            restrictions=restrictions,
            allowed_actions=allowed_actions,
            winddown_active=winddown_active,
            winddown_started_at=self._winddown_started_at,
            winddown_target_zero_at=winddown_target_zero,
            computed_at=now,
        )

        # Generate escalation alerts if level changed upward
        if level > self._previously_escalated_to:
            self._generate_escalation_alerts(level, hours, now)

        self._previously_escalated_to = level

        return state

    # --- Restriction Checks ---

    def is_absent(self) -> bool:
        """Check if operator is currently absent (Level 1+)."""
        state = self.compute_state()
        return state.absence_level >= AbsenceLevel.ABSENT_LEVEL_1

    def is_restricted(self, restriction: AbsenceRestriction) -> bool:
        """Check if a specific restriction is currently in effect."""
        state = self.compute_state()
        return restriction in state.restrictions

    def can_enter_new_positions(self) -> bool:
        """Check if new position entry is allowed."""
        return not self.is_restricted(AbsenceRestriction.NO_NEW_POSITIONS)

    def can_increase_sizes(self) -> bool:
        """Check if position size increases are allowed."""
        return not self.is_restricted(AbsenceRestriction.NO_SIZE_INCREASES)

    def get_size_reduction_pct(self) -> float:
        """Get the current total size reduction percentage."""
        state = self.compute_state()
        return state.total_size_reduction_pct

    # --- Action Recording ---

    def record_action(self, action: AbsenceActionRecord) -> None:
        """Record an autonomous action taken during absence."""
        self._actions_taken.append(action)
        _log.info(
            "absence_action_recorded",
            action=action.action.value,
            level=action.absence_level.value,
            description=action.description,
            positions=len(action.positions_affected),
        )

    # --- Return Workflow ---

    def generate_return_summary(self) -> OperatorReturnSummary:
        """Generate a summary of autonomous actions taken during absence.

        This is presented to the operator when they return.
        Explicit acknowledgment required before normal operation resumes.
        """
        peak_name = ABSENCE_LEVEL_NAMES.get(
            self._peak_absence_level, "unknown"
        )

        # Collect affected positions
        reduced = set()
        closed = set()
        for a in self._actions_taken:
            if a.action in (AbsenceAction.REDUCE_POSITIONS,):
                reduced.update(a.positions_affected)
            elif a.action in (AbsenceAction.CLOSE_AT_TARGETS, AbsenceAction.CLOSE_AT_EXPIRY):
                closed.update(a.positions_affected)

        hours = self._return_duration_hours or 0.0
        if hours == 0.0 and self._last_interaction is not None:
            hours = (
                datetime.now(tz=UTC) - self._last_interaction.interacted_at
            ).total_seconds() / 3600.0

        summary = OperatorReturnSummary(
            absence_duration_hours=round(hours, 2),
            peak_absence_level=self._peak_absence_level,
            peak_absence_level_name=peak_name,
            actions_taken=list(self._actions_taken),
            positions_reduced=sorted(reduced),
            positions_closed=sorted(closed),
            alerts_sent=len(self._alerts_sent),
            total_size_reduction_pct=self._compute_total_reduction(
                self._peak_absence_level
            ),
        )

        _log.info(
            "return_summary_generated",
            duration_hours=summary.absence_duration_hours,
            peak_level=self._peak_absence_level.value,
            actions=len(summary.actions_taken),
            positions_reduced=len(summary.positions_reduced),
            positions_closed=len(summary.positions_closed),
        )

        return summary

    def acknowledge_return(self, summary: OperatorReturnSummary) -> AbsenceState:
        """Process operator acknowledgment of return summary.

        Normal operation resumes only after acknowledgment.
        Reduced positions are NOT automatically re-entered.
        """
        summary.acknowledged = True
        summary.acknowledged_at = datetime.now(tz=UTC)

        # Reset absence tracking
        self._peak_absence_level = AbsenceLevel.NORMAL
        self._actions_taken.clear()
        self._alerts_sent.clear()
        self._winddown_started_at = None
        self._size_reductions_applied.clear()
        self._previously_escalated_to = AbsenceLevel.NORMAL
        self._return_ack_pending = False
        self._return_duration_hours = None

        # Record the return as an interaction
        interaction = OperatorInteraction(
            interaction_type=InteractionType.ALERT_ACKNOWLEDGMENT,
            details={"event": "return_acknowledged"},
        )
        state = self.record_interaction(interaction)

        _log.info(
            "operator_return_acknowledged",
            acknowledged_at=summary.acknowledged_at.isoformat(),
        )

        return state

    # --- Private Helpers ---

    def _compute_level(self, hours: float) -> AbsenceLevel:
        """Compute absence level from hours since last interaction."""
        if hours >= self._config.graceful_winddown_hours:
            return AbsenceLevel.GRACEFUL_WINDDOWN
        if hours >= self._config.second_size_reduction_hours:
            return AbsenceLevel.ABSENT_LEVEL_3
        if hours >= self._config.first_size_reduction_hours:
            return AbsenceLevel.ABSENT_LEVEL_2
        if hours >= self._config.no_new_entries_hours:
            return AbsenceLevel.ABSENT_LEVEL_1
        return AbsenceLevel.NORMAL

    def _compute_total_reduction(self, level: AbsenceLevel) -> float:
        """Compute total cumulative size reduction for a given level."""
        reduction = 0.0
        if level >= AbsenceLevel.ABSENT_LEVEL_2:
            reduction += self._config.first_size_reduction_pct
        if level >= AbsenceLevel.ABSENT_LEVEL_3:
            reduction += self._config.second_size_reduction_pct
        # At wind-down, full reduction (target zero)
        if level >= AbsenceLevel.GRACEFUL_WINDDOWN:
            reduction = 1.0  # targeting zero exposure
        return min(reduction, 1.0)

    def _generate_escalation_alerts(
        self,
        level: AbsenceLevel,
        hours: float,
        now: datetime,
    ) -> None:
        """Generate alerts for absence level escalation."""
        if level == AbsenceLevel.ABSENT_LEVEL_1:
            alert = AbsenceAlert(
                alert_type=AbsenceAlertType.ABSENCE_MODE_ACTIVATED,
                absence_level=level,
                message=(
                    f"Operator absent for {hours:.1f} hours. "
                    f"Level 1: No new positions, increased review frequency."
                ),
                channels=DEFAULT_ALERT_CHANNELS,
                generated_at=now,
            )
        elif level == AbsenceLevel.ABSENT_LEVEL_2:
            alert = AbsenceAlert(
                alert_type=AbsenceAlertType.ABSENCE_SIZE_REDUCTION,
                absence_level=level,
                message=(
                    f"Operator absent for {hours:.1f} hours. "
                    f"Level 2: 25% position size reduction applied."
                ),
                channels=DEFAULT_ALERT_CHANNELS,
                generated_at=now,
            )
        elif level == AbsenceLevel.ABSENT_LEVEL_3:
            alert = AbsenceAlert(
                alert_type=AbsenceAlertType.ABSENCE_ESCALATED,
                absence_level=level,
                message=(
                    f"Operator absent for {hours:.1f} hours. "
                    f"Level 3: Additional 25% reduction, wind-down preparation."
                ),
                channels=DEFAULT_ALERT_CHANNELS,
                generated_at=now,
            )
        elif level == AbsenceLevel.GRACEFUL_WINDDOWN:
            alert = AbsenceAlert(
                alert_type=AbsenceAlertType.ABSENCE_WINDDOWN_STARTED,
                absence_level=level,
                message=(
                    f"Operator absent for {hours:.1f} hours. "
                    f"GRACEFUL WIND-DOWN: Closing positions to zero in 72 hours."
                ),
                channels=DEFAULT_ALERT_CHANNELS,
                generated_at=now,
            )
        else:
            return

        self._alerts_sent.append(alert)
        _log.warning(
            "absence_alert_generated",
            alert_type=alert.alert_type.value,
            level=level.value,
            hours=round(hours, 1),
        )
