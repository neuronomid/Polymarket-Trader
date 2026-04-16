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
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import JSON, event, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core.enums import CostClass, ModelTier
from data.base import Base
from execution.types import EntryMode, ExecutionRequest
from scanner.types import MarketWatchEntry
from workflows.types import (
    PipelineResult,
    PipelineStage,
    ScheduledTaskState,
    SystemPhase,
    SystemState,
)
from workflows.scheduler import PeriodicTask, WorkflowScheduler


class _FakeScanner:
    """Minimal scanner stub for paper-trade and trigger-candidate tests."""

    def __init__(self) -> None:
        self._by_token: dict[str, MarketWatchEntry] = {}
        self._by_market: dict[str, MarketWatchEntry] = {}

    def get_watch_entry(self, token_id: str) -> MarketWatchEntry | None:
        return self._by_token.get(token_id)

    def get_watch_entry_by_market(self, market_id: str) -> MarketWatchEntry | None:
        return self._by_market.get(market_id)

    def add_to_watch_list(self, entry: MarketWatchEntry) -> None:
        self._by_token[entry.token_id] = entry
        self._by_market[entry.market_id] = entry

    def update_watch_entry(self, token_id: str, **updates) -> None:
        entry = self._by_token.get(token_id)
        if entry is None:
            return
        for key, value in updates.items():
            setattr(entry, key, value)

    def get_watch_list(self) -> list[MarketWatchEntry]:
        return list(self._by_market.values())


async def _make_isolated_session_factory():
    """Create an isolated in-memory SQLite session factory for workflow integration tests."""
    eng = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
    )

    @event.listens_for(eng.sync_engine, "connect")
    def set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    for table in Base.metadata.tables.values():
        for column in table.columns:
            if isinstance(column.type, JSONB):
                column.type = JSON()

    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    return eng, async_sessionmaker(
        bind=eng,
        class_=AsyncSession,
        expire_on_commit=False,
    )


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

    def test_record_investigation_spend_updates_cost_governor(self):
        from config.settings import AppConfig
        from workflows.orchestrator import WorkflowOrchestrator

        orch = WorkflowOrchestrator(AppConfig())
        orch._cost_governor = MagicMock()
        orch._sync_dashboard_state = MagicMock()

        result = MagicMock(
            actual_cost_usd=0.069174,
            models_used=["claude-sonnet-4-6"],
        )

        orch._record_investigation_spend("wf-123", result)

        orch._cost_governor.record_spend.assert_called_once()
        record = orch._cost_governor.record_spend.call_args.args[0]
        assert record.workflow_run_id == "wf-123"
        assert record.actual_cost_usd == 0.069174
        assert record.tier == ModelTier.B
        assert record.cost_class == CostClass.M
        assert record.provider == "openrouter"
        orch._sync_dashboard_state.assert_called_once()


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


