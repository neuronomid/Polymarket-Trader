"""Learning system runtime types.

Pydantic models for fast/slow learning loops, category performance ledger,
no-trade rate monitoring, patience budget, and policy review.

These are in-process types — not ORM models.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# --- Enums ---


class LearningLoopType(str, Enum):
    """Type of learning loop iteration."""

    FAST = "fast"    # daily
    SLOW = "slow"    # weekly/biweekly


class PolicyChangeStatus(str, Enum):
    """Status of a proposed policy change."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    DEFERRED = "deferred"


class PatienceDecision(str, Enum):
    """Operator decision at patience budget expiry."""

    CONTINUE = "continue"
    ADJUST = "adjust"
    TERMINATE = "terminate"


class NoTradeRateSignal(str, Enum):
    """Signal from no-trade rate monitoring."""

    NORMAL = "normal"
    LOW_RATE_WARNING = "low_rate_warning"    # potential quality erosion
    HIGH_RATE_WARNING = "high_rate_warning"  # potential over-filtering


# --- Category Performance Ledger ---


class CategoryLedgerEntry(BaseModel):
    """Single category's weekly performance metrics.

    Per spec Section 15.8: updated weekly per category with all required fields.
    """

    category: str
    period_start: datetime
    period_end: datetime

    # Trade metrics
    trades_count: int = 0
    win_rate: float | None = None
    gross_pnl: float | None = None
    net_pnl: float | None = None
    inference_cost_usd: float | None = None
    average_edge: float | None = None
    average_holding_hours: float | None = None

    # Quality metrics
    rejection_rate: float | None = None
    no_trade_rate: float | None = None
    brier_score: float | None = None
    system_vs_market_brier: float | None = None

    # Cost metrics
    cost_of_selectivity: float | None = None
    slippage_ratio: float | None = None
    entry_impact_pct: float | None = None

    # Exit distribution
    exit_distribution: dict[str, int] = Field(default_factory=dict)


class CategoryLedgerReport(BaseModel):
    """Complete weekly category performance report."""

    entries: list[CategoryLedgerEntry] = Field(default_factory=list)
    period_start: datetime
    period_end: datetime
    generated_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))

    @property
    def total_trades(self) -> int:
        return sum(e.trades_count for e in self.entries)

    @property
    def total_pnl(self) -> float:
        return sum(e.net_pnl or 0.0 for e in self.entries)

    @property
    def total_cost(self) -> float:
        return sum(e.inference_cost_usd or 0.0 for e in self.entries)


# --- Fast Learning Loop ---


class FastLoopInput(BaseModel):
    """Input data for the daily fast learning loop."""

    as_of: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))

    # Calibration metrics
    new_resolutions: int = 0
    updated_segments: list[str] = Field(default_factory=list)

    # Cost metrics
    daily_spend_usd: float = 0.0
    trades_entered_today: int = 0
    cost_selectivity_ratio: float | None = None

    # Slippage metrics
    mean_slippage_ratio: float | None = None
    trades_since_friction_check: int = 0

    # Budget status
    daily_budget_remaining_pct: float = 1.0
    lifetime_budget_consumed_pct: float = 0.0

    # Absence status
    operator_absent: bool = False
    absence_hours: float = 0.0


class FastLoopResult(BaseModel):
    """Output from the daily fast learning loop."""

    loop_type: LearningLoopType = LearningLoopType.FAST
    executed_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))

    # Actions taken
    calibration_updated: bool = False
    segments_updated: list[str] = Field(default_factory=list)
    friction_recalibration_triggered: bool = False
    budget_alerts: list[str] = Field(default_factory=list)
    no_trade_signal: NoTradeRateSignal = NoTradeRateSignal.NORMAL

    # Metrics computed
    metrics: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


# --- Slow Learning Loop ---


class SlowLoopInput(BaseModel):
    """Input data for the weekly/biweekly slow learning loop."""

    as_of: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))
    period_weeks: int = 1  # 1 = weekly, 2 = biweekly

    # Category ledger data
    category_ledger: CategoryLedgerReport | None = None

    # Brier data (from calibration engine)
    brier_comparisons: list[dict[str, Any]] = Field(default_factory=list)

    # Agent usage data
    agent_usage_by_role: dict[str, dict[str, Any]] = Field(default_factory=dict)

    # Accumulation report
    accumulation_report: dict[str, Any] = Field(default_factory=dict)


