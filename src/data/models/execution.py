"""Execution, slippage, and friction models.

EntryImpactEstimate, RealizedSlippageRecord, FrictionModelParameters.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from data.base import Base, TimestampMixin


class EntryImpactEstimate(TimestampMixin, Base):
    """Pre-execution entry impact estimate from order book analysis.

    Tier D deterministic: walks visible order book to estimate mid-price movement.
    """

    __tablename__ = "entry_impact_estimates"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    thesis_card_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("thesis_cards.id"), nullable=True, index=True
    )
    order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id"), nullable=True, index=True
    )

    # Impact estimate
    estimated_impact_bps: Mapped[float] = mapped_column(Float, nullable=False)
    order_size: Mapped[float] = mapped_column(Float, nullable=False)
    levels_consumed: Mapped[int] = mapped_column(Integer, nullable=False)

    # Order book context
    depth_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    mid_price_before: Mapped[float] = mapped_column(Float, nullable=False)
    estimated_mid_price_after: Mapped[float] = mapped_column(Float, nullable=False)

    estimated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RealizedSlippageRecord(TimestampMixin, Base):
    """Realized slippage measurement per executed order.

    Compares estimated vs. actual slippage for friction model calibration.
    """

    __tablename__ = "realized_slippage_records"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id"), nullable=False, index=True
    )
    position_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("positions.id"), nullable=False, index=True
    )

    # Slippage
    estimated_slippage_bps: Mapped[float] = mapped_column(Float, nullable=False)
    realized_slippage_bps: Mapped[float] = mapped_column(Float, nullable=False)
    slippage_ratio: Mapped[float] = mapped_column(Float, nullable=False)

    # Context
    order_size: Mapped[float] = mapped_column(Float, nullable=False)
    liquidity_relative_size_pct: Mapped[float | None] = mapped_column(Float, nullable=True)

    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_slippage_recorded_at", "recorded_at"),
    )


class FrictionModelParameters(TimestampMixin, Base):
    """Current friction model parameters.

    Updated when realized/estimated slippage diverges > 50% over 20 trades.
    """

    __tablename__ = "friction_model_parameters"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Parameters
    spread_estimate: Mapped[float] = mapped_column(Float, nullable=False)
    depth_assumption: Mapped[float] = mapped_column(Float, nullable=False)
    impact_coefficient: Mapped[float] = mapped_column(Float, nullable=False)

    # Calibration state
    last_calibrated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    trades_since_calibration: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    mean_slippage_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    recalibration_triggered: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )

    # Version tracking
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
