"""Edge discovery focus scoring.

Spec: Phase 4 Step 5.

Ranks eligible markets by information asymmetry potential:
- Prioritize: niche political events, specific policy decisions requiring
  technical interpretation, scientific outcomes with domain-knowledge barriers,
  timing-sensitive markets
- Deprioritize: heavily covered events (major elections, championship finals,
  top-line economic releases) where market prices are likely already efficient

All scoring is deterministic (Tier D). Score range: 0.0 → 1.0.
"""

from __future__ import annotations

from eligibility.types import EdgeDiscoveryScore, MarketEligibilityInput

# --- High-value edge indicators (information asymmetry) ---

_NICHE_KEYWORDS = {
    # Niche political
    "committee", "subcommittee", "amendment", "markup", "cloture",
    "redistricting", "runoff", "special election", "recall",
    "municipal", "local", "state legislature", "ballot measure",
    "proposition", "referendum",
    # Technical policy
    "regulation", "rulemaking", "comment period", "fcc", "ftc",
    "cfpb", "omb", "executive order", "memorandum",
    "technical standard", "compliance",
    # Scientific domain
    "phase iii", "phase ii", "phase 3", "phase 2",
    "peer review", "clinical endpoint", "biomarker",
    "gene therapy", "crispr", "mrna",
    "approval pathway", "expedited review",
    # Timing-sensitive
    "deadline", "expiring", "window closes",
    "scheduled for", "hearing date",
}

# --- Efficiency indicators (markets likely already well-priced) ---

_HIGH_COVERAGE_KEYWORDS = {
    # Major elections
    "presidential election", "president of the united states",
    "general election winner", "who will win the presidency",
    # Championship finals
    "super bowl winner", "nba championship", "world series winner",
    "champions league final", "world cup final",
    "stanley cup winner",
    # Top-line macro
    "will the fed cut", "will the fed raise",
    "gdp growth rate", "jobs report",
    "unemployment rate",
    # Extremely high coverage
    "most discussed", "most watched",
    "most popular",
}

# Volume thresholds that suggest efficient pricing
_HIGH_VOLUME_THRESHOLD = 50_000  # $50k+ 24h volume suggests efficient
_MEDIUM_VOLUME_THRESHOLD = 10_000


def score_edge_discovery(
    market: MarketEligibilityInput,
) -> EdgeDiscoveryScore:
    """Score a market for information asymmetry potential.

    Higher score = more likely to have an exploitable edge.

    Scoring dimensions:
    1. Coverage score (0-0.3): Lower media coverage → higher score
    2. Domain barrier (0-0.3): Domain knowledge requirements → higher score
    3. Timing score (0-0.2): Time-sensitive opportunities → higher score
    4. Niche score (0-0.2): Niche/specific events → higher score
    5. Efficiency penalty (0-0.3): High volume → likely efficient → penalty

    Args:
        market: Market data to score.

    Returns:
        EdgeDiscoveryScore with component and final scores.
    """
    text = f"{market.title} {market.description or ''}".lower()
    tag_text = " ".join(market.tags).lower() if market.tags else ""
    combined = f"{text} {tag_text}"

    # --- Coverage score (inverse) ---
    high_coverage_matches = sum(
        1 for kw in _HIGH_COVERAGE_KEYWORDS if kw in combined
    )
    if high_coverage_matches >= 2:
        coverage_score = 0.0
    elif high_coverage_matches == 1:
        coverage_score = 0.10
    else:
        coverage_score = 0.25

    # --- Domain barrier score ---
    niche_matches = sum(1 for kw in _NICHE_KEYWORDS if kw in combined)
    if niche_matches >= 3:
        domain_barrier_score = 0.30
    elif niche_matches >= 2:
        domain_barrier_score = 0.20
    elif niche_matches >= 1:
        domain_barrier_score = 0.10
    else:
        domain_barrier_score = 0.0

    # --- Timing score ---
    timing_keywords = {"deadline", "expiring", "window closes", "scheduled for", "hearing date"}
    timing_matches = sum(1 for kw in timing_keywords if kw in combined)
    timing_score = min(timing_matches * 0.10, 0.20)

    # --- Niche score ---
    niche_event_keywords = {
        "committee", "subcommittee", "amendment", "runoff",
        "special election", "municipal", "ballot measure",
        "phase iii", "phase ii", "clinical endpoint",
        "rulemaking", "executive order", "recall",
    }
    niche_matches_specific = sum(
        1 for kw in niche_event_keywords if kw in combined
    )
    niche_score = min(niche_matches_specific * 0.07, 0.20)

    # --- Efficiency penalty ---
    volume = market.volume_24h or 0.0
    if volume >= _HIGH_VOLUME_THRESHOLD:
        efficiency_penalty = 0.25
    elif volume >= _MEDIUM_VOLUME_THRESHOLD:
        efficiency_penalty = 0.10
    else:
        efficiency_penalty = 0.0

    # Also penalize for high coverage
    if high_coverage_matches >= 2:
        efficiency_penalty = min(efficiency_penalty + 0.15, 0.30)

    # --- Compute final score ---
    raw_score = coverage_score + domain_barrier_score + timing_score + niche_score
    final_score = max(0.0, min(1.0, raw_score - efficiency_penalty))

    return EdgeDiscoveryScore(
        raw_score=round(raw_score, 3),
        coverage_score=round(coverage_score, 3),
        domain_barrier_score=round(domain_barrier_score, 3),
        timing_score=round(timing_score, 3),
        niche_score=round(niche_score, 3),
        efficiency_penalty=round(efficiency_penalty, 3),
        final_score=round(final_score, 3),
    )