class TestOrchestratorScheduledSweepPersistence:
    """Test scheduled sweep workflow persistence."""

    @pytest.mark.asyncio
    async def test_scheduled_sweep_persists_no_candidate_run(self):
        from config.settings import AppConfig
        from workflows.orchestrator import WorkflowOrchestrator

        orch = WorkflowOrchestrator(AppConfig())
        orch._absence_manager = MagicMock()
        orch._absence_manager.can_enter_new_positions.return_value = True
        orch._risk_governor = MagicMock()
        orch._risk_governor.can_trade.return_value = (True, None)
        orch._cost_governor = MagicMock()
        orch._cost_governor.can_start_workflow.return_value = (True, None)
        orch._market_data = MagicMock()
        orch._market_data.discover_markets = AsyncMock(return_value=[])
        orch._scanner = MagicMock()
        orch._scanner.get_watch_list.return_value = []
        orch._persist_workflow_run = AsyncMock()

        await orch._run_scheduled_sweep()

        assert orch._persist_workflow_run.await_count == 2
        running_call, completed_call = orch._persist_workflow_run.await_args_list

        assert running_call.kwargs["run_type"] == "scheduled_sweep"
        assert running_call.kwargs["status"] == "running"

        assert completed_call.kwargs["run_type"] == "scheduled_sweep"
        assert completed_call.kwargs["status"] == "completed"
        assert completed_call.kwargs["outcome"] == "no_trade"
        assert completed_call.kwargs["outcome_reason"] == "No eligible investigate-now candidates"

    @pytest.mark.asyncio
    async def test_scheduled_sweep_persists_completed_run(self):
        from config.settings import AppConfig
        from workflows.orchestrator import WorkflowOrchestrator

        orch = WorkflowOrchestrator(AppConfig())
        orch._absence_manager = MagicMock()
        orch._absence_manager.can_enter_new_positions.return_value = True
        orch._risk_governor = MagicMock()
        orch._risk_governor.can_trade.return_value = (True, None)
        orch._cost_governor = MagicMock()
        orch._cost_governor.can_start_workflow.return_value = (True, None)
        orch._scanner = MagicMock()
        orch._scanner.get_watch_list.return_value = []

        market = SimpleNamespace(
            market_id="m-123",
            title="Will rates stay flat?",
            description="",
            category="macro_policy",
            slug="will-rates-stay-flat",
            tags=[],
            liquidity=500000.0,
            spread=0.01,
            end_date=datetime.now(tz=UTC) + timedelta(days=7),
            resolution_source="polymarket.com",
            token_ids=["tok-123"],
        )
        orch._market_data = MagicMock()
        orch._market_data.discover_markets = AsyncMock(return_value=[market])
        orch._eligibility = MagicMock()
        orch._eligibility.evaluate.return_value = SimpleNamespace(
            outcome="investigate_now",
            category_classification=SimpleNamespace(
                category="macro_policy",
                quality_tier="standard",
            ),
        )
        orch._investigator = MagicMock()
        orch._investigator.run = AsyncMock(
            return_value=SimpleNamespace(
                actual_cost_usd=0.12,
                thesis_cards=[],
                no_trade_results=[
                    SimpleNamespace(reason="Candidate did not survive investigation")
                ],
                candidates_evaluated=1,
                candidates_accepted=0,
                agent_costs={},
            )
        )
        orch._build_regime_context = MagicMock(return_value=MagicMock())
        orch._record_investigation_spend = MagicMock()
        orch._process_thesis_card = AsyncMock()
        orch._persist_workflow_run = AsyncMock()

        await orch._run_scheduled_sweep()

        assert orch._investigator.run.await_count == 1
        assert orch._persist_workflow_run.await_count == 2
        running_call, completed_call = orch._persist_workflow_run.await_args_list

        assert running_call.kwargs["status"] == "running"
        assert completed_call.kwargs["status"] == "completed"
        assert completed_call.kwargs["actual_cost_usd"] == 0.12
        assert completed_call.kwargs["outcome"] == "no_trade"
        assert completed_call.kwargs["outcome_reason"] == "Candidate did not survive investigation"

    @pytest.mark.asyncio
    async def test_scheduled_sweep_persists_failures(self):
        from config.settings import AppConfig
        from workflows.orchestrator import WorkflowOrchestrator

        orch = WorkflowOrchestrator(AppConfig())
        orch._absence_manager = MagicMock()
        orch._absence_manager.can_enter_new_positions.return_value = True
        orch._risk_governor = MagicMock()
        orch._risk_governor.can_trade.return_value = (True, None)
        orch._cost_governor = MagicMock()
        orch._cost_governor.can_start_workflow.return_value = (True, None)
        orch._market_data = MagicMock()
        orch._market_data.discover_markets = AsyncMock(side_effect=RuntimeError("gamma down"))
        orch._persist_workflow_run = AsyncMock()

        await orch._run_scheduled_sweep()

        assert orch._persist_workflow_run.await_count == 2
        running_call, failed_call = orch._persist_workflow_run.await_args_list

        assert running_call.kwargs["status"] == "running"
        assert failed_call.kwargs["status"] == "failed"
        assert failed_call.kwargs["outcome"] == "error"
        assert failed_call.kwargs["outcome_reason"] == "gamma down"


