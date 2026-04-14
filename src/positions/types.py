"""Position Management & Review runtime types.

Structured input/output containers for:
- Review scheduling (tiered frequency)
- Deterministic-first review checks (7 checks, Tier D)
- LLM-escalated review (Position Review Orchestration Agent)
- Position actions (Hold, Trim, Partial Close, Full Close, etc.)
- Exit classification (all 11 exit types)
- Cumulative review cost tracking per position

These are in-process Pydantic types — not ORM models.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from core.enums import (
    DrawdownLevel,
    ExitClass,
    ReviewTier,
    TriggerClass,
    TriggerLevel,
)


# --- Position Action ---


class PositionAction(str, Enum):
    """Actions that can be taken on a position after review.

    Per spec Section 11.5:
    - HOLD: maintain current position, no changes
    - TRIM: reduce position size by a fraction
    - PARTIAL_CLOSE: close a specific portion
    - FULL_CLOSE: exit the position entirely
    - FORCED_RISK_REDUCTION: risk governor mandated reduction
    - WATCH_AND_REVIEW: schedule earlier next review
    - REDUCE_TO_MINIMUM: drop to minimum monitoring (cost-triggered)
    """

    HOLD = "hold"
    TRIM = "trim"
    PARTIAL_CLOSE = "partial_close"
    FULL_CLOSE = "full_close"
    FORCED_RISK_REDUCTION = "forced_risk_reduction"
    WATCH_AND_REVIEW = "watch_and_review"
    REDUCE_TO_MINIMUM = "reduce_to_minimum"


class ReviewMode(str, Enum):
    """Review mode classification per spec Section 11.7.

    Determines which checks and agents are invoked.
    """

    SCHEDULED = "scheduled"
    STRESS = "stress"
    PROFIT_PROTECTION = "profit_protection"
    CATALYST = "catalyst"
    COST_EFFICIENCY = "cost_efficiency"


class ReviewOutcome(str, Enum):
    """Outcome classification for a review."""

    DETERMINISTIC_CLEAR = "deterministic_clear"
    LLM_ESCALATED = "llm_escalated"
    OPUS_ESCALATED = "opus_escalated"
    ERROR = "error"


# --- Deterministic Check Names ---


class DeterministicCheckName(str, Enum):
    """Names of the seven deterministic position review checks.

    Per spec Section 11.2, Step 1:
    1. Price vs entry/thesis range
    2. Spread vs limits
    3. Depth vs minimums
    4. Catalyst date proximity
    5. Drawdown state
    6. Position age vs horizon
    7. Cumulative review cost vs cap
    """

    PRICE_VS_THESIS = "price_vs_thesis"
    SPREAD_VS_LIMITS = "spread_vs_limits"
    DEPTH_VS_MINIMUMS = "depth_vs_minimums"
    CATALYST_PROXIMITY = "catalyst_proximity"
    DRAWDOWN_STATE = "drawdown_state"
    POSITION_AGE_VS_HORIZON = "position_age_vs_horizon"
    CUMULATIVE_REVIEW_COST = "cumulative_review_cost"


# --- Position Snapshot ---


class PositionSnapshot(BaseModel):
    """Current state of a held position for review purposes."""

    position_id: str
    market_id: str
    token_id: str = ""

    # Entry context
    entry_price: float
    entry_size_usd: float
    entry_side: str = "buy"
    entered_at: datetime

    # Current state
    current_price: float
    current_size_usd: float
    current_value_usd: float
    unrealized_pnl_usd: float = 0.0
    unrealized_pnl_pct: float = 0.0

    # Market data
    current_spread: float = 0.0
    current_depth_usd: float = 0.0
    current_best_bid: float | None = None
    current_best_ask: float | None = None

    # Thesis context
    thesis_card_id: str | None = None
    proposed_side: str = "yes"
    thesis_price_target: float | None = None
    thesis_price_floor: float | None = None
    core_thesis: str = ""
    invalidation_conditions: list[str] = Field(default_factory=list)

    # Catalyst and timing
    expected_catalyst: str | None = None
    expected_catalyst_date: datetime | None = None
    expected_horizon_hours: int | None = None

    # Category
    category: str = ""
    category_quality_tier: str = "standard"

    # Cluster correlation
    event_cluster_id: str | None = None
    cluster_ids: list[str] = Field(default_factory=list)

    # Review tier and history
    review_tier: ReviewTier = ReviewTier.NEW
    last_review_at: datetime | None = None
    total_reviews: int = 0
    last_trigger_at: datetime | None = None

    # Review cost tracking
    cumulative_review_cost_usd: float = 0.0
    cost_pct_of_value: float = 0.0
    review_cost_warning_hit: bool = False
    review_cost_cap_hit: bool = False

    # Drawdown and operator context
    drawdown_level: DrawdownLevel = DrawdownLevel.NORMAL
    operator_mode: str = "paper"

    # Workflow
    workflow_run_id: str = ""


# --- Deterministic Check Result ---


class DeterministicCheckResult(BaseModel):
    """Result of a single deterministic position review check."""

    check_name: DeterministicCheckName
    passed: bool
    detail: str = ""
    severity: str = "info"  # info, warning, critical
    threshold_value: float | None = None
    actual_value: float | None = None
    suggests_action: PositionAction | None = None
    suggests_exit_class: ExitClass | None = None


class DeterministicReviewResult(BaseModel):
    """Combined result of all seven deterministic checks.

    Per spec Section 11.2:
    - Step 2: ALL pass → DETERMINISTIC_REVIEW_CLEAR, no LLM cost (~65%)
    - Step 3: ANY flags → escalate to LLM review focused on flagged issues
    """

    all_passed: bool
    checks: list[DeterministicCheckResult] = Field(default_factory=list)
    flagged_checks: list[DeterministicCheckName] = Field(default_factory=list)
    suggested_action: PositionAction = PositionAction.HOLD
    suggested_exit_class: ExitClass | None = None
    review_mode: ReviewMode = ReviewMode.SCHEDULED
    reviewed_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))

    @property
    def needs_llm_escalation(self) -> bool:
        """Whether this review should escalate to LLM-based review."""
        return not self.all_passed

    @property
    def flag_summary(self) -> str:
        return "; ".join(c.value for c in self.flagged_checks) if self.flagged_checks else "All clear"


# --- Trigger Promotion ---


class TriggerPromotionEvent(BaseModel):
    """Event that promotes a position to Tier 1 review immediately.

    Per spec Section 11.1: Level C/D triggers promote to Tier 1 immediately.
    """

    position_id: str
    trigger_class: TriggerClass
    trigger_level: TriggerLevel
    reason: str = ""
    promoted_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))


# --- LLM Review Input/Output ---


class LLMReviewInput(BaseModel):
    """Input to the LLM-escalated review pipeline.

    Contains the flagged deterministic checks and position context
    so agents can focus their analysis on the flagged issues.
    """

    position: PositionSnapshot
    deterministic_result: DeterministicReviewResult
    flagged_issues: list[str] = Field(default_factory=list)
    review_mode: ReviewMode = ReviewMode.SCHEDULED
    workflow_run_id: str = ""

    # Cost constraints
    max_review_cost_usd: float | None = None
    allows_opus_escalation: bool = True
    cumulative_review_cost_usd: float = 0.0
    cost_pct_of_value: float = 0.0


class SubAgentResult(BaseModel):
    """Result from a position review sub-agent."""

    agent_role: str
    success: bool = True
    findings: dict[str, Any] = Field(default_factory=dict)
    cost_usd: float = 0.0
    error: str | None = None


class LLMReviewResult(BaseModel):
    """Combined output from LLM-escalated position review.

    Assembled from sub-agent results by the Position Review
    Orchestration Agent (Tier B).
    """

    position_id: str
    workflow_run_id: str = ""

    # Sub-agent results
    evidence_update: SubAgentResult | None = None
    thesis_integrity: SubAgentResult | None = None
    opposing_signals: SubAgentResult | None = None
    liquidity_assessment: SubAgentResult | None = None
    catalyst_shift: SubAgentResult | None = None

    # Orchestrator synthesis
    synthesis: dict[str, Any] = Field(default_factory=dict)
    recommended_action: PositionAction = PositionAction.HOLD
    recommended_exit_class: ExitClass | None = None
    confidence_in_action: float = 0.5  # 0-1

    # Opus escalation tracking
    opus_escalated: bool = False
    opus_escalation_reason: str | None = None

    # Cost
    total_review_cost_usd: float = 0.0
    agents_invoked: list[str] = Field(default_factory=list)

    reviewed_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))


# --- Position Review Result (Final) ---


class PositionReviewResult(BaseModel):
    """Complete output of a position review cycle.

    Per spec Section 11 acceptance criteria:
    - Every review produces structured action result with explicit action class
    - Exits always have explicit exit class
    """

    position_id: str
    market_id: str
    workflow_run_id: str = ""

    # Review classification
    review_tier: ReviewTier
    review_mode: ReviewMode
    review_outcome: ReviewOutcome

    # Deterministic phase
    deterministic_result: DeterministicReviewResult

    # LLM phase (None if deterministic clear)
    llm_result: LLMReviewResult | None = None

    # Final decision
    action: PositionAction
    exit_class: ExitClass | None = None
    action_reason: str = ""
    action_detail: dict[str, Any] = Field(default_factory=dict)

    # Sizing for trim/partial close
    target_size_usd: float | None = None
    reduction_pct: float | None = None

    # Next review scheduling
    next_review_tier: ReviewTier | None = None
    next_review_in_hours: float | None = None

    # Cost tracking
    review_cost_usd: float = 0.0
    was_deterministic_only: bool = True

    reviewed_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))


# --- Review Schedule ---


class ReviewScheduleEntry(BaseModel):
    """Scheduled review entry for a position."""

    position_id: str
    review_tier: ReviewTier
    scheduled_at: datetime
    review_mode: ReviewMode = ReviewMode.SCHEDULED
    promoted_by_trigger: bool = False
    trigger_event_id: str | None = None


class ReviewScheduleState(BaseModel):
    """Overall state of the review scheduler."""

    pending_reviews: list[ReviewScheduleEntry] = Field(default_factory=list)
    overdue_reviews: list[ReviewScheduleEntry] = Field(default_factory=list)
    next_review_at: datetime | None = None
    total_positions_tracked: int = 0
    tier_distribution: dict[str, int] = Field(default_factory=dict)
