"""Phase 15 — Dashboard API and Service comprehensive tests.

Tests cover:
- Schema validation (all Pydantic response models)
- Service layer (database queries, state assembly, operator controls)
- FastAPI route integration (endpoint responses, CORS, error handling)
- Agent start/stop and mode change controls
- Data integrity (positions, workflows, triggers, risk, cost)
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from dashboard_api.schemas import (
    AbsenceStatus,
    AgentStatus,
    BiasAuditOverview,
    BiasPatternItem,
    CalibrationOverview,
    CalibrationSegmentStatus,
    CategoryPerformanceEntry,
    CostMetrics,
    DrawdownLadder,
    EquitySnapshot,
    ExposureByCategory,
    OperatorModeRequest,
    PortfolioOverview,
    PositionDetail,
    PositionSummary,
    RiskBoard,
    ScannerHealth,
    SystemControlResponse,
    SystemHealthItem,
    SystemHealthOverview,
    TriggerEventItem,
    ViabilityCheckpointItem,
    ViabilityOverview,
    WorkflowRunSummary,
)
from dashboard_api.services import DashboardService
from dashboard_api.app import create_dashboard_app, _system_state, set_app_config

# ─── Imports for ORM test data ───────────────
from data.models import Market, Position
from data.models.workflow import WorkflowRun, TriggerEvent
from config.settings import AppConfig


# =============================================================================
# Schema Tests
# =============================================================================


class TestSchemas:
    """Test that all Pydantic schemas serialize correctly."""

    def test_equity_snapshot(self):
        snap = EquitySnapshot(
            timestamp=datetime.now(tz=UTC), equity_usd=10000.0, pnl_usd=150.0
        )
        assert snap.equity_usd == 10000.0
        assert snap.pnl_usd == 150.0

    def test_portfolio_overview_defaults(self):
        overview = PortfolioOverview()
        assert overview.total_equity_usd == 0.0
        assert overview.open_positions_count == 0
        assert overview.drawdown_level == "normal"
        assert overview.operator_mode == "paper"
        assert overview.system_status == "running"
        assert overview.equity_history == []

    def test_portfolio_overview_populated(self):
        overview = PortfolioOverview(
            total_equity_usd=12345.67,
            total_open_exposure_usd=5000.0,
            daily_pnl_usd=-42.50,
            unrealized_pnl_usd=-60.0,
            realized_pnl_usd=17.50,
            open_positions_count=3,
            drawdown_level="soft_warning",
            drawdown_pct=3.5,
            operator_mode="shadow",
            system_status="running",
        )
        assert overview.total_equity_usd == 12345.67
        assert overview.daily_pnl_usd == -42.50
        assert overview.drawdown_level == "soft_warning"
        assert overview.operator_mode == "shadow"

    def test_position_summary(self):
        pos = PositionSummary(
            id=uuid.uuid4(),
            market_id="mkt-001",
            market_title="Test Market",
            side="yes",
            entry_price=0.45,
            size=500.0,
            remaining_size=500.0,
            status="open",
            review_tier="new",
        )
        assert pos.side == "yes"
        assert pos.entry_price == 0.45
        assert pos.current_price is None

    def test_position_detail_extends_summary(self):
        detail = PositionDetail(
            id=uuid.uuid4(),
            market_id="mkt-002",
            market_title="Detail Market",
            side="no",
            entry_price=0.65,
            size=700.0,
            remaining_size=700.0,
            status="open",
            review_tier="stable",
            probability_estimate=0.55,
            confidence_estimate=0.7,
            cumulative_review_cost_usd=1.25,
        )
        assert detail.probability_estimate == 0.55
        assert detail.cumulative_review_cost_usd == 1.25

    def test_drawdown_ladder_defaults(self):
        ladder = DrawdownLadder()
        assert ladder.current_drawdown_pct == 0.0
        assert ladder.soft_warning_pct == 0.03
        assert ladder.risk_reduction_pct == 0.05
        assert ladder.entries_disabled_pct == 0.065
        assert ladder.hard_kill_switch_pct == 0.08
        assert ladder.current_level == "normal"

    def test_exposure_by_category(self):
        exp = ExposureByCategory(
            category="politics",
            exposure_usd=850.0,
            cap_usd=5000.0,
            positions_count=2,
            pct_of_cap=0.17,
        )
        assert exp.pct_of_cap == 0.17

    def test_risk_board_defaults(self):
        board = RiskBoard()
        assert board.total_exposure_usd == 0.0
        assert board.max_exposure_usd == 0.0
        assert board.exposure_by_category == []
        assert isinstance(board.drawdown_ladder, DrawdownLadder)

    def test_workflow_run_summary(self):
        wf = WorkflowRunSummary(
            id=uuid.uuid4(),
            workflow_type="investigation",
            status="completed",
            cost_usd=1.50,
        )
        assert wf.workflow_type == "investigation"
        assert wf.cost_usd == 1.50

    def test_trigger_event_item(self):
        evt = TriggerEventItem(
            id=uuid.uuid4(),
            trigger_class="repricing",
            trigger_level="B",
            timestamp=datetime.now(tz=UTC),
        )
        assert evt.trigger_class == "repricing"
        assert evt.trigger_level == "B"
        assert evt.price is None

    def test_cost_metrics_defaults(self):
        cost = CostMetrics()
        assert cost.daily_spend_usd == 0.0
        assert cost.daily_budget_usd == 25.0
        assert cost.daily_budget_remaining_usd == 25.0
        assert cost.selectivity_target == 0.20

    def test_calibration_segment_status(self):
        seg = CalibrationSegmentStatus(
            segment_name="politics",
            resolved_count=12,
            required_count=30,
            system_brier=0.165,
            market_brier=0.188,
            advantage=0.023,
            status="insufficient",
        )
        assert seg.advantage == 0.023
        assert seg.status == "insufficient"

    def test_calibration_overview_defaults(self):
        cal = CalibrationOverview()
        assert cal.total_shadow_forecasts == 0
        assert cal.segments == []
        assert cal.patience_budget_months == 9

    def test_scanner_health_defaults(self):
        health = ScannerHealth()
        assert health.api_status == "healthy"
        assert health.degraded_level == 0
        assert health.uptime_pct == 100.0

    def test_category_performance(self):
        entry = CategoryPerformanceEntry(
            category="technology",
            total_trades=10,
            win_rate=0.6,
            gross_pnl_usd=200.0,
            net_pnl_usd=150.0,
            inference_cost_usd=50.0,
            avg_edge=0.07,
            avg_holding_hours=120.0,
        )
        assert entry.win_rate == 0.6
        assert entry.brier_score is None

    def test_bias_pattern_item(self):
        pattern = BiasPatternItem(
            pattern_type="directional_bias",
            severity="warning",
            description="Bullish skew",
            weeks_active=2,
            is_persistent=False,
        )
        assert not pattern.is_persistent
        assert pattern.weeks_active == 2

    def test_bias_audit_overview_defaults(self):
        audit = BiasAuditOverview()
        assert audit.active_patterns == []
        assert audit.persistent_pattern_count == 0

    def test_viability_checkpoint_item(self):
        cp = ViabilityCheckpointItem(
            checkpoint_week=4,
            assessed_at=datetime.now(tz=UTC),
            signal="neutral",
            resolved_count=14,
        )
        assert cp.signal == "neutral"
        assert cp.system_brier is None

    def test_viability_overview_defaults(self):
        via = ViabilityOverview()
        assert via.current_signal == "unassessed"
        assert via.checkpoints == []

    def test_absence_status_defaults(self):
        absence = AbsenceStatus()
        assert not absence.is_absent
        assert absence.absence_level == 0
        assert absence.restrictions_active == []

    def test_system_health_item(self):
        item = SystemHealthItem(
            component="Database",
            status="healthy",
        )
        assert item.component == "Database"
        assert item.details is None

    def test_system_health_overview_defaults(self):
        health = SystemHealthOverview()
        assert health.overall_status == "healthy"
        assert health.components == []

    def test_agent_status(self):
        agent = AgentStatus(
            name="Test Agent",
            role="test_role",
            tier="B",
            is_active=True,
            total_invocations=42,
            total_cost_usd=5.50,
        )
        assert agent.is_active
        assert agent.total_invocations == 42

    def test_operator_mode_request(self):
        req = OperatorModeRequest(mode="shadow", reason="testing")
        assert req.mode == "shadow"

    def test_system_control_response(self):
        resp = SystemControlResponse(
            success=True,
            message="Mode changed",
            current_mode="shadow",
            timestamp=datetime.now(tz=UTC),
        )
        assert resp.success

    def test_portfolio_json_serialization(self):
        overview = PortfolioOverview(
            total_equity_usd=10000.0,
            equity_history=[
                EquitySnapshot(
                    timestamp=datetime.now(tz=UTC),
                    equity_usd=9800.0,
                    pnl_usd=-200.0,
                )
            ],
        )
        data = overview.model_dump()
        assert len(data["equity_history"]) == 1
        assert data["equity_history"][0]["equity_usd"] == 9800.0


# =============================================================================
# Service Tests — Database-Backed
# =============================================================================


class TestDashboardServiceDB:
    """Test DashboardService methods that query the database."""

    @pytest_asyncio.fixture
    async def populated_session(self, session: AsyncSession):
        """Create test data: 2 markets, 3 positions (2 open, 1 closed)."""
        mkt1 = Market(
            market_id="clob-001",
            title="US Election Senator",
            category="politics",
        )
        mkt2 = Market(
            market_id="clob-002",
            title="AI Safety Regulation",
            category="technology",
        )
        session.add_all([mkt1, mkt2])
        await session.flush()

        pos1 = Position(
            market_id=mkt1.id,
            side="yes",
            entry_price=0.42,
            current_price=0.50,
            size=800.0,
            remaining_size=800.0,
            status="open",
            review_tier="stable",
            unrealized_pnl=64.0,
            realized_pnl=0.0,
            entered_at=datetime.now(tz=UTC) - timedelta(days=5),
        )
        pos2 = Position(
            market_id=mkt2.id,
            side="no",
            entry_price=0.60,
            current_price=0.55,
            size=600.0,
            remaining_size=600.0,
            status="open",
            review_tier="new",
            unrealized_pnl=30.0,
            realized_pnl=0.0,
            entered_at=datetime.now(tz=UTC) - timedelta(days=1),
        )
        pos3 = Position(
            market_id=mkt1.id,
            side="yes",
            entry_price=0.38,
            current_price=0.45,
            size=400.0,
            remaining_size=0.0,
            status="closed",
            review_tier="stable",
            unrealized_pnl=0.0,
            realized_pnl=28.0,
            entered_at=datetime.now(tz=UTC) - timedelta(days=10),
            exited_at=datetime.now(tz=UTC) - timedelta(days=2),
            exit_class="profit_protection",
        )
        session.add_all([pos1, pos2, pos3])
        await session.flush()

        return session, mkt1, mkt2, pos1, pos2, pos3

    async def test_portfolio_overview_sums(self, populated_session):
        """Portfolio overview correctly sums open positions."""
        session, _, _, _, _, _ = populated_session
        service = DashboardService(session=session)
        overview = await service.get_portfolio_overview()

        assert overview.open_positions_count == 2
        assert overview.total_open_exposure_usd == 1400.0  # 800 + 600
        assert overview.unrealized_pnl_usd == 94.0  # 64 + 30
        assert overview.realized_pnl_usd == 0.0  # Only open positions
        assert overview.operator_mode == "paper"
        assert overview.system_status == "running"

    async def test_portfolio_empty_db(self, session: AsyncSession):
        """Portfolio overview with no positions returns zeros."""
        service = DashboardService(session=session)
        overview = await service.get_portfolio_overview()
        assert overview.open_positions_count == 0
        assert overview.total_open_exposure_usd == 0.0
        assert overview.unrealized_pnl_usd == 0.0

    async def test_portfolio_uses_mark_to_market_paper_equity(self, session: AsyncSession):
        """Portfolio overview prefers simulated equity over static paper balance."""
        service = DashboardService(
            session=session,
            system_state={
                "paper_balance_usd": 500.0,
                "paper_equity_usd": 545.0,
                "operator_mode": "paper",
                "system_status": "running",
                "equity_history": [],
            },
        )
        overview = await service.get_portfolio_overview()
        assert overview.total_equity_usd == 545.0

    async def test_get_positions_all(self, populated_session):
        """Get all positions returns correct count."""
        session, _, _, _, _, _ = populated_session
        service = DashboardService(session=session)
        positions = await service.get_positions()
        assert len(positions) == 3

    async def test_get_positions_open_filter(self, populated_session):
        """Get positions with open filter returns only open ones."""
        session, _, _, _, _, _ = populated_session
        service = DashboardService(session=session)
        positions = await service.get_positions(status="open")
        assert len(positions) == 2
        assert all(p.status == "open" for p in positions)

    async def test_get_positions_closed_filter(self, populated_session):
        """Get positions with closed filter returns only closed ones."""
        session, _, _, _, _, _ = populated_session
        service = DashboardService(session=session)
        positions = await service.get_positions(status="closed")
        assert len(positions) == 1
        assert positions[0].status == "closed"

    async def test_get_positions_limit(self, populated_session):
        """Get positions respects limit parameter."""
        session, _, _, _, _, _ = populated_session
        service = DashboardService(session=session)
        positions = await service.get_positions(limit=1)
        assert len(positions) == 1

    async def test_get_position_detail(self, populated_session):
        """Position detail returns extended fields."""
        session, _, _, pos1, _, _ = populated_session
        service = DashboardService(session=session)
        detail = await service.get_position_detail(pos1.id)
        assert detail is not None
        assert detail.side == "yes"
        assert detail.entry_price == 0.42
        assert detail.market_title == "US Election Senator"
        assert detail.category == "politics"

    async def test_get_position_detail_not_found(self, session: AsyncSession):
        """Position detail returns None for nonexistent ID."""
        service = DashboardService(session=session)
        result = await service.get_position_detail(uuid.uuid4())
        assert result is None

    async def test_risk_board_exposure(self, populated_session):
        """Risk board correctly calculates exposure by category."""
        session, _, _, _, _, _ = populated_session
        service = DashboardService(session=session)
        risk = await service.get_risk_board()

        assert risk.total_exposure_usd == 1400.0
        assert len(risk.exposure_by_category) == 2

        categories = {e.category: e for e in risk.exposure_by_category}
        assert "politics" in categories
        assert "technology" in categories
        assert categories["politics"].exposure_usd == 800.0
        assert categories["technology"].exposure_usd == 600.0

    async def test_risk_board_empty(self, session: AsyncSession):
        """Risk board with no positions shows zero exposure."""
        service = DashboardService(session=session)
        risk = await service.get_risk_board()
        assert risk.total_exposure_usd == 0.0
        assert len(risk.exposure_by_category) == 0

    async def test_risk_board_with_config(self, populated_session):
        """Risk board uses config for caps."""
        session, _, _, _, _, _ = populated_session
        config = AppConfig()
        service = DashboardService(session=session, config=config)
        risk = await service.get_risk_board()
        assert risk.max_exposure_usd == config.risk.max_total_open_exposure_usd
        assert risk.max_daily_deployment_pct == config.risk.max_daily_deployment_pct

    async def test_positions_include_category(self, populated_session):
        """Position summaries include category from market join."""
        session, _, _, _, _, _ = populated_session
        service = DashboardService(session=session)
        positions = await service.get_positions(status="open")
        categories = {p.category for p in positions}
        assert "politics" in categories
        assert "technology" in categories

    async def test_positions_include_market_title(self, populated_session):
        """Position summaries include market title from market join."""
        session, _, _, _, _, _ = populated_session
        service = DashboardService(session=session)
        positions = await service.get_positions()
        titles = {p.market_title for p in positions}
        assert "US Election Senator" in titles
        assert "AI Safety Regulation" in titles


# =============================================================================
# Service Tests — State-Based (No DB Required)
# =============================================================================


class TestDashboardServiceState:
    """Test DashboardService methods that use system_state dict."""

    async def test_cost_metrics_defaults(self, session: AsyncSession):
        """Cost metrics with default state returns sane defaults."""
        service = DashboardService(session=session)
        cost = await service.get_cost_metrics()
        assert cost.daily_spend_usd == 0.0
        assert cost.daily_budget_usd == 25.0
        assert cost.daily_budget_remaining_usd == 25.0

    async def test_cost_metrics_with_config(self, session: AsyncSession):
        """Cost metrics uses config for budgets."""
        config = AppConfig()
        service = DashboardService(session=session, config=config)
        cost = await service.get_cost_metrics()
        assert cost.daily_budget_usd == config.cost.daily_llm_budget_usd
        assert cost.lifetime_budget_usd == config.cost.lifetime_experiment_budget_usd

    async def test_cost_metrics_with_spend(self, session: AsyncSession):
        """Cost metrics correctly calculates remaining budget."""
        state = {"daily_spend_usd": 12.5, "lifetime_spend_usd": 1500.0}
        service = DashboardService(session=session, system_state=state)
        cost = await service.get_cost_metrics()
        assert cost.daily_spend_usd == 12.5
        assert cost.daily_budget_remaining_usd == 12.5  # 25 - 12.5

    async def test_scanner_health_defaults(self, session: AsyncSession):
        """Scanner health returns healthy defaults."""
        service = DashboardService(session=session)
        health = await service.get_scanner_health()
        assert health.api_status == "healthy"
        assert health.degraded_level == 0
        assert health.uptime_pct == 100.0

    async def test_scanner_health_degraded(self, session: AsyncSession):
        """Scanner health reflects degraded state."""
        state = {
            "scanner_api_status": "degraded",
            "scanner_degraded_level": 2,
            "scanner_consecutive_failures": 8,
        }
        service = DashboardService(session=session, system_state=state)
        health = await service.get_scanner_health()
        assert health.api_status == "degraded"
        assert health.degraded_level == 2
        assert health.consecutive_failures == 8

    async def test_calibration_overview_from_state(self, session: AsyncSession):
        """Calibration overview reads from system state."""
        state = {
            "total_shadow_forecasts": 87,
            "total_resolved": 34,
            "overall_system_brier": 0.182,
            "overall_market_brier": 0.198,
            "overall_advantage": 0.016,
        }
        service = DashboardService(session=session, system_state=state)
        cal = await service.get_calibration_overview()
        assert cal.total_shadow_forecasts == 87
        assert cal.overall_system_brier == 0.182
        assert cal.overall_advantage == 0.016

    async def test_category_performance_empty(self, session: AsyncSession):
        """Category performance with empty state returns empty."""
        service = DashboardService(session=session)
        entries = await service.get_category_performance()
        assert entries == []

    async def test_category_performance_from_state(self, session: AsyncSession):
        """Category performance reads list from state."""
        state = {
            "category_performance": [
                CategoryPerformanceEntry(
                    category="politics", total_trades=12, win_rate=0.67,
                    gross_pnl_usd=245.0, net_pnl_usd=198.0, inference_cost_usd=47.0,
                    avg_edge=0.08, avg_holding_hours=168.0,
                )
            ]
        }
        service = DashboardService(session=session, system_state=state)
        entries = await service.get_category_performance()
        assert len(entries) == 1
        assert entries[0].category == "politics"

    async def test_bias_audit_defaults(self, session: AsyncSession):
        """Bias audit overview with default state."""
        service = DashboardService(session=session)
        audit = await service.get_bias_audit()
        assert audit.active_patterns == []
        assert audit.persistent_pattern_count == 0

    async def test_viability_defaults(self, session: AsyncSession):
        """Viability overview with default state."""
        service = DashboardService(session=session)
        via = await service.get_viability()
        assert via.current_signal == "unassessed"
        assert via.checkpoints == []

    async def test_absence_defaults(self, session: AsyncSession):
        """Absence status with default state."""
        service = DashboardService(session=session)
        absence = await service.get_absence_status()
        assert not absence.is_absent
        assert absence.absence_level == 0

    async def test_absence_active(self, session: AsyncSession):
        """Absence status reflects active absence."""
        state = {
            "is_absent": True,
            "absence_level": 2,
            "hours_since_activity": 80.5,
            "absence_restrictions": ["no_new_entries", "size_reduced_25pct"],
            "autonomous_actions_count": 3,
        }
        service = DashboardService(session=session, system_state=state)
        absence = await service.get_absence_status()
        assert absence.is_absent
        assert absence.absence_level == 2
        assert absence.hours_since_activity == 80.5
        assert len(absence.restrictions_active) == 2
        assert absence.autonomous_actions_count == 3

    async def test_system_health_all_healthy(self, session: AsyncSession):
        """System health returns healthy when all components healthy."""
        service = DashboardService(session=session)
        health = await service.get_system_health()
        assert health.overall_status == "healthy"
        assert len(health.components) >= 5

    async def test_system_health_degraded_scanner(self, session: AsyncSession):
        """System health reflects degraded scanner."""
        state = {"scanner_api_status": "degraded"}
        service = DashboardService(session=session, system_state=state)
        health = await service.get_system_health()
        assert health.overall_status == "warning"

    async def test_system_health_critical_telegram(self, session: AsyncSession):
        """System health reflects critical telegram."""
        state = {"telegram_status": "critical"}
        service = DashboardService(session=session, system_state=state)
        health = await service.get_system_health()
        assert health.overall_status == "critical"

    async def test_agent_statuses_default(self, session: AsyncSession):
        """Agent statuses returns default agent list."""
        service = DashboardService(session=session)
        agents = await service.get_agent_statuses()
        assert len(agents) >= 8
        roles = {a.role for a in agents}
        assert "risk_governor" in roles
        assert "cost_governor" in roles
        assert "trigger_scanner" in roles

    async def test_agent_statuses_reflects_running_state(self, session: AsyncSession):
        """Agent statuses reflect agents_running state."""
        state_running = {"agents_running": True}
        service = DashboardService(session=session, system_state=state_running)
        agents = await service.get_agent_statuses()
        assert all(a.is_active for a in agents)

        state_stopped = {"agents_running": False}
        service2 = DashboardService(session=session, system_state=state_stopped)
        agents2 = await service2.get_agent_statuses()
        assert not any(a.is_active for a in agents2)


# =============================================================================
# Service Tests — Operator Controls
# =============================================================================


class TestOperatorControls:
    """Test mode change and agent toggle controls."""

    async def test_set_valid_mode(self, session: AsyncSession):
        """Setting a valid operator mode succeeds."""
        state = {"operator_mode": "paper"}
        service = DashboardService(session=session, system_state=state)
        result = await service.set_operator_mode("shadow", reason="testing")
        assert result.success
        assert result.current_mode == "shadow"
        assert state["operator_mode"] == "shadow"

    async def test_set_invalid_mode(self, session: AsyncSession):
        """Setting an invalid mode returns failure."""
        state = {"operator_mode": "paper"}
        service = DashboardService(session=session, system_state=state)
        result = await service.set_operator_mode("invalid_mode!")
        assert not result.success
        assert "Invalid mode" in result.message
        assert state["operator_mode"] == "paper"

    async def test_set_all_valid_modes(self, session: AsyncSession):
        """All valid operator modes are accepted."""
        from core.enums import OperatorMode

        state = {"operator_mode": "paper"}
        service = DashboardService(session=session, system_state=state)
        for mode in OperatorMode:
            result = await service.set_operator_mode(mode.value)
            assert result.success, f"Mode {mode.value} should be valid"
            assert result.current_mode == mode.value

    async def test_toggle_agents_start(self, session: AsyncSession):
        """Starting agents updates state correctly."""
        state = {"agents_running": False, "system_status": "stopped", "operator_mode": "paper"}
        service = DashboardService(session=session, system_state=state)
        result = await service.toggle_agents(running=True)
        assert result.success
        assert state["agents_running"] is True
        assert state["system_status"] == "running"

    async def test_toggle_agents_stop(self, session: AsyncSession):
        """Stopping agents updates state correctly."""
        state = {"agents_running": True, "system_status": "running", "operator_mode": "paper"}
        service = DashboardService(session=session, system_state=state)
        result = await service.toggle_agents(running=False)
        assert result.success
        assert state["agents_running"] is False
        assert state["system_status"] == "stopped"


# =============================================================================
# FastAPI Integration Tests
# =============================================================================


class TestDashboardAPI:
    """Test FastAPI endpoints via httpx.AsyncClient."""

    @pytest_asyncio.fixture
    async def client(self, session: AsyncSession):
        """Create a test client with mocked session factory."""
        from dashboard_api.app import set_session_factory

        # Create a session factory that yields the test session
        class FakeSessionFactory:
            def __call__(self):
                return FakeContextManager(session)

        class FakeContextManager:
            def __init__(self, sess: AsyncSession):
                self._sess = sess

            async def __aenter__(self):
                return self._sess

            async def __aexit__(self, *args):
                pass

        set_session_factory(FakeSessionFactory())
        set_app_config(AppConfig())

        # Reset system state for each test
        _system_state.clear()
        _system_state.update({
            "operator_mode": "paper",
            "system_status": "running",
            "agents_running": False,
            "drawdown_level": "normal",
            "drawdown_pct": 0.0,
        })

        app = create_dashboard_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client

    async def test_health_check(self, client: AsyncClient):
        """Health endpoint returns OK."""
        resp = await client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "timestamp" in data
        assert data["version"] == "0.1.0"

    async def test_portfolio_endpoint(self, client: AsyncClient):
        """Portfolio endpoint returns PortfolioOverview."""
        resp = await client.get("/api/portfolio")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_equity_usd" in data
        assert "drawdown_level" in data
        assert "operator_mode" in data
        assert data["operator_mode"] == "paper"

    async def test_positions_endpoint(self, client: AsyncClient):
        """Positions endpoint returns list."""
        resp = await client.get("/api/positions")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    async def test_positions_with_status_filter(self, client: AsyncClient):
        """Positions endpoint accepts status query param."""
        resp = await client.get("/api/positions?status=open")
        assert resp.status_code == 200

    async def test_positions_with_pagination(self, client: AsyncClient):
        """Positions endpoint accepts limit and offset."""
        resp = await client.get("/api/positions?limit=5&offset=0")
        assert resp.status_code == 200

    async def test_risk_endpoint(self, client: AsyncClient):
        """Risk endpoint returns RiskBoard."""
        resp = await client.get("/api/risk")
        assert resp.status_code == 200
        data = resp.json()
        assert "drawdown_ladder" in data
        assert "total_exposure_usd" in data
        assert "exposure_by_category" in data

    async def test_cost_endpoint(self, client: AsyncClient):
        """Cost endpoint returns CostMetrics."""
        resp = await client.get("/api/cost")
        assert resp.status_code == 200
        data = resp.json()
        assert "daily_spend_usd" in data
        assert "daily_budget_usd" in data
        assert "selectivity_ratio" in data

    async def test_scanner_endpoint(self, client: AsyncClient):
        """Scanner endpoint returns ScannerHealth."""
        resp = await client.get("/api/scanner")
        assert resp.status_code == 200
        data = resp.json()
        assert data["api_status"] == "healthy"
        assert data["uptime_pct"] == 100.0

    async def test_paper_balance_deposit_updates_portfolio_equity_immediately(
        self,
        client: AsyncClient,
    ):
        """Manual paper deposits should sync the portfolio overview immediately."""
        _system_state.update(
            {
                "paper_balance_usd": 500.0,
                "paper_equity_usd": 500.0,
                "start_of_day_equity_usd": 500.0,
                "paper_transactions": [],
                "equity_history": [],
            }
        )

        resp = await client.post(
            "/api/paper-balance/deposit",
            json={"amount_usd": 25.0, "reason": "test"},
        )
        assert resp.status_code == 200
        assert resp.json()["balance_usd"] == 525.0

        portfolio_resp = await client.get("/api/portfolio")
        assert portfolio_resp.status_code == 200
        portfolio = portfolio_resp.json()
        assert portfolio["total_equity_usd"] == 525.0
        assert portfolio["equity_history"][-1]["equity_usd"] == 525.0

    async def test_paper_balance_withdraw_updates_portfolio_equity_immediately(
        self,
        client: AsyncClient,
    ):
        """Manual paper withdrawals should sync the portfolio overview immediately."""
        _system_state.update(
            {
                "paper_balance_usd": 540.0,
                "paper_equity_usd": 540.0,
                "start_of_day_equity_usd": 500.0,
                "paper_transactions": [],
                "equity_history": [],
            }
        )

        resp = await client.post(
            "/api/paper-balance/withdraw",
            json={"amount_usd": 15.0, "reason": "test"},
        )
        assert resp.status_code == 200
        assert resp.json()["balance_usd"] == 525.0

        portfolio_resp = await client.get("/api/portfolio")
        assert portfolio_resp.status_code == 200
        portfolio = portfolio_resp.json()
        assert portfolio["total_equity_usd"] == 525.0
        assert portfolio["equity_history"][-1]["equity_usd"] == 525.0

    async def test_calibration_endpoint(self, client: AsyncClient):
        """Calibration endpoint returns CalibrationOverview."""
        resp = await client.get("/api/calibration")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_shadow_forecasts" in data
        assert "segments" in data

    async def test_categories_endpoint(self, client: AsyncClient):
        """Categories endpoint returns list."""
        resp = await client.get("/api/categories")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    async def test_bias_endpoint(self, client: AsyncClient):
        """Bias endpoint returns BiasAuditOverview."""
        resp = await client.get("/api/bias")
        assert resp.status_code == 200
        data = resp.json()
        assert "active_patterns" in data
        assert "persistent_pattern_count" in data

    async def test_viability_endpoint(self, client: AsyncClient):
        """Viability endpoint returns ViabilityOverview."""
        resp = await client.get("/api/viability")
        assert resp.status_code == 200
        data = resp.json()
        assert "current_signal" in data
        assert data["current_signal"] == "unassessed"

    async def test_absence_endpoint(self, client: AsyncClient):
        """Absence endpoint returns AbsenceStatus."""
        resp = await client.get("/api/absence")
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_absent"] is False

    async def test_system_health_endpoint(self, client: AsyncClient):
        """System health endpoint returns SystemHealthOverview."""
        resp = await client.get("/api/system-health")
        assert resp.status_code == 200
        data = resp.json()
        assert "overall_status" in data
        assert "components" in data
        assert data["overall_status"] == "healthy"

    async def test_agents_endpoint(self, client: AsyncClient):
        """Agents endpoint returns agent status list."""
        resp = await client.get("/api/agents")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 8

    async def test_control_mode_change(self, client: AsyncClient):
        """Mode change endpoint works."""
        resp = await client.post(
            "/api/control/mode",
            json={"mode": "shadow", "reason": "test"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["current_mode"] == "shadow"

    async def test_control_mode_invalid(self, client: AsyncClient):
        """Invalid mode change returns failure (but 200 with success=false)."""
        resp = await client.post(
            "/api/control/mode",
            json={"mode": "totally_invalid"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False

    async def test_control_agents_start(self, client: AsyncClient):
        """Start agents endpoint works."""
        resp = await client.post("/api/control/agents/start")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"]
        assert "started" in data["message"].lower()

    async def test_control_agents_stop(self, client: AsyncClient):
        """Stop agents endpoint works."""
        resp = await client.post("/api/control/agents/stop")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"]
        assert "stopped" in data["message"].lower()

    async def test_position_not_found(self, client: AsyncClient):
        """Requesting a non-existent position returns 404."""
        fake_id = str(uuid.uuid4())
        resp = await client.get(f"/api/positions/{fake_id}")
        assert resp.status_code == 404


# =============================================================================
# State Consistency Tests
# =============================================================================


class TestStateConsistency:
    """Test that system state changes are consistent across services."""

    async def test_mode_change_persists_in_portfolio(self, session: AsyncSession):
        """Mode change is reflected in portfolio overview."""
        state = {"operator_mode": "paper", "system_status": "running", "agents_running": False}
        service = DashboardService(session=session, system_state=state)

        await service.set_operator_mode("shadow")
        portfolio = await service.get_portfolio_overview()
        assert portfolio.operator_mode == "shadow"

    async def test_agent_toggle_persists_in_portfolio(self, session: AsyncSession):
        """Agent toggle is reflected in portfolio overview."""
        state = {"operator_mode": "paper", "system_status": "stopped", "agents_running": False}
        service = DashboardService(session=session, system_state=state)

        await service.toggle_agents(running=True)
        portfolio = await service.get_portfolio_overview()
        assert portfolio.system_status == "running"

    async def test_drawdown_level_in_risk_and_portfolio(self, session: AsyncSession):
        """Drawdown level is consistent between risk and portfolio."""
        state = {
            "operator_mode": "paper",
            "system_status": "running",
            "agents_running": False,
            "drawdown_level": "soft_warning",
            "drawdown_pct": 3.5,
        }
        service = DashboardService(session=session, system_state=state)

        portfolio = await service.get_portfolio_overview()
        risk = await service.get_risk_board()

        assert portfolio.drawdown_level == "soft_warning"
        assert portfolio.drawdown_pct == 3.5
        assert risk.drawdown_ladder.current_level == "soft_warning"
        assert risk.drawdown_ladder.current_drawdown_pct == 3.5


# =============================================================================
# Edge Case Tests
# =============================================================================


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_cost_metrics_zero_budget(self):
        """CostMetrics handles zero budget gracefully."""
        cost = CostMetrics(
            daily_budget_usd=0.0,
            daily_budget_remaining_usd=0.0,
            lifetime_budget_usd=0.0,
        )
        assert cost.daily_budget_usd == 0.0

    def test_drawdown_ladder_at_kill_switch(self):
        """DrawdownLadder at kill switch level."""
        ladder = DrawdownLadder(
            current_drawdown_pct=8.5,
            current_level="hard_kill_switch",
        )
        assert ladder.current_drawdown_pct > ladder.hard_kill_switch_pct
        assert ladder.current_level == "hard_kill_switch"

    def test_scanner_health_fully_degraded(self):
        """Scanner health at max degradation."""
        health = ScannerHealth(
            api_status="down",
            degraded_level=3,
            consecutive_failures=50,
            uptime_pct=0.0,
        )
        assert health.degraded_level == 3
        assert health.uptime_pct == 0.0

    def test_absence_max_level(self):
        """Absence at maximum escalation."""
        absence = AbsenceStatus(
            is_absent=True,
            absence_level=5,
            hours_since_activity=150.0,
            restrictions_active=[
                "no_new_entries",
                "size_reduced_25pct",
                "size_reduced_50pct",
                "graceful_winddown",
            ],
        )
        assert len(absence.restrictions_active) == 4

    def test_negative_pnl(self):
        """Portfolio handles negative P&L correctly."""
        overview = PortfolioOverview(
            daily_pnl_usd=-500.0,
            unrealized_pnl_usd=-600.0,
            realized_pnl_usd=100.0,
        )
        assert overview.daily_pnl_usd < 0

    def test_calibration_negative_advantage(self):
        """Calibration handles negative system advantage."""
        seg = CalibrationSegmentStatus(
            segment_name="sports",
            resolved_count=5,
            system_brier=0.240,
            market_brier=0.235,
            advantage=-0.005,
            status="insufficient",
        )
        assert seg.advantage is not None
        assert seg.advantage < 0

    def test_position_summary_all_optional_null(self):
        """Position summary with all optional fields null."""
        pos = PositionSummary(
            id=uuid.uuid4(),
            market_id="x",
            market_title="Test",
            side="yes",
            entry_price=0.5,
            size=100.0,
            remaining_size=100.0,
            status="open",
            review_tier="new",
        )
        assert pos.current_price is None
        assert pos.unrealized_pnl is None
        assert pos.category is None
        assert pos.entered_at is None

    async def test_service_with_none_config(self, session: AsyncSession):
        """Service handles None config gracefully."""
        service = DashboardService(session=session, config=None)
        cost = await service.get_cost_metrics()
        assert cost.daily_budget_usd == 25.0  # Falls back to default

        risk = await service.get_risk_board()
        assert risk.max_exposure_usd == 10000.0  # Falls back to default


# =============================================================================
# Workflow and Trigger DB Tests
# =============================================================================


class TestWorkflowAndTriggerDB:
    """Test workflow and trigger event database queries."""

    @pytest_asyncio.fixture
    async def trigger_session(self, session: AsyncSession):
        """Create test data with workflows and triggers."""
        mkt = Market(
            market_id="clob-trigger-001",
            title="Trigger Test Market",
            category="politics",
        )
        session.add(mkt)
        await session.flush()

        trigger = TriggerEvent(
            market_id=mkt.id,
            trigger_class="repricing",
            trigger_level="B",
            price_at_trigger=0.55,
            spread_at_trigger=0.03,
            data_source="live",
            reason="Price moved 8% in 2h",
            triggered_at=datetime.now(tz=UTC),
        )
        session.add(trigger)
        await session.flush()

        wf = WorkflowRun(
            workflow_run_id=f"wf-test-{uuid.uuid4().hex[:8]}",
            run_type="scheduled_sweep",
            market_id=mkt.id,
            trigger_event_id=trigger.id,
            status="completed",
            started_at=datetime.now(tz=UTC) - timedelta(minutes=5),
            completed_at=datetime.now(tz=UTC),
            actual_cost_usd=1.25,
        )
        session.add(wf)
        await session.flush()

        return session, mkt, trigger, wf

    async def test_get_trigger_events(self, trigger_session):
        """Trigger events are returned with correct fields."""
        session, mkt, trigger, _ = trigger_session
        service = DashboardService(session=session)
        events = await service.get_trigger_events()
        assert len(events) >= 1

        evt = events[0]
        assert evt.trigger_class == "repricing"
        assert evt.trigger_level == "B"
        assert evt.price == 0.55
        assert evt.spread == 0.03

    async def test_get_workflow_runs(self, trigger_session):
        """Workflow runs are returned with correct fields."""
        session, _, _, wf = trigger_session
        service = DashboardService(session=session)
        runs = await service.get_workflow_runs()
        assert len(runs) >= 1

        run = runs[0]
        assert run.workflow_type == "scheduled_sweep"
        assert run.status == "completed"
        assert run.cost_usd == 1.25

    async def test_get_workflow_runs_orders_by_latest_event_time(
        self, session: AsyncSession
    ):
        """Workflow runs are ordered by the latest event timestamp, not insertion time."""
        market = Market(
            market_id="workflow-ordering-market",
            title="Workflow Ordering Market",
            description="Dashboard ordering test",
            category="politics",
            market_status="active",
            is_active=True,
            slug="workflow-ordering-market",
        )
        session.add(market)
        await session.flush()

        older_created_later_completed = WorkflowRun(
            workflow_run_id=f"wf-order-old-{uuid.uuid4().hex[:8]}",
            run_type="trigger_based",
            market_id=market.id,
            status="completed",
            created_at=datetime(2026, 4, 15, 4, 0, tzinfo=UTC),
            started_at=datetime(2026, 4, 15, 4, 0, tzinfo=UTC),
            completed_at=datetime(2026, 4, 15, 6, 16, tzinfo=UTC),
        )
        newer_created_earlier_completed = WorkflowRun(
            workflow_run_id=f"wf-order-new-{uuid.uuid4().hex[:8]}",
            run_type="scheduled_sweep",
            market_id=market.id,
            status="completed",
            created_at=datetime(2026, 4, 15, 5, 30, tzinfo=UTC),
            started_at=datetime(2026, 4, 15, 5, 30, tzinfo=UTC),
            completed_at=datetime(2026, 4, 15, 5, 45, tzinfo=UTC),
        )
        session.add_all([older_created_later_completed, newer_created_earlier_completed])
        await session.flush()

        service = DashboardService(session=session)
        runs = await service.get_workflow_runs(limit=2)

        assert [run.id for run in runs] == [
            older_created_later_completed.id,
            newer_created_earlier_completed.id,
        ]

    async def test_trigger_events_empty(self, session: AsyncSession):
        """Empty trigger events list."""
        service = DashboardService(session=session)
        events = await service.get_trigger_events()
        assert events == []

    async def test_workflow_runs_empty(self, session: AsyncSession):
        """Empty workflow runs list."""
        service = DashboardService(session=session)
        runs = await service.get_workflow_runs()
        assert runs == []