class TestOrchestratorCandidateSelection:
    """Trigger candidate construction and sweep ranking behavior."""

    @pytest.mark.asyncio
    async def test_trigger_candidate_uses_configured_sports_horizon(self):
        from config.settings import AppConfig
        from workflows.orchestrator import WorkflowOrchestrator

        orch = WorkflowOrchestrator(AppConfig())
        orch._scanner = _FakeScanner()

        allowed_entry = MarketWatchEntry(
            market_id="sports-allowed",
            token_id="tok-allowed",
            title="Will Liverpool FC win on 2026-04-19?",
            category="sports",
            category_quality_tier="quality_gated",
            resolution_source="Official match result",
            end_date=datetime.now(tz=UTC) + timedelta(hours=60),
            last_price=0.56,
            last_spread=0.02,
            last_depth_top3=1500.0,
        )
        blocked_entry = allowed_entry.model_copy(update={
            "market_id": "sports-blocked",
            "token_id": "tok-blocked",
            "end_date": datetime.now(tz=UTC) + timedelta(hours=36),
        })
        orch._scanner.add_to_watch_list(allowed_entry)
        orch._scanner.add_to_watch_list(blocked_entry)

        allowed_trigger = SimpleNamespace(
            market_id="sports-allowed",
            token_id="tok-allowed",
            trigger_class="repricing",
            trigger_level="C",
            reason="repricing",
            price=0.56,
            spread=0.02,
            depth_snapshot={"top3_usd": 1600.0},
        )
        blocked_trigger = SimpleNamespace(
            market_id="sports-blocked",
            token_id="tok-blocked",
            trigger_class="repricing",
            trigger_level="C",
            reason="repricing",
            price=0.56,
            spread=0.02,
            depth_snapshot={"top3_usd": 1600.0},
        )

        allowed_candidate = await orch._build_candidate_from_trigger(allowed_trigger)
        blocked_candidate = await orch._build_candidate_from_trigger(blocked_trigger)

        assert allowed_candidate is not None
        assert allowed_candidate.category == "sports"
        assert blocked_candidate is None

    def test_rank_sweep_candidates_prefers_edge_over_liquidity(self):
        from config.settings import AppConfig
        from workflows.orchestrator import WorkflowOrchestrator

        orch = WorkflowOrchestrator(AppConfig())
        low_edge_high_liquidity = SimpleNamespace(
            market_id="m-low-edge",
            edge_discovery_score=0.2,
            visible_depth_usd=9000.0,
        )
        high_edge_lower_liquidity = SimpleNamespace(
            market_id="m-high-edge",
            edge_discovery_score=0.7,
            visible_depth_usd=1200.0,
        )

        ranked = orch._rank_sweep_candidates([
            low_edge_high_liquidity,
            high_edge_lower_liquidity,
        ])

        assert ranked[0].market_id == "m-high-edge"


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

    def test_sync_dashboard_state_publishes_mark_to_market_equity(self):
        """Dashboard sync should expose simulated paper equity, not just deposited cash."""
        from config.settings import AppConfig
        from dashboard_api.app import _system_state
        from workflows.orchestrator import WorkflowOrchestrator

        original_equity = _system_state.get("paper_equity_usd")
        original_start = _system_state.get("start_of_day_equity_usd")
        original_history = list(_system_state.get("equity_history", []))

        try:
            orch = WorkflowOrchestrator(AppConfig())
            orch._state.phase = SystemPhase.RUNNING
            orch._portfolio.current_equity_usd = 545.0
            orch._portfolio.start_of_day_equity_usd = 500.0
            _system_state["start_of_day_equity_usd"] = 500.0
            _system_state["equity_history"] = []

            orch._sync_dashboard_state()

            assert _system_state["paper_equity_usd"] == 545.0
            assert _system_state["equity_history"][-1]["equity_usd"] == 545.0
            assert _system_state["equity_history"][-1]["pnl_usd"] == 45.0
        finally:
            if original_equity is None:
                _system_state.pop("paper_equity_usd", None)
            else:
                _system_state["paper_equity_usd"] = original_equity
            _system_state["start_of_day_equity_usd"] = original_start
            _system_state["equity_history"] = original_history

    def test_sync_dashboard_state_updates_cost_and_scanner_metrics(self):
        """Dashboard sync should publish cost state and scanner runtime metrics."""
        from config.settings import AppConfig
        from dashboard_api.app import _system_state
        from market_data.types import CacheStats
        from scanner.types import DegradedModeLevel, ScannerHealthStatus
        from workflows.orchestrator import WorkflowOrchestrator

        original_state = {
            "daily_spend_usd": _system_state.get("daily_spend_usd"),
            "lifetime_spend_usd": _system_state.get("lifetime_spend_usd"),
            "opus_spend_today_usd": _system_state.get("opus_spend_today_usd"),
            "selectivity_ratio": _system_state.get("selectivity_ratio"),
            "scanner_cache_entries": _system_state.get("scanner_cache_entries"),
            "scanner_cache_hit_rate": _system_state.get("scanner_cache_hit_rate"),
            "scanner_consecutive_failures": _system_state.get("scanner_consecutive_failures"),
            "scanner_last_poll": _system_state.get("scanner_last_poll"),
            "scanner_uptime_pct": _system_state.get("scanner_uptime_pct"),
        }

        try:
            orch = WorkflowOrchestrator(AppConfig())
            last_poll = datetime(2026, 4, 14, 16, 45, tzinfo=UTC)

            orch._scanner = MagicMock()
            orch._scanner.health_monitor.get_health_status.return_value = (
                ScannerHealthStatus(
                    api_available=True,
                    degraded_mode_level=DegradedModeLevel.NORMAL,
                    last_successful_poll=last_poll,
                    consecutive_global_failures=1,
                    total_polls=4,
                    successful_polls=3,
                    failed_polls=1,
                )
            )
            orch._market_data = MagicMock()
            orch._market_data.get_cache_stats_snapshot.return_value = CacheStats(
                total_entries=21,
                hit_rate=0.75,
            )
            orch._cost_governor = MagicMock()
            orch._cost_governor.budget_tracker.state = MagicMock(
                daily_spent_usd=0.066153,
                lifetime_spent_usd=1.234567,
                daily_opus_spent_usd=0.01,
            )
            orch._cost_governor.get_selectivity_snapshot.return_value = MagicMock(
                cost_to_edge_ratio=0.125,
            )

            orch._sync_dashboard_state()

            assert _system_state["daily_spend_usd"] == 0.0662
            assert _system_state["lifetime_spend_usd"] == 1.2346
            assert _system_state["opus_spend_today_usd"] == 0.01
            assert _system_state["selectivity_ratio"] == 0.125
            assert _system_state["scanner_cache_entries"] == 21
            assert _system_state["scanner_cache_hit_rate"] == 0.75
            assert _system_state["scanner_consecutive_failures"] == 1
            assert _system_state["scanner_last_poll"] == last_poll.isoformat()
            assert _system_state["scanner_uptime_pct"] == 75.0
        finally:
            for key, value in original_state.items():
                _system_state[key] = value

    def test_sync_dashboard_state_isolates_scanner_failures_from_cost_metrics(self):
        """A scanner sync error must not block cost metrics from updating."""
        from config.settings import AppConfig
        from dashboard_api.app import _system_state
        from workflows.orchestrator import WorkflowOrchestrator

        original_daily = _system_state.get("daily_spend_usd")
        original_lifetime = _system_state.get("lifetime_spend_usd")

        try:
            orch = WorkflowOrchestrator(AppConfig())
            orch._scanner = MagicMock()
            orch._scanner.health_monitor.get_health_status.side_effect = RuntimeError(
                "scanner sync failed"
            )
            orch._cost_governor = MagicMock()
            orch._cost_governor.budget_tracker.state = MagicMock(
                daily_spent_usd=0.5,
                lifetime_spent_usd=2.0,
                daily_opus_spent_usd=0.0,
            )
            orch._cost_governor.get_selectivity_snapshot.return_value = MagicMock(
                cost_to_edge_ratio=None,
            )

            orch._sync_dashboard_state()

            assert _system_state["daily_spend_usd"] == 0.5
            assert _system_state["lifetime_spend_usd"] == 2.0
        finally:
            _system_state["daily_spend_usd"] = original_daily
            _system_state["lifetime_spend_usd"] = original_lifetime


