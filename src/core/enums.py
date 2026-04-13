"""Core enums for the Polymarket Trader Agent.

All shared enumerations used across the system. These are the canonical
definitions — import from here, not from individual modules.
"""

from enum import Enum, auto


# --- Market Categories ---


class Category(str, Enum):
    """Allowed market categories the system may trade."""

    POLITICS = "politics"
    GEOPOLITICS = "geopolitics"
    TECHNOLOGY = "technology"
    SCIENCE_HEALTH = "science_health"
    MACRO_POLICY = "macro_policy"
    SPORTS = "sports"


class ExcludedCategory(str, Enum):
    """Categories the system must never trade.

    News: reactive, speed-dominated.
    Culture: sentiment-driven, weak objective grounding.
    Crypto: latency-oriented competition.
    Weather: needs meteorological models, not LLM reasoning.
    """

    NEWS = "news"
    CULTURE = "culture"
    CRYPTO = "crypto"
    WEATHER = "weather"


class CategoryQualityTier(str, Enum):
    """Quality tier assignment per category.

    Standard categories use normal sizing.
    QualityGated categories (Sports) carry lower default size multiplier
    until category-level calibration threshold (40 resolved trades) is met.
    """

    STANDARD = "standard"
    QUALITY_GATED = "quality_gated"


# --- Eligibility ---


class EligibilityOutcome(str, Enum):
    """Result of the eligibility gate for a market."""

    REJECT = "reject"
    WATCHLIST = "watchlist"
    TRIGGER_ELIGIBLE = "trigger_eligible"
    INVESTIGATE_NOW = "investigate_now"


# --- Trigger Scanner ---


class TriggerClass(str, Enum):
    """Classification of scanner trigger events."""

    DISCOVERY = "discovery"
    REPRICING = "repricing"
    LIQUIDITY = "liquidity"
    POSITION_STRESS = "position_stress"
    PROFIT_PROTECTION = "profit_protection"
    CATALYST_WINDOW = "catalyst_window"
    OPERATOR = "operator"


class TriggerLevel(str, Enum):
    """Severity level of a trigger event.

    A: log only.
    B: lightweight review.
    C: full investigation/review.
    D: immediate risk intervention.
    """

    A = "A"
    B = "B"
    C = "C"
    D = "D"


# --- Risk Governor ---


class RiskApproval(str, Enum):
    """Risk Governor decision on a proposed action."""

    REJECT = "reject"
    DELAY = "delay"
    WATCH = "watch"
    APPROVE_REDUCED = "approve_reduced"
    APPROVE_NORMAL = "approve_normal"
    APPROVE_SPECIAL = "approve_special"


class DrawdownLevel(str, Enum):
    """Drawdown defense ladder stages.

    Normal: no intervention.
    SoftWarning (3%): higher evidence threshold, reduced size suggestions.
    RiskReduction (5%): new entries materially reduced, low-conviction blocked.
    EntriesDisabled (6.5%): no new entries, management/reduction only.
    HardKillSwitch (8%): all entries blocked, capital preservation.
    """

    NORMAL = "normal"
    SOFT_WARNING = "soft_warning"
    RISK_REDUCTION = "risk_reduction"
    ENTRIES_DISABLED = "entries_disabled"
    HARD_KILL_SWITCH = "hard_kill_switch"


# --- Position Management ---


class ExitClass(str, Enum):
    """Classification for all position exits. Every exit must have one."""

    THESIS_INVALIDATED = "thesis_invalidated"
    RESOLUTION_RISK = "resolution_risk"
    TIME_DECAY = "time_decay"
    NEWS_SHOCK = "news_shock"
    PROFIT_PROTECTION = "profit_protection"
    LIQUIDITY_COLLAPSE = "liquidity_collapse"
    CORRELATION_RISK = "correlation_risk"
    PORTFOLIO_DEFENSE = "portfolio_defense"
    COST_INEFFICIENCY = "cost_inefficiency"
    OPERATOR_ABSENCE = "operator_absence"
    SCANNER_DEGRADATION = "scanner_degradation"


class ReviewTier(str, Enum):
    """Position review frequency tiers.

    NEW: first 48 hours, every 2-4 hours.
    STABLE: every 6-8 hours.
    LOW_VALUE: every 12 hours.
    """

    NEW = "new"
    STABLE = "stable"
    LOW_VALUE = "low_value"


# --- Operator Modes ---


class OperatorMode(str, Enum):
    """System operating modes. Progressive rollout: Paper → Shadow → LiveSmall → LiveStandard."""

    PAPER = "paper"
    SHADOW = "shadow"
    LIVE_SMALL = "live_small"
    LIVE_STANDARD = "live_standard"
    RISK_REDUCTION = "risk_reduction"
    EMERGENCY_HALT = "emergency_halt"
    OPERATOR_ABSENT = "operator_absent"
    SCANNER_DEGRADED = "scanner_degraded"


# --- LLM Model Tiers ---


class ModelTier(str, Enum):
    """LLM model tiers per V4 model philosophy.

    A: Premium (Opus) — high-value synthesis/decision bottlenecks only.
    B: Workhorse (Sonnet) — repeated meaningful reasoning.
    C: Utility (GPT-5.4 nano/mini) — extraction, formatting, summaries.
    D: No LLM — fully deterministic.
    """

    A = "A"
    B = "B"
    C = "C"
    D = "D"


class CostClass(str, Enum):
    """Cost classification for pre-run estimation.

    H: $0.05-$0.30 per call (premium).
    M: $0.01-$0.05 per call (workhorse).
    L: $0.001-$0.005 per call (utility).
    Z: $0 (deterministic).
    """

    H = "H"
    M = "M"
    L = "L"
    Z = "Z"


# --- Calibration ---


class CalibrationRegime(str, Enum):
    """Calibration data sufficiency state."""

    INSUFFICIENT = "insufficient"
    SUFFICIENT = "sufficient"
    VIABILITY_UNCERTAIN = "viability_uncertain"


# --- Notifications ---


class NotificationSeverity(str, Enum):
    """Severity level for operator notifications."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class NotificationType(str, Enum):
    """Types of operator notifications."""

    TRADE_ENTRY = "trade_entry"
    TRADE_EXIT = "trade_exit"
    RISK_ALERT = "risk_alert"
    NO_TRADE = "no_trade"
    WEEKLY_PERFORMANCE = "weekly_performance"
    SYSTEM_HEALTH = "system_health"
    STRATEGY_VIABILITY = "strategy_viability"
    OPERATOR_ABSENCE = "operator_absence"
