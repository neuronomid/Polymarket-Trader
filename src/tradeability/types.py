"""Tradeability & Resolution runtime types.

Structured input/output containers for the resolution parser,
hard rejection filters, and tradeability synthesizer.

These are in-process Pydantic types — not ORM models.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# --- Enums ---


class ResolutionClarity(str, Enum):
    """Overall clarity classification from the deterministic parser."""

    CLEAR = "clear"
    MARGINAL = "marginal"
    AMBIGUOUS = "ambiguous"
    REJECT = "reject"


class TradeabilityOutcome(str, Enum):
    """Output of the tradeability assessment.

    From spec Section 9.5:
    - REJECT: with reason code
    - WATCH: recheck later
    - TRADABLE_REDUCED: tradable with reduced size + liquidity-adjusted max
    - TRADABLE_NORMAL: tradable at normal size range + liquidity-adjusted max
    """

    REJECT = "reject"
    WATCH = "watch"
    TRADABLE_REDUCED = "tradable_reduced"
    TRADABLE_NORMAL = "tradable_normal"


class HardRejectionReason(str, Enum):
    """Enumerated hard rejection reasons.

    From spec Section 9.4 — auto-reject patterns.
    """

    AMBIGUOUS_WORDING = "ambiguous_wording"
    UNSTABLE_RESOLUTION_SOURCE = "unstable_resolution_source"
    COUNTER_INTUITIVE_RESOLUTION = "counter_intuitive_resolution"
    UNACCEPTABLE_EXIT_CONDITIONS = "unacceptable_exit_conditions"
    SPREAD_DEPTH_HARD_LIMIT = "spread_depth_hard_limit"
    EXTREME_MANIPULATION_RISK = "extreme_manipulation_risk"
    DEPTH_BELOW_MINIMUM = "depth_below_minimum"
    WORDING_CHANGED = "wording_changed"


# --- Resolution Parser Types ---


class AmbiguousPhrase(BaseModel):
    """A detected ambiguous phrase in contract wording."""

    phrase: str
    context: str = ""
    severity: str = "medium"  # low, medium, high


class ResolutionCheck(BaseModel):
    """Result of a single resolution check."""

    check_name: str
    passed: bool
    detail: str = ""
    severity: str = "info"  # info, warning, critical


class ResolutionParseInput(BaseModel):
    """Input to the deterministic resolution parser."""

    market_id: str
    title: str
    description: str | None = None
    resolution_source: str | None = None
    resolution_deadline: datetime | None = None
    contract_wording: str | None = None
    previous_wording: str | None = None  # for version change detection
    end_date_hours: float | None = None  # hours from now
    spread: float | None = None
    depth_usd: float = 0.0
    min_position_size_usd: float = 50.0  # system minimum


class ResolutionParseOutput(BaseModel):
    """Output of the deterministic resolution parser.

    Every surviving candidate gets one of these.
    """

    market_id: str
    clarity: ResolutionClarity

    # Individual checks
    checks: list[ResolutionCheck] = Field(default_factory=list)

    # Specific flags
    has_named_source: bool = False
    has_explicit_deadline: bool = False
    has_ambiguous_wording: bool = False
    has_undefined_terms: bool = False
    has_multi_step_deps: bool = False
    has_unclear_jurisdiction: bool = False
    has_counter_intuitive_risk: bool = False
    wording_changed: bool = False

    # Detected issues
    ambiguous_phrases: list[AmbiguousPhrase] = Field(default_factory=list)
    undefined_terms: list[str] = Field(default_factory=list)
    flagged_items: list[str] = Field(default_factory=list)

    # Rejection
    rejection_reason: HardRejectionReason | None = None
    rejection_detail: str | None = None

    parsed_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))

    @property
    def is_rejected(self) -> bool:
        return self.clarity == ResolutionClarity.REJECT

    @property
    def has_residual_ambiguity(self) -> bool:
        """Non-trivial residual ambiguity requiring Tier B synthesizer."""
        return self.clarity == ResolutionClarity.MARGINAL


# --- Tradeability Types ---


class TradeabilityInput(BaseModel):
    """Input to the tradeability synthesizer.

    Includes resolution parse output plus market quality data.
    """

    market_id: str
    workflow_run_id: str
    title: str
    description: str | None = None

    # Resolution parser result
    resolution_parse: ResolutionParseOutput

    # Market quality data
    spread: float | None = None
    visible_depth_usd: float = 0.0
    liquidity_usd: float | None = None
    best_bid: float | None = None
    best_ask: float | None = None
    mid_price: float | None = None

    # Edge and thesis context
    gross_edge: float | None = None
    net_edge: float | None = None
    entry_impact_bps: float | None = None

    # Sizing context
    min_position_size_usd: float = 50.0
    depth_fraction_limit: float = 0.12


class TradeabilityResult(BaseModel):
    """Output of the tradeability assessment.

    Includes the final decision, liquidity-adjusted max size, and
    the reason for the decision.
    """

    market_id: str
    outcome: TradeabilityOutcome
    reason: str = ""
    reason_code: str = ""

    # Liquidity-adjusted sizing
    liquidity_adjusted_max_size_usd: float = 0.0

    # Resolution context
    resolution_clarity: ResolutionClarity = ResolutionClarity.CLEAR
    residual_ambiguity_issues: list[str] = Field(default_factory=list)

    # Hard rejection detail
    hard_rejection_reasons: list[HardRejectionReason] = Field(default_factory=list)

    # Synthesizer output (only for agent-assisted assessment)
    synthesizer_output: dict[str, Any] | None = None
    synthesizer_cost_usd: float = 0.0

    assessed_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))

    @property
    def is_tradable(self) -> bool:
        return self.outcome in (
            TradeabilityOutcome.TRADABLE_NORMAL,
            TradeabilityOutcome.TRADABLE_REDUCED,
        )
