"""Candidate rubric — multi-dimensional scoring per spec Section 8.7.

Scores every candidate on all dimensions to produce a holistic
quality assessment. The composite score determines whether the
candidate warrants further investigation or should result in no-trade.

Fully deterministic (Tier D). No LLM calls.
"""

from __future__ import annotations

import structlog

from investigation.types import (
    CandidateContext,
    CandidateRubricScore,
    DomainMemo,
    EntryImpactResult,
    BaseRateResult,
    ResearchPackResult,
)

_log = structlog.get_logger(component="candidate_rubric")

# --- Score thresholds ---
# NOTE: Thresholds are calibrated for paper/shadow mode where no historical
# calibration data exists and gross_edge estimates are preliminary.
# In live mode with calibration data these should be raised back toward 0.25/0.35.
MIN_COMPOSITE_FOR_OPUS = 0.30  # Must exceed this for Tier A escalation (was 0.35)
MIN_COMPOSITE_FOR_ACCEPTANCE = 0.15  # Below this → automatic no-trade (was 0.25)
STRONG_CANDIDATE_THRESHOLD = 0.50  # Above this → high-quality candidate (was 0.55)


class CandidateRubric:
    """Scores investigation candidates on all dimensions.

    Usage:
        rubric = CandidateRubric()
        score = rubric.score(
            candidate=candidate_ctx,
            domain_memo=domain_memo,
            research=research_result,
            entry_impact=impact_result,
            base_rate=base_rate_result,
        )
        if score.composite_score >= MIN_COMPOSITE_FOR_ACCEPTANCE:
            # proceed
    """

    def score(
        self,
        candidate: CandidateContext,
        domain_memo: DomainMemo | None = None,
        research: ResearchPackResult | None = None,
        entry_impact: EntryImpactResult | None = None,
        base_rate: BaseRateResult | None = None,
        *,
        gross_edge: float = 0.0,
        market_implied_probability: float = 0.5,
        correlation_burden: float = 0.0,
        calibration_source_class: str = "no_data",
    ) -> CandidateRubricScore:
        """Score a candidate on all rubric dimensions.

        Args:
            candidate: Market context data.
            domain_memo: Domain manager output (optional).
            research: Research pack results (optional).
            entry_impact: Entry impact calculation (optional).
            base_rate: Base rate lookup result (optional).
            gross_edge: Expected gross edge.
            market_implied_probability: Current market price.
            correlation_burden: Cluster correlation score (0-1).
            calibration_source_class: Calibration data status.

        Returns:
            CandidateRubricScore with composite score.
        """
        rubric = CandidateRubricScore()

        # Evidence quality from research pack
        if research and research.evidence:
            rubric.evidence_quality = self._score_evidence_quality(research)
            rubric.evidence_diversity = self._score_evidence_diversity(research)
            rubric.evidence_freshness = self._score_evidence_freshness(research)

        # Resolution clarity
        if research and research.resolution_review:
            rubric.resolution_clarity = self._score_resolution_clarity(research.resolution_review)

        # Market structure quality
        rubric.market_structure_quality = self._score_market_structure(candidate)

        # Timing clarity
        if research and research.timing_assessment:
            rubric.timing_clarity = self._score_timing_clarity(research.timing_assessment)

        # Counter-case strength
        if research and research.counter_case:
            rubric.counter_case_strength = self._score_counter_case(research.counter_case)

        # Ambiguity level
        if research and research.resolution_review:
            rubric.ambiguity_level = self._score_ambiguity(research.resolution_review)

        # Edge and correlation
        rubric.expected_gross_edge = gross_edge
        rubric.cluster_correlation_burden = correlation_burden

        # Calibration
        rubric.calibration_confidence_source_class = calibration_source_class

        # Cost and horizon
        if research:
            rubric.cost_to_evaluate_estimate = research.total_research_cost_usd
        if candidate.end_date_hours is not None:
            rubric.expected_holding_horizon_hours = int(candidate.end_date_hours)

        # Category quality tier
        rubric.category_quality_tier = candidate.category_quality_tier

        # Base rate and market context
        if base_rate:
            rubric.base_rate = base_rate.base_rate
            rubric.base_rate_deviation = base_rate.deviation_from_estimate or 0.0

        rubric.market_implied_probability = market_implied_probability

        # Entry impact and liquidity
        if entry_impact:
            rubric.entry_impact_estimate_bps = entry_impact.estimated_impact_bps

        rubric.liquidity_adjusted_max_size_usd = candidate.visible_depth_usd * 0.12

        # Compute composite
        rubric.compute_composite()

        _log.info(
            "candidate_rubric_scored",
            market_id=candidate.market_id,
            composite_score=rubric.composite_score,
            evidence_quality=rubric.evidence_quality,
            resolution_clarity=rubric.resolution_clarity,
            gross_edge=rubric.expected_gross_edge,
            counter_case_strength=rubric.counter_case_strength,
        )

        return rubric

    # --- Per-dimension scoring ---

    def _score_evidence_quality(self, research: ResearchPackResult) -> float:
        """Score evidence quality from 0-1."""
        if not research.evidence:
            return 0.0

        total_relevance = sum(e.relevance_score for e in research.evidence)
        count = len(research.evidence)
        avg_relevance = total_relevance / count if count > 0 else 0.0

        # Bonus for having multiple high-quality items
        high_quality_count = sum(1 for e in research.evidence if e.relevance_score >= 0.7)
        diversity_bonus = min(0.2, high_quality_count * 0.05)

        return min(1.0, avg_relevance + diversity_bonus)

    def _score_evidence_diversity(self, research: ResearchPackResult) -> float:
        """Score evidence source diversity from 0-1."""
        if not research.evidence:
            return 0.0

        sources = {e.source for e in research.evidence}
        # More unique sources → higher diversity
        diversity = min(1.0, len(sources) / 5.0)
        return round(diversity, 2)

    def _score_evidence_freshness(self, research: ResearchPackResult) -> float:
        """Score evidence freshness from 0-1."""
        if not research.evidence:
            return 0.0

        freshness_map = {"fresh": 1.0, "recent": 0.7, "stale": 0.3, "unknown": 0.5}
        scores = [freshness_map.get(e.freshness, 0.5) for e in research.evidence]
        return round(sum(scores) / len(scores), 2) if scores else 0.5

    def _score_resolution_clarity(self, resolution_review: dict) -> float:
        """Score resolution clarity from 0-1."""
        clarity = resolution_review.get("clarity_score", 0.5)
        has_source = resolution_review.get("has_named_source", False)
        has_deadline = resolution_review.get("has_deadline", False)
        no_ambiguity = not resolution_review.get("has_ambiguous_wording", True)

        score = clarity * 0.4
        if has_source:
            score += 0.2
        if has_deadline:
            score += 0.2
        if no_ambiguity:
            score += 0.2

        return min(1.0, score)

    def _score_market_structure(self, candidate: CandidateContext) -> float:
        """Score market structure quality from 0-1."""
        score = 0.0

        # Spread quality (tighter is better)
        if candidate.spread is not None:
            if candidate.spread < 0.03:
                score += 0.3
            elif candidate.spread < 0.08:
                score += 0.2
            elif candidate.spread < 0.15:
                score += 0.1

        # Depth quality
        if candidate.visible_depth_usd > 0:
            if candidate.visible_depth_usd > 10000:
                score += 0.3
            elif candidate.visible_depth_usd > 5000:
                score += 0.2
            elif candidate.visible_depth_usd > 1000:
                score += 0.1

        # Volume
        if candidate.volume_24h is not None:
            if candidate.volume_24h > 50000:
                score += 0.2
            elif candidate.volume_24h > 10000:
                score += 0.15
            elif candidate.volume_24h > 1000:
                score += 0.1

        # Price not extreme (not near 0 or 1)
        if candidate.price is not None:
            if 0.15 <= candidate.price <= 0.85:
                score += 0.2
            elif 0.05 <= candidate.price <= 0.95:
                score += 0.1

        return min(1.0, score)

    def _score_timing_clarity(self, timing: dict) -> float:
        """Score timing/catalyst clarity from 0-1."""
        return timing.get("timing_clarity_score", 0.5)

    def _score_counter_case(self, counter_case: dict) -> float:
        """Score counter-case strength from 0-1 (higher = stronger opposition)."""
        return counter_case.get("strength_score", 0.3)

    def _score_ambiguity(self, resolution_review: dict) -> float:
        """Score ambiguity level from 0-1 (higher = more ambiguous)."""
        ambiguity_flags = resolution_review.get("ambiguity_flags", [])
        base = len(ambiguity_flags) * 0.15
        if resolution_review.get("has_ambiguous_wording", False):
            base += 0.3
        return min(1.0, base)
