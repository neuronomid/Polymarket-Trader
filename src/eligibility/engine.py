"""Eligibility engine — orchestrates the full pipeline.

Spec: Phase 4 Steps 1-8.

Pipeline stages:
1. Category classification → reject excluded categories immediately
2. Hard eligibility rules → reject malformed/unsuitable markets
3. Sports Quality Gate → (if sports category) apply five-criteria check
4. Preferred market profile filter → assess market quality
5. Edge discovery focus scoring → rank by information asymmetry
6. Category quality tier assignment → standard or quality-gated
7. Final outcome tagging → Reject / Watchlist / Trigger-Eligible / Investigate-Now
8. Logging → every decision logged with reason codes and timestamps

All pipeline stages are Tier D (deterministic). No LLM calls.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Sequence

from config.settings import EligibilityConfig
from core.enums import Category, EligibilityOutcome
from core.constants import CATEGORY_QUALITY_TIERS
from eligibility.category_classifier import classify_category
from eligibility.edge_scoring import score_edge_discovery
from eligibility.hard_rules import check_all_hard_rules
from eligibility.market_profile import evaluate_market_profile
from eligibility.sports_quality_gate import evaluate_sports_gate
from eligibility.types import (
    EligibilityReasonCode,
    MarketEligibilityInput,
    MarketEligibilityResult,
    SportsGateInput,
)

# Edge score thresholds for final outcome determination
_INVESTIGATE_NOW_EDGE_THRESHOLD = 0.40
_TRIGGER_ELIGIBLE_EDGE_THRESHOLD = 0.15
_WATCHLIST_EDGE_THRESHOLD = 0.05

# Current rule version — bump on rule changes
RULE_VERSION = "1.0.0"


class EligibilityEngine:
    """Orchestrates the full eligibility pipeline.

    All decisions are deterministic (Tier D). The engine runs each stage
    in order, short-circuiting on rejections for efficiency.
    """

    def __init__(self, config: EligibilityConfig | None = None) -> None:
        self.config = config or EligibilityConfig()

    def evaluate(self, market: MarketEligibilityInput) -> MarketEligibilityResult:
        """Run the full eligibility pipeline for a single market.

        Args:
            market: Complete market data for evaluation.

        Returns:
            MarketEligibilityResult with outcome, sub-results, and metadata.
        """

        # --- Stage 1: Category Classification ---
        classification = classify_category(
            raw_category=market.category_raw,
            tags=market.tags,
            slug=market.slug,
            title=market.title,
        )

        # Immediate reject for excluded categories
        if classification.is_excluded:
            return MarketEligibilityResult(
                market_id=market.market_id,
                outcome=EligibilityOutcome.REJECT.value,
                reason_code=EligibilityReasonCode.EXCLUDED_CATEGORY.value,
                reason_detail=(
                    f"Excluded category detected "
                    f"(raw: {classification.raw_category}, "
                    f"method: {classification.classification_method})"
                ),
                category_classification=classification,
                category_quality_tier="excluded",
                rule_version=RULE_VERSION,
            )

        # Unknown category → reject (can't proceed without classification)
        if classification.category is None:
            return MarketEligibilityResult(
                market_id=market.market_id,
                outcome=EligibilityOutcome.REJECT.value,
                reason_code=EligibilityReasonCode.UNKNOWN_CATEGORY.value,
                reason_detail="Unable to classify market into any allowed category",
                category_classification=classification,
                category_quality_tier="unknown",
                rule_version=RULE_VERSION,
            )

        # --- Stage 2: Hard Eligibility Rules ---
        hard_rules = check_all_hard_rules(market, self.config)

        if not hard_rules.all_passed:
            first_fail = hard_rules.first_failure
            return MarketEligibilityResult(
                market_id=market.market_id,
                outcome=EligibilityOutcome.REJECT.value,
                reason_code=first_fail.reason_code.value if first_fail else "unknown",
                reason_detail=first_fail.detail if first_fail else "",
                category_classification=classification,
                hard_rules_result=hard_rules,
                category_quality_tier=classification.quality_tier,
                rule_version=RULE_VERSION,
            )

        # --- Stage 3: Sports Quality Gate (if applicable) ---
        sports_gate = None
        if classification.category == Category.SPORTS.value:
            gate_input = SportsGateInput(
                title=market.title,
                description=market.description,
                category=classification.category,
                resolution_source=market.resolution_source,
                end_date=market.end_date,
                liquidity_usd=market.liquidity_usd,
                spread=market.spread,
                depth_usd_top3=None,  # Computed from depth_levels if available
                tags=market.tags,
            )
            sports_gate = evaluate_sports_gate(gate_input, self.config)

            if not sports_gate.all_criteria_passed:
                return MarketEligibilityResult(
                    market_id=market.market_id,
                    outcome=EligibilityOutcome.REJECT.value,
                    reason_code=EligibilityReasonCode.SPORTS_GATE_FAILED.value,
                    reason_detail="; ".join(sports_gate.rejection_reasons),
                    category_classification=classification,
                    hard_rules_result=hard_rules,
                    sports_gate_result=sports_gate,
                    category_quality_tier="quality_gated",
                    rule_version=RULE_VERSION,
                )

        # --- Stage 4: Preferred Market Profile ---
        profile = evaluate_market_profile(market, self.config)

        # --- Stage 5: Edge Discovery Scoring ---
        edge_score = score_edge_discovery(market)

        # --- Stage 6: Category Quality Tier Assignment ---
        quality_tier = CATEGORY_QUALITY_TIERS.get(
            classification.category, "standard"
        )

        # --- Stage 7: Final Outcome Determination ---
        outcome, reason_code, reason_detail = self._determine_outcome(
            profile=profile,
            edge_score=edge_score,
        )

        return MarketEligibilityResult(
            market_id=market.market_id,
            outcome=outcome,
            reason_code=reason_code,
            reason_detail=reason_detail,
            category_classification=classification,
            hard_rules_result=hard_rules,
            sports_gate_result=sports_gate,
            market_profile_score=profile,
            edge_discovery_score=edge_score,
            category_quality_tier=quality_tier,
            rule_version=RULE_VERSION,
        )

    def evaluate_batch(
        self, markets: Sequence[MarketEligibilityInput]
    ) -> list[MarketEligibilityResult]:
        """Evaluate multiple markets through the eligibility pipeline.

        Args:
            markets: Sequence of market inputs.

        Returns:
            List of eligibility results, one per market.
        """
        return [self.evaluate(m) for m in markets]

    def _determine_outcome(
        self,
        *,
        profile: "from eligibility.types import MarketProfileScore",
        edge_score: "from eligibility.types import EdgeDiscoveryScore",
    ) -> tuple[str, str, str]:
        """Determine the final eligibility outcome.

        Outcome levels:
        - Investigate-Now: High edge score + good profile
        - Trigger-Eligible: Moderate edge score + acceptable profile
        - Watchlist: Low edge score or marginal profile
        - Reject: Profile disqualifiers

        Returns:
            Tuple of (outcome, reason_code, reason_detail).
        """
        # Profile disqualifiers can reduce to watchlist
        profile_penalty = len(profile.disqualifying_reasons) > 0

        # Determine based on edge score and profile
        if not profile.all_criteria_met and not profile.objectively_resolvable:
            return (
                EligibilityOutcome.REJECT.value,
                EligibilityReasonCode.NOT_OBJECTIVELY_RESOLVABLE.value,
                "; ".join(profile.disqualifying_reasons),
            )

        if edge_score.final_score >= _INVESTIGATE_NOW_EDGE_THRESHOLD and not profile_penalty:
            return (
                EligibilityOutcome.INVESTIGATE_NOW.value,
                EligibilityReasonCode.ELIGIBLE.value,
                f"High edge potential ({edge_score.final_score:.2f}), strong profile",
            )

        if edge_score.final_score >= _TRIGGER_ELIGIBLE_EDGE_THRESHOLD:
            return (
                EligibilityOutcome.TRIGGER_ELIGIBLE.value,
                EligibilityReasonCode.ELIGIBLE.value,
                f"Moderate edge potential ({edge_score.final_score:.2f})"
                + (f"; profile notes: {profile.disqualifying_reasons}" if profile_penalty else ""),
            )

        if edge_score.final_score >= _WATCHLIST_EDGE_THRESHOLD:
            return (
                EligibilityOutcome.WATCHLIST.value,
                EligibilityReasonCode.WATCHLIST_LOW_SCORE.value,
                f"Low edge score ({edge_score.final_score:.2f}), placed on watchlist",
            )

        return (
            EligibilityOutcome.WATCHLIST.value,
            EligibilityReasonCode.WATCHLIST_LOW_SCORE.value,
            f"Minimal edge potential ({edge_score.final_score:.2f}), watchlist only",
        )
