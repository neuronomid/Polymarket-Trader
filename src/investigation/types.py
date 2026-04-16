"""Investigation engine runtime types.

Structured input/output containers for the investigation pipeline:
- InvestigationRequest: trigger/schedule/operator input
- CandidateContext: enriched market data for investigation
- DomainMemo: domain manager output
- ThesisCardData: runtime thesis card (all spec Section 14.2 fields)
- CandidateRubricScore: multi-dimensional candidate scoring
- InvestigationResult: full workflow output
- EntryImpactResult: Tier D impact calculation output
- BaseRateResult: historical resolution rate lookup output
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from cost.types import CostApproval, CostEstimate, EstimateAccuracy

# --- Enums ---


class InvestigationMode(str, Enum):
    """How the investigation was triggered."""

    SCHEDULED_SWEEP = "scheduled_sweep"
    TRIGGER_BASED = "trigger_based"
    OPERATOR_FORCED = "operator_forced"


class InvestigationOutcome(str, Enum):
    """Final outcome of an investigation run."""

    NO_TRADE = "no_trade"
    CANDIDATE_ACCEPTED = "candidate_accepted"
    DEFERRED = "deferred"
    COST_REJECTED = "cost_rejected"
    ERROR = "error"


class CalibrationSourceStatus(str, Enum):
    """Calibration data availability for a thesis card."""

    NO_DATA = "no_data"
    INSUFFICIENT = "insufficient"
    PRELIMINARY = "preliminary"
    RELIABLE = "reliable"


class EntryUrgency(str, Enum):
    """Urgency classification for trade entry."""

    IMMEDIATE = "immediate"
    WITHIN_HOURS = "within_hours"
    WITHIN_DAY = "within_day"
    LOW = "low"


class SizeBand(str, Enum):
    """Recommended position size band."""

    MINIMUM = "minimum"
    SMALL = "small"
    STANDARD = "standard"
    LARGE = "large"


# --- Entry Impact ---


class EntryImpactResult(BaseModel):
    """Output of the Tier D entry impact calculator.

    Deterministic: walks visible order book at top N levels,
    computes levels consumed, estimates mid-price movement.
    """

    estimated_impact_bps: float = 0.0
    levels_consumed: int = 0
    total_fill_size_usd: float = 0.0
    avg_fill_price: float = 0.0
    reference_price: float = 0.0
    remaining_unfilled_usd: float = 0.0
    computed_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))


# --- Base Rate ---


class BaseRateResult(BaseModel):
    """Output of the base-rate reference system.

    Default 50% when no data. Attached to every thesis card.
    """

    base_rate: float = 0.5
    market_type: str = "unknown"
    category: str = ""
    sample_size: int = 0
    confidence_level: str = "none"  # none, low, medium, high
    source: str = "default"
    deviation_from_estimate: float | None = None  # system estimate minus base rate


# --- Candidate Rubric ---


class CandidateRubricScore(BaseModel):
    """Multi-dimensional candidate scoring per spec Section 8.7.

    Every candidate is scored on all dimensions to produce a
    holistic quality assessment.
    """

    # Evidence quality
    evidence_quality: float = 0.0  # 0-1
    evidence_diversity: float = 0.0  # 0-1
    evidence_freshness: float = 0.0  # 0-1

    # Resolution and market structure
    resolution_clarity: float = 0.0  # 0-1
    market_structure_quality: float = 0.0  # 0-1
    timing_clarity: float = 0.0  # 0-1

    # Adversarial
    counter_case_strength: float = 0.0  # 0-1 (higher = stronger counter-case)
    ambiguity_level: float = 0.0  # 0-1 (higher = more ambiguous)

    # Edge and correlation
    expected_gross_edge: float = 0.0
    cluster_correlation_burden: float = 0.0  # 0-1

    # Calibration
    calibration_confidence_source_class: str = "no_data"

    # Cost and horizon
    cost_to_evaluate_estimate: float = 0.0  # USD
    expected_holding_horizon_hours: int = 0

    # Category
    category_quality_tier: str = "standard"

    # Base rate and market context
    base_rate: float = 0.5
    base_rate_deviation: float = 0.0
    market_implied_probability: float = 0.5

    # Impact and liquidity
    entry_impact_estimate_bps: float = 0.0
    liquidity_adjusted_max_size_usd: float = 0.0

    # Composite score
    composite_score: float = 0.0

    def compute_composite(self) -> float:
        """Compute weighted composite score from individual dimensions."""
        weights = {
            "evidence_quality": 0.15,
            "evidence_diversity": 0.05,
            "evidence_freshness": 0.05,
            "resolution_clarity": 0.15,
            "market_structure_quality": 0.10,
            "timing_clarity": 0.05,
            "edge_score": 0.20,
            "ambiguity_penalty": -0.10,
            "counter_case_penalty": -0.10,
            "correlation_penalty": -0.05,
        }

        edge_score = min(1.0, max(0.0, self.expected_gross_edge * 10))  # normalize edge

        score = (
            weights["evidence_quality"] * self.evidence_quality
            + weights["evidence_diversity"] * self.evidence_diversity
            + weights["evidence_freshness"] * self.evidence_freshness
            + weights["resolution_clarity"] * self.resolution_clarity
            + weights["market_structure_quality"] * self.market_structure_quality
            + weights["timing_clarity"] * self.timing_clarity
            + weights["edge_score"] * edge_score
            + weights["ambiguity_penalty"] * self.ambiguity_level
            + weights["counter_case_penalty"] * self.counter_case_strength
            + weights["correlation_penalty"] * self.cluster_correlation_burden
        )

        self.composite_score = round(max(0.0, min(1.0, score)), 4)
        return self.composite_score


# --- Evidence Items ---


class EvidenceItem(BaseModel):
    """A structured evidence item for thesis cards."""

    content: str
    source: str
    freshness: str = "unknown"  # fresh, recent, stale, unknown
    relevance_score: float = 0.0
    url: str | None = None


# --- Domain Memo ---


class DomainMemo(BaseModel):
    """Structured output from a domain manager agent.

    The domain manager synthesizes category-specific analysis
    and recommends whether to proceed with investigation.
    """

    category: str
    market_id: str
    summary: str = ""
    key_findings: list[str] = Field(default_factory=list)
    concerns: list[str] = Field(default_factory=list)
    recommended_proceed: bool = False
    proceed_blocker_code: str | None = None
    proceed_blocker_detail: str | None = None
    optional_agents_justified: list[str] = Field(default_factory=list)
    optional_agents_justification: str | None = None
    confidence_level: str = "low"  # low, medium, high
    domain_specific_data: dict[str, Any] = Field(default_factory=dict)
    estimated_probability: float | None = None  # LLM's estimate of P(YES), 0.0-1.0
    probability_direction: str | None = None  # "overpriced" | "underpriced" | "fair"


# --- Research Pack Results ---


class ResearchPackResult(BaseModel):
    """Combined output from the five default research agents."""

    evidence: list[EvidenceItem] = Field(default_factory=list)
    counter_case: dict[str, Any] = Field(default_factory=dict)
    resolution_review: dict[str, Any] = Field(default_factory=dict)
    timing_assessment: dict[str, Any] = Field(default_factory=dict)
    market_structure: dict[str, Any] = Field(default_factory=dict)

    # Optional agent results (only populated if invoked)
    data_cross_check: dict[str, Any] | None = None
    sentiment_drift: dict[str, Any] | None = None
    source_reliability: dict[str, Any] | None = None

    # Cost tracking
    total_research_cost_usd: float = 0.0
    agents_invoked: list[str] = Field(default_factory=list)
    per_agent_costs: dict[str, float] = Field(default_factory=dict)


# --- Candidate Context ---


class CandidateContext(BaseModel):
    """Enriched context for a single investigation candidate.

    Assembled from eligibility result, market data, and trigger event.
    """

    market_id: str
    token_id: str = ""
    title: str = ""
    description: str | None = None
    category: str = ""
    category_quality_tier: str = "standard"
    tags: list[str] = Field(default_factory=list)

    # Market data
    price: float | None = None
    best_bid: float | None = None
    best_ask: float | None = None
    spread: float | None = None
    mid_price: float | None = None
    depth_levels: list[dict] | None = None
    visible_depth_usd: float = 0.0
    volume_24h: float | None = None

    # Eligibility context
    eligibility_outcome: str = ""
    edge_discovery_score: float = 0.0

    # Trigger context
    trigger_class: str | None = None
    trigger_level: str | None = None
    trigger_reason: str | None = None

    # Resolution source
    resolution_source: str | None = None
    end_date: datetime | None = None
    end_date_hours: float | None = None

    # Cluster context
    held_event_cluster_ids: set[str] = Field(default_factory=set)
    market_event_cluster_id: str | None = None

    # Priority
    urgency_rank: int = 0

    # Metadata hydration quality
    metadata_status: str = "complete"  # complete, unknown_category, metadata_incomplete
    metadata_issues: list[str] = Field(default_factory=list)


# --- Net Edge Calculation ---


class NetEdgeCalculation(BaseModel):
    """Four-level net edge distinction per spec Section 14.3.

    A candidate with positive gross edge but negative/near-zero
    impact-adjusted net edge must NOT be entered.
    """

    gross_edge: float = 0.0  # market price vs estimated probability
    friction_adjusted_edge: float = 0.0  # after spread and slippage
    impact_adjusted_edge: float = 0.0  # after entry impact estimate
    net_edge_after_cost: float = 0.0  # the number the system acts on
    min_viable_edge: float = 0.002

    @property
    def is_viable(self) -> bool:
        """Whether the net edge is positive enough to trade."""
        return self.impact_adjusted_edge > self.min_viable_edge

    @property
    def is_cost_efficient(self) -> bool:
        """Whether inference cost doesn't consume the edge."""
        return self.net_edge_after_cost > 0.0


