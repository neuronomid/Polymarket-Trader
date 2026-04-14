"""Base-rate reference system.

Lookup/compute historical resolution rates per market type.
Default 50% when no data. Base rate and deviation attached
to every thesis card.

Fully deterministic (Tier D). No LLM calls.
"""

from __future__ import annotations

import structlog

from investigation.types import BaseRateResult

_log = structlog.get_logger(component="base_rate_system")


# --- Default base rates by category and market subcategory ---
# These are starting priors; actual rates are updated from
# resolved trade data in the calibration system.

_DEFAULT_BASE_RATES: dict[str, float] = {
    # Politics
    "politics_election": 0.50,
    "politics_legislation": 0.35,  # most bills fail
    "politics_appointment": 0.40,
    "politics_policy_decision": 0.45,
    "politics_general": 0.50,

    # Geopolitics
    "geopolitics_treaty": 0.30,
    "geopolitics_sanctions": 0.45,
    "geopolitics_conflict": 0.50,
    "geopolitics_diplomatic": 0.40,
    "geopolitics_general": 0.50,

    # Technology
    "technology_product_launch": 0.55,
    "technology_regulatory": 0.40,
    "technology_patent": 0.35,
    "technology_adoption": 0.45,
    "technology_general": 0.50,

    # Science & Health
    "science_health_clinical_trial": 0.30,  # most trials fail
    "science_health_regulatory_approval": 0.40,
    "science_health_publication": 0.50,
    "science_health_general": 0.50,

    # Macro/Policy
    "macro_policy_rate_decision": 0.50,
    "macro_policy_economic_indicator": 0.50,
    "macro_policy_legislation": 0.35,
    "macro_policy_general": 0.50,

    # Sports
    "sports_match_outcome": 0.50,
    "sports_championship": 0.50,
    "sports_record": 0.20,  # records are rare
    "sports_general": 0.50,
}


class BaseRateSystem:
    """Lookup and compute historical resolution rates per market type.

    Usage:
        system = BaseRateSystem()
        result = system.lookup("politics", "election", system_estimate=0.65)
        print(f"Base rate: {result.base_rate}, deviation: {result.deviation_from_estimate}")
    """

    def __init__(
        self,
        *,
        custom_rates: dict[str, float] | None = None,
    ) -> None:
        self._rates = dict(_DEFAULT_BASE_RATES)
        if custom_rates:
            self._rates.update(custom_rates)

    def lookup(
        self,
        category: str,
        subcategory: str | None = None,
        *,
        system_estimate: float | None = None,
    ) -> BaseRateResult:
        """Look up the base rate for a market type.

        Searches for: {category}_{subcategory} → {category}_general → default 50%.

        Args:
            category: Market category (e.g., "politics").
            subcategory: Market subcategory (e.g., "election").
            system_estimate: System's probability estimate for deviation calc.

        Returns:
            BaseRateResult with base rate and optional deviation.
        """
        # Try specific key first
        market_type = f"{category}_{subcategory}" if subcategory else f"{category}_general"
        base_rate = self._rates.get(market_type)

        # Fallback to general category
        if base_rate is None:
            market_type = f"{category}_general"
            base_rate = self._rates.get(market_type)

        # Fallback to global default
        if base_rate is None:
            market_type = "unknown"
            base_rate = 0.5

        # Compute deviation from system estimate
        deviation = None
        if system_estimate is not None:
            deviation = round(system_estimate - base_rate, 4)

        # Determine confidence level based on sample size
        # (in production this would query actual resolved trade data)
        sample_size = self._get_sample_size(market_type)
        confidence = self._confidence_from_sample_size(sample_size)

        result = BaseRateResult(
            base_rate=base_rate,
            market_type=market_type,
            category=category,
            sample_size=sample_size,
            confidence_level=confidence,
            source="system_defaults" if market_type != "unknown" else "default",
            deviation_from_estimate=deviation,
        )

        _log.debug(
            "base_rate_lookup",
            market_type=market_type,
            base_rate=base_rate,
            system_estimate=system_estimate,
            deviation=deviation,
        )

        return result

    def infer_subcategory(self, title: str, category: str) -> str | None:
        """Infer market subcategory from title for base-rate lookup.

        Simple keyword matching — deterministic, no LLM.
        """
        title_lower = title.lower()

        _subcategory_patterns: dict[str, list[tuple[str, list[str]]]] = {
            "politics": [
                ("election", ["election", "vote", "ballot", "primary", "poll"]),
                ("legislation", ["bill", "legislation", "law", "act", "congress", "parliament"]),
                ("appointment", ["nominate", "appoint", "confirm", "cabinet"]),
                ("policy_decision", ["executive order", "policy", "regulation"]),
            ],
            "geopolitics": [
                ("treaty", ["treaty", "agreement", "accord", "pact"]),
                ("sanctions", ["sanction", "embargo", "tariff"]),
                ("conflict", ["war", "conflict", "military", "invasion"]),
                ("diplomatic", ["diplomat", "summit", "talks", "negotiat"]),
            ],
            "technology": [
                ("product_launch", ["launch", "release", "ship", "deploy"]),
                ("regulatory", ["regulat", "antitrust", "ban", "restrict"]),
                ("patent", ["patent", "intellectual property", "ip"]),
                ("adoption", ["adopt", "user", "market share"]),
            ],
            "science_health": [
                ("clinical_trial", ["trial", "phase", "fda", "ema"]),
                ("regulatory_approval", ["approv", "authori"]),
                ("publication", ["publish", "paper", "study", "research"]),
            ],
            "macro_policy": [
                ("rate_decision", ["rate", "fed", "ecb", "boj", "interest"]),
                ("economic_indicator", ["gdp", "inflation", "unemployment", "cpi"]),
                ("legislation", ["bill", "legislation", "congress"]),
            ],
            "sports": [
                ("match_outcome", ["win", "beat", "defeat", "match", "game", "vs"]),
                ("championship", ["champion", "title", "finals", "cup", "series"]),
                ("record", ["record", "milestone", "all-time"]),
            ],
        }

        patterns = _subcategory_patterns.get(category, [])
        for subcategory, keywords in patterns:
            if any(kw in title_lower for kw in keywords):
                return subcategory

        return None

    def _get_sample_size(self, market_type: str) -> int:
        """Get the historical sample size for a market type.

        In production, this queries the calibration database.
        For now returns 0 (no historical data yet).
        """
        # TODO: Query CalibrationRecord / BaseRateReference table
        return 0

    @staticmethod
    def _confidence_from_sample_size(sample_size: int) -> str:
        """Derive confidence level from sample size."""
        if sample_size >= 100:
            return "high"
        if sample_size >= 30:
            return "medium"
        if sample_size >= 10:
            return "low"
        return "none"
