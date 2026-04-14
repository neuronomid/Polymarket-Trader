"""FastAPI application and route definitions for the dashboard API.

All endpoints are grouped by dashboard page. CORS is configured for
the Next.js frontend running on localhost:3000.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession

from dashboard_api.schemas import (
    AbsenceStatus,
    ActivityLogEntry,
    AgentStatus,
    AlertItem,
    BiasAuditOverview,
    CalibrationOverview,
    CategoryPerformanceEntry,
    CostMetrics,
    OperatorModeRequest,
    PaperBalanceRequest,
    PaperBalanceResponse,
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
# Persisted state — survives restarts
# ──────────────────────────────────────────────

_STATE_FILE = Path("data") / "system_state.json"

# Keys that are persisted to disk so they survive restarts
_PERSISTED_KEYS = ("operator_mode", "paper_balance_usd", "start_of_day_equity_usd")


def _load_persisted_state() -> dict[str, Any]:
    """Load persisted state values from the JSON state file."""
    try:
        if _STATE_FILE.exists():
            with open(_STATE_FILE) as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def save_persisted_state() -> None:
    """Write the persisted subset of _system_state to disk."""
    try:
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        payload = {k: _system_state[k] for k in _PERSISTED_KEYS if k in _system_state}
        with open(_STATE_FILE, "w") as f:
            json.dump(payload, f, indent=2)
    except OSError as exc:
        _log.warning("state_persist_failed", error=str(exc))


# ──────────────────────────────────────────────
# Shared system state — mutable singleton
# ──────────────────────────────────────────────

_persisted = _load_persisted_state()

_system_state: dict[str, Any] = {
    "operator_mode": _persisted.get("operator_mode", "shadow"),
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
    # Paper balance tracking
    "paper_balance_usd": _persisted.get("paper_balance_usd", 500.0),
    "start_of_day_equity_usd": _persisted.get("start_of_day_equity_usd", 500.0),
    "paper_transactions": [],
    # Activity log (circular buffer, last 200 events)
    "activity_log": [],
}


# ──────────────────────────────────────────────
# Dependencies
# ──────────────────────────────────────────────

# Session factory — injected at startup
_session_factory = None
_app_config = None

# Shutdown event — injected by the orchestrator / __main__
# When set, the system performs a graceful shutdown.
_shutdown_event: asyncio.Event | None = None


def set_session_factory(factory: Any) -> None:
    """Set the async session factory for dependency injection."""
    global _session_factory
    _session_factory = factory


def set_app_config(config: Any) -> None:
    """Set the application config for dependency injection."""
    global _app_config
    _app_config = config


def set_shutdown_event(event: asyncio.Event) -> None:
    """Inject the shutdown event so the dashboard can trigger system shutdown."""
    global _shutdown_event
    _shutdown_event = event


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
        """Stop all agents and trigger system shutdown."""
        result = await service.toggle_agents(running=False)
        _add_activity("system", "Operator", "System shutdown requested from dashboard", severity="warning")
        # Trigger graceful system shutdown
        if _shutdown_event is not None:
            _log.info("dashboard_shutdown_requested")
            _shutdown_event.set()
        else:
            _log.warning("shutdown_event_not_wired", message="No shutdown event — system state toggled only")
        return result

    @app.post(
        "/api/control/shutdown",
        response_model=SystemControlResponse,
        tags=["operator"],
    )
    async def shutdown_system(
        service: DashboardService = Depends(get_dashboard_service),
    ):
        """Initiate a graceful system shutdown."""
        _add_activity("system", "Operator", "Graceful shutdown initiated from dashboard", severity="warning")
        await service.toggle_agents(running=False)
        if _shutdown_event is not None:
            _log.info("dashboard_shutdown_requested")
            _shutdown_event.set()
            return SystemControlResponse(
                success=True,
                message="Shutdown initiated — system is shutting down",
                current_mode=_system_state.get("operator_mode", "shadow"),
                timestamp=datetime.now(tz=UTC),
            )
        return SystemControlResponse(
            success=False,
            message="Shutdown event not wired — cannot shut down from dashboard",
            current_mode=_system_state.get("operator_mode", "shadow"),
            timestamp=datetime.now(tz=UTC),
        )

    # ─── Paper Balance ────────────────────────────

    @app.get(
        "/api/paper-balance",
        response_model=PaperBalanceResponse,
        tags=["operator"],
    )
    async def get_paper_balance():
        """Get current paper balance."""
        return PaperBalanceResponse(
            balance_usd=_system_state.get("paper_balance_usd", 500.0),
            start_of_day_equity_usd=_system_state.get("start_of_day_equity_usd", 500.0),
            operator_mode=_system_state.get("operator_mode", "shadow"),
            transactions=_system_state.get("paper_transactions", [])[-20:],
        )

    @app.post(
        "/api/paper-balance/deposit",
        response_model=PaperBalanceResponse,
        tags=["operator"],
    )
    async def deposit_paper_funds(request: PaperBalanceRequest):
        """Deposit paper funds."""
        if request.amount_usd <= 0:
            raise HTTPException(status_code=400, detail="Amount must be positive")
        mode = _system_state.get("operator_mode", "shadow")
        if mode not in ("shadow", "paper"):
            raise HTTPException(status_code=400, detail="Can only deposit in shadow/paper mode")

        _system_state["paper_balance_usd"] = _system_state.get("paper_balance_usd", 500.0) + request.amount_usd
        txn = {
            "type": "deposit",
            "amount_usd": request.amount_usd,
            "reason": request.reason or "Manual deposit",
            "timestamp": datetime.now(tz=UTC).isoformat(),
            "balance_after": _system_state["paper_balance_usd"],
        }
        _system_state.setdefault("paper_transactions", []).append(txn)
        _add_activity("system", "Paper Balance", f"Deposited ${request.amount_usd:.2f}", severity="success")
        _log.info("paper_deposit", amount=request.amount_usd, new_balance=_system_state["paper_balance_usd"])
        save_persisted_state()

        return PaperBalanceResponse(
            balance_usd=_system_state["paper_balance_usd"],
            start_of_day_equity_usd=_system_state.get("start_of_day_equity_usd", 500.0),
            operator_mode=mode,
            transactions=_system_state.get("paper_transactions", [])[-20:],
        )

    @app.post(
        "/api/paper-balance/withdraw",
        response_model=PaperBalanceResponse,
        tags=["operator"],
    )
    async def withdraw_paper_funds(request: PaperBalanceRequest):
        """Withdraw paper funds."""
        if request.amount_usd <= 0:
            raise HTTPException(status_code=400, detail="Amount must be positive")
        mode = _system_state.get("operator_mode", "shadow")
        if mode not in ("shadow", "paper"):
            raise HTTPException(status_code=400, detail="Can only withdraw in shadow/paper mode")

        current = _system_state.get("paper_balance_usd", 500.0)
        if request.amount_usd > current:
            raise HTTPException(status_code=400, detail=f"Insufficient balance: ${current:.2f}")

        _system_state["paper_balance_usd"] = current - request.amount_usd
        txn = {
            "type": "withdraw",
            "amount_usd": request.amount_usd,
            "reason": request.reason or "Manual withdrawal",
            "timestamp": datetime.now(tz=UTC).isoformat(),
            "balance_after": _system_state["paper_balance_usd"],
        }
        _system_state.setdefault("paper_transactions", []).append(txn)
        _add_activity("system", "Paper Balance", f"Withdrew ${request.amount_usd:.2f}", severity="warning")
        _log.info("paper_withdraw", amount=request.amount_usd, new_balance=_system_state["paper_balance_usd"])
        save_persisted_state()

        return PaperBalanceResponse(
            balance_usd=_system_state["paper_balance_usd"],
            start_of_day_equity_usd=_system_state.get("start_of_day_equity_usd", 500.0),
            operator_mode=mode,
            transactions=_system_state.get("paper_transactions", [])[-20:],
        )

    # ─── Activity Log ─────────────────────────────

    @app.get(
        "/api/activity",
        response_model=list[ActivityLogEntry],
        tags=["system"],
    )
    async def get_activity_log(
        limit: int = Query(50, ge=1, le=200),
    ):
        """Get recent system activity log."""
        log_entries = _system_state.get("activity_log", [])
        return [ActivityLogEntry(**e) for e in log_entries[-limit:][::-1]]

    return app


# ──────────────────────────────────────────────
# Activity Log Helper
# ──────────────────────────────────────────────

def _add_activity(
    event_type: str,
    component: str,
    message: str,
    detail: str | None = None,
    severity: str = "info",
) -> None:
    """Add an entry to the in-memory activity log."""
    import uuid as _uuid
    entry = {
        "id": str(_uuid.uuid4()),
        "timestamp": datetime.now(tz=UTC).isoformat(),
        "event_type": event_type,
        "component": component,
        "message": message,
        "detail": detail,
        "severity": severity,
    }
    log = _system_state.setdefault("activity_log", [])
    log.append(entry)
    # Keep only last 200 entries
    if len(log) > 200:
        _system_state["activity_log"] = log[-200:]
