"""Preferred market profile filter.

Spec: Phase 4 Step 4.

Prioritizes contracts that are:
- Objectively resolvable against a named authoritative source
- Not reflexive sentiment contests
- Not dominated by latency advantages
- Supported by verifiable public evidence across independent sources
- Suitable for thesis-based holding over days to weeks
- Liquid enough for reasonable entry/exit friction

All checks are deterministic (Tier D).
"""

from __future__ import annotations

from config.settings import EligibilityConfig
from eligibility.types import MarketEligibilityInput, MarketProfileScore

_DEFAULT_CONFIG = EligibilityConfig()

# Keywords indicating reflexive sentiment contest
_SENTIMENT_KEYWORDS = {
    "popularity", "approval rating", "favorability",
    "trending", "viral", "likes", "followers",
    "sentiment", "perception", "opinion poll",
    "how many people", "what percentage think",
    "public opinion", "feeling about",
}

# Keywords indicating latency-dominated competition
_LATENCY_KEYWORDS = {
    "first to", "breaking", "announced first",
    "within the hour", "within minutes",
    "live result", "real-time",
    "flash", "intraday", "same day",
}

# Keywords suggesting verifiable evidence
_EVIDENCE_KEYWORDS = {
    "official", "government", "agency", "commission",
    "court", "judge", "ruling", "law",
    "report", "study", "data", "announcement",
    "release", "publication", "fda", "sec",
    "filing", "decision", "vote", "certification",
}


def evaluate_market_profile(
    market: MarketEligibilityInput,
    config: EligibilityConfig | None = None,
) -> MarketProfileScore:
    """Evaluate whether a market matches the preferred profile.

    Returns a MarketProfileScore with per-criterion assessments.
    Markets that fail any criterion get flagged but are not necessarily
    rejected — the engine uses this to downgrade to watchlist or reduce
    edge discovery score.

    Args:
        market: Market data to evaluate.
        config: Eligibility configuration thresholds.

    Returns:
        MarketProfileScore with disqualifying reasons if applicable.
    """
    cfg = config or _DEFAULT_CONFIG
    reasons: list[str] = []
    text = f"{market.title} {market.description or ''}".lower()

    # Check 1: Objectively resolvable
    objectively_resolvable = bool(
        market.resolution_source
        and len(market.resolution_source.strip()) >= 3
    )
    if not objectively_resolvable:
        reasons.append("No named authoritative resolution source")

    # Check 2: Not reflexive sentiment contest
    sentiment_count = sum(1 for kw in _SENTIMENT_KEYWORDS if kw in text)
    not_reflexive = sentiment_count < 2
    if not not_reflexive:
        reasons.append("Market appears to be a reflexive sentiment contest")

    # Check 3: Not latency dominated
    latency_count = sum(1 for kw in _LATENCY_KEYWORDS if kw in text)
    not_latency = latency_count < 2
    if not not_latency:
        reasons.append("Market appears dominated by latency advantages")

    # Check 4: Verifiable evidence across independent sources
    evidence_count = sum(1 for kw in _EVIDENCE_KEYWORDS if kw in text)
    verifiable = evidence_count >= 1
    if not verifiable:
        # Not a hard fail — some markets are inherently evidence-based
        # even without explicit keyword mention
        verifiable = bool(market.resolution_source)

    # Check 5: Suitable for thesis-based holding (days to weeks)
    suitable_holding = True
    if market.end_date:
        from datetime import UTC, datetime

        now = datetime.now(tz=UTC)
        hours_to_resolution = (market.end_date - now).total_seconds() / 3600
        # Too short for thesis-based holding
        if hours_to_resolution < cfg.min_horizon_hours:
            suitable_holding = False
            reasons.append(
                f"Too short for thesis-based holding ({hours_to_resolution:.0f}h)"
            )

    # Check 6: Liquid enough
    liquid_enough = (
        market.liquidity_usd is not None
        and market.liquidity_usd >= cfg.min_liquidity_usd
    )
    if not liquid_enough:
        reasons.append("Insufficient liquidity for reasonable entry/exit friction")

    all_met = (
        objectively_resolvable
        and not_reflexive
        and not_latency
        and verifiable
        and suitable_holding
        and liquid_enough
    )

    return MarketProfileScore(
        objectively_resolvable=objectively_resolvable,
        not_reflexive_sentiment=not_reflexive,
        not_latency_dominated=not_latency,
        verifiable_evidence=verifiable,
        suitable_for_thesis_holding=suitable_holding,
        liquid_enough=liquid_enough,
        all_criteria_met=all_met,
        disqualifying_reasons=reasons,
    )
