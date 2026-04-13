"""Notification models.

NotificationEvent, NotificationDeliveryRecord.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from data.base import Base, TimestampMixin


class NotificationEvent(TimestampMixin, Base):
    """Internal notification event emitted by workflows.

    Workflows emit typed events; the notification service subscribes
    and delivers via configured channels.
    """

    __tablename__ = "notification_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Event identification
    event_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)

    # Context
    market_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    position_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    workflow_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # Payload
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Deduplication
    dedup_key: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)

    emitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Relationships
    delivery_records: Mapped[list[NotificationDeliveryRecord]] = relationship(
        back_populates="notification_event"
    )

    __table_args__ = (
        Index("ix_notification_type_severity", "event_type", "severity"),
    )


class NotificationDeliveryRecord(TimestampMixin, Base):
    """Delivery attempt record for a notification event.

    Tracks per-channel delivery: Telegram, email, etc.
    """

    __tablename__ = "notification_delivery_records"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    notification_event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("notification_events.id"),
        nullable=False,
        index=True,
    )

    # Delivery
    channel: Mapped[str] = mapped_column(String(30), nullable=False)  # telegram, email
    status: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # pending, sent, failed, retrying
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Channel-specific
    channel_message_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    first_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    notification_event: Mapped[NotificationEvent] = relationship(
        back_populates="delivery_records"
    )
