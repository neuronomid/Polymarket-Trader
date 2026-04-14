"""Template-based alert formatter.

Produces concise, scannable, structured Telegram messages from typed
notification payloads. This is the deterministic (Tier D) formatter
that handles the vast majority of messages. The optional Tier C
LLM-based alert composer is reserved for complex weekly/critical events.

Message format (spec Section 26.5):
    severity → event type → market/workflow → action → reason →
    risk impact → timestamp → reference ID

All messages are concise by default with an optional detailed follow-up
for critical and weekly events.
"""

from __future__ import annotations

from datetime import datetime

from core.enums import NotificationSeverity, NotificationType
from notifications.types import (
    NoTradePayload,
    NotificationEnvelope,
    OperatorAbsencePayload,
    RiskAlertPayload,
    StrategyViabilityPayload,
    SystemHealthPayload,
    TradeEntryPayload,
    TradeExitPayload,
    WeeklyPerformancePayload,
)

# Severity emoji mapping
_SEVERITY_ICON: dict[NotificationSeverity, str] = {
    NotificationSeverity.INFO: "ℹ️",
    NotificationSeverity.WARNING: "⚠️",
    NotificationSeverity.CRITICAL: "🚨",
}

# Event type label mapping
_EVENT_LABEL: dict[NotificationType, str] = {
    NotificationType.TRADE_ENTRY: "Trade Entry",
    NotificationType.TRADE_EXIT: "Trade Exit",
    NotificationType.RISK_ALERT: "Risk Alert",
    NotificationType.NO_TRADE: "No Trade",
    NotificationType.WEEKLY_PERFORMANCE: "Weekly Performance",
    NotificationType.SYSTEM_HEALTH: "System Health",
    NotificationType.STRATEGY_VIABILITY: "Strategy Viability",
    NotificationType.OPERATOR_ABSENCE: "Operator Absence",
}


def _ts(dt: datetime) -> str:
    """Format timestamp for Telegram messages."""
    return dt.strftime("%Y-%m-%d %H:%M UTC")


def _header(envelope: NotificationEnvelope) -> str:
    """Build the standard message header."""
    icon = _SEVERITY_ICON.get(envelope.severity, "ℹ️")
    label = _EVENT_LABEL.get(envelope.event_type, envelope.event_type.value)
    return f"{icon} *{label}*"


def format_trade_entry(envelope: NotificationEnvelope) -> str:
    """Format a trade entry alert message."""
    p = TradeEntryPayload(**envelope.payload)
    return (
        f"{_header(envelope)}\n"
        f"📊 {p.market_title}\n"
        f"Side: {p.side} @ ${p.entry_price:.4f}\n"
        f"Capital: ${p.allocated_capital_usd:.2f} ({p.portfolio_percentage:.1f}%)\n"
        f"Confidence: {p.confidence:.0%} | Edge: {p.estimated_edge:.1%}\n"
        f"Thesis: {p.thesis_summary[:120]}\n"
        f"🕐 {_ts(envelope.timestamp)} | ID: {p.trade_id[:8]}"
    )


def format_trade_exit(envelope: NotificationEnvelope) -> str:
    """Format a trade exit alert message."""
    p = TradeExitPayload(**envelope.payload)
    pnl_emoji = "📈" if p.realized_pnl_usd >= 0 else "📉"
    return (
        f"{_header(envelope)}\n"
        f"{pnl_emoji} {p.market_title}\n"
        f"{p.exit_type.title()} exit ({p.exit_class})\n"
        f"Exit price: ${p.exit_price:.4f}\n"
        f"PnL: ${p.realized_pnl_usd:+.2f}\n"
        f"Reason: {p.exit_reason}\n"
        f"Remaining: ${p.remaining_size_usd:.2f}\n"
        f"🕐 {_ts(envelope.timestamp)} | ID: {p.trade_id[:8]}"
    )


def format_risk_alert(envelope: NotificationEnvelope) -> str:
    """Format a risk alert message."""
    p = RiskAlertPayload(**envelope.payload)
    return (
        f"{_header(envelope)}\n"
        f"🛡️ {p.threshold_type.replace('_', ' ').title()}\n"
        f"Drawdown: {p.current_drawdown_pct:.1%}\n"
        f"Equity: ${p.current_equity_usd:,.2f} "
        f"(SOD: ${p.start_of_day_equity_usd:,.2f})\n"
        f"Deployed: ${p.deployed_capital_usd:,.2f}\n"
        f"State: {p.risk_state}\n"
        + (f"Detail: {p.detail}\n" if p.detail else "")
        + f"🕐 {_ts(envelope.timestamp)}"
    )


def format_no_trade(envelope: NotificationEnvelope) -> str:
    """Format a no-trade alert message."""
    p = NoTradePayload(**envelope.payload)
    status = "✅ Healthy" if p.is_healthy else "❌ Failed"
    lines = [
        f"{_header(envelope)}",
        f"Status: {status}",
        f"Duration: {p.workflow_run_duration_seconds:.1f}s",
        f"Candidates reviewed: {p.candidates_reviewed}",
        f"Reason: {p.reason}",
    ]
    if p.top_rejected_market:
        lines.append(f"Top rejected: {p.top_rejected_market}")
    if p.rejection_reasons:
        lines.append(f"Reasons: {', '.join(p.rejection_reasons[:3])}")
    lines.append(f"🕐 {_ts(envelope.timestamp)}")
    return "\n".join(lines)


