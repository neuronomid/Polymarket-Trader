"""Workflow Orchestration — Phase 15C.

Wires all 13 subsystems into a coordinated end-to-end pipeline:

    Eligibility Intake → Trigger Scanner → Investigator → Tradeability →
    Risk/Cost Approval → Execution → Position Review → Calibration →
    Performance Review → Policy Review → Viability → Bias Audit →
    Absence Management

Key components:
- WorkflowOrchestrator: central coordinator, owns system lifecycle
- WorkflowScheduler: periodic background task management
- PeriodicTask: individual recurring task with error isolation
"""

from workflows.orchestrator import WorkflowOrchestrator
from workflows.scheduler import PeriodicTask, WorkflowScheduler
from workflows.types import (
    PipelineResult,
    PipelineStage,
    ScheduledTaskState,
    SystemPhase,
    SystemState,
)

__all__ = [
    "WorkflowOrchestrator",
    "WorkflowScheduler",
    "PeriodicTask",
    "PipelineResult",
    "PipelineStage",
    "ScheduledTaskState",
    "SystemPhase",
    "SystemState",
]
