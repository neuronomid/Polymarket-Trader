"""Cost governor models.

CostSnapshot, PreRunCostEstimate, CostGovernorDecision, CostOfSelectivityRecord,
CumulativeReviewCostRecord — cost tracking and budget enforcement.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from data.base import Base, TimestampMixin


class CostSnapshot(TimestampMixin, Base):
    """Post-run cost accounting for a workflow execution.

    Tracks per-call costs aggregated by model, provider, and cost class.
    """

    __tablename__ = "cost_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workflow_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_runs.id"), nullable=False, index=True
    )

    # Per-call breakdown
    model: Mapped[str] = mapped_column(String(50), nullable=False)
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    cost_class: Mapped[str] = mapped_column(String(5), nullable=False)
    tier: Mapped[str] = mapped_column(String(5), nullable=False)

    # Token counts
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)

    # Cost
    estimated_cost_usd: Mapped[float] = mapped_column(Float, nullable=False)
    actual_cost_usd: Mapped[float] = mapped_column(Float, nullable=False)

    # Context
    agent_role: Mapped[str | None] = mapped_column(String(100), nullable=True)
    market_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    position_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )

    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Relationships
    workflow_run = relationship("WorkflowRun", back_populates="cost_snapshots")

    __table_args__ = (
        Index("ix_cost_snapshots_model_provider", "model", "provider"),
        Index("ix_cost_snapshots_recorded_at", "recorded_at"),
    )


class PreRunCostEstimate(TimestampMixin, Base):
    """Pre-run cost estimate computed before a workflow starts.

    Contains min/max estimated costs, run type classification,
    and per-agent token budgets.
    """

    __tablename__ = "pre_run_cost_estimates"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workflow_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_runs.id"), nullable=False, index=True
    )

    # Run classification
    run_type: Mapped[str] = mapped_column(String(30), nullable=False)

    # Cost estimates
    expected_cost_min_usd: Mapped[float] = mapped_column(Float, nullable=False)
    expected_cost_max_usd: Mapped[float] = mapped_column(Float, nullable=False)

    # Budget context
    daily_budget_remaining_usd: Mapped[float] = mapped_column(Float, nullable=False)
    lifetime_budget_remaining_usd: Mapped[float] = mapped_column(Float, nullable=False)
    daily_budget_pct_remaining: Mapped[float] = mapped_column(Float, nullable=False)

    # Per-agent breakdown
    agent_budgets: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    estimated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Relationships
    workflow_run = relationship("WorkflowRun", back_populates="pre_run_cost_estimates")


class CostGovernorDecision(TimestampMixin, Base):
    """Cost Governor approval or rejection decision for a workflow.

    Records the decision logic: whether budget allows full tier,
    reduced tier, or deferral.
    """

    __tablename__ = "cost_governor_decisions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workflow_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_runs.id"), nullable=False, index=True
    )

    # Decision
    decision: Mapped[str] = mapped_column(
        String(30), nullable=False
    )  # approve_full, approve_reduced, defer, reject
    reason: Mapped[str] = mapped_column(Text, nullable=False)

    # Tier ceiling
    approved_max_tier: Mapped[str | None] = mapped_column(String(5), nullable=True)
    approved_max_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Cost-of-selectivity context
    cost_selectivity_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    opus_escalation_threshold: Mapped[float | None] = mapped_column(Float, nullable=True)

    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Relationships
    workflow_run = relationship("WorkflowRun", back_populates="cost_governor_decisions")


class CostOfSelectivityRecord(TimestampMixin, Base):
    """Daily cost-of-selectivity tracking.

    Total daily inference spend ÷ trades entered (7-day rolling).
    """

    __tablename__ = "cost_of_selectivity_records"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Date and period
    record_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, unique=True, index=True
    )

    # Metrics
    daily_inference_spend_usd: Mapped[float] = mapped_column(Float, nullable=False)
    trades_entered: Mapped[int] = mapped_column(Integer, nullable=False)
    rolling_7d_cost_per_trade: Mapped[float | None] = mapped_column(Float, nullable=True)
    cost_to_edge_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    rolling_7d_selectivity_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Warning flag
    warning_triggered: Mapped[bool | None] = mapped_column(nullable=True)


class CumulativeReviewCostRecord(TimestampMixin, Base):
    """Cumulative review cost tracking per position.

    Tracks total LLM cost attributed to reviewing a position across all reviews.
    """

    __tablename__ = "cumulative_review_cost_records"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    position_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("positions.id"), nullable=False, index=True
    )

    # Costs
    total_review_cost_usd: Mapped[float] = mapped_column(Float, nullable=False)
    position_value_usd: Mapped[float] = mapped_column(Float, nullable=False)
    cost_pct_of_value: Mapped[float] = mapped_column(Float, nullable=False)

    # Review counts
    total_reviews: Mapped[int] = mapped_column(Integer, nullable=False)
    deterministic_reviews: Mapped[int] = mapped_column(Integer, nullable=False)
    llm_reviews: Mapped[int] = mapped_column(Integer, nullable=False)

    # Cap status
    warning_threshold_hit: Mapped[bool] = mapped_column(default=False, nullable=False)
    cap_threshold_hit: Mapped[bool] = mapped_column(default=False, nullable=False)

    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
