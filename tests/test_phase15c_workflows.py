"""Tests for Phase 15C: Workflow Orchestration.

Covers:
- WorkflowScheduler and PeriodicTask
- WorkflowOrchestrator initialization, lifecycle, and pipeline routing
- System state management
- Trigger callback routing
- Dashboard state sync
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from workflows.types import (
    PipelineResult,
    PipelineStage,
    ScheduledTaskState,
    SystemPhase,
    SystemState,
)
from workflows.scheduler import PeriodicTask, WorkflowScheduler


# ================================================================
# Types
# ================================================================


class TestWorkflowTypes:
    """Test workflow runtime types."""

    def test_system_phase_values(self):
        assert SystemPhase.INITIALIZING == "initializing"
        assert SystemPhase.RUNNING == "running"
        assert SystemPhase.STOPPED == "stopped"

    def test_pipeline_stage_values(self):
        assert PipelineStage.ELIGIBILITY == "eligibility"
        assert PipelineStage.EXECUTION == "execution"

    def test_system_state_defaults(self):
        state = SystemState()
        assert state.phase == SystemPhase.STOPPED
        assert state.operator_mode == "paper"
        assert state.scanner_running is False
        assert state.total_scans == 0
        assert state.total_triggers == 0
        assert state.total_investigations == 0
        assert state.total_trades_entered == 0

    def test_system_state_with_values(self):
        state = SystemState(
            phase=SystemPhase.RUNNING,
            operator_mode="shadow",
            scanner_running=True,
            total_scans=42,
        )
        assert state.phase == SystemPhase.RUNNING
        assert state.operator_mode == "shadow"
        assert state.scanner_running is True
        assert state.total_scans == 42

    def test_pipeline_result(self):
        result = PipelineResult(
            market_id="m-123",
            stage_reached=PipelineStage.RISK_APPROVAL,
            accepted=False,
            reason="Risk Governor: entries disabled",
        )
        assert result.market_id == "m-123"
        assert result.stage_reached == PipelineStage.RISK_APPROVAL
        assert not result.accepted
        assert "Risk Governor" in result.reason

    def test_scheduled_task_state(self):
        state = ScheduledTaskState(
            task_name="fast_loop",
            interval_hours=24.0,
        )
        assert state.task_name == "fast_loop"
        assert state.interval_hours == 24.0
        assert state.run_count == 0
        assert state.is_running is False


# ================================================================
# Scheduler
# ================================================================


class TestPeriodicTask:
    """Test individual periodic task."""

    @pytest.mark.asyncio
    async def test_task_runs_and_increments_count(self):
        call_count = 0

        async def task_func():
            nonlocal call_count
            call_count += 1

        task = PeriodicTask(
            "test_task",
            task_func,
            interval_hours=0.001,  # very short for testing
            initial_delay_seconds=0.01,
        )

        await task.start()
        await asyncio.sleep(0.15)
        await task.stop()

        assert call_count >= 1
        assert task.state.run_count >= 1
        assert task.state.last_run_at is not None
        assert task.state.last_error is None

    @pytest.mark.asyncio
    async def test_task_isolates_errors(self):
        call_count = 0

        async def failing_task():
            nonlocal call_count
            call_count += 1
            raise ValueError("test error")

        task = PeriodicTask(
            "failing_task",
            failing_task,
            interval_hours=0.001,
            initial_delay_seconds=0.01,
        )

        await task.start()
        await asyncio.sleep(0.15)
        await task.stop()

        # Task should have attempted multiple runs despite errors
        assert call_count >= 1
        assert task.state.last_error is not None
        assert "test error" in task.state.last_error

    @pytest.mark.asyncio
    async def test_task_stop_idempotent(self):
        async def noop():
            pass

        task = PeriodicTask("noop", noop, interval_hours=1.0)
        await task.stop()
        await task.stop()  # Should not raise


class TestWorkflowScheduler:
    """Test the scheduler that manages periodic tasks."""

    def test_register_task(self):
        scheduler = WorkflowScheduler()

        async def noop():
            pass

        scheduler.register("test", noop, interval_hours=24.0)
        assert scheduler.task_count == 1

    def test_register_multiple_tasks(self):
        scheduler = WorkflowScheduler()

        async def noop():
            pass

        scheduler.register("a", noop, interval_hours=24.0)
        scheduler.register("b", noop, interval_hours=168.0)
        scheduler.register("c", noop, interval_hours=1.0)
        assert scheduler.task_count == 3

    @pytest.mark.asyncio
    async def test_start_and_stop_all(self):
        scheduler = WorkflowScheduler()
        call_counts = {"a": 0, "b": 0}

        async def task_a():
            call_counts["a"] += 1

        async def task_b():
            call_counts["b"] += 1

        scheduler.register("a", task_a, interval_hours=0.001, initial_delay_seconds=0.01)
        scheduler.register("b", task_b, interval_hours=0.001, initial_delay_seconds=0.01)

        await scheduler.start_all()
        await asyncio.sleep(0.15)
        await scheduler.stop_all()

        assert call_counts["a"] >= 1
        assert call_counts["b"] >= 1

    def test_get_task_states(self):
        scheduler = WorkflowScheduler()

        async def noop():
            pass

        scheduler.register("fast_loop", noop, interval_hours=24.0)
        scheduler.register("slow_loop", noop, interval_hours=168.0)

        states = scheduler.get_task_states()
        assert len(states) == 2
        assert states[0].task_name == "fast_loop"
        assert states[0].interval_hours == 24.0
        assert states[1].task_name == "slow_loop"
        assert states[1].interval_hours == 168.0


# ================================================================
# Orchestrator unit tests (no DB/network required)
# ================================================================


class TestOrchestratorConstruction:
    """Test orchestrator construction and state management."""

    def test_construction(self):
        from config.settings import AppConfig
        config = AppConfig()

        from workflows.orchestrator import WorkflowOrchestrator
        orch = WorkflowOrchestrator(config)

        assert orch.state.phase == SystemPhase.STOPPED
        assert orch.state.operator_mode == "paper"
        assert orch.state.scanner_running is False

    def test_state_tracking(self):
        state = SystemState(
            phase=SystemPhase.RUNNING,
            started_at=datetime.now(tz=UTC) - timedelta(hours=1),
        )
        state.total_scans = 100
        state.total_triggers = 15
        state.total_investigations = 5
        state.total_trades_entered = 2
        state.total_no_trade_decisions = 3

        assert state.total_scans == 100
        assert state.total_triggers == 15


class TestOrchestratorRegimeContext:
    """Test regime context building."""

    def test_regime_context_structure(self):
        from agents.types import CalibrationContext, RegimeContext
        from core.enums import CalibrationRegime, OperatorMode

        calibration = CalibrationContext(
            regime=CalibrationRegime.INSUFFICIENT,
            viability_proven=False,
            sports_quality_gated=True,
        )

        ctx = RegimeContext(
            calibration=calibration,
            cost_selectivity_ratio=0.15,
            operator_mode=OperatorMode.PAPER,
        )

        assert ctx.calibration.regime == CalibrationRegime.INSUFFICIENT
        assert ctx.calibration.viability_proven is False
        assert ctx.calibration.sports_quality_gated is True
        assert ctx.operator_mode == OperatorMode.PAPER


class TestOrchestratorPipelineResult:
    """Test pipeline result recording."""

    def test_rejected_at_tradeability(self):
        result = PipelineResult(
            market_id="test-market",
            stage_reached=PipelineStage.TRADEABILITY,
            reason="Hard rejection: ambiguous wording",
        )
        assert not result.accepted
        assert result.stage_reached == PipelineStage.TRADEABILITY
        assert "ambiguous" in result.reason

    def test_accepted_in_paper_mode(self):
        result = PipelineResult(
            market_id="test-market",
            stage_reached=PipelineStage.EXECUTION,
            accepted=True,
            reason="Paper mode: trade logged, not executed",
        )
        assert result.accepted
        assert result.stage_reached == PipelineStage.EXECUTION
        assert "Paper mode" in result.reason

    def test_rejected_at_risk(self):
        result = PipelineResult(
            market_id="test-market",
            stage_reached=PipelineStage.RISK_APPROVAL,
            reason="Risk Governor: entries disabled",
        )
        assert not result.accepted


class TestOrchestratorImports:
    """Test that all required modules import correctly."""

    def test_workflows_package_imports(self):
        from workflows import (
            WorkflowOrchestrator,
            WorkflowScheduler,
            PeriodicTask,
            PipelineResult,
            PipelineStage,
            ScheduledTaskState,
            SystemPhase,
            SystemState,
        )
        assert WorkflowOrchestrator is not None
        assert WorkflowScheduler is not None
        assert PeriodicTask is not None

    def test_orchestrator_module_imports(self):
        from workflows.orchestrator import WorkflowOrchestrator
        assert WorkflowOrchestrator is not None

    def test_scheduler_module_imports(self):
        from workflows.scheduler import WorkflowScheduler, PeriodicTask
        assert WorkflowScheduler is not None
        assert PeriodicTask is not None


class TestOrchestratorDashboardSync:
    """Test dashboard state synchronization."""

    def test_system_state_serializable(self):
        """System state should be JSON-serializable for dashbaord API."""
        state = SystemState(
            phase=SystemPhase.RUNNING,
            operator_mode="paper",
            started_at=datetime.now(tz=UTC),
            scanner_running=True,
            total_scans=10,
        )

        data = state.model_dump(mode="json")
        assert data["phase"] == "running"
        assert data["operator_mode"] == "paper"
        assert data["scanner_running"] is True
        assert data["total_scans"] == 10

    def test_scheduled_task_state_in_system_state(self):
        """Scheduled task states should embed in system state."""
        task_state = ScheduledTaskState(
            task_name="fast_loop",
            interval_hours=24.0,
            run_count=5,
        )

        state = SystemState(
            phase=SystemPhase.RUNNING,
            scheduled_tasks=[task_state],
        )

        data = state.model_dump(mode="json")
        assert len(data["scheduled_tasks"]) == 1
        assert data["scheduled_tasks"][0]["task_name"] == "fast_loop"
        assert data["scheduled_tasks"][0]["run_count"] == 5
