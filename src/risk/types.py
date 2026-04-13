"""Risk Governor runtime types.

Pydantic models for risk assessment inputs, outputs, sizing, drawdown state,
and correlation assessment. These are in-process types — not ORM models.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from core.enums import (
    CategoryQualityTier,
    DrawdownLevel,
    OperatorMode,
    RiskApproval,
)


class PortfolioState(BaseModel):
    """Current portfolio snapshot used as input to risk assessment."""

    account_balance_usd: float
    start_of_day_equity_usd: float
    current_equity_usd: float
    total_open_exposure_usd: float = 0.0
    daily_deployment_used_usd: float = 0.0
    open_position_count: int = 0
    category_exposure_usd: dict[str, float] = Field(default_factory=dict)
    cluster_exposure_usd: dict[str, float] = Field(default_factory=dict)
    operator_mode: OperatorMode = OperatorMode.PAPER


class SizingRequest(BaseModel):
    """Input to the position sizer for a candidate trade."""

    market_id: str
    token_id: str
    category: str
    category_quality_tier: CategoryQualityTier = CategoryQualityTier.STANDARD

    # Edge and confidence (from thesis card)
    gross_edge: float
    net_edge_after_cost: float | None = None
    probability_estimate: float
    confidence_estimate: float
    calibration_confidence: float = 0.5

    # Evidence quality
    evidence_quality_score: float = 0.5
    evidence_diversity_score: float = 0.5
    ambiguity_score: float = 0.0

    # Liquidity data
    visible_depth_usd: float = 0.0
    best_bid: float | None = None
    best_ask: float | None = None
    spread: float | None = None

    # Correlation
    correlation_burden_score: float = 0.0
    cluster_ids: list[str] = Field(default_factory=list)

    # Source quality
    weak_source_score: float = 0.0  # 0 = strong sources, 1 = all weak
    timing_uncertainty_score: float = 0.0  # 0 = clear timing, 1 = unclear

    # Resolved trades for sports quality gate
    category_resolved_trades: int = 0


class SizingResult(BaseModel):
    """Output of the position sizer."""

    recommended_size_usd: float
    max_size_usd: float  # hard cap from liquidity
    size_factors: dict[str, float] = Field(default_factory=dict)
    penalties_applied: dict[str, float] = Field(default_factory=dict)
    capped_by: str | None = None  # which constraint was binding


class LiquidityCheck(BaseModel):
    """Result of liquidity-relative sizing check."""

    max_order_usd: float  # hard cap from depth fraction
    depth_at_top_levels_usd: float
    entry_impact_bps: float = 0.0
    entry_impact_edge_fraction: float = 0.0
    passes_depth_check: bool = True
    passes_impact_check: bool = True
    reason: str = ""


class CorrelationAssessment(BaseModel):
    """Result of correlation engine evaluation for a candidate."""

    burden_score: float = 0.0  # 0-1 aggregate correlation burden
    cluster_violations: list[str] = Field(default_factory=list)
    total_correlated_exposure_usd: float = 0.0
    passes: bool = True
    reason: str = ""


class DrawdownState(BaseModel):
    """Current drawdown ladder state."""

    level: DrawdownLevel = DrawdownLevel.NORMAL
    current_drawdown_pct: float = 0.0
    start_of_day_equity: float = 0.0
    current_equity: float = 0.0
    entries_allowed: bool = True
    size_multiplier: float = 1.0
    min_evidence_score: float = 0.0
    changed_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))


class RiskRuleResult(BaseModel):
    """Result of a single deterministic risk rule evaluation."""

    rule_name: str
    passed: bool
    reason: str
    threshold_value: float | None = None
    actual_value: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RiskAssessment(BaseModel):
    """Complete Risk Governor assessment for a candidate trade."""

    approval: RiskApproval
    sizing: SizingResult | None = None
    drawdown_state: DrawdownState
    liquidity_check: LiquidityCheck | None = None
    correlation: CorrelationAssessment | None = None
    rule_results: list[RiskRuleResult] = Field(default_factory=list)
    reason: str = ""
    special_conditions: list[str] = Field(default_factory=list)
    assessed_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))

    @property
    def is_approved(self) -> bool:
        return self.approval in (
            RiskApproval.APPROVE_NORMAL,
            RiskApproval.APPROVE_REDUCED,
            RiskApproval.APPROVE_SPECIAL,
        )
