"""Pydantic response schemas for dashboard API endpoints.

These are API-facing DTOs — they translate internal domain models
into clean JSON shapes for the Next.js frontend.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


# ──────────────────────────────────────────────
# Portfolio Overview
# ──────────────────────────────────────────────


class EquitySnapshot(BaseModel):
    """Point-in-time equity reading."""

    timestamp: datetime
    equity_usd: float
    pnl_usd: float


class PortfolioOverview(BaseModel):
    """Executive-level portfolio summary."""

    total_equity_usd: float = 0.0
    total_open_exposure_usd: float = 0.0
    daily_pnl_usd: float = 0.0
    unrealized_pnl_usd: float = 0.0
    realized_pnl_usd: float = 0.0
    open_positions_count: int = 0
    drawdown_level: str = "normal"
    drawdown_pct: float = 0.0
    operator_mode: str = "paper"
    system_status: str = "running"  # running | stopped | degraded
    equity_history: list[EquitySnapshot] = Field(default_factory=list)


# ──────────────────────────────────────────────
# Positions
# ──────────────────────────────────────────────


class PositionSummary(BaseModel):
    """Compact position for list views."""

    id: UUID
    market_id: str
    market_title: str
    side: str
    entry_price: float
    current_price: float | None = None
    size: float
    remaining_size: float
    unrealized_pnl: float | None = None
    realized_pnl: float | None = None
    status: str
    review_tier: str
    category: str | None = None
    entered_at: datetime | None = None


class PositionDetail(PositionSummary):
    """Extended position with thesis and cost data."""

    thesis_summary: str | None = None
    probability_estimate: float | None = None
    confidence_estimate: float | None = None
    calibration_confidence: float | None = None
    risk_approval: str | None = None
    cumulative_review_cost_usd: float = 0.0
    total_inference_cost_usd: float = 0.0
    exit_class: str | None = None
    exit_price: float | None = None
    exited_at: datetime | None = None
    last_reviewed_at: datetime | None = None
    next_review_at: datetime | None = None


# ──────────────────────────────────────────────
# Risk Board
# ──────────────────────────────────────────────


class DrawdownLadder(BaseModel):
    """Current drawdown defense ladder state."""

    current_drawdown_pct: float = 0.0
    soft_warning_pct: float = 0.03
    risk_reduction_pct: float = 0.05
    entries_disabled_pct: float = 0.065
    hard_kill_switch_pct: float = 0.08
    current_level: str = "normal"


class ExposureByCategory(BaseModel):
    """Exposure breakdown per category."""

    category: str
    exposure_usd: float
    cap_usd: float
    positions_count: int
    pct_of_cap: float


class RiskBoard(BaseModel):
    """Full risk dashboard data."""

    drawdown_ladder: DrawdownLadder = Field(default_factory=DrawdownLadder)
    total_exposure_usd: float = 0.0
    max_exposure_usd: float = 0.0
    exposure_by_category: list[ExposureByCategory] = Field(default_factory=list)
    correlation_groups_count: int = 0
    daily_deployment_used_pct: float = 0.0
    max_daily_deployment_pct: float = 0.10


# ──────────────────────────────────────────────
# Workflows & Agents
# ──────────────────────────────────────────────


class WorkflowRunSummary(BaseModel):
    """Summary of a workflow run."""

    id: UUID
    workflow_type: str
    status: str
    started_at: datetime | None = None
    completed_at: datetime | None = None
    cost_usd: float = 0.0
    candidates_reviewed: int = 0
    candidates_accepted: int = 0
    market_title: str | None = None


# ──────────────────────────────────────────────
# Trigger Events
# ──────────────────────────────────────────────


class TriggerEventItem(BaseModel):
    """A scanner trigger event."""

    id: UUID
    trigger_class: str
    trigger_level: str
    market_id: str | None = None
    market_title: str | None = None
    reason: str | None = None
    price: float | None = None
    spread: float | None = None
    data_source: str | None = None
    timestamp: datetime


# ──────────────────────────────────────────────
# Cost Metrics
# ──────────────────────────────────────────────


class CostMetrics(BaseModel):
    """Aggregated cost data for dashboard."""

    daily_spend_usd: float = 0.0
    daily_budget_usd: float = 25.0
    daily_budget_remaining_usd: float = 25.0
    lifetime_spend_usd: float = 0.0
    lifetime_budget_usd: float = 5000.0
    lifetime_budget_pct: float = 0.0
    selectivity_ratio: float = 0.0
    selectivity_target: float = 0.20
    opus_spend_today_usd: float = 0.0
    opus_budget_usd: float = 5.0


# ──────────────────────────────────────────────
# Calibration
# ──────────────────────────────────────────────


class CalibrationSegmentStatus(BaseModel):
    """Calibration status for a single segment."""

    segment_name: str
    resolved_count: int = 0
    required_count: int = 20
    system_brier: float | None = None
    market_brier: float | None = None
    advantage: float | None = None
    projected_threshold_date: datetime | None = None
    status: str = "insufficient"  # insufficient | preliminary | reliable


class CalibrationOverview(BaseModel):
    """Dashboard calibration overview."""

    total_shadow_forecasts: int = 0
    total_resolved: int = 0
    overall_system_brier: float | None = None
    overall_market_brier: float | None = None
    overall_advantage: float | None = None
    patience_budget_months: int = 9
    patience_budget_remaining_days: int | None = None
    segments: list[CalibrationSegmentStatus] = Field(default_factory=list)


# ──────────────────────────────────────────────
# Scanner Health
# ──────────────────────────────────────────────


class ScannerHealth(BaseModel):
    """Scanner infrastructure health."""

    api_status: str = "healthy"  # healthy | degraded | down
    degraded_level: int = 0  # 0-3
    cache_entries_count: int = 0
    cache_hit_rate: float = 0.0
    last_successful_poll: datetime | None = None
    consecutive_failures: int = 0
    uptime_pct: float = 100.0


# ──────────────────────────────────────────────
# Category Performance
# ──────────────────────────────────────────────


class CategoryPerformanceEntry(BaseModel):
    """Performance ledger for one category."""

    category: str
    total_trades: int = 0
    win_rate: float = 0.0
    gross_pnl_usd: float = 0.0
    net_pnl_usd: float = 0.0
    inference_cost_usd: float = 0.0
    avg_edge: float = 0.0
    avg_holding_hours: float = 0.0
    brier_score: float | None = None
    system_vs_market_brier: float | None = None
    no_trade_rate: float = 0.0


# ──────────────────────────────────────────────
# Bias Audit
# ──────────────────────────────────────────────


class BiasPatternItem(BaseModel):
    """A detected bias pattern."""

    pattern_type: str
    severity: str
    description: str
    weeks_active: int = 0
    is_persistent: bool = False
    first_detected: datetime | None = None


class BiasAuditOverview(BaseModel):
    """Dashboard bias summary."""

    last_audit_at: datetime | None = None
    active_patterns: list[BiasPatternItem] = Field(default_factory=list)
    persistent_pattern_count: int = 0
    resolved_pattern_count: int = 0


# ──────────────────────────────────────────────
# Viability
# ──────────────────────────────────────────────


class ViabilityCheckpointItem(BaseModel):
    """A viability checkpoint result."""

    checkpoint_week: int
    assessed_at: datetime
    signal: str  # positive | neutral | negative | strongly_negative
    system_brier: float | None = None
    market_brier: float | None = None
    resolved_count: int = 0
    recommendation: str | None = None


class ViabilityOverview(BaseModel):
    """Dashboard viability summary."""

    current_signal: str = "unassessed"
    checkpoints: list[ViabilityCheckpointItem] = Field(default_factory=list)
    lifetime_budget_pct: float = 0.0
    patience_budget_remaining_days: int | None = None


# ──────────────────────────────────────────────
# Operator Absence
# ──────────────────────────────────────────────


class AbsenceStatus(BaseModel):
    """Operator absence state."""

    is_absent: bool = False
    absence_level: int = 0
    hours_since_activity: float = 0.0
    last_activity: datetime | None = None
    restrictions_active: list[str] = Field(default_factory=list)
    autonomous_actions_count: int = 0


# ──────────────────────────────────────────────
# System Health
# ──────────────────────────────────────────────


class SystemHealthItem(BaseModel):
    """Health status for a system component."""

    component: str
    status: str  # healthy | warning | critical | down
    last_check: datetime | None = None
    details: str | None = None


class SystemHealthOverview(BaseModel):
    """Dashboard system health."""

    overall_status: str = "healthy"
    components: list[SystemHealthItem] = Field(default_factory=list)
    active_alerts_count: int = 0


# ──────────────────────────────────────────────
# Alerts
# ──────────────────────────────────────────────


class AlertItem(BaseModel):
    """A notification/alert record."""

    id: UUID
    event_type: str
    severity: str
    title: str
    message: str
    timestamp: datetime
    delivered: bool = False
    delivery_channel: str | None = None


# ──────────────────────────────────────────────
# Agent Status
# ──────────────────────────────────────────────


class AgentStatus(BaseModel):
    """Status of a system agent or service."""

    name: str
    role: str
    tier: str
    is_active: bool = False
    last_invoked: datetime | None = None
    total_invocations: int = 0
    total_cost_usd: float = 0.0


# ──────────────────────────────────────────────
# Operator Controls
# ──────────────────────────────────────────────


class OperatorModeRequest(BaseModel):
    """Request to change system mode."""

    mode: str
    reason: str | None = None


class SystemControlResponse(BaseModel):
    """Response for system control operations."""

    success: bool
    message: str
    current_mode: str
    timestamp: datetime
