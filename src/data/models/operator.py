"""Operator interaction and absence models.

OperatorInteractionEvent, OperatorAbsenceEvent — absence tracking
with full escalation ladder.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from data.base import Base, TimestampMixin


class OperatorInteractionEvent(TimestampMixin, Base):
    """Record of an operator interaction with the system.

    Used to determine absence status: login, dashboard view,
    manual trigger, config change, alert acknowledgment.
    """

    __tablename__ = "operator_interaction_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    interaction_type: Mapped[str] = mapped_column(
        String(30), nullable=False
    )  # login, dashboard_view, manual_trigger, config_change, alert_acknowledgment
    details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    interacted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_operator_interaction_time", "interacted_at"),
    )


class OperatorAbsenceEvent(TimestampMixin, Base):
    """Operator absence escalation event.

    Tracks the absence level, autonomous actions taken, and
    return workflow status.
    """

    __tablename__ = "operator_absence_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Absence state
    absence_level: Mapped[int] = mapped_column(
        Integer, nullable=False
    )  # 0=normal, 1, 2, 3, 4=winddown
    absence_level_name: Mapped[str] = mapped_column(String(30), nullable=False)
    hours_since_last_interaction: Mapped[float] = mapped_column(Float, nullable=False)

    # Actions taken
    actions_taken: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    positions_affected: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    size_reduction_pct: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Alert delivery
    alert_channels: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    alert_delivered: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Return workflow
    operator_returned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    return_acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    event_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_absence_level_time", "absence_level", "event_at"),
    )
