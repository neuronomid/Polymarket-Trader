"""Tests for Phase 4: Eligibility Gate & Category Classification.

Test categories:
1. Category Classifier — excluded/allowed detection, priority ordering
2. Hard Eligibility Rules — all 8 deterministic checks
3. Sports Quality Gate — five criteria
4. Market Profile Filter — preferred profile assessment
5. Edge Discovery Scoring — information asymmetry ranking
6. Eligibility Engine — full pipeline orchestration
7. Acceptance Criteria — spec compliance validation
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from config.settings import EligibilityConfig
from eligibility.category_classifier import classify_category
from eligibility.edge_scoring import score_edge_discovery
from eligibility.engine import EligibilityEngine
from eligibility.hard_rules import check_all_hard_rules
from eligibility.market_profile import evaluate_market_profile
from eligibility.sports_quality_gate import evaluate_sports_gate
from eligibility.types import (
    EligibilityReasonCode,
    MarketEligibilityInput,
    SportsGateInput,
)


# ============================================================
# Helpers — reusable market fixtures
# ============================================================

def _make_market(**overrides) -> MarketEligibilityInput:
    """Create a valid market input with sensible defaults."""
    defaults = dict(
        market_id="test-market-001",
        title="Will the FDA approve drug X by December 2026?",
        description="The FDA is reviewing drug X for approval. Resolution via official FDA announcement.",
        category_raw="science",
        tags=["health", "fda"],
        slug="fda-drug-x-approval-2026",
        is_active=True,
        end_date=datetime.now(tz=UTC) + timedelta(days=30),
        resolution_source="Official FDA announcement",
        price=0.55,
        best_bid=0.54,
        best_ask=0.56,
        spread=0.02,
        liquidity_usd=5000.0,
        volume_24h=2000.0,
        depth_levels=[
            {"price": 0.54, "size": 500},
            {"price": 0.53, "size": 400},
            {"price": 0.52, "size": 300},
        ],
    )
    defaults.update(overrides)
    return MarketEligibilityInput(**defaults)


def _make_sports_market(**overrides) -> MarketEligibilityInput:
    """Create a valid sports market input."""
    defaults = dict(
        market_id="sports-001",
        title="Will the Lakers win the NBA Championship 2026?",
        description="The Lakers are competing in the NBA playoffs. Key injury updates and matchup analysis.",
        category_raw="sports",
        tags=["nba", "basketball"],
        slug="lakers-nba-championship-2026",
        is_active=True,
        end_date=datetime.now(tz=UTC) + timedelta(days=60),
        resolution_source="Official NBA results",
        price=0.30,
        best_bid=0.29,
        best_ask=0.31,
        spread=0.02,
        liquidity_usd=8000.0,
        volume_24h=5000.0,
        depth_levels=[
            {"price": 0.29, "size": 800},
            {"price": 0.28, "size": 600},
            {"price": 0.27, "size": 500},
        ],
    )
    defaults.update(overrides)
    return MarketEligibilityInput(**defaults)


# ============================================================
# 1. Category Classifier Tests
# ============================================================


class TestCategoryClassifier:
    """Test deterministic category classification."""

    # --- Excluded categories ---

    def test_crypto_excluded_via_api_category(self):
        result = classify_category(raw_category="crypto")
        assert result.is_excluded is True
        assert result.classification_method == "api_category_excluded"

    def test_news_excluded_via_api_category(self):
        result = classify_category(raw_category="news")
        assert result.is_excluded is True

    def test_culture_excluded_via_api_category(self):
        result = classify_category(raw_category="culture")
        assert result.is_excluded is True

    def test_weather_excluded_via_api_category(self):
        result = classify_category(raw_category="weather")
        assert result.is_excluded is True

    def test_entertainment_excluded(self):
        result = classify_category(raw_category="entertainment")
        assert result.is_excluded is True

    def test_crypto_excluded_via_tags(self):
        result = classify_category(tags=["cryptocurrency", "defi"])
        assert result.is_excluded is True
        assert result.classification_method == "tag_match"

    def test_crypto_excluded_via_title(self):
        result = classify_category(title="Will Bitcoin reach $100k?")
        assert result.is_excluded is True
        assert result.classification_method == "title_match"

    def test_crypto_excluded_via_slug(self):
        result = classify_category(slug="bitcoin-price-100k")
        assert result.is_excluded is True
        assert result.classification_method == "slug_match"

    def test_weather_excluded_via_title(self):
        result = classify_category(title="Will the hurricane hit Florida?")
        assert result.is_excluded is True

    # --- Allowed categories ---

    def test_politics_via_api(self):
        result = classify_category(raw_category="politics")
        assert result.category == "politics"
        assert result.is_excluded is False
        assert result.quality_tier == "standard"

    def test_geopolitics_via_api(self):
        result = classify_category(raw_category="geopolitics")
        assert result.category == "geopolitics"
        assert result.quality_tier == "standard"

    def test_technology_via_api(self):
        result = classify_category(raw_category="technology")
        assert result.category == "technology"

    def test_sports_via_api(self):
        result = classify_category(raw_category="sports")
        assert result.category == "sports"
        assert result.quality_tier == "quality_gated"

    def test_science_health_via_tags(self):
        result = classify_category(tags=["fda", "drug approval"])
        assert result.category == "science_health"

    def test_macro_policy_via_title(self):
        result = classify_category(title="Will the Federal Reserve cut interest rates?")
        assert result.category == "macro_policy"

    def test_sports_title_override_handles_team_win_form(self):
        result = classify_category(title="Will Liverpool FC win on 2026-04-19?")
        assert result.category == "sports"
        assert result.classification_method == "title_override"

    def test_sports_title_override_handles_league_outright(self):
        result = classify_category(title="Premier League winner 2026")
        assert result.category == "sports"
        assert result.classification_method == "title_override"

    def test_geopolitics_title_override_handles_iran_military_market(self):
        result = classify_category(title="Will Iran retaliate with military strikes against Israel?")
        assert result.category == "geopolitics"
        assert result.classification_method == "title_override"

    # --- Priority ordering ---

    def test_api_category_takes_priority(self):
        """API category should win over conflicting tags."""
        result = classify_category(
            raw_category="politics",
            tags=["crypto"],
        )
        assert result.category == "politics"
        assert result.is_excluded is False

    def test_excluded_api_category_takes_priority(self):
        """Excluded API category should win over conflicting title."""
        result = classify_category(
            raw_category="crypto",
            title="Will the president sign the bill?",
        )
        assert result.is_excluded is True

    # --- Unknown/unclassifiable ---

    def test_unknown_category(self):
        result = classify_category(
            raw_category=None,
            tags=[],
            title="Something completely unrelated",
        )
        assert result.category is None
        assert result.is_excluded is False
        assert result.classification_method == "unclassified"

    # --- Confidence levels ---

    def test_api_match_highest_confidence(self):
        result = classify_category(raw_category="politics")
        assert result.confidence == 1.0

    def test_tag_match_high_confidence(self):
        result = classify_category(tags=["election"])
        assert result.confidence == 0.9

    def test_slug_match_medium_confidence(self):
        result = classify_category(slug="presidential-election-2026")
        assert result.confidence == 0.85

    def test_title_match_lower_confidence(self):
        result = classify_category(title="Who will be the next president?")
        assert result.confidence == 0.75


# ============================================================
# 2. Hard Eligibility Rules Tests
# ============================================================


class TestHardRules:
    """Test all 8 hard eligibility rule checks."""

    def test_all_rules_pass_valid_market(self):
        market = _make_market()
        result = check_all_hard_rules(market)
        assert result.all_passed is True
        assert len(result.results) == 8

    # Rule 1: Market active
    def test_inactive_market_rejected(self):
        market = _make_market(is_active=False)
        result = check_all_hard_rules(market)
        assert result.all_passed is False
        assert any(
            r.reason_code == EligibilityReasonCode.MARKET_NOT_ACTIVE
            for r in result.results if not r.passed
        )

    # Rule 2: Wording check
    def test_malformed_title_rejected(self):
        market = _make_market(title="xy")
        result = check_all_hard_rules(market)
        assert any(
            r.reason_code == EligibilityReasonCode.WORDING_MALFORMED
            for r in result.results if not r.passed
        )

    def test_garbled_title_rejected(self):
        market = _make_market(title="!!!@@@###$$$%%%^^^&&&***")
        result = check_all_hard_rules(market)
        assert any(
            r.reason_code == EligibilityReasonCode.WORDING_MALFORMED
            for r in result.results if not r.passed
        )

    def test_all_caps_title_rejected(self):
        market = _make_market(title="WILL THE PRESIDENT SIGN THE BILL INTO LAW")
        result = check_all_hard_rules(market)
        assert any(
            r.reason_code == EligibilityReasonCode.WORDING_MALFORMED
            for r in result.results if not r.passed
        )

    # Rule 3: Resolution source
    def test_no_resolution_source_rejected(self):
        market = _make_market(resolution_source=None)
        result = check_all_hard_rules(market)
        assert any(
            r.reason_code == EligibilityReasonCode.NO_RESOLUTION_SOURCE
            for r in result.results if not r.passed
        )

    def test_empty_resolution_source_rejected(self):
        market = _make_market(resolution_source="")
        result = check_all_hard_rules(market)
        assert any(
            r.reason_code == EligibilityReasonCode.NO_RESOLUTION_SOURCE
            for r in result.results if not r.passed
        )

    # Rule 4: Horizon
    def test_horizon_too_short_rejected(self):
        market = _make_market(end_date=datetime.now(tz=UTC) + timedelta(hours=12))
        result = check_all_hard_rules(market)
        assert any(
            r.reason_code == EligibilityReasonCode.HORIZON_TOO_SHORT
            for r in result.results if not r.passed
        )

    def test_horizon_too_long_rejected(self):
        market = _make_market(end_date=datetime.now(tz=UTC) + timedelta(days=180))
        result = check_all_hard_rules(market)
        assert any(
            r.reason_code == EligibilityReasonCode.HORIZON_TOO_LONG
            for r in result.results if not r.passed
        )

    def test_no_end_date_passes(self):
        """Markets without end dates should pass horizon check."""
        market = _make_market(end_date=None)
        result = check_all_hard_rules(market)
        horizon_result = next(r for r in result.results if r.rule_name == "horizon_check")
        assert horizon_result.passed is True

    # Rule 5: Liquidity
    def test_low_liquidity_rejected(self):
        market = _make_market(liquidity_usd=100.0)
        result = check_all_hard_rules(market)
        assert any(
            r.reason_code == EligibilityReasonCode.INSUFFICIENT_LIQUIDITY
            for r in result.results if not r.passed
        )

    def test_no_liquidity_data_rejected(self):
        market = _make_market(liquidity_usd=None)
        result = check_all_hard_rules(market)
        assert any(
            r.reason_code == EligibilityReasonCode.INSUFFICIENT_LIQUIDITY
            for r in result.results if not r.passed
        )

    # Rule 6: Spread
    def test_wide_spread_rejected(self):
        market = _make_market(spread=0.25, best_bid=0.40, best_ask=0.65)
        result = check_all_hard_rules(market)
        assert any(
            r.reason_code == EligibilityReasonCode.SPREAD_TOO_WIDE
            for r in result.results if not r.passed
        )

    def test_spread_computed_from_bid_ask(self):
        """When spread is None, should compute from bid/ask."""
        market = _make_market(spread=None, best_bid=0.50, best_ask=0.52)
        result = check_all_hard_rules(market)
        spread_result = next(r for r in result.results if r.rule_name == "spread_check")
        assert spread_result.passed is True

    # Rule 7: Depth
    def test_no_depth_with_liquidity_passes(self):
        """No depth levels but sufficient liquidity should pass."""
        market = _make_market(depth_levels=None, liquidity_usd=5000.0)
        result = check_all_hard_rules(market)
        depth_result = next(r for r in result.results if r.rule_name == "depth_check")
        assert depth_result.passed is True

    def test_insufficient_depth_rejected(self):
        market = _make_market(
            depth_levels=[{"price": 0.54, "size": 10}],
            liquidity_usd=5000.0,
        )
        result = check_all_hard_rules(market)
        depth_result = next(r for r in result.results if r.rule_name == "depth_check")
        assert depth_result.passed is False

    # Rule 8: Duplicate cluster
    def test_duplicate_cluster_rejected(self):
        market = _make_market(
            market_event_cluster_id="cluster-abc",
            held_event_cluster_ids={"cluster-abc", "cluster-xyz"},
        )
        result = check_all_hard_rules(market)
        assert any(
            r.reason_code == EligibilityReasonCode.DUPLICATE_EVENT_CLUSTER
            for r in result.results if not r.passed
        )

    def test_no_cluster_overlap_passes(self):
        market = _make_market(
            market_event_cluster_id="cluster-new",
            held_event_cluster_ids={"cluster-abc", "cluster-xyz"},
        )
        result = check_all_hard_rules(market)
        cluster_result = next(r for r in result.results if r.rule_name == "duplicate_cluster")
        assert cluster_result.passed is True

    # Custom config
    def test_custom_config_thresholds(self):
        """Custom config should override default thresholds."""
        config = EligibilityConfig(
            min_liquidity_usd=10000.0,
            max_spread=0.01,
        )
        market = _make_market(liquidity_usd=5000.0, spread=0.02)
        result = check_all_hard_rules(market, config)
        assert result.all_passed is False

    def test_result_contains_threshold_values(self):
        """Rule results should include threshold and actual values."""
        market = _make_market(liquidity_usd=100.0)
        result = check_all_hard_rules(market)
        liq_result = next(r for r in result.results if r.rule_name == "liquidity_check")
        assert liq_result.threshold_value == 500.0
        assert liq_result.actual_value == 100.0


# ============================================================
# 3. Sports Quality Gate Tests
# ============================================================


class TestSportsQualityGate:
    """Test the five-criteria Sports Quality Gate."""

    def _make_gate_input(self, **overrides) -> SportsGateInput:
        defaults = dict(
            title="Will the Lakers win the NBA Championship 2026?",
            description="Key injury updates for the Lakers. Matchup analysis vs Celtics.",
            category="sports",
            resolution_source="Official NBA results",
            end_date=datetime.now(tz=UTC) + timedelta(days=60),
            liquidity_usd=5000.0,
            spread=0.02,
            tags=["nba", "basketball"],
        )
        defaults.update(overrides)
        return SportsGateInput(**defaults)

    def test_valid_sports_market_passes(self):
        result = evaluate_sports_gate(self._make_gate_input())
        assert result.all_criteria_passed is True
        assert result.size_multiplier == 0.7

    def test_size_multiplier_is_reduced(self):
        """Sports markets should have a 0.7 size multiplier."""
        result = evaluate_sports_gate(self._make_gate_input())
        assert result.size_multiplier == 0.7
        assert result.size_multiplier < 1.0

    def test_non_objective_resolution_fails(self):
        result = evaluate_sports_gate(
            self._make_gate_input(
                title="Will fans enjoy the game?",
                description="A fun game to watch",
            )
        )
        assert result.resolution_fully_objective is False
        assert result.all_criteria_passed is False

    def test_short_horizon_fails(self):
        result = evaluate_sports_gate(
            self._make_gate_input(
                end_date=datetime.now(tz=UTC) + timedelta(hours=12),
            )
        )
        assert result.resolves_in_48h_plus is False
        assert result.all_criteria_passed is False

    def test_no_end_date_fails_horizon(self):
        result = evaluate_sports_gate(
            self._make_gate_input(end_date=None)
        )
        assert result.resolves_in_48h_plus is False

    def test_low_liquidity_fails(self):
        result = evaluate_sports_gate(
            self._make_gate_input(liquidity_usd=100.0)
        )
        assert result.adequate_liquidity_and_depth is False

    def test_statistical_modeling_fails(self):
        result = evaluate_sports_gate(
            self._make_gate_input(
                title="Lakers vs Celtics: Over/Under 220.5 total points",
                description="Point spread and total points prop bet",
            )
        )
        assert result.not_statistical_modeling is False

    def test_failed_gate_zero_multiplier(self):
        """Failed sports gate should set size multiplier to 0."""
        result = evaluate_sports_gate(
            self._make_gate_input(
                title="Will fans enjoy the game?",
                description="Sentiment contest",
            )
        )
        assert result.size_multiplier == 0.0

    def test_rejection_reasons_populated(self):
        result = evaluate_sports_gate(
            self._make_gate_input(
                title="Will fans enjoy the game?",
                description="Sentiment contest",
                liquidity_usd=10.0,
            )
        )
        assert len(result.rejection_reasons) >= 2


# ============================================================
# 4. Market Profile Filter Tests
# ============================================================


class TestMarketProfile:
    """Test preferred market profile evaluation."""

    def test_good_market_passes_all(self):
        market = _make_market()
        result = evaluate_market_profile(market)
        assert result.objectively_resolvable is True
        assert result.liquid_enough is True

    def test_no_resolution_source_fails(self):
        market = _make_market(resolution_source=None)
        result = evaluate_market_profile(market)
        assert result.objectively_resolvable is False

    def test_sentiment_contest_detected(self):
        market = _make_market(
            title="What is the public opinion on the new sentiment popularity?",
            description="Approval rating and favorability tracking",
        )
        result = evaluate_market_profile(market)
        assert result.not_reflexive_sentiment is False

    def test_latency_market_detected(self):
        market = _make_market(
            title="First to announce breaking news within minutes",
            description="Real-time result tracking",
        )
        result = evaluate_market_profile(market)
        assert result.not_latency_dominated is False

    def test_low_liquidity_detected(self):
        market = _make_market(liquidity_usd=50.0)
        result = evaluate_market_profile(market)
        assert result.liquid_enough is False


# ============================================================
# 5. Edge Discovery Scoring Tests
# ============================================================


class TestEdgeDiscoveryScoring:
    """Test edge discovery focus scoring."""

    def test_niche_market_high_score(self):
        market = _make_market(
            title="Will the Senate subcommittee approve the amendment during the scheduled hearing?",
            description="Committee markup on regulatory rulemaking, deadline approaching",
            volume_24h=500.0,
        )
        score = score_edge_discovery(market)
        assert score.final_score >= 0.3
        assert score.domain_barrier_score > 0
        assert score.niche_score > 0

    def test_major_election_low_score(self):
        market = _make_market(
            title="Who will win the presidential election 2028?",
            description="The general election winner of the president of the United States",
            volume_24h=100_000,
        )
        score = score_edge_discovery(market)
        assert score.final_score < 0.2
        assert score.efficiency_penalty > 0

    def test_high_volume_penalized(self):
        market_low = _make_market(volume_24h=500.0)
        market_high = _make_market(volume_24h=100_000)

        score_low = score_edge_discovery(market_low)
        score_high = score_edge_discovery(market_high)

        assert score_low.efficiency_penalty < score_high.efficiency_penalty

    def test_score_in_valid_range(self):
        market = _make_market()
        score = score_edge_discovery(market)
        assert 0.0 <= score.final_score <= 1.0

    def test_clinical_trial_has_domain_barrier(self):
        market = _make_market(
            title="Will the Phase III clinical trial meet its primary endpoint?",
            description="Biomarker data from expedited review",
        )
        score = score_edge_discovery(market)
        assert score.domain_barrier_score > 0


# ============================================================
# 6. Eligibility Engine — Full Pipeline Tests
# ============================================================


class TestEligibilityEngine:
    """Test the full eligibility pipeline orchestration."""

    def setup_method(self):
        self.engine = EligibilityEngine()

    # --- Excluded categories rejected ---

    def test_crypto_market_rejected(self):
        market = _make_market(
            category_raw="crypto",
            title="Will Bitcoin reach $100k?",
            tags=["cryptocurrency"],
        )
        result = self.engine.evaluate(market)
        assert result.outcome == "reject"
        assert result.reason_code == EligibilityReasonCode.EXCLUDED_CATEGORY.value

    def test_news_rejected(self):
        market = _make_market(category_raw="news")
        result = self.engine.evaluate(market)
        assert result.outcome == "reject"
        assert result.reason_code == EligibilityReasonCode.EXCLUDED_CATEGORY.value

    def test_culture_rejected(self):
        market = _make_market(category_raw="culture")
        result = self.engine.evaluate(market)
        assert result.outcome == "reject"

    def test_weather_rejected(self):
        market = _make_market(category_raw="weather")
        result = self.engine.evaluate(market)
        assert result.outcome == "reject"

    # --- Unknown category rejected ---

    def test_unknown_category_rejected(self):
        market = _make_market(
            category_raw=None,
            tags=[],
            slug=None,
            title="Something completely unclassifiable here",
        )
        result = self.engine.evaluate(market)
        assert result.outcome == "reject"
        assert result.reason_code == EligibilityReasonCode.UNKNOWN_CATEGORY.value

    # --- Hard rules pipeline ---

    def test_inactive_market_rejected_before_profile(self):
        market = _make_market(is_active=False)
        result = self.engine.evaluate(market)
        assert result.outcome == "reject"
        assert result.reason_code == EligibilityReasonCode.MARKET_NOT_ACTIVE.value
        # Profile and edge should not be computed on rejection
        assert result.market_profile_score is None
        assert result.edge_discovery_score is None

    def test_no_resolution_rejected(self):
        market = _make_market(resolution_source=None)
        result = self.engine.evaluate(market)
        assert result.outcome == "reject"

    def test_low_liquidity_rejected(self):
        market = _make_market(liquidity_usd=50.0)
        result = self.engine.evaluate(market)
        assert result.outcome == "reject"
        assert result.reason_code == EligibilityReasonCode.INSUFFICIENT_LIQUIDITY.value

    # --- Sports gate pipeline ---

    def test_valid_sports_market_passes(self):
        market = _make_sports_market()
        result = self.engine.evaluate(market)
        assert result.outcome != "reject"
        assert result.sports_gate_result is not None
        assert result.sports_gate_result.all_criteria_passed is True
        assert result.category_quality_tier == "quality_gated"

    def test_sports_statistical_modeling_rejected(self):
        market = _make_sports_market(
            title="Lakers vs Celtics: Over/Under 220.5 total points spread",
            description="Point spread prop bet total points over under",
        )
        result = self.engine.evaluate(market)
        assert result.outcome == "reject"
        assert result.reason_code == EligibilityReasonCode.SPORTS_GATE_FAILED.value

    # --- Full qualifying pipeline ---

    def test_good_market_passes_full_pipeline(self):
        market = _make_market()
        result = self.engine.evaluate(market)
        assert result.outcome in ("trigger_eligible", "investigate_now", "watchlist")
        assert result.category_classification.category == "science_health"
        assert result.hard_rules_result is not None
        assert result.hard_rules_result.all_passed is True
        assert result.market_profile_score is not None
        assert result.edge_discovery_score is not None

    def test_niche_market_scores_high(self):
        market = _make_market(
            title="Will the Senate subcommittee approve the FDA rulemaking amendment?",
            description="Committee markup deadline phase III clinical endpoint review",
            category_raw="science",
            tags=["health", "fda"],
            volume_24h=500.0,
        )
        result = self.engine.evaluate(market)
        assert result.outcome in ("trigger_eligible", "investigate_now")

    # --- Result metadata ---

    def test_result_has_rule_version(self):
        market = _make_market()
        result = self.engine.evaluate(market)
        assert result.rule_version == "1.0.0"

    def test_result_has_timestamp(self):
        market = _make_market()
        result = self.engine.evaluate(market)
        assert result.evaluated_at is not None

    # --- Batch evaluation ---

    def test_batch_evaluation(self):
        markets = [
            _make_market(market_id=f"batch-{i}") for i in range(5)
        ]
        results = self.engine.evaluate_batch(markets)
        assert len(results) == 5
        for r in results:
            assert r.outcome in ("reject", "watchlist", "trigger_eligible", "investigate_now")

    # --- Custom config ---

    def test_custom_config_used(self):
        config = EligibilityConfig(
            min_liquidity_usd=100_000.0,
        )
        engine = EligibilityEngine(config=config)
        market = _make_market(liquidity_usd=5000.0)
        result = engine.evaluate(market)
        assert result.outcome == "reject"
        assert result.reason_code == EligibilityReasonCode.INSUFFICIENT_LIQUIDITY.value


# ============================================================
# 7. Acceptance Criteria Tests
# ============================================================


class TestAcceptanceCriteria:
    """Validate spec acceptance criteria from Phase 4."""

    def setup_method(self):
        self.engine = EligibilityEngine()

    def test_excluded_categories_never_reach_investigation(self):
        """Excluded categories must NEVER produce trigger_eligible or investigate_now."""
        excluded_markets = [
            _make_market(category_raw="crypto", market_id="crypto-1"),
            _make_market(category_raw="news", market_id="news-1"),
            _make_market(category_raw="culture", market_id="culture-1"),
            _make_market(category_raw="entertainment", market_id="ent-1"),
            _make_market(category_raw="weather", market_id="weather-1"),
            _make_market(
                category_raw=None,
                tags=["cryptocurrency"],
                market_id="crypto-tag-1",
            ),
            _make_market(
                category_raw=None,
                tags=[],
                slug=None,
                title="Will Bitcoin crash?",
                market_id="crypto-title-1",
            ),
        ]

        for market in excluded_markets:
            result = self.engine.evaluate(market)
            assert result.outcome == "reject", (
                f"Market {market.market_id} with excluded category "
                f"should be rejected but got {result.outcome}"
            )

    def test_malformed_contracts_rejected_before_llm(self):
        """Malformed/ambiguous contracts must be rejected at hard rules, before any LLM use."""
        malformed_markets = [
            _make_market(title="x", market_id="short-1"),
            _make_market(title="!!!###$$$", market_id="garbled-1"),
            _make_market(resolution_source=None, market_id="no-source-1"),
            _make_market(is_active=False, market_id="inactive-1"),
        ]

        for market in malformed_markets:
            result = self.engine.evaluate(market)
            assert result.outcome == "reject", (
                f"Malformed market {market.market_id} should be rejected"
            )
            # No profile or edge score computed (no LLM reached)
            assert result.market_profile_score is None or result.edge_discovery_score is None

    def test_sports_markets_carry_quality_gate(self):
        """Sports markets must have a SportsQualityGateResult record."""
        market = _make_sports_market()
        result = self.engine.evaluate(market)
        assert result.sports_gate_result is not None
        assert result.category_quality_tier == "quality_gated"

    def test_markets_with_insufficient_depth_rejected(self):
        """Markets with insufficient depth are rejected at intake."""
        market = _make_market(
            depth_levels=[{"price": 0.54, "size": 5}],
            liquidity_usd=5000.0,
        )
        result = self.engine.evaluate(market)
        assert result.outcome == "reject"

    def test_all_decisions_have_reason_codes_and_timestamps(self):
        """Every decision must have a reason code and timestamp."""
        test_cases = [
            _make_market(market_id="test-pass"),
            _make_market(market_id="test-crypto", category_raw="crypto"),
            _make_market(market_id="test-inactive", is_active=False),
            _make_sports_market(market_id="test-sports"),
        ]

        for market in test_cases:
            result = self.engine.evaluate(market)
            assert result.reason_code, f"Missing reason code for {market.market_id}"
            assert result.evaluated_at is not None, f"Missing timestamp for {market.market_id}"
            assert result.rule_version, f"Missing rule version for {market.market_id}"

    def test_category_quality_tiers_assigned(self):
        """Standard and quality-gated tiers must be correctly assigned."""
        # Standard tier
        standard = _make_market(category_raw="politics")
        result_standard = self.engine.evaluate(standard)
        if result_standard.outcome != "reject":
            assert result_standard.category_quality_tier == "standard"

        # Quality-gated tier
        sports = _make_sports_market()
        result_sports = self.engine.evaluate(sports)
        if result_sports.outcome != "reject":
            assert result_sports.category_quality_tier == "quality_gated"

    def test_no_llm_calls_in_pipeline(self):
        """The entire eligibility pipeline is Tier D (no LLM)."""
        # This is a structural test — we verify no import of any LLM/agent module
        from eligibility import engine, hard_rules, category_classifier
        from eligibility import sports_quality_gate, market_profile, edge_scoring

        # Check module source doesn't reference LLM-related imports
        for mod in [engine, hard_rules, category_classifier, 
                    sports_quality_gate, market_profile, edge_scoring]:
            source = open(mod.__file__).read()
            assert "from agents" not in source, (
                f"{mod.__name__} imports from agents (LLM)"
            )
            assert "anthropic" not in source.lower() or "api_key" not in source.lower()