class SlowLoopResult(BaseModel):
    """Output from the weekly slow learning loop."""

    loop_type: LearningLoopType = LearningLoopType.SLOW
    executed_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))

    # Analyses completed
    category_analysis_complete: bool = False
    agent_usefulness_reviewed: bool = False
    threshold_review_complete: bool = False
    policy_proposals_generated: int = 0

    # Key findings
    categories_needing_attention: list[str] = Field(default_factory=list)
    underperforming_agents: list[str] = Field(default_factory=list)
    threshold_adjustments: list[dict[str, Any]] = Field(default_factory=list)

    # Reports generated
    brier_comparison_included: bool = False
    accumulation_projection_included: bool = False
    friction_review_included: bool = False

    # Policy proposals
    policy_proposals: list[PolicyProposal] = Field(default_factory=list)

    warnings: list[str] = Field(default_factory=list)


# --- Policy Change ---


class PolicyProposal(BaseModel):
    """A proposed policy change from the learning system.

    Per spec Section 15.11:
    - No automatic policy change unless minimum sample threshold met
    - Pattern persistence exists (not a one-time observation)
    - Change documented with evidence and rationale
    - In early deployment, ALL changes require operator review
    """

    area: str  # risk, cost, eligibility, sizing, etc.
    title: str
    description: str
    rationale: str
    evidence: dict[str, Any] = Field(default_factory=dict)

    # Evidence thresholds
    sample_size: int = 0
    min_threshold_met: bool = False
    pattern_persistence_weeks: int = 0

    # Status
    status: PolicyChangeStatus = PolicyChangeStatus.PENDING
    requires_operator_review: bool = True

    proposed_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))


# Fix forward reference in SlowLoopResult
SlowLoopResult.model_rebuild()


# --- No-Trade Rate ---


class NoTradeRateMetrics(BaseModel):
    """No-trade rate metrics for monitoring.

    Per spec Section 15.12:
    - Not a failure metric
    - Low no-trade rate → potential quality erosion
    - High no-trade rate → potential over-filtering
    """

    # Per-run metrics
    runs_total: int = 0
    runs_with_no_trade: int = 0
    no_trade_rate: float = 0.0

    # Rolling metrics
    rolling_7d_rate: float | None = None
    rolling_30d_rate: float | None = None

    # Signal
    signal: NoTradeRateSignal = NoTradeRateSignal.NORMAL
    signal_reason: str = ""

    computed_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))


# --- Patience Budget ---


class PatienceBudgetState(BaseModel):
    """Current patience budget state.

    Per spec Section 15.13:
    - Default 9 months from shadow mode start
    - At expiry: comprehensive viability report
    - Operator must explicitly decide (continue/adjust/terminate)
    - Operator silence does NOT extend the budget
    """

    start_date: datetime
    expiry_date: datetime
    budget_months: int = 9

    elapsed_days: int
    remaining_days: int
    elapsed_pct: float

    is_expired: bool = False
    operator_decision: PatienceDecision | None = None
    decision_at: datetime | None = None

    @property
    def needs_decision(self) -> bool:
        """True when expired and no operator decision made."""
        return self.is_expired and self.operator_decision is None


# --- Performance Review ---


class PerformanceReviewInput(BaseModel):
    """Input for the weekly Performance Review workflow.

    Per spec Section 15.15: uses Performance Analyzer (Opus Tier A).
    """

    period_start: datetime
    period_end: datetime

    # Mandatory inputs (compressed from Tier D computations)
    category_ledger: CategoryLedgerReport
    brier_comparisons: list[dict[str, Any]] = Field(default_factory=list)
    accumulation_report: dict[str, Any] = Field(default_factory=dict)
    cost_metrics: dict[str, Any] = Field(default_factory=dict)
    friction_feedback: dict[str, Any] = Field(default_factory=dict)

    # Context
    system_week_number: int = 0
    operator_mode: str = "paper"


class PerformanceReviewResult(BaseModel):
    """Output from the Performance Review workflow.

    Mandatory outputs: Category Performance Ledger, shadow-vs-market Brier.
    """

    period_start: datetime
    period_end: datetime

    # Mandatory outputs
    category_ledger: CategoryLedgerReport
    brier_summary: dict[str, Any] = Field(default_factory=dict)

    # Strategic synthesis
    strategic_synthesis: str = ""
    category_scaling_evidence: dict[str, Any] = Field(default_factory=dict)
    policy_proposals: list[PolicyProposal] = Field(default_factory=list)

    # Cost
    review_cost_usd: float = 0.0
    opus_used: bool = False

    generated_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))
