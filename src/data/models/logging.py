"""Logging, journal, and alert models.

JournalEntry, StructuredLogEntry, Alert.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from data.base import Base, TimestampMixin


class JournalEntry(TimestampMixin, Base):
    """Narrative journal entry grounded in structured logs.

    Written by Journal Writer (Tier C). Links to underlying structured
    log entries for drill-down. Full trade reconstruction possible from
    trigger to exit through journals + structured logs.
    """

    __tablename__ = "journal_entries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Context
    workflow_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_runs.id"), nullable=True, index=True
    )
    market_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    position_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # Content
    journal_type: Mapped[str] = mapped_column(
        String(30), nullable=False
    )  # investigation, review, exit, performance
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    narrative: Mapped[str] = mapped_column(Text, nullable=False)

    # Linked log entry IDs
    linked_log_ids: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)

    written_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_journal_type_time", "journal_type", "written_at"),
    )


class StructuredLogEntry(TimestampMixin, Base):
    """Persistent structured log entry for audit and analysis.

    Mirrors the JSON-structured log output but stored in the database
    for querying, dashboard display, and long-term retention.
    """

    __tablename__ = "structured_log_entries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Attribution
    workflow_run_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    market_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    position_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Event
    event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    component: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Payload
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)

    logged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_log_event_severity", "event_type", "severity"),
        Index("ix_log_time", "logged_at"),
    )


class Alert(TimestampMixin, Base):
    """System alert requiring attention or acknowledgment.

    Raised by various subsystems: risk, cost, viability, bias, scanner, etc.
    """

    __tablename__ = "alerts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    alert_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    source_component: Mapped[str] = mapped_column(String(100), nullable=False)

    title: Mapped[str] = mapped_column(String(500), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Context
    market_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    position_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # Status
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    raised_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_alerts_type_severity", "alert_type", "severity"),
        Index("ix_alerts_acknowledged", "acknowledged"),
    )
