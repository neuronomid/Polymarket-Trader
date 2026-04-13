"""Workflow, trigger, and eligibility models.

WorkflowRun, TriggerEvent, EligibilityDecision — pipeline execution tracking.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from data.base import Base, TimestampMixin

if TYPE_CHECKING:
    from data.models import Market, Position
    from data.models.thesis import ThesisCard
    from data.models.cost import CostSnapshot, PreRunCostEstimate, CostGovernorDecision


class WorkflowRun(TimestampMixin, Base):
    """A single execution of an investigation or review workflow.

    Tracks the full lifecycle: trigger → cost approval → investigation →
    risk/tradeability → execution decision.
    """

    __tablename__ = "workflow_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workflow_run_id: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, index=True
    )

    # Context
    run_type: Mapped[str] = mapped_column(
        String(30), nullable=False
    )  # scheduled_sweep, trigger_based, operator_forced, position_review
    market_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("markets.id"), nullable=True, index=True
    )
    position_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("positions.id"), nullable=True, index=True
    )
    trigger_event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("trigger_events.id"), nullable=True
    )

    # Execution state
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending"
    )  # pending, running, completed, failed, cancelled
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Outcome
    outcome: Mapped[str | None] = mapped_column(
        String(30), nullable=True
    )  # no_trade, candidate_accepted, position_reviewed, error
    outcome_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Model usage
    models_used: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    max_tier_used: Mapped[str | None] = mapped_column(String(5), nullable=True)

    # Cost
    estimated_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Operator mode at time of run
    operator_mode: Mapped[str | None] = mapped_column(String(30), nullable=True)

    # Relationships
    market: Mapped[Market | None] = relationship(foreign_keys="WorkflowRun.market_id")
    position: Mapped[Position | None] = relationship(back_populates="workflow_runs")
    trigger_event: Mapped[TriggerEvent | None] = relationship(back_populates="workflow_run")
    thesis_cards: Mapped[list[ThesisCard]] = relationship(back_populates="workflow_run")
    cost_snapshots: Mapped[list[CostSnapshot]] = relationship(back_populates="workflow_run")
    pre_run_cost_estimates: Mapped[list[PreRunCostEstimate]] = relationship(
        back_populates="workflow_run"
    )
    cost_governor_decisions: Mapped[list[CostGovernorDecision]] = relationship(
        back_populates="workflow_run"
    )

    __table_args__ = (
        Index("ix_workflow_runs_type_status", "run_type", "status"),
        Index("ix_workflow_runs_market_status", "market_id", "status"),
    )


class TriggerEvent(TimestampMixin, Base):
    """A detected trigger event from the scanner.

    Captures the trigger class, level, data snapshot, and whether
    it led to a workflow run.
    """

    __tablename__ = "trigger_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    market_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("markets.id"), nullable=False, index=True
    )

    # Classification
    trigger_class: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    trigger_level: Mapped[str] = mapped_column(String(5), nullable=False, index=True)

    # Snapshot at trigger time
    price_at_trigger: Mapped[float | None] = mapped_column(Float, nullable=True)
    spread_at_trigger: Mapped[float | None] = mapped_column(Float, nullable=True)
    depth_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    data_source: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )  # live, cache, secondary

    # Reasoning
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    escalation_status: Mapped[str | None] = mapped_column(String(30), nullable=True)

    triggered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Relationships
    market: Mapped[Market] = relationship(back_populates="trigger_events")
    workflow_run: Mapped[WorkflowRun | None] = relationship(
        back_populates="trigger_event", uselist=False
    )

    __table_args__ = (
        Index("ix_trigger_events_class_level", "trigger_class", "trigger_level"),
        Index("ix_trigger_events_market_time", "market_id", "triggered_at"),
    )


class EligibilityDecision(TimestampMixin, Base):
    """Record of an eligibility gate decision for a market.

    Every eligibility evaluation is logged with outcome, reason code,
    rule version, and depth snapshot.
    """

    __tablename__ = "eligibility_decisions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    market_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("markets.id"), nullable=False, index=True
    )

    # Decision
    outcome: Mapped[str] = mapped_column(String(30), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(100), nullable=False)
    reason_detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Context
    rule_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    depth_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    market_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Relationships
    market: Mapped[Market] = relationship(back_populates="eligibility_decisions")

    __table_args__ = (
        Index("ix_eligibility_market_outcome", "market_id", "outcome"),
    )
