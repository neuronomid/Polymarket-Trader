"""Resolution and quality gate models.

ResolutionParseResult, SportsQualityGateResult.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from data.base import Base, TimestampMixin

if TYPE_CHECKING:
    from data.models.thesis import ThesisCard


class ResolutionParseResult(TimestampMixin, Base):
    """Deterministic resolution parser output for a thesis card.

    Checks every surviving candidate for resolution clarity, source naming,
    wording ambiguity, and other tradeability factors.
    """

    __tablename__ = "resolution_parse_results"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    thesis_card_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("thesis_cards.id"), nullable=False, unique=True
    )

    # Checks
    has_named_source: Mapped[bool] = mapped_column(Boolean, nullable=False)
    has_explicit_deadline: Mapped[bool] = mapped_column(Boolean, nullable=False)
    has_ambiguous_wording: Mapped[bool] = mapped_column(Boolean, nullable=False)
    has_undefined_terms: Mapped[bool] = mapped_column(Boolean, nullable=False)
    has_multi_step_deps: Mapped[bool] = mapped_column(Boolean, nullable=False)
    has_unclear_jurisdiction: Mapped[bool] = mapped_column(Boolean, nullable=False)
    has_counter_intuitive_risk: Mapped[bool] = mapped_column(Boolean, nullable=False)
    wording_changed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Overall
    overall_clarity: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # clear, marginal, ambiguous, reject
    rejection_reason: Mapped[str | None] = mapped_column(String(100), nullable=True)
    flagged_items: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)

    parsed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Relationships
    thesis_card: Mapped[ThesisCard] = relationship(
        back_populates="resolution_parse_result"
    )


class SportsQualityGateResult(TimestampMixin, Base):
    """Sports Quality Gate five-criteria check.

    Sports markets require: objective resolution, >48h horizon,
    adequate liquidity, not statistical-modeling-dominated,
    credible evidential basis.
    """

    __tablename__ = "sports_quality_gate_results"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    thesis_card_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("thesis_cards.id"), nullable=False, unique=True
    )

    # Five criteria
    resolution_fully_objective: Mapped[bool] = mapped_column(Boolean, nullable=False)
    resolves_in_48h_plus: Mapped[bool] = mapped_column(Boolean, nullable=False)
    adequate_liquidity_and_depth: Mapped[bool] = mapped_column(Boolean, nullable=False)
    not_statistical_modeling: Mapped[bool] = mapped_column(Boolean, nullable=False)
    credible_evidential_basis: Mapped[bool] = mapped_column(Boolean, nullable=False)

    # Overall
    all_criteria_passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    size_multiplier: Mapped[float] = mapped_column(Float, nullable=False)
    rejection_reasons: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)

    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Relationships
    thesis_card: Mapped[ThesisCard] = relationship(
        back_populates="sports_quality_gate_result"
    )
