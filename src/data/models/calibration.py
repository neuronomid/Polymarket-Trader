"""Calibration, shadow forecast, and performance ledger models.

CalibrationRecord, CalibrationSegment, ShadowForecastRecord,
CategoryPerformanceLedgerEntry, CalibrationAccumulationProjection,
CalibrationThresholdRegistry.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from data.base import Base, TimestampMixin


class CalibrationRecord(TimestampMixin, Base):
    """Overall calibration state for a segment or the system.

    Updated after each resolution, tracks Brier scores and sample counts.
    """

    __tablename__ = "calibration_records"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Segment identification
    segment_type: Mapped[str] = mapped_column(
        String(30), nullable=False
    )  # overall, category, horizon, market_type
    segment_label: Mapped[str] = mapped_column(String(100), nullable=False)

    # Regime
    regime: Mapped[str] = mapped_column(
        String(30), nullable=False
    )  # insufficient, sufficient, viability_uncertain

    # Brier scores
    system_brier: Mapped[float | None] = mapped_column(Float, nullable=True)
    market_brier: Mapped[float | None] = mapped_column(Float, nullable=True)
    base_rate_brier: Mapped[float | None] = mapped_column(Float, nullable=True)
    system_advantage: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Counts
    resolved_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_forecasts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Thresholds
    min_threshold: Mapped[int] = mapped_column(Integer, nullable=False)
    threshold_met: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    updated_at_cal: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Relationships
    segments: Mapped[list[CalibrationSegment]] = relationship(
        back_populates="calibration_record"
    )

    __table_args__ = (
        Index("ix_calibration_segment", "segment_type", "segment_label"),
    )


class CalibrationSegment(TimestampMixin, Base):
    """Detailed calibration segment within a CalibrationRecord.

    Stores per-bucket calibration data for fine-grained analysis.
    """

    __tablename__ = "calibration_segments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    calibration_record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("calibration_records.id"), nullable=False, index=True
    )

    # Bucket
    bucket_label: Mapped[str] = mapped_column(String(50), nullable=False)
    bucket_lower: Mapped[float] = mapped_column(Float, nullable=False)
    bucket_upper: Mapped[float] = mapped_column(Float, nullable=False)

    # Stats
    count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    mean_predicted: Mapped[float | None] = mapped_column(Float, nullable=True)
    mean_actual: Mapped[float | None] = mapped_column(Float, nullable=True)
    calibration_error: Mapped[float | None] = mapped_column(Float, nullable=True)

    calibration_record: Mapped[CalibrationRecord] = relationship(
        back_populates="segments"
    )


class ShadowForecastRecord(TimestampMixin, Base):
    """Shadow forecast entry for calibration data collection.

    Every investigated market produces a shadow forecast from day one,
    regardless of whether a trade is placed.
    """

    __tablename__ = "shadow_forecast_records"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    market_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("markets.id"), nullable=False, index=True
    )
    workflow_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_runs.id"), nullable=True
    )

    # Forecast
    system_probability: Mapped[float] = mapped_column(Float, nullable=False)
    market_implied_probability: Mapped[float] = mapped_column(Float, nullable=False)
    base_rate_probability: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Segment
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    horizon_bucket: Mapped[str | None] = mapped_column(String(30), nullable=True)
    market_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    ambiguity_band: Mapped[str | None] = mapped_column(String(20), nullable=True)
    evidence_quality_class: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Resolution (filled when resolved)
    resolution_outcome: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )  # 1.0 for yes, 0.0 for no
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_resolved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Brier scores (computed after resolution)
    system_brier: Mapped[float | None] = mapped_column(Float, nullable=True)
    market_brier: Mapped[float | None] = mapped_column(Float, nullable=True)
    base_rate_brier: Mapped[float | None] = mapped_column(Float, nullable=True)

    forecast_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Relationships
    market = relationship("Market", back_populates="shadow_forecasts")

    __table_args__ = (
        Index("ix_shadow_forecasts_category", "category"),
        Index("ix_shadow_forecasts_resolved", "is_resolved"),
    )


class CategoryPerformanceLedgerEntry(TimestampMixin, Base):
    """Weekly category performance ledger entry.

    Updated weekly per category with all required performance metrics.
    """

    __tablename__ = "category_performance_ledger"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Period
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Trade metrics
    trades_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    win_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    gross_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    net_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    inference_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    average_edge: Mapped[float | None] = mapped_column(Float, nullable=True)
    average_holding_hours: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Quality metrics
    rejection_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    no_trade_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    brier_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    system_vs_market_brier: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Cost metrics
    cost_of_selectivity: Mapped[float | None] = mapped_column(Float, nullable=True)
    slippage_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    entry_impact_pct: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Exit distribution
    exit_distribution: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        Index("ix_category_ledger_period", "category", "period_start"),
    )


class CalibrationAccumulationProjection(TimestampMixin, Base):
    """Projected timeline for reaching calibration thresholds per segment."""

    __tablename__ = "calibration_accumulation_projections"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Segment
    segment_type: Mapped[str] = mapped_column(String(30), nullable=False)
    segment_label: Mapped[str] = mapped_column(String(100), nullable=False)

    # Accumulation
    current_resolved: Mapped[int] = mapped_column(Integer, nullable=False)
    target_threshold: Mapped[int] = mapped_column(Integer, nullable=False)
    resolved_per_week: Mapped[float] = mapped_column(Float, nullable=False)
    projected_threshold_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_bottleneck: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    projected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_cal_accum_segment", "segment_type", "segment_label"),
    )


class CalibrationThresholdRegistry(TimestampMixin, Base):
    """Configurable calibration thresholds stored as seed data.

    Provides per-segment minimum sample counts and related parameters.
    """

    __tablename__ = "calibration_threshold_registry"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    threshold_name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    segment_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    min_trades: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    parameters: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
