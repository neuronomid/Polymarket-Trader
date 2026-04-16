"""Notification event types.

Pydantic models for all 8 required event types (spec Section 26.3).
These are the structured payloads that workflows emit into the event bus.
The notification service subscribes, formats, and delivers them.

Each event type carries only the data relevant to that event category.
Formatting into human-readable messages is the responsibility of the
alert composer or template formatters.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from core.enums import NotificationSeverity, NotificationType


class NotificationEnvelope(BaseModel):
    """Common envelope wrapping every notification event.

    Provides event identification, deduplication key, severity routing,
    and correlation back to workflows/markets/positions.
    """

    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_type: NotificationType
    severity: NotificationSeverity
    timestamp: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))

    # Context references (optional depending on event type)
    market_id: str | None = None
    position_id: str | None = None
    workflow_run_id: str | None = None

    # Deduplication: identical dedup_key within a window is suppressed
    dedup_key: str | None = None

    # The typed payload (one of the event-specific models below)
    payload: dict[str, Any] = Field(default_factory=dict)


# ========================
# A. Trade Entry Alerts
# ========================


class TradeEntryPayload(BaseModel):
    """Payload for trade entry notification (spec Section 26.3-A)."""

    market_title: str
    market_identifier: str
    side: str  # "Yes" or "No"
    entry_price: float
    allocated_capital_usd: float
    portfolio_percentage: float
    confidence: float
    estimated_edge: float
    thesis_summary: str
    trade_id: str
    workflow_source: str


# ========================
# B. Trade Exit Alerts
# ========================


class TradeExitPayload(BaseModel):
    """Payload for trade exit notification (spec Section 26.3-B)."""

    market_title: str
    market_identifier: str
    side: str
    exit_type: str  # "full" or "partial"
    exit_reason: str
    exit_class: str  # ExitClass value
    exit_price: float
    realized_pnl_usd: float
    remaining_size_usd: float
    trade_id: str
    workflow_source: str


# ========================
# C. Risk Alerts
# ========================


class RiskAlertPayload(BaseModel):
    """Payload for risk alert notification (spec Section 26.3-C)."""

    threshold_type: str  # soft_warning, risk_reduction, entries_disabled, kill_switch, etc.
    current_equity_usd: float
    start_of_day_equity_usd: float
    current_drawdown_pct: float
    deployed_capital_usd: float
    risk_state: str  # DrawdownLevel value
    affected_position_ids: list[str] = Field(default_factory=list)
    detail: str = ""


# ========================
# D. No-Trade Alerts
# ========================


class NoTradePayload(BaseModel):
    """Payload for no-trade alert notification (spec Section 26.3-D).

    Distinguishes healthy no-trade (good selectivity) from failed workflow
    or stalled scheduler.
    """

    workflow_run_duration_seconds: float
    reason: str  # healthy_no_trade, failed_workflow, stalled_scheduler
    stage: str | None = None
    reason_code: str | None = None
    reason_detail: str | None = None
    candidates_reviewed: int
    top_rejected_market: str | None = None
    rejection_reasons: list[str] = Field(default_factory=list)
    quantitative_context: dict[str, Any] = Field(default_factory=dict)
    is_healthy: bool = True  # False indicates workflow failure, not quality filtering


# ========================
# E. Weekly Performance Alerts
# ========================


class WeeklyPerformancePayload(BaseModel):
    """Payload for weekly performance notification (spec Section 26.3-E)."""

    realized_pnl_usd: float
    unrealized_pnl_usd: float
    total_wins: int
    total_losses: int
    best_category: str | None = None
    worst_category: str | None = None
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    policy_recommendations: list[str] = Field(default_factory=list)
    system_brier_score: float | None = None
    market_brier_score: float | None = None
    cost_of_selectivity_ratio: float | None = None


# ========================
# F. System Health Alerts
# ========================


class SystemHealthPayload(BaseModel):
    """Payload for system health notification (spec Section 26.3-F)."""

    health_event: str  # workflow_started, workflow_completed, workflow_failed,
    # scheduler_missed, api_failure, data_source_down,
    # logging_failure, latency_spike, execution_mismatch
    service: str
    summary: str
    run_id: str | None = None
    detail: str = ""


# ========================
# G. Strategy Viability Alerts
# ========================


class StrategyViabilityPayload(BaseModel):
    """Payload for strategy viability notification (spec Section 26.3-G)."""

    checkpoint_type: str  # viability_concern, viability_warning, budget_warning, bias_pattern
    system_brier: float | None = None
    market_brier: float | None = None
    system_advantage: float | None = None
    lifetime_budget_consumed_pct: float | None = None
    bias_pattern_name: str | None = None
    detail: str = ""


# ========================
# H. Operator Absence Alerts
# ========================


class OperatorAbsencePayload(BaseModel):
    """Payload for operator absence notification (spec Section 26.3-H)."""

    absence_event: str  # mode_activation, escalation_change, autonomous_action
    absence_level: int  # 0 (normal), 1, 2, 3, 4 (wind-down)
    hours_since_last_interaction: float
    autonomous_actions_taken: list[str] = Field(default_factory=list)
    detail: str = ""


# --- Helper to create envelopes from typed payloads ---

_PAYLOAD_SEVERITY_DEFAULTS: dict[NotificationType, NotificationSeverity] = {
    NotificationType.TRADE_ENTRY: NotificationSeverity.INFO,
    NotificationType.TRADE_EXIT: NotificationSeverity.INFO,
    NotificationType.RISK_ALERT: NotificationSeverity.WARNING,
    NotificationType.NO_TRADE: NotificationSeverity.INFO,
    NotificationType.WEEKLY_PERFORMANCE: NotificationSeverity.INFO,
    NotificationType.SYSTEM_HEALTH: NotificationSeverity.WARNING,
    NotificationType.STRATEGY_VIABILITY: NotificationSeverity.WARNING,
    NotificationType.OPERATOR_ABSENCE: NotificationSeverity.CRITICAL,
}


def create_envelope(
    event_type: NotificationType,
    payload: BaseModel,
    *,
    severity: NotificationSeverity | None = None,
    market_id: str | None = None,
    position_id: str | None = None,
    workflow_run_id: str | None = None,
    dedup_key: str | None = None,
) -> NotificationEnvelope:
    """Build a notification envelope from a typed payload.

    Uses the default severity for the event type if not provided.
    """
    effective_severity = severity or _PAYLOAD_SEVERITY_DEFAULTS.get(
        event_type, NotificationSeverity.INFO
    )

    return NotificationEnvelope(
        event_type=event_type,
        severity=effective_severity,
        market_id=market_id,
        position_id=position_id,
        workflow_run_id=workflow_run_id,
        dedup_key=dedup_key,
        payload=payload.model_dump(mode="json"),
    )
