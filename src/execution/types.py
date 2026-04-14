"""Execution engine runtime types.

Structured input/output containers for the execution engine,
slippage tracking, and friction model calibration.

These are in-process Pydantic types — not ORM models.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# --- Enums ---


class EntryMode(str, Enum):
    """Controlled entry mode for order execution.

    From spec Section 12.4:
    - IMMEDIATE: rare, high-confidence, low-friction, time-sensitive
    - STAGED: split across multiple orders (preferred when > 5% of depth)
    - PRICE_IMPROVEMENT: hold pending better fill within window
    - CANCEL_IF_DEGRADED: cancel if conditions don't improve within timeout
    """

    IMMEDIATE = "immediate"
    STAGED = "staged"
    PRICE_IMPROVEMENT = "price_improvement"
    CANCEL_IF_DEGRADED = "cancel_if_degraded"


class ExecutionOutcome(str, Enum):
    """Result of the execution engine."""

    EXECUTED = "executed"
    DELAYED_AND_RETRIED = "delayed_and_retried"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class RevalidationCheckName(str, Enum):
    """Names of pre-execution revalidation checks."""

    MARKET_OPEN = "market_open"
    SIDE_CORRECT = "side_correct"
    SPREAD_WITHIN_BOUNDS = "spread_within_bounds"
    DEPTH_ACCEPTABLE = "depth_acceptable"
    DRAWDOWN_NOT_WORSENED = "drawdown_not_worsened"
    EXPOSURE_BUDGET_AVAILABLE = "exposure_budget_available"
    NO_DUPLICATE_ORDER = "no_duplicate_order"
    NO_NEW_AMBIGUITY = "no_new_ambiguity"
    APPROVAL_NOT_STALE = "approval_not_stale"
    LIQUIDITY_RELATIVE_LIMIT = "liquidity_relative_limit"
    ENTRY_IMPACT_WITHIN_BOUNDS = "entry_impact_within_bounds"
    NOT_IN_OPERATOR_ABSENT = "not_in_operator_absent"


# --- Revalidation Types ---


class RevalidationCheck(BaseModel):
    """Result of a single pre-execution revalidation check."""

    check_name: RevalidationCheckName
    passed: bool
    detail: str = ""


class RevalidationResult(BaseModel):
    """Combined result of all pre-execution revalidation checks."""

    all_passed: bool
    checks: list[RevalidationCheck] = Field(default_factory=list)
    failed_checks: list[str] = Field(default_factory=list)
    validated_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))

    @property
    def failure_summary(self) -> str:
        return "; ".join(self.failed_checks) if self.failed_checks else "All passed"


# --- Execution Request ---


class ExecutionRequest(BaseModel):
    """Input to the execution engine for placing an order.

    Contains the full approval chain context for logging.
    """

    # Identifiers
    workflow_run_id: str
    market_id: str
    token_id: str
    thesis_card_id: str | None = None
    position_id: str | None = None  # set for exits/adjustments on existing positions

    # Order parameters
    side: str  # "buy" or "sell"
    price: float
    size_usd: float
    order_type: str = "limit"

    # Market context (for revalidation)
    current_spread: float | None = None
    current_depth_usd: float = 0.0
    current_best_bid: float | None = None
    current_best_ask: float | None = None
    current_mid_price: float | None = None
    market_status: str = "active"

    # Approval context
    risk_approval: str = ""
    risk_conditions: list[str] = Field(default_factory=list)
    cost_approval: str = ""
    tradeability_outcome: str = ""

    # Impact and sizing
    entry_impact_bps: float = 0.0
    gross_edge: float = 0.0
    liquidity_relative_size_pct: float = 0.0

    # Entry mode preference
    preferred_entry_mode: EntryMode = EntryMode.IMMEDIATE

    # Drawdown and operator context
    drawdown_level: str = "normal"
    operator_mode: str = "paper"

    # Approval freshness
    approved_at: datetime | None = None
    max_staleness_seconds: int = 300  # 5 minutes

    # Duplicate detection
    existing_order_ids: set[str] = Field(default_factory=set)

    # Config thresholds
    max_spread: float = 0.15
    max_order_depth_fraction: float = 0.12
    max_entry_impact_edge_fraction: float = 0.25
    depth_levels_for_sizing: int = 3


# --- Execution Result ---


class ExecutionResult(BaseModel):
    """Output of the execution engine."""

    outcome: ExecutionOutcome
    order_id: str | None = None

    # Revalidation
    revalidation: RevalidationResult | None = None
    retry_attempted: bool = False
    retry_revalidation: RevalidationResult | None = None

    # Entry mode used
    entry_mode: EntryMode | None = None

    # Order details
    submitted_price: float | None = None
    submitted_size: float | None = None
    forced_resize: bool = False
    forced_resize_reason: str | None = None

    # Impact estimate at execution time
    entry_impact_bps: float | None = None

    # Cancellation/rejection detail
    rejection_reason: str | None = None

    # Approval chain log
    approval_chain: dict[str, Any] = Field(default_factory=dict)

    executed_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))


# --- Slippage Types ---


class SlippageRecord(BaseModel):
    """Realized slippage measurement for a single order.

    Per spec Section 12.5:
    - estimated_slippage_bps: pre-trade estimate
    - realized_slippage_bps: actual fill vs mid-price at submission
    - slippage_ratio: realized / estimated
    """

    order_id: str
    position_id: str

    estimated_slippage_bps: float
    realized_slippage_bps: float
    slippage_ratio: float  # realized / estimated

    order_size_usd: float
    mid_price_at_submission: float
    fill_price: float
    liquidity_relative_size_pct: float | None = None

    recorded_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))


class FrictionModelState(BaseModel):
    """Current state of the friction model parameters.

    Updated when realized/estimated slippage diverges > 1.5x
    across the last 20 trades.
    """

    spread_estimate: float
    depth_assumption: float
    impact_coefficient: float

    last_calibrated_at: datetime | None = None
    trades_since_calibration: int = 0
    mean_slippage_ratio: float | None = None
    needs_recalibration: bool = False
    version: int = 1


# --- Execution Log ---


class ExecutionLogEntry(BaseModel):
    """Complete execution log entry for an order.

    From spec Section 12.6: full approval chain, revalidation outcome,
    forced resize reason, entry impact, realized slippage, links to
    thesis card and workflow run.
    """

    # Identifiers
    workflow_run_id: str
    market_id: str
    order_id: str | None = None
    thesis_card_id: str | None = None
    position_id: str | None = None

    # Approval chain
    risk_approval: str = ""
    cost_approval: str = ""
    tradeability_outcome: str = ""

    # Revalidation
    revalidation_passed: bool = False
    revalidation_detail: str = ""

    # Execution
    entry_mode: str = ""
    forced_resize: bool = False
    forced_resize_reason: str | None = None

    # Impact and slippage
    entry_impact_bps: float | None = None
    estimated_slippage_bps: float | None = None
    realized_slippage_bps: float | None = None

    # Result
    outcome: str = ""

    logged_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))