# --- Thesis Card Data (runtime, all spec Section 14.2 fields) ---


class ThesisCardData(BaseModel):
    """Complete thesis card with all fields from spec Section 14.2.

    This is the runtime representation; the ORM model is in
    data/models/thesis.py.
    """

    # Identifiers
    market_id: str
    workflow_run_id: str

    # Core thesis
    category: str
    category_quality_tier: str = "standard"
    proposed_side: str = "yes"  # "yes" or "no"
    resolution_interpretation: str = ""
    resolution_source_language: str | None = None
    core_thesis: str = ""
    why_mispriced: str = ""

    # Evidence (top 3 each, with source and freshness)
    supporting_evidence: list[dict[str, Any]] = Field(default_factory=list)
    opposing_evidence: list[dict[str, Any]] = Field(default_factory=list)

    # Catalysts and timing
    expected_catalyst: str | None = None
    expected_time_horizon: str | None = None
    expected_time_horizon_hours: int | None = None

    # Invalidation
    invalidation_conditions: list[str] = Field(default_factory=list)

    # Risk summaries
    resolution_risk_summary: str | None = None
    market_structure_summary: str | None = None

    # Quality scores
    evidence_quality_score: float | None = None
    evidence_diversity_score: float | None = None
    ambiguity_score: float | None = None

    # Calibration
    calibration_source_status: str = CalibrationSourceStatus.NO_DATA.value
    raw_model_probability: float | None = None
    calibrated_probability: float | None = None
    calibration_segment_label: str | None = None

    # Section 23: Three separate confidence fields
    probability_estimate: float | None = None
    confidence_estimate: float | None = None
    calibration_confidence: float | None = None
    confidence_note: str | None = None

    # Section 14.3: Four-level net edge distinction
    gross_edge: float | None = None
    friction_adjusted_edge: float | None = None
    impact_adjusted_edge: float | None = None
    net_edge_after_cost: float | None = None

    # Friction and impact
    expected_friction_spread: float | None = None
    expected_friction_slippage: float | None = None
    entry_impact_estimate_bps: float | None = None
    expected_inference_cost_usd: float | None = None

    # Sizing and urgency
    recommended_size_band: str | None = None
    urgency_of_entry: str | None = None
    liquidity_adjusted_max_size_usd: float | None = None

    # Trigger and market context
    trigger_source: str | None = None
    market_implied_probability: float | None = None
    base_rate: float | None = None
    base_rate_deviation: float | None = None

    # Sports quality gate result
    sports_quality_gate_result: dict[str, Any] | None = None

    # Rubric score
    rubric_score: CandidateRubricScore | None = None

    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))


