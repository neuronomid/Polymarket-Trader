"""Bias detection models.

BiasAuditReport, BiasPatternRecord — statistical bias detection tracking.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from data.base import Base, TimestampMixin


class BiasAuditReport(TimestampMixin, Base):
    """Weekly bias audit report from the five statistical checks.

    All detection is statistical (Tier D). The Tier C summary is for
    human-readable description only — LLM does NOT detect biases.
    """

    __tablename__ = "bias_audit_reports"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Period
    report_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Five statistical checks
    directional_bias_detected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    directional_bias_skew_pp: Mapped[float | None] = mapped_column(Float, nullable=True)

    confidence_clustering_detected: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    clustering_band_pct: Mapped[float | None] = mapped_column(Float, nullable=True)

    anchoring_detected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    anchoring_diff_pp: Mapped[float | None] = mapped_column(Float, nullable=True)

    narrative_overweighting_detected: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    narrative_correlation: Mapped[float | None] = mapped_column(Float, nullable=True)

    base_rate_neglect_detected: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    base_rate_deviation_direction: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Summary
    any_bias_detected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    summary_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        Index("ix_bias_audit_date", "report_date"),
    )


class BiasPatternRecord(TimestampMixin, Base):
    """Persistent bias pattern tracking.

    Tracks how many consecutive weeks a pattern has been observed.
    Alerts: DETECTED (new), PERSISTENT (3+ weeks), RESOLVED.
    """

    __tablename__ = "bias_pattern_records"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    pattern_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # directional, clustering, anchoring, narrative, base_rate_neglect
    first_detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consecutive_weeks: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    is_persistent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_resolved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Alert status
    alert_status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="detected"
    )  # detected, persistent, resolved

    details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        Index("ix_bias_pattern_type_status", "pattern_type", "alert_status"),
    )
