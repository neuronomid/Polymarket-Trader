"""Market quality and reference data models.

BaseRateReference, MarketImpliedProbabilitySnapshot, MarketQualitySnapshot,
ShadowVsMarketComparisonRecord, PolicyUpdateRecommendation, SystemHealthSnapshot.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from data.base import Base, TimestampMixin


class BaseRateReference(TimestampMixin, Base):
    """Historical resolution rates per market type.

    Default 50% when no data. Attached to every thesis card.
    """

    __tablename__ = "base_rate_references"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    market_type: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, index=True
    )
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    base_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)

    # Source & confidence
    sample_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    confidence_level: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )  # none, low, medium, high
    source: Mapped[str | None] = mapped_column(String(100), nullable=True)

    last_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MarketImpliedProbabilitySnapshot(TimestampMixin, Base):
    """Snapshot of market-implied probability at a point in time."""

    __tablename__ = "market_implied_probability_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    market_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    implied_probability: Mapped[float] = mapped_column(Float, nullable=False)
    mid_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    spread: Mapped[float | None] = mapped_column(Float, nullable=True)

    snapshot_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_mip_market_time", "market_id", "snapshot_at"),
    )


class MarketQualitySnapshot(TimestampMixin, Base):
    """Periodic market quality assessment for monitoring."""

    __tablename__ = "market_quality_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    market_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    liquidity_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    spread_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    depth_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    resolution_clarity_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    assessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ShadowVsMarketComparisonRecord(TimestampMixin, Base):
    """Weekly shadow-vs-market Brier score comparison.

    System Brier vs Market Brier, aggregated at strategy, category,
    horizon, and time period levels.
    """

    __tablename__ = "shadow_vs_market_comparison_records"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Period and scope
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    scope: Mapped[str] = mapped_column(
        String(30), nullable=False
    )  # overall, category, horizon, period
    scope_label: Mapped[str] = mapped_column(String(100), nullable=False)

    # Brier scores
    system_brier: Mapped[float] = mapped_column(Float, nullable=False)
    market_brier: Mapped[float] = mapped_column(Float, nullable=False)
    base_rate_brier: Mapped[float | None] = mapped_column(Float, nullable=True)
    system_advantage: Mapped[float] = mapped_column(Float, nullable=False)

    resolved_count: Mapped[int] = mapped_column(Integer, nullable=False)

    compared_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_shadow_comparison_scope", "scope", "scope_label"),
    )


class PolicyUpdateRecommendation(TimestampMixin, Base):
    """Policy change recommendation from the learning system.

    No automatic policy change unless minimum sample threshold met,
    pattern persistence exists, and change is documented.
    """

    __tablename__ = "policy_update_recommendations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Recommendation
    area: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Evidence thresholds
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False)
    min_threshold_met: Mapped[bool] = mapped_column(Boolean, nullable=False)
    pattern_persistence_weeks: Mapped[int] = mapped_column(Integer, nullable=False)

    # Status
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending"
    )  # pending, approved, rejected, deferred
    operator_reviewed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    recommended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SystemHealthSnapshot(TimestampMixin, Base):
    """Periodic system health check snapshot.

    Covers: API availability, cache state, degraded mode, scanner health,
    database connectivity, notification delivery status.
    """

    __tablename__ = "system_health_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # API health
    clob_api_available: Mapped[bool] = mapped_column(Boolean, nullable=False)
    clob_api_latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Cache
    cache_entries_count: Mapped[int] = mapped_column(Integer, nullable=False)
    cache_stale_count: Mapped[int] = mapped_column(Integer, nullable=False)

    # Scanner
    scanner_degraded_level: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    scanner_last_success: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Database
    db_connection_pool_active: Mapped[int | None] = mapped_column(Integer, nullable=True)
    db_connection_pool_idle: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Notifications
    notification_delivery_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    failed_notifications_24h: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Overall
    overall_status: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # healthy, degraded, unhealthy
    details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    snapshot_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_system_health_time", "snapshot_at"),
    )
