"""Cost Governor runtime types.

Pydantic models for cost estimation, budget state, approval decisions,
selectivity tracking, and review cost monitoring. These are in-process
types — not ORM models.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from core.enums import CostClass, ModelTier


# --- Enums ---


class RunType(str, Enum):
    """Classification of a workflow run for cost estimation."""

    SCHEDULED_SWEEP = "scheduled_sweep"
    TRIGGER_BASED = "trigger_based"
    OPERATOR_FORCED = "operator_forced"
    POSITION_REVIEW = "position_review"


class CostDecision(str, Enum):
    """Cost Governor approval decisions."""

    APPROVE_FULL = "approve_full"
    APPROVE_REDUCED = "approve_reduced"
    DEFER = "defer"
    REJECT = "reject"


# --- Input types ---


class AgentCostSpec(BaseModel):
    """Expected cost specification for a single agent in a workflow."""

    agent_role: str
    tier: ModelTier
    cost_class: CostClass
    estimated_input_tokens: int = 0
    estimated_output_tokens: int = 0
    estimated_cost_min_usd: float = 0.0
    estimated_cost_max_usd: float = 0.0


class CostEstimateRequest(BaseModel):
    """Input to the pre-run cost estimator."""

    workflow_run_id: str
    run_type: RunType
    market_id: str | None = None
    position_id: str | None = None

    # Agent breakdown
    agent_specs: list[AgentCostSpec] = Field(default_factory=list)

    # Optional overrides
    candidate_count: int = 1
    expected_net_edge: float | None = None  # for cost-efficiency check


class CostRecordInput(BaseModel):
    """Input for recording actual cost of a single LLM call."""

    workflow_run_id: str
    agent_role: str
    model: str
    provider: str
    tier: ModelTier
    cost_class: CostClass
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float
    actual_cost_usd: float
    market_id: str | None = None
    position_id: str | None = None


# --- State types ---


class BudgetState(BaseModel):
    """Current budget state across all dimensions."""

    # Daily
    daily_spent_usd: float = 0.0
    daily_budget_usd: float = 0.0
    daily_remaining_usd: float = 0.0
    daily_pct_remaining: float = 1.0

    # Daily Opus escalation sub-budget
    daily_opus_spent_usd: float = 0.0
    daily_opus_budget_usd: float = 0.0
    daily_opus_remaining_usd: float = 0.0

    # Lifetime
    lifetime_spent_usd: float = 0.0
    lifetime_budget_usd: float = 0.0
    lifetime_remaining_usd: float = 0.0
    lifetime_pct_consumed: float = 0.0

    @property
    def daily_budget_critically_low(self) -> bool:
        """True when daily budget below 10%."""
        return self.daily_pct_remaining < 0.10

    @property
    def lifetime_heavily_consumed(self) -> bool:
        """True when lifetime budget above 75% consumed."""
        return self.lifetime_pct_consumed > 0.75


class LifetimeBudgetAlert(str, Enum):
    """Lifetime budget consumption alert levels."""

    NONE = "none"
    PCT_50 = "50pct"
    PCT_75 = "75pct"
    PCT_100 = "100pct"


# --- Output types ---


class CostEstimate(BaseModel):
    """Result of pre-run cost estimation."""

    workflow_run_id: str
    run_type: RunType
    expected_cost_min_usd: float
    expected_cost_max_usd: float
    agent_budgets: dict[str, dict[str, Any]] = Field(default_factory=dict)
    budget_state: BudgetState
    estimated_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))


class CostApproval(BaseModel):
    """Cost Governor decision for a workflow run."""

    decision: CostDecision
    reason: str
    approved_max_tier: ModelTier | None = None
    approved_max_cost_usd: float | None = None
    cost_selectivity_ratio: float | None = None
    opus_escalation_threshold: float | None = None
    decided_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))

    @property
    def is_approved(self) -> bool:
        return self.decision in (CostDecision.APPROVE_FULL, CostDecision.APPROVE_REDUCED)


class SelectivitySnapshot(BaseModel):
    """Point-in-time cost-of-selectivity metrics."""

    record_date: datetime
    daily_inference_spend_usd: float
    trades_entered: int
    rolling_7d_cost_per_trade: float | None = None
    cost_to_edge_ratio: float | None = None
    rolling_7d_selectivity_ratio: float | None = None
    warning_triggered: bool = False


class ReviewCostStatus(BaseModel):
    """Cumulative review cost status for a position."""

    position_id: str
    total_review_cost_usd: float
    position_value_usd: float
    cost_pct_of_value: float
    total_reviews: int
    deterministic_reviews: int
    llm_reviews: int
    warning_threshold_hit: bool = False
    cap_threshold_hit: bool = False

    @property
    def allows_opus_escalation(self) -> bool:
        """Opus escalation blocked when cap threshold is hit."""
        return not self.cap_threshold_hit


class EstimateAccuracy(BaseModel):
    """Comparison of estimated vs actual cost for a single run."""

    workflow_run_id: str
    run_type: RunType
    estimated_min_usd: float
    estimated_max_usd: float
    actual_usd: float
    accuracy_ratio: float  # actual / midpoint_estimate
    within_bounds: bool  # actual between min and max
