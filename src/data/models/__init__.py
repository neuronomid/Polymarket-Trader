"""Market and position core models.

Market, Position, Order, Trade — the foundational trading entities.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from data.base import Base, TimestampMixin

if TYPE_CHECKING:
    from data.models.thesis import ThesisCard
    from data.models.workflow import EligibilityDecision, TriggerEvent, WorkflowRun
    from data.models.risk import RiskSnapshot
    from data.models.execution import RealizedSlippageRecord
    from data.models.scanner import CLOBCacheEntry
    from data.models.calibration import ShadowForecastRecord
    from data.models.correlation import EventCluster


class Market(TimestampMixin, Base):
    """A Polymarket prediction market contract.

    Represents a single market fetched from the CLOB API, with metadata,
    eligibility state, and category classification.
    """

    __tablename__ = "markets"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    market_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    condition_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Category & eligibility
    category: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    category_quality_tier: Mapped[str | None] = mapped_column(String(30), nullable=True)
    eligibility_outcome: Mapped[str | None] = mapped_column(String(30), nullable=True, index=True)
    eligibility_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Market metadata
    resolution_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolution_deadline: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    market_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Last snapshot data
    last_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_spread: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_volume: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_snapshot_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Tags/slugs from polymarket
    tags: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    slug: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Cluster assignment
    event_cluster_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("event_clusters.id"), nullable=True
    )

    # Relationships
    positions: Mapped[list[Position]] = relationship(back_populates="market")
    thesis_cards: Mapped[list[ThesisCard]] = relationship(back_populates="market")
    eligibility_decisions: Mapped[list[EligibilityDecision]] = relationship(
        back_populates="market"
    )
    trigger_events: Mapped[list[TriggerEvent]] = relationship(back_populates="market")
    clob_cache_entries: Mapped[list[CLOBCacheEntry]] = relationship(back_populates="market")
    shadow_forecasts: Mapped[list[ShadowForecastRecord]] = relationship(
        back_populates="market"
    )
    event_cluster: Mapped[EventCluster | None] = relationship(back_populates="markets")

    __table_args__ = (
        Index("ix_markets_category_eligibility", "category", "eligibility_outcome"),
        Index("ix_markets_status_active", "market_status", "is_active"),
    )


class Position(TimestampMixin, Base):
    """An open or closed position in a market.

    Tracks entry, current state, review tier, exit classification, and
    all associated cost/risk data.
    """

    __tablename__ = "positions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    market_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("markets.id"), nullable=False, index=True
    )
    thesis_card_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("thesis_cards.id"), nullable=True
    )

    # Position state
    side: Mapped[str] = mapped_column(String(10), nullable=False)  # "yes" or "no"
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    current_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    size: Mapped[float] = mapped_column(Float, nullable=False)
    remaining_size: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="open", index=True
    )  # open, closed, reducing

    # Entry details
    entered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    entry_mode: Mapped[str | None] = mapped_column(String(30), nullable=True)

    # Review state
    review_tier: Mapped[str] = mapped_column(String(20), nullable=False, default="new")
    last_reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_review_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Exit details
    exit_class: Mapped[str | None] = mapped_column(String(30), nullable=True)
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    exited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # PnL tracking
    realized_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    unrealized_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Cost tracking
    cumulative_review_cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    total_inference_cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    # Confidence fields (Section 23 — three separate)
    probability_estimate: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence_estimate: Mapped[float | None] = mapped_column(Float, nullable=True)
    calibration_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Risk metadata
    risk_approval: Mapped[str | None] = mapped_column(String(30), nullable=True)
    correlation_group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("correlation_groups.id"), nullable=True
    )

    # Relationships
    market: Mapped[Market] = relationship(back_populates="positions")
    thesis_card: Mapped[ThesisCard | None] = relationship(back_populates="position")
    orders: Mapped[list[Order]] = relationship(back_populates="position")
    trades: Mapped[list[Trade]] = relationship(back_populates="position")
    risk_snapshots: Mapped[list[RiskSnapshot]] = relationship(back_populates="position")
    workflow_runs: Mapped[list[WorkflowRun]] = relationship(back_populates="position")

    __table_args__ = (
        Index("ix_positions_status_review", "status", "review_tier"),
        Index("ix_positions_market_status", "market_id", "status"),
    )


class Order(TimestampMixin, Base):
    """An order placed or simulated for a position."""

    __tablename__ = "orders"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    position_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("positions.id"), nullable=False, index=True
    )
    workflow_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_runs.id"), nullable=True
    )

    # Order details
    order_type: Mapped[str] = mapped_column(String(20), nullable=False)  # limit, market
    side: Mapped[str] = mapped_column(String(10), nullable=False)  # buy, sell
    price: Mapped[float] = mapped_column(Float, nullable=False)
    size: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending"
    )  # pending, filled, partial, cancelled, rejected

    # Execution metadata
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    filled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fill_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    filled_size: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Pre-execution validation
    revalidation_passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    revalidation_details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Impact & slippage
    estimated_impact_bps: Mapped[float | None] = mapped_column(Float, nullable=True)
    estimated_slippage_bps: Mapped[float | None] = mapped_column(Float, nullable=True)
    realized_slippage_bps: Mapped[float | None] = mapped_column(Float, nullable=True)
    slippage_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    liquidity_relative_size_pct: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Approval chain
    approval_chain: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Relationships
    position: Mapped[Position] = relationship(back_populates="orders")
    trades: Mapped[list[Trade]] = relationship(back_populates="order")

    __table_args__ = (
        Index("ix_orders_position_status", "position_id", "status"),
    )


class Trade(TimestampMixin, Base):
    """A filled trade resulting from an order."""

    __tablename__ = "trades"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id"), nullable=False, index=True
    )
    position_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("positions.id"), nullable=False, index=True
    )

    # Trade details
    price: Mapped[float] = mapped_column(Float, nullable=False)
    size: Mapped[float] = mapped_column(Float, nullable=False)
    side: Mapped[str] = mapped_column(String(10), nullable=False)
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Fees
    fee_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    # Relationships
    order: Mapped[Order] = relationship(back_populates="trades")
    position: Mapped[Position] = relationship(back_populates="trades")
