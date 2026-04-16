"""Workflow orchestration runtime types.

Pydantic models for system-wide state, pipeline stage results,
and scheduled task tracking.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class SystemPhase(str, Enum):
    """System lifecycle phases."""

    INITIALIZING = "initializing"
    STARTING = "starting"
    RUNNING = "running"
    DEGRADED = "degraded"
    SHUTTING_DOWN = "shutting_down"
    STOPPED = "stopped"


class PipelineStage(str, Enum):
    """Stages in the candidate pipeline."""

    ELIGIBILITY = "eligibility"
    INVESTIGATION = "investigation"
    TRADEABILITY = "tradeability"
    RISK_APPROVAL = "risk_approval"
    COST_APPROVAL = "cost_approval"
    EXECUTION = "execution"


class ScheduledTaskState(BaseModel):
    """Tracks state of a recurring scheduled task."""

    task_name: str
    interval_hours: float
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None
    run_count: int = 0
    last_error: str | None = None
    is_running: bool = False


class PipelineResult(BaseModel):
    """Result of processing a candidate through the full pipeline."""

    market_id: str
    stage_reached: PipelineStage
    accepted: bool = False
    reason: str = ""
    reason_code: str = ""
    reason_detail: str | None = None
    thesis_card_id: str | None = None
    execution_id: str | None = None
    total_cost_usd: float = 0.0
    duration_seconds: float = 0.0
    quantitative_context: dict[str, Any] = Field(default_factory=dict)


class SystemState(BaseModel):
    """Snapshot of the full system state for dashboard and diagnostics."""

    phase: SystemPhase = SystemPhase.STOPPED
    operator_mode: str = "paper"
    started_at: datetime | None = None
    uptime_seconds: float = 0.0

    # Subsystem status
    scanner_running: bool = False
    scanner_watch_list_size: int = 0
    dashboard_api_running: bool = False
    notification_service_running: bool = False

    # Counters
    total_scans: int = 0
    total_triggers: int = 0
    total_investigations: int = 0
    total_trades_entered: int = 0
    total_no_trade_decisions: int = 0

    # Scheduled tasks
    scheduled_tasks: list[ScheduledTaskState] = Field(default_factory=list)

    # Errors
    recent_errors: list[str] = Field(default_factory=list, max_length=50)
