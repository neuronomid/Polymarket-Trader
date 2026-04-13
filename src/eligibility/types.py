"""Eligibility gate data types.

Input/output structures for the eligibility pipeline.
All types are Pydantic models for validation and serialization.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, Field


class EligibilityReasonCode(str, Enum):
    """Structured reason codes for eligibility decisions.

    Every rejection/watchlist decision must have one of these codes.
    """

    # Category rejection
    EXCLUDED_CATEGORY = "excluded_category"
    UNKNOWN_CATEGORY = "unknown_category"

    # Hard rule rejections
    MARKET_NOT_ACTIVE = "market_not_active"
    WORDING_MALFORMED = "wording_malformed"
    NO_RESOLUTION_SOURCE = "no_resolution_source"
    HORIZON_TOO_SHORT = "horizon_too_short"
    HORIZON_TOO_LONG = "horizon_too_long"
    INSUFFICIENT_LIQUIDITY = "insufficient_liquidity"
    SPREAD_TOO_WIDE = "spread_too_wide"
    INSUFFICIENT_DEPTH = "insufficient_depth"
    DUPLICATE_EVENT_CLUSTER = "duplicate_event_cluster"

    # Sports quality gate
    SPORTS_GATE_FAILED = "sports_gate_failed"
    SPORTS_NOT_OBJECTIVE = "sports_not_objective"
    SPORTS_HORIZON_TOO_SHORT = "sports_horizon_too_short"
    SPORTS_INSUFFICIENT_LIQUIDITY = "sports_insufficient_liquidity"
    SPORTS_STATISTICAL_MODELING = "sports_statistical_modeling"
    SPORTS_NO_EVIDENCE_BASIS = "sports_no_evidence_basis"

    # Market profile
    REFLEXIVE_SENTIMENT = "reflexive_sentiment"
    LATENCY_DOMINATED = "latency_dominated"
    NOT_OBJECTIVELY_RESOLVABLE = "not_objectively_resolvable"

    # Positive outcomes
    ELIGIBLE = "eligible"
    WATCHLIST_LOW_SCORE = "watchlist_low_score"
    WATCHLIST_MARGINAL_DEPTH = "watchlist_marginal_depth"


class CategoryClassification(BaseModel):
    """Result of categorizing a market."""

    category: str | None = None
    is_excluded: bool = False
    quality_tier: str = "standard"
    confidence: float = 1.0
    classification_method: str = "pattern_match"  # pattern_match, tag_match, slug_match, llm_fallback
    raw_category: str | None = None  # Original category from API


class HardRuleResult(BaseModel):
    """Result of a single hard eligibility rule check."""

    rule_name: str
    passed: bool
    reason_code: EligibilityReasonCode
    detail: str = ""
    threshold_value: float | None = None
    actual_value: float | None = None


class HardRulesResult(BaseModel):
    """Aggregate result of all hard eligibility rules."""

    all_passed: bool
    results: list[HardRuleResult] = Field(default_factory=list)
    first_failure: HardRuleResult | None = None

    @property
    def failure_codes(self) -> list[EligibilityReasonCode]:
        return [r.reason_code for r in self.results if not r.passed]


class SportsGateInput(BaseModel):
    """Input data for the Sports Quality Gate evaluation."""

    title: str
    description: str | None = None
    category: str
    resolution_source: str | None = None
    end_date: datetime | None = None
    liquidity_usd: float | None = None
    spread: float | None = None
    depth_usd_top3: float | None = None
    tags: list[str] = Field(default_factory=list)


class SportsGateResult(BaseModel):
    """Output of the Sports Quality Gate five-criteria check."""

    resolution_fully_objective: bool = False
    resolves_in_48h_plus: bool = False
    adequate_liquidity_and_depth: bool = False
    not_statistical_modeling: bool = False
    credible_evidential_basis: bool = False
    all_criteria_passed: bool = False
    size_multiplier: float = 0.7  # Default reduced multiplier for sports
    rejection_reasons: list[str] = Field(default_factory=list)


class MarketProfileScore(BaseModel):
    """Preferred market profile assessment."""

    objectively_resolvable: bool = False
    not_reflexive_sentiment: bool = False
    not_latency_dominated: bool = False
    verifiable_evidence: bool = False
    suitable_for_thesis_holding: bool = False
    liquid_enough: bool = False
    all_criteria_met: bool = False
    disqualifying_reasons: list[str] = Field(default_factory=list)


class EdgeDiscoveryScore(BaseModel):
    """Edge discovery focus score for ranking eligible markets."""

    raw_score: float = 0.0
    coverage_score: float = 0.0  # Lower coverage = higher score
    domain_barrier_score: float = 0.0  # Domain knowledge barriers
    timing_score: float = 0.0  # Time-sensitive opportunities
    niche_score: float = 0.0  # Niche event score
    efficiency_penalty: float = 0.0  # Penalty for likely efficient markets
    final_score: float = 0.0


class MarketEligibilityInput(BaseModel):
    """Complete market input for the eligibility pipeline."""

    market_id: str
    title: str
    description: str | None = None
    category_raw: str | None = None
    tags: list[str] = Field(default_factory=list)
    slug: str | None = None

    # Market state
    is_active: bool = True
    end_date: datetime | None = None
    resolution_source: str | None = None

    # Market data
    price: float | None = None
    best_bid: float | None = None
    best_ask: float | None = None
    spread: float | None = None
    liquidity_usd: float | None = None
    volume_24h: float | None = None
    depth_levels: list[dict] | None = None

    # Cluster context
    held_event_cluster_ids: set[str] = Field(default_factory=set)
    market_event_cluster_id: str | None = None


class MarketEligibilityResult(BaseModel):
    """Complete output of the eligibility pipeline for one market."""

    market_id: str
    outcome: str  # EligibilityOutcome value
    reason_code: str
    reason_detail: str = ""

    # Sub-results
    category_classification: CategoryClassification
    hard_rules_result: HardRulesResult | None = None
    sports_gate_result: SportsGateResult | None = None
    market_profile_score: MarketProfileScore | None = None
    edge_discovery_score: EdgeDiscoveryScore | None = None

    # Tier assignment
    category_quality_tier: str = "standard"

    # Metadata
    rule_version: str = "1.0.0"
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))
