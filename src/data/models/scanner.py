"""Scanner data models.

CLOBCacheEntry, ScannerDataSnapshot, ScannerHealthEvent.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from data.base import Base, TimestampMixin


class CLOBCacheEntry(TimestampMixin, Base):
    """CLOB API cache entry for a market snapshot.

    Stores every successful poll result with timestamp per market.
    Cache depth configurable (default: 4 hours).
    """

    __tablename__ = "clob_cache_entries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    market_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("markets.id"), nullable=False, index=True
    )

    # Snapshot data
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    best_bid: Mapped[float | None] = mapped_column(Float, nullable=True)
    best_ask: Mapped[float | None] = mapped_column(Float, nullable=True)
    spread: Mapped[float | None] = mapped_column(Float, nullable=True)
    mid_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    depth_levels: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    last_trade_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_trade_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    volume_24h: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Source & freshness
    source: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # live, cache, secondary
    is_stale: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    polled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Relationships
    market = relationship("Market", back_populates="clob_cache_entries")

    __table_args__ = (
        Index("ix_clob_cache_market_time", "market_id", "polled_at"),
    )


class ScannerDataSnapshot(TimestampMixin, Base):
    """Full scanner batch snapshot for audit trail.

    Captures the state of all scanned markets in a single batch.
    """

    __tablename__ = "scanner_data_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Batch
    batch_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    markets_scanned: Mapped[int] = mapped_column(Integer, nullable=False)
    triggers_detected: Mapped[int] = mapped_column(Integer, nullable=False)

    # Data source state
    data_source: Mapped[str] = mapped_column(String(20), nullable=False)
    cache_age_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    degraded_mode_level: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Summary
    trigger_summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    scanned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ScannerHealthEvent(TimestampMixin, Base):
    """Scanner infrastructure health event.

    Emitted on API failures, degraded mode transitions, and recovery.
    """

    __tablename__ = "scanner_health_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    event_type: Mapped[str] = mapped_column(
        String(30), nullable=False
    )  # api_failure, degraded_enter, degraded_exit, recovery
    severity: Mapped[str] = mapped_column(String(20), nullable=False)

    # Details
    api_available: Mapped[bool] = mapped_column(Boolean, nullable=False)
    cache_state: Mapped[str | None] = mapped_column(String(20), nullable=True)
    degraded_mode_level: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_successful_poll: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_scanner_health_type_time", "event_type", "event_at"),
    )
