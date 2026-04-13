"""Thesis card model.

The ThesisCard is the comprehensive output of an investigation, containing
all fields from spec Section 14.2 including net edge distinctions, confidence
calibration, and base-rate comparisons.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from data.base import Base, TimestampMixin

if TYPE_CHECKING:
    from data.models import Market, Position
    from data.models.workflow import WorkflowRun
    from data.models.resolution import ResolutionParseResult, SportsQualityGateResult


class ThesisCard(TimestampMixin, Base):
    """Complete thesis card produced by an investigation workflow.

    Contains all fields from spec Section 14.2 including four-level net edge
    distinction (Section 14.3) and three-field confidence calibration (Section 23).
    """

    __tablename__ = "thesis_cards"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    market_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("markets.id"), nullable=False, index=True
    )
    workflow_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_runs.id"), nullable=False, index=True
    )

    # --- Core thesis ---
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    category_quality_tier: Mapped[str] = mapped_column(String(30), nullable=False)
    proposed_side: Mapped[str] = mapped_column(String(10), nullable=False)  # "yes" / "no"
    resolution_interpretation: Mapped[str] = mapped_column(Text, nullable=False)
    resolution_source_language: Mapped[str | None] = mapped_column(Text, nullable=True)
    core_thesis: Mapped[str] = mapped_column(Text, nullable=False)
    why_mispriced: Mapped[str] = mapped_column(Text, nullable=False)

    # --- Evidence ---
    supporting_evidence: Mapped[list[dict]] = mapped_column(JSONB, nullable=False)
    opposing_evidence: Mapped[list[dict]] = mapped_column(JSONB, nullable=False)

    # --- Catalysts & timing ---
    expected_catalyst: Mapped[str | None] = mapped_column(Text, nullable=True)
    expected_time_horizon: Mapped[str | None] = mapped_column(String(50), nullable=True)
    expected_time_horizon_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # --- Invalidation ---
    invalidation_conditions: Mapped[list[str]] = mapped_column(JSONB, nullable=False)

    # --- Risk summaries ---
    resolution_risk_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    market_structure_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Quality scores ---
    evidence_quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    evidence_diversity_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    ambiguity_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    # --- Calibration ---
    calibration_source_status: Mapped[str | None] = mapped_column(
        String(30), nullable=True
    )  # no_data, insufficient, preliminary, reliable
    raw_model_probability: Mapped[float | None] = mapped_column(Float, nullable=True)
    calibrated_probability: Mapped[float | None] = mapped_column(Float, nullable=True)
    calibration_segment_label: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # --- Section 23: Three separate confidence fields ---
    probability_estimate: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence_estimate: Mapped[float | None] = mapped_column(Float, nullable=True)
    calibration_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Section 14.3: Four-level net edge distinction ---
    gross_edge: Mapped[float | None] = mapped_column(Float, nullable=True)
    friction_adjusted_edge: Mapped[float | None] = mapped_column(Float, nullable=True)
    impact_adjusted_edge: Mapped[float | None] = mapped_column(Float, nullable=True)
    net_edge_after_cost: Mapped[float | None] = mapped_column(Float, nullable=True)

    # --- Friction & impact ---
    expected_friction_spread: Mapped[float | None] = mapped_column(Float, nullable=True)
    expected_friction_slippage: Mapped[float | None] = mapped_column(Float, nullable=True)
    entry_impact_estimate_bps: Mapped[float | None] = mapped_column(Float, nullable=True)
    expected_inference_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)

    # --- Sizing & urgency ---
    recommended_size_band: Mapped[str | None] = mapped_column(String(30), nullable=True)
    urgency_of_entry: Mapped[str | None] = mapped_column(String(30), nullable=True)
    liquidity_adjusted_max_size: Mapped[float | None] = mapped_column(Float, nullable=True)

    # --- Trigger & market context ---
    trigger_source: Mapped[str | None] = mapped_column(String(50), nullable=True)
    market_implied_probability: Mapped[float | None] = mapped_column(Float, nullable=True)
    base_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    base_rate_deviation: Mapped[float | None] = mapped_column(Float, nullable=True)

    # --- Relationships ---
    market: Mapped[Market] = relationship(back_populates="thesis_cards")
    workflow_run: Mapped[WorkflowRun] = relationship(back_populates="thesis_cards")
    position: Mapped[Position | None] = relationship(back_populates="thesis_card", uselist=False)
    resolution_parse_result: Mapped[ResolutionParseResult | None] = relationship(
        back_populates="thesis_card", uselist=False
    )
    sports_quality_gate_result: Mapped[SportsQualityGateResult | None] = relationship(
        back_populates="thesis_card", uselist=False
    )
    net_edge_estimates: Mapped[list[NetEdgeEstimate]] = relationship(
        back_populates="thesis_card"
    )

    __table_args__ = (
        Index("ix_thesis_cards_market_workflow", "market_id", "workflow_run_id"),
        Index("ix_thesis_cards_category", "category"),
    )


class NetEdgeEstimate(TimestampMixin, Base):
    """Historical net edge estimate records for a thesis card.

    Tracks how the four-level edge distinction evolves as conditions change.
    """

    __tablename__ = "net_edge_estimates"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    thesis_card_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("thesis_cards.id"), nullable=False, index=True
    )

    gross_edge: Mapped[float] = mapped_column(Float, nullable=False)
    friction_adjusted_edge: Mapped[float] = mapped_column(Float, nullable=False)
    impact_adjusted_edge: Mapped[float] = mapped_column(Float, nullable=False)
    net_edge_after_cost: Mapped[float] = mapped_column(Float, nullable=False)

    market_price_at_estimate: Mapped[float | None] = mapped_column(Float, nullable=True)
    estimated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    thesis_card: Mapped[ThesisCard] = relationship(back_populates="net_edge_estimates")
