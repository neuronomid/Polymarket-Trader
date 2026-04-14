"""Operator absence system — deterministic absence management.

Tracks operator interactions, enforces the escalation ladder, manages
autonomous actions during absence, and handles the return workflow.

All logic is deterministic (Tier D). The absence manager may NEVER:
- Enter new positions
- Increase sizes
- Change parameters
- Override Risk/Cost Governor
- Delay Level D interventions

Components:
- AbsenceManager: escalation ladder, restriction enforcement, return workflow
- types: runtime Pydantic models for absence tracking
"""

from absence.manager import AbsenceManager
from absence.types import (
    AbsenceAction,
    AbsenceActionRecord,
    AbsenceAlert,
    AbsenceAlertType,
    AbsenceLevel,
    ABSENCE_LEVEL_NAMES,
    AbsenceRestriction,
    AbsenceState,
    InteractionType,
    OperatorInteraction,
    OperatorReturnSummary,
)

__all__ = [
    "AbsenceManager",
    "AbsenceAction",
    "AbsenceActionRecord",
    "AbsenceAlert",
    "AbsenceAlertType",
    "AbsenceLevel",
    "ABSENCE_LEVEL_NAMES",
    "AbsenceRestriction",
    "AbsenceState",
    "InteractionType",
    "OperatorInteraction",
    "OperatorReturnSummary",
]
