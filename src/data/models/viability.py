"""Strategy viability and budget models.

StrategyViabilityCheckpoint, LifetimeBudgetStatus, PatienceBudgetStatus.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from data.base import Base, TimestampMixin


class StrategyViabilityCheckpoint(TimestampMixin, Base):
    """Strategy viability checkpoint at weeks 4, 8, 12 and budget thresholds.

    Determination is by deterministic threshold comparison (Tier D).
    """

    __tablename__ = "strategy_viability_checkpoints"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Checkpoint identity
    checkpoint_type: Mapped[str] = mapped_column(
        String(30), nullable=False
    )  # week_4, week_8, week_12, budget_50, budget_75, budget_100
    checkpoint_week: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Viability metrics
    resolved_forecasts: Mapped[int] = mapped_column(Integer, nullable=False)
    system_brier: Mapped[float | None] = mapped_column(Float, nullable=True)
    market_brier: Mapped[float | None] = mapped_column(Float, nullable=True)
    system_advantage: Mapped[float | None] = mapped_column(Float, nullable=True)
    hypothetical_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    cost_of_selectivity: Mapped[float | None] = mapped_column(Float, nullable=True)
    accumulation_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    budget_consumed_pct: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Determination
    viability_status: Mapped[str] = mapped_column(
        String(30), nullable=False
    )  # insufficient_data, viable, concern, warning
    viability_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Operator acknowledgment
    operator_acknowledged: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    checkpoint_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_viability_checkpoint_type", "checkpoint_type"),
    )


class LifetimeBudgetStatus(TimestampMixin, Base):
    """Lifetime experiment budget consumption tracking.

    Alerts at 50%, 75%, 100% consumption. Level D never blocked.
    """

    __tablename__ = "lifetime_budget_status"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    total_budget_usd: Mapped[float] = mapped_column(Float, nullable=False)
    consumed_usd: Mapped[float] = mapped_column(Float, nullable=False)
    remaining_usd: Mapped[float] = mapped_column(Float, nullable=False)
    consumed_pct: Mapped[float] = mapped_column(Float, nullable=False)

    # Alert thresholds
    alert_50_triggered: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    alert_75_triggered: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    alert_100_triggered: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PatienceBudgetStatus(TimestampMixin, Base):
    """Patience budget tracking (default 9 months).

    At expiry, operator must explicitly decide continue/adjust/terminate.
    Operator silence does NOT extend the budget.
    """

    __tablename__ = "patience_budget_status"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    start_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expiry_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    budget_months: Mapped[int] = mapped_column(Integer, default=9, nullable=False)

    # Status
    elapsed_days: Mapped[int] = mapped_column(Integer, nullable=False)
    remaining_days: Mapped[int] = mapped_column(Integer, nullable=False)
    is_expired: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Operator decision at expiry
    operator_decision: Mapped[str | None] = mapped_column(
        String(30), nullable=True
    )  # continue, adjust, terminate
    decision_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
