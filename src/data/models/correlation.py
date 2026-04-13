"""Correlation and event cluster models.

EventCluster, CorrelationGroup — correlation engine data structures.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from data.base import Base, TimestampMixin

if TYPE_CHECKING:
    from data.models import Market


class EventCluster(TimestampMixin, Base):
    """Group of markets that share an underlying event.

    Used by the Correlation Engine to prevent over-concentration:
    two markets on the same election are one event cluster.
    """

    __tablename__ = "event_clusters"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    cluster_name: Mapped[str] = mapped_column(String(255), nullable=False)
    cluster_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # event, narrative, source_dependency, domain, catalyst
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Exposure limits
    max_exposure_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_exposure_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)

    # Relationships
    markets: Mapped[list[Market]] = relationship(back_populates="event_cluster")

    __table_args__ = (
        Index("ix_event_cluster_type", "cluster_type"),
    )


class CorrelationGroup(TimestampMixin, Base):
    """A group of positions sharing hidden dependencies.

    Five correlation dimensions: event, narrative, source dependency,
    domain overlap, catalyst overlap.
    """

    __tablename__ = "correlation_groups"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    group_name: Mapped[str] = mapped_column(String(255), nullable=False)
    correlation_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # event, narrative, source, domain, catalyst
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Exposure tracking
    max_cluster_exposure_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_cluster_exposure_usd: Mapped[float] = mapped_column(
        Float, default=0.0, nullable=False
    )
    position_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Member position IDs
    position_ids: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)

    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)

    __table_args__ = (
        Index("ix_correlation_group_type", "correlation_type"),
    )
