"""FastAPI application and route definitions for the dashboard API.

All endpoints are grouped by dashboard page. CORS is configured for
the Next.js frontend running on localhost:3000.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import structlog
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession

from dashboard_api.schemas import (
    AbsenceStatus,
    AgentStatus,
    AlertItem,
    BiasAuditOverview,
    CalibrationOverview,
    CategoryPerformanceEntry,
    CostMetrics,
    OperatorModeRequest,
    PortfolioOverview,
    PositionDetail,
    PositionSummary,
    RiskBoard,
    ScannerHealth,
    SystemControlResponse,
    SystemHealthOverview,
    TriggerEventItem,
    ViabilityOverview,
    WorkflowRunSummary,
)
from dashboard_api.services import DashboardService

_log = structlog.get_logger(component="dashboard_api")

# ──────────────────────────────────────────────
# Shared system state — mutable singleton
# ──────────────────────────────────────────────

_system_state: dict[str, Any] = {
    "operator_mode": "paper",
    "system_status": "running",
    "agents_running": False,
    "drawdown_level": "normal",
    "drawdown_pct": 0.0,
    "daily_deployment_used_pct": 0.0,
    "daily_spend_usd": 0.0,
    "lifetime_spend_usd": 0.0,
    "selectivity_ratio": 0.0,
    "opus_spend_today_usd": 0.0,
    "scanner_api_status": "healthy",
    "scanner_degraded_level": 0,
    "scanner_cache_entries": 0,
    "scanner_cache_hit_rate": 0.0,
    "scanner_consecutive_failures": 0,
    "scanner_uptime_pct": 100.0,
    "telegram_status": "healthy",
    "is_absent": False,
    "absence_level": 0,
    "hours_since_activity": 0.0,
    "viability_signal": "unassessed",
    "active_alerts_count": 0,
}


# ──────────────────────────────────────────────
# Dependencies
# ──────────────────────────────────────────────

# Session factory — injected at startup
_session_factory = None
_app_config = None


def set_session_factory(factory: Any) -> None:
    """Set the async session factory for dependency injection."""
    global _session_factory
    _session_factory = factory


def set_app_config(config: Any) -> None:
    """Set the application config for dependency injection."""
    global _app_config
    _app_config = config


async def get_db_session():
    """Dependency that yields an async DB session."""
    if _session_factory is None:
        raise HTTPException(status_code=503, detail="Database not initialized")
    async with _session_factory() as session:
        yield session


async def get_dashboard_service(
    session: AsyncSession = Depends(get_db_session),
) -> DashboardService:
    """Dependency that provides a DashboardService instance."""
    return DashboardService(
        session=session,
        config=_app_config,
        system_state=_system_state,
    )


# ──────────────────────────────────────────────
# App creation
# ──────────────────────────────────────────────


def create_dashboard_app() -> FastAPI:
    """Create and configure the FastAPI dashboard application."""

    app = FastAPI(
        title="Polymarket Trader Dashboard API",
        description="Operational dashboard backend for the Polymarket trading system",
        version="0.1.0",
    )

    # CORS for Next.js frontend
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:3001",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ─── Health ───────────────────────────────────

    @app.get("/api/health", tags=["health"])
    async def health_check():
        """Simple health check endpoint."""
        return {
            "status": "ok",
            "timestamp": datetime.now(tz=UTC).isoformat(),
            "version": "0.1.0",
        }

    # ─── Portfolio ────────────────────────────────

    @app.get(
        "/api/portfolio",
        response_model=PortfolioOverview,
        tags=["portfolio"],
    )
    async def get_portfolio(
        service: DashboardService = Depends(get_dashboard_service),
    ):
        """Executive-level portfolio overview."""
        return await service.get_portfolio_overview()

    # ─── Positions ────────────────────────────────

    @app.get(
        "/api/positions",
        response_model=list[PositionSummary],
        tags=["positions"],
    )
    async def list_positions(
        status: str | None = Query(None, description="Filter by status: open, closed, reducing"),
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
        service: DashboardService = Depends(get_dashboard_service),
    ):
        """List positions with optional filtering."""
        return await service.get_positions(status=status, limit=limit, offset=offset)

    @app.get(
        "/api/positions/{position_id}",
        response_model=PositionDetail,
        tags=["positions"],
    )
    async def get_position(
        position_id: uuid.UUID,
        service: DashboardService = Depends(get_dashboard_service),
    ):
        """Get detailed position data."""
        detail = await service.get_position_detail(position_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="Position not found")
        return detail

    # ─── Risk Board ───────────────────────────────

    @app.get(
        "/api/risk",
        response_model=RiskBoard,
        tags=["risk"],
    )
    async def get_risk_board(
        service: DashboardService = Depends(get_dashboard_service),
    ):
        """Risk dashboard with drawdown ladder and exposure breakdown."""
        return await service.get_risk_board()

    # ─── Workflows ────────────────────────────────

    @app.get(
        "/api/workflows",
        response_model=list[WorkflowRunSummary],
        tags=["workflows"],
    )
    async def list_workflows(
        limit: int = Query(20, ge=1, le=100),
        offset: int = Query(0, ge=0),
        service: DashboardService = Depends(get_dashboard_service),
    ):
        """Recent workflow runs."""
        return await service.get_workflow_runs(limit=limit, offset=offset)

    # ─── Triggers ─────────────────────────────────

    @app.get(
        "/api/triggers",
        response_model=list[TriggerEventItem],
        tags=["triggers"],
    )
    async def list_triggers(
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
        service: DashboardService = Depends(get_dashboard_service),
    ):
        """Recent scanner trigger events."""
        return await service.get_trigger_events(limit=limit, offset=offset)

    # ─── Cost Metrics ─────────────────────────────

    @app.get(
        "/api/cost",
        response_model=CostMetrics,
        tags=["cost"],
    )
    async def get_cost_metrics(
        service: DashboardService = Depends(get_dashboard_service),
    ):
        """Aggregated cost governor metrics."""
        return await service.get_cost_metrics()

    # ─── Calibration ──────────────────────────────

    @app.get(
        "/api/calibration",
        response_model=CalibrationOverview,
        tags=["calibration"],
    )
    async def get_calibration(
        service: DashboardService = Depends(get_dashboard_service),
    ):
        """Calibration status and Brier scores."""
        return await service.get_calibration_overview()

    # ─── Scanner Health ───────────────────────────

    @app.get(
        "/api/scanner",
        response_model=ScannerHealth,
        tags=["scanner"],
    )
    async def get_scanner_health(
        service: DashboardService = Depends(get_dashboard_service),
    ):
        """Scanner infrastructure health."""
        return await service.get_scanner_health()

    # ─── Category Performance ─────────────────────

    @app.get(
        "/api/categories",
        response_model=list[CategoryPerformanceEntry],
        tags=["analytics"],
    )
    async def get_categories(
        service: DashboardService = Depends(get_dashboard_service),
    ):
        """Category Performance Ledger."""
        return await service.get_category_performance()

    # ─── Bias Audit ───────────────────────────────

    @app.get(
        "/api/bias",
        response_model=BiasAuditOverview,
        tags=["analytics"],
    )
    async def get_bias_audit(
        service: DashboardService = Depends(get_dashboard_service),
    ):
        """Bias audit summary."""
        return await service.get_bias_audit()

    # ─── Viability ────────────────────────────────

    @app.get(
        "/api/viability",
        response_model=ViabilityOverview,
        tags=["analytics"],
    )
    async def get_viability(
        service: DashboardService = Depends(get_dashboard_service),
    ):
        """Strategy viability status."""
        return await service.get_viability()

    # ─── Absence Status ──────────────────────────

    @app.get(
        "/api/absence",
        response_model=AbsenceStatus,
        tags=["operator"],
    )
    async def get_absence_status(
        service: DashboardService = Depends(get_dashboard_service),
    ):
        """Operator absence state."""
        return await service.get_absence_status()

    # ─── System Health ────────────────────────────

    @app.get(
        "/api/system-health",
        response_model=SystemHealthOverview,
        tags=["health"],
    )
    async def get_system_health(
        service: DashboardService = Depends(get_dashboard_service),
    ):
        """System-wide health overview."""
        return await service.get_system_health()

    # ─── Agents ───────────────────────────────────

    @app.get(
        "/api/agents",
        response_model=list[AgentStatus],
        tags=["agents"],
    )
    async def get_agents(
        service: DashboardService = Depends(get_dashboard_service),
    ):
        """Agent status list."""
        return await service.get_agent_statuses()

    # ─── Operator Controls ────────────────────────

    @app.post(
        "/api/control/mode",
        response_model=SystemControlResponse,
        tags=["operator"],
    )
    async def change_mode(
        request: OperatorModeRequest,
        service: DashboardService = Depends(get_dashboard_service),
    ):
        """Change the system operator mode."""
        return await service.set_operator_mode(request.mode, request.reason)

    @app.post(
        "/api/control/agents/start",
        response_model=SystemControlResponse,
        tags=["operator"],
    )
    async def start_agents(
        service: DashboardService = Depends(get_dashboard_service),
    ):
        """Start all agents."""
        return await service.toggle_agents(running=True)

    @app.post(
        "/api/control/agents/stop",
        response_model=SystemControlResponse,
        tags=["operator"],
    )
    async def stop_agents(
        service: DashboardService = Depends(get_dashboard_service),
    ):
        """Stop all agents."""
        return await service.toggle_agents(running=False)

    return app