def format_weekly_performance(envelope: NotificationEnvelope) -> str:
    """Format a weekly performance alert message."""
    p = WeeklyPerformancePayload(**envelope.payload)
    total_pnl = p.realized_pnl_usd + p.unrealized_pnl_usd
    pnl_emoji = "📈" if total_pnl >= 0 else "📉"

    lines = [
        f"{_header(envelope)}",
        f"{pnl_emoji} Total: ${total_pnl:+,.2f}",
        f"Realized: ${p.realized_pnl_usd:+,.2f} | Unrealized: ${p.unrealized_pnl_usd:+,.2f}",
        f"W/L: {p.total_wins}/{p.total_losses}",
    ]
    if p.best_category:
        lines.append(f"Best: {p.best_category}")
    if p.worst_category:
        lines.append(f"Worst: {p.worst_category}")
    if p.system_brier_score is not None and p.market_brier_score is not None:
        advantage = p.market_brier_score - p.system_brier_score
        lines.append(
            f"Brier: System {p.system_brier_score:.4f} vs "
            f"Market {p.market_brier_score:.4f} (Δ{advantage:+.4f})"
        )
    if p.cost_of_selectivity_ratio is not None:
        lines.append(f"Cost-of-selectivity: {p.cost_of_selectivity_ratio:.1%}")
    if p.strengths:
        lines.append(f"💪 {', '.join(p.strengths[:2])}")
    if p.weaknesses:
        lines.append(f"⚠️ {', '.join(p.weaknesses[:2])}")
    if p.policy_recommendations:
        lines.append(f"📋 {'; '.join(p.policy_recommendations[:2])}")
    lines.append(f"🕐 {_ts(envelope.timestamp)}")
    return "\n".join(lines)


def format_system_health(envelope: NotificationEnvelope) -> str:
    """Format a system health alert message."""
    p = SystemHealthPayload(**envelope.payload)
    return (
        f"{_header(envelope)}\n"
        f"🔧 {p.health_event.replace('_', ' ').title()}\n"
        f"Service: {p.service}\n"
        f"Summary: {p.summary}\n"
        + (f"Detail: {p.detail}\n" if p.detail else "")
        + (f"Run ID: {p.run_id[:8]}\n" if p.run_id else "")
        + f"🕐 {_ts(envelope.timestamp)}"
    )


def format_strategy_viability(envelope: NotificationEnvelope) -> str:
    """Format a strategy viability alert message."""
    p = StrategyViabilityPayload(**envelope.payload)
    lines = [
        f"{_header(envelope)}",
        f"📊 {p.checkpoint_type.replace('_', ' ').title()}",
    ]
    if p.system_brier is not None and p.market_brier is not None:
        advantage = p.market_brier - p.system_brier
        lines.append(
            f"Brier: System {p.system_brier:.4f} vs "
            f"Market {p.market_brier:.4f} (Δ{advantage:+.4f})"
        )
    if p.system_advantage is not None:
        lines.append(f"System advantage: {p.system_advantage:+.4f}")
    if p.lifetime_budget_consumed_pct is not None:
        lines.append(f"Budget consumed: {p.lifetime_budget_consumed_pct:.1%}")
    if p.bias_pattern_name:
        lines.append(f"Bias: {p.bias_pattern_name}")
    if p.detail:
        lines.append(f"Detail: {p.detail}")
    lines.append(f"🕐 {_ts(envelope.timestamp)}")
    return "\n".join(lines)


def format_operator_absence(envelope: NotificationEnvelope) -> str:
    """Format an operator absence alert message."""
    p = OperatorAbsencePayload(**envelope.payload)
    level_labels = {
        0: "Normal",
        1: "Absent Level 1 — No new entries",
        2: "Absent Level 2 — Size reduction 25%",
        3: "Absent Level 3 — Additional reduction",
        4: "Graceful Wind-Down",
    }
    level_label = level_labels.get(p.absence_level, f"Level {p.absence_level}")

    lines = [
        f"{_header(envelope)}",
        f"👤 {p.absence_event.replace('_', ' ').title()}",
        f"Status: {level_label}",
        f"Hours since interaction: {p.hours_since_last_interaction:.1f}h",
    ]
    if p.autonomous_actions_taken:
        lines.append(f"Actions: {', '.join(p.autonomous_actions_taken[:3])}")
    if p.detail:
        lines.append(f"Detail: {p.detail}")
    lines.append(f"🕐 {_ts(envelope.timestamp)}")
    return "\n".join(lines)


# --- Dispatch ---

_FORMATTERS: dict[NotificationType, callable] = {
    NotificationType.TRADE_ENTRY: format_trade_entry,
    NotificationType.TRADE_EXIT: format_trade_exit,
    NotificationType.RISK_ALERT: format_risk_alert,
    NotificationType.NO_TRADE: format_no_trade,
    NotificationType.WEEKLY_PERFORMANCE: format_weekly_performance,
    NotificationType.SYSTEM_HEALTH: format_system_health,
    NotificationType.STRATEGY_VIABILITY: format_strategy_viability,
    NotificationType.OPERATOR_ABSENCE: format_operator_absence,
}


def format_notification(envelope: NotificationEnvelope) -> str:
    """Format a notification envelope into a human-readable Telegram message.

    Uses deterministic template formatting. Falls back to a generic format
    if no specific formatter is registered.
    """
    formatter = _FORMATTERS.get(envelope.event_type)
    if formatter:
        return formatter(envelope)

    # Fallback generic format
    return (
        f"{_header(envelope)}\n"
        f"Payload: {envelope.payload}\n"
        f"🕐 {_ts(envelope.timestamp)} | ID: {envelope.event_id[:8]}"
    )
