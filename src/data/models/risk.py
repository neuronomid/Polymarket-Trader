"""Risk governor models.

RiskSnapshot, RuleDecision — risk state and approval tracking.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from data.base import Base, TimestampMixin

if TYPE_CHECKING:
    from data.models import Position


class RiskSnapshot(TimestampMixin, Base):
    """Point-in-time risk state when a risk decision is made.

    Captures drawdown level, exposure, correlation burden, and all
    inputs to the Risk Governor decision.
    """

    __tablename__ = "risk_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    position_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("positions.id"), nullable=True, index=True
    )
    workflow_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_runs.id"), nullable=True, index=True
    )

    # Drawdown state
    drawdown_level: Mapped[str] = mapped_column(String(30), nullable=False)
    current_drawdown_pct: Mapped[float] = mapped_column(Float, nullable=False)
    start_of_day_equity: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Exposure
    total_open_exposure_usd: Mapped[float] = mapped_column(Float, nullable=False)
    daily_deployment_used_pct: Mapped[float] = mapped_column(Float, nullable=False)
    simultaneous_positions: Mapped[int] = mapped_column(nullable=False)

    # Category exposure
    category_exposure: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    cluster_exposure: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Correlation burden
    correlation_burden_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    snapshot_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Relationships
    position: Mapped[Position | None] = relationship(back_populates="risk_snapshots")
    rule_decisions: Mapped[list[RuleDecision]] = relationship(back_populates="risk_snapshot")


class RuleDecision(TimestampMixin, Base):
    """Individual deterministic rule evaluation within a risk assessment.

    Each rule check (e.g., drawdown limit, exposure cap, correlation limit)
    is logged separately for auditability.
    """

    __tablename__ = "rule_decisions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    risk_snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("risk_snapshots.id"), nullable=False, index=True
    )

    # Rule details
    rule_name: Mapped[str] = mapped_column(String(100), nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)

    # Threshold context
    threshold_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual_value: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Final risk approval (set on the deciding rule or summary)
    risk_approval: Mapped[str | None] = mapped_column(String(30), nullable=True)

    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)

    # Relationships
    risk_snapshot: Mapped[RiskSnapshot] = relationship(back_populates="rule_decisions")