# --- No-Trade Result ---


class NoTradeResult(BaseModel):
    """Structured no-trade decision output.

    No-trade is a logged, structured output — not simply the absence
    of a trade.
    """

    market_id: str | None = None
    market_title: str | None = None
    category: str | None = None
    reason: str = ""
    reason_code: str = ""
    stage: str = ""  # which stage rejected
    reason_detail: str | None = None
    quantitative_context: dict[str, Any] = Field(default_factory=dict)
    rubric_score: CandidateRubricScore | None = None
    cost_spent_usd: float = 0.0
    decided_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))


class CandidateInvestigationResult(BaseModel):
    """Outcome for a single investigated candidate."""

    market_id: str
    market_title: str = ""
    category: str = "unknown"
    accepted: bool = False
    stage_reached: str = ""
    reason: str = ""
    reason_code: str = ""
    reason_detail: str | None = None
    quantitative_context: dict[str, Any] = Field(default_factory=dict)
    cost_spent_usd: float = 0.0
    thesis_card: ThesisCardData | None = None
    no_trade_result: NoTradeResult | None = None


# --- Investigation Request ---


class InvestigationRequest(BaseModel):
    """Input to the investigation orchestrator."""

    workflow_run_id: str
    mode: InvestigationMode
    candidates: list[CandidateContext] = Field(default_factory=list)
    max_candidates: int = 3  # 0-3 per run
    trigger_event_id: str | None = None
    operator_notes: str | None = None


# --- Investigation Result ---


class InvestigationResult(BaseModel):
    """Complete output of an investigation workflow run."""

    workflow_run_id: str
    mode: InvestigationMode
    outcome: InvestigationOutcome

    # Thesis cards for accepted candidates
    thesis_cards: list[ThesisCardData] = Field(default_factory=list)

    # No-trade records
    no_trade_results: list[NoTradeResult] = Field(default_factory=list)
    candidate_outcomes: list[CandidateInvestigationResult] = Field(default_factory=list)

    # Cost tracking
    estimated_cost_usd: float = 0.0
    actual_cost_usd: float = 0.0
    agent_costs: dict[str, float] = Field(default_factory=dict)
    cost_estimate: CostEstimate | None = None
    cost_approval: CostApproval | None = None
    estimate_accuracy: EstimateAccuracy | None = None

    # Metadata
    candidates_evaluated: int = 0
    candidates_accepted: int = 0
    models_used: list[str] = Field(default_factory=list)
    max_tier_used: str = "D"

    started_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))
    completed_at: datetime | None = None

    @property
    def is_no_trade(self) -> bool:
        return self.outcome == InvestigationOutcome.NO_TRADE

    @property
    def has_accepted_candidates(self) -> bool:
        return len(self.thesis_cards) > 0