class TestPaperExecutionIntegration:
    """Paper-mode execution should behave like live execution with simulated cash."""

    @pytest.mark.asyncio
    async def test_execute_paper_trade_debits_cash_and_persists_trade_objects(self):
        from config.settings import AppConfig
        from dashboard_api.app import _system_state
        from workflows.orchestrator import WorkflowOrchestrator
        from data.models import Market, Order, Position, Trade
        from data.models.thesis import ThesisCard
        from data.models.workflow import WorkflowRun

        original_state = {
            "operator_mode": _system_state.get("operator_mode"),
            "paper_balance_usd": _system_state.get("paper_balance_usd"),
            "paper_equity_usd": _system_state.get("paper_equity_usd"),
            "paper_reserved_capital_usd": _system_state.get("paper_reserved_capital_usd"),
            "paper_transactions": list(_system_state.get("paper_transactions", [])),
            "start_of_day_equity_usd": _system_state.get("start_of_day_equity_usd"),
        }

        engine, session_factory = await _make_isolated_session_factory()
        market_id = f"paper-market-{uuid.uuid4().hex[:8]}"
        workflow_run_id = f"trig-paper-{uuid.uuid4().hex[:8]}"

        try:
            _system_state.update({
                "operator_mode": "paper",
                "paper_balance_usd": 500.0,
                "paper_equity_usd": 500.0,
                "paper_reserved_capital_usd": 0.0,
                "paper_transactions": [],
                "start_of_day_equity_usd": 500.0,
            })

            orch = WorkflowOrchestrator(AppConfig())
            orch._session_factory = session_factory
            orch._dashboard_state = _system_state
            orch._scanner = _FakeScanner()
            orch._calibration_store = MagicMock()
            orch._risk_governor = MagicMock()
            orch._risk_governor.drawdown_state = SimpleNamespace(current_drawdown_pct=0.0)
            orch._risk_governor.update_equity = MagicMock()

            card = SimpleNamespace(
                market_id=market_id,
                workflow_run_id=workflow_run_id,
                category="macro_policy",
                category_quality_tier="standard",
                proposed_side="yes",
                core_thesis="Paper execution test thesis",
                why_mispriced="Recent repricing overshot the macro update",
                supporting_evidence=[{"content": "Test support", "source": "test", "freshness": "fresh"}],
                opposing_evidence=[],
                invalidation_conditions=["A conflicting policy statement"],
                resolution_interpretation="Resolves YES if the policy decision is announced",
                probability_estimate=0.61,
                confidence_estimate=0.64,
                calibration_confidence=0.52,
                gross_edge=0.06,
                friction_adjusted_edge=0.05,
                impact_adjusted_edge=0.048,
                net_edge_after_cost=0.047,
                expected_friction_spread=0.02,
                expected_friction_slippage=0.002,
                entry_impact_estimate_bps=5.0,
                expected_inference_cost_usd=0.11,
                recommended_size_band="standard",
                urgency_of_entry="within_hours",
                liquidity_adjusted_max_size_usd=100.0,
                trigger_source="repricing",
                market_implied_probability=0.55,
                base_rate=0.50,
                base_rate_deviation=0.11,
            )
            request = ExecutionRequest(
                workflow_run_id=workflow_run_id,
                market_id=market_id,
                token_id="tok-paper",
                side="buy",
                price=0.55,
                size_usd=100.0,
                order_type="limit",
                current_spread=0.02,
                current_depth_usd=2000.0,
                current_best_bid=0.54,
                current_best_ask=0.56,
                current_mid_price=0.55,
                risk_approval="approve_normal",
                cost_approval="approve_full",
                tradeability_outcome="tradeable",
                entry_impact_bps=5.0,
                gross_edge=0.06,
                preferred_entry_mode=EntryMode.IMMEDIATE,
                operator_mode="paper",
                approved_at=datetime.now(tz=UTC),
            )
            risk_assessment = SimpleNamespace(approval=SimpleNamespace(value="approve_normal"))

            result = await orch._execute_paper_trade(
                card,
                request,
                risk_assessment,
                started=datetime.now(tz=UTC),
            )

            assert result.accepted is True
            assert _system_state["paper_balance_usd"] == 400.0
            assert _system_state["paper_transactions"][-1]["type"] == "trade_entry"
            assert _system_state["paper_transactions"][-1]["amount_usd"] == -100.0

            await orch._refresh_runtime_portfolio_state()
            orch._sync_dashboard_state()

            assert orch._portfolio.total_open_exposure_usd == 100.0
            assert orch._portfolio.current_equity_usd == 500.0
            assert _system_state["paper_reserved_capital_usd"] == 100.0
            assert _system_state["paper_equity_usd"] == 500.0

            async with session_factory() as session:
                market = (
                    await session.execute(
                        select(Market).where(Market.market_id == market_id)
                    )
                ).scalar_one()
                workflow_run = (
                    await session.execute(
                        select(WorkflowRun).where(WorkflowRun.workflow_run_id == workflow_run_id)
                    )
                ).scalar_one()
                thesis_cards = (
                    await session.execute(
                        select(ThesisCard).where(ThesisCard.market_id == market.id)
                    )
                ).scalars().all()
                positions = (
                    await session.execute(
                        select(Position).where(Position.market_id == market.id)
                    )
                ).scalars().all()
                orders = (
                    await session.execute(
                        select(Order).where(Order.workflow_run_id == workflow_run.id)
                    )
                ).scalars().all()
                trades = (
                    await session.execute(
                        select(Trade).join(Order, Trade.order_id == Order.id).where(Order.workflow_run_id == workflow_run.id)
                    )
                ).scalars().all()

                assert len(thesis_cards) == 1
                assert len(positions) == 1
                assert len(orders) == 1
                assert len(trades) == 1

        finally:
            await engine.dispose()
            _system_state.update(original_state)

    @pytest.mark.asyncio
    async def test_mark_to_market_updates_equity_without_changing_cash(self):
        from config.settings import AppConfig
        from dashboard_api.app import _system_state
        from workflows.orchestrator import WorkflowOrchestrator
        from data.models import Market, Position

        original_state = {
            "operator_mode": _system_state.get("operator_mode"),
            "paper_balance_usd": _system_state.get("paper_balance_usd"),
            "paper_equity_usd": _system_state.get("paper_equity_usd"),
            "paper_reserved_capital_usd": _system_state.get("paper_reserved_capital_usd"),
            "start_of_day_equity_usd": _system_state.get("start_of_day_equity_usd"),
        }

        engine, session_factory = await _make_isolated_session_factory()
        market_id = f"m2m-market-{uuid.uuid4().hex[:8]}"

        try:
            _system_state.update({
                "operator_mode": "paper",
                "paper_balance_usd": 400.0,
                "paper_equity_usd": 500.0,
                "paper_reserved_capital_usd": 100.0,
                "start_of_day_equity_usd": 500.0,
            })

            orch = WorkflowOrchestrator(AppConfig())
            orch._session_factory = session_factory
            orch._dashboard_state = _system_state
            orch._scanner = _FakeScanner()
            orch._risk_governor = MagicMock()
            orch._risk_governor.update_equity = MagicMock()

            async with session_factory() as session:
                market = Market(
                    market_id=market_id,
                    title="Mark to market test",
                    category="macro_policy",
                    last_price=0.55,
                )
                session.add(market)
                await session.flush()
                position = Position(
                    market_id=market.id,
                    side="yes",
                    entry_price=0.55,
                    current_price=0.55,
                    size=100.0,
                    remaining_size=100.0,
                    status="open",
                    review_tier="new",
                    entered_at=datetime.now(tz=UTC),
                    unrealized_pnl=0.0,
                    realized_pnl=0.0,
                )
                session.add(position)
                await session.commit()
                position_id = str(position.id)

            orch._scanner.add_to_watch_list(
                MarketWatchEntry(
                    market_id=market_id,
                    token_id="tok-m2m",
                    title="Mark to market test",
                    category="macro_policy",
                    is_held_position=True,
                    position_id=position_id,
                    last_price=0.60,
                    last_spread=0.01,
                )
            )

            await orch._mark_to_market_paper_positions()
            await orch._refresh_runtime_portfolio_state()
            orch._sync_dashboard_state()

            assert _system_state["paper_balance_usd"] == 400.0
            assert orch._portfolio.current_equity_usd == 505.0
            assert _system_state["paper_equity_usd"] == 505.0
            assert _system_state["paper_reserved_capital_usd"] == 100.0

            async with session_factory() as session:
                refreshed_position = (
                    await session.execute(
                        select(Position).join(Market, Position.market_id == Market.id).where(Market.market_id == market_id)
                    )
                ).scalar_one()
                assert refreshed_position.current_price == 0.60
                assert refreshed_position.unrealized_pnl == 5.0

        finally:
            await engine.dispose()
            _system_state.update(original_state)
