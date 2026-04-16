"""Phase 9: Investigation Engine & Thesis Cards — comprehensive tests.

Tests cover:
1. Investigation types and runtime models
2. Entry impact calculator (Tier D, deterministic)
3. Base-rate system (Tier D, deterministic)
4. Candidate rubric scoring (Tier D, deterministic)
5. Domain manager agents (structure and factory)
6. Research pack agents (structure)
7. Thesis card builder (assembly from sub-outputs)
8. Net edge calculation
9. Investigation orchestrator (full pipeline with mocked LLM calls)
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from market_data.types import OrderBookLevel

# --- Types ---
from investigation.types import (
    BaseRateResult,
    CalibrationSourceStatus,
    CandidateContext,
    CandidateRubricScore,
    DomainMemo,
    EntryImpactResult,
    EntryUrgency,
    EvidenceItem,
    InvestigationMode,
    InvestigationOutcome,
    InvestigationRequest,
    InvestigationResult,
    NetEdgeCalculation,
    NoTradeResult,
    ResearchPackResult,
    SizeBand,
    ThesisCardData,
)

# --- Deterministic components ---
from investigation.entry_impact import EntryImpactCalculator
from investigation.base_rate import BaseRateSystem
from investigation.rubric import (
    CandidateRubric,
    MIN_COMPOSITE_FOR_ACCEPTANCE,
    MIN_COMPOSITE_FOR_OPUS,
    STRONG_CANDIDATE_THRESHOLD,
)

# --- Agent components ---
from investigation.domain_managers import (
    DOMAIN_MANAGERS,
    BaseDomainManager,
    GeopoliticsDomainManager,
    MacroPolicyDomainManager,
    PoliticsDomainManager,
    ScienceHealthDomainManager,
    SportsDomainManager,
    TechnologyDomainManager,
    get_domain_manager_class,
)
from investigation.research_agents import (
    CounterCaseAgent,
    DataCrossCheckAgent,
    EvidenceResearchAgent,
    MarketStructureAgent,
    ResolutionReviewAgent,
    SentimentDriftAgent,
    SourceReliabilityAgent,
    TimingCatalystAgent,
)

# --- Builders ---
from investigation.thesis_builder import ThesisCardBuilder

# --- Orchestrator ---
from investigation.orchestrator import InvestigationOrchestrator


# ============================================================
# Test Fixtures
# ============================================================

@pytest.fixture
def sample_ask_levels() -> list[OrderBookLevel]:
    """Sorted ask levels for entry impact tests."""
    return [
        OrderBookLevel(price=0.55, size=500),
        OrderBookLevel(price=0.56, size=400),
        OrderBookLevel(price=0.57, size=300),
        OrderBookLevel(price=0.58, size=200),
        OrderBookLevel(price=0.60, size=100),
    ]


@pytest.fixture
def sample_candidate() -> CandidateContext:
    """A realistic candidate context for testing."""
    return CandidateContext(
        market_id="mkt-001",
        token_id="tok-001",
        title="Will the Federal Reserve cut interest rates in June 2026?",
        description="Resolves YES if the Federal Reserve reduces the federal funds rate target.",
        category="macro_policy",
        category_quality_tier="standard",
        tags=["fed", "interest-rates", "macro"],
        price=0.45,
        best_bid=0.44,
        best_ask=0.46,
        spread=0.02,
        mid_price=0.45,
        visible_depth_usd=5000.0,
        volume_24h=25000.0,
        eligibility_outcome="trigger_eligible",
        edge_discovery_score=0.55,
        trigger_class="repricing",
        trigger_level="C",
        trigger_reason="10% price move in 4 hours",
        resolution_source="Federal Reserve FOMC statement",
        end_date=datetime.now(tz=UTC) + timedelta(days=45),
        end_date_hours=1080.0,
    )


@pytest.fixture
def sample_domain_memo() -> DomainMemo:
    """A domain memo recommending proceeding."""
    return DomainMemo(
        category="macro_policy",
        market_id="mkt-001",
        summary="The FOMC meeting is approaching with mixed economic signals. "
                "Recent employment data suggests softening labor market. "
                "Market may be underpricing the probability of a rate cut.",
        key_findings=[
            "Unemployment ticked up to 4.2% in March",
            "Core PCE inflation has been declining for 3 months",
            "Fed dot plot suggests 2 cuts in 2026",
        ],
        concerns=[
            "Services inflation remains sticky",
            "Market is heavily covered by macro analysts",
        ],
        recommended_proceed=True,
        optional_agents_justified=[],
        confidence_level="medium",
    )


@pytest.fixture
def sample_research_pack() -> ResearchPackResult:
    """Pre-built research pack result."""
    return ResearchPackResult(
        evidence=[
            EvidenceItem(
                content="BLS report shows unemployment at 4.2%",
                source="Bureau of Labor Statistics",
                freshness="fresh",
                relevance_score=0.9,
            ),
            EvidenceItem(
                content="Core PCE fell to 2.4% in March",
                source="BEA",
                freshness="fresh",
                relevance_score=0.85,
            ),
            EvidenceItem(
                content="Fed Chair testimony hinted at easing",
                source="Congressional testimony",
                freshness="recent",
                relevance_score=0.75,
            ),
        ],
        counter_case={
            "strongest_arguments_against": [
                "Services inflation remains at 3.5%",
                "Risk of inflating asset prices further",
            ],
            "evidence_gaps": ["Recent tariff uncertainty"],
            "strength_score": 0.4,
        },
        resolution_review={
            "clarity_score": 0.9,
            "has_named_source": True,
            "has_deadline": True,
            "has_ambiguous_wording": False,
            "ambiguity_flags": [],
            "resolution_interpretation": "FOMC statement will indicate rate decision",
        },
        timing_assessment={
            "expected_catalyst": "June FOMC meeting",
            "expected_time_horizon": "weeks",
            "expected_time_horizon_hours": 720,
            "timing_clarity_score": 0.85,
            "time_pressure": "low",
        },
        market_structure={
            "metrics": {
                "price": 0.45,
                "spread": 0.02,
                "depth_usd": 5000,
                "spread_quality": "excellent",
            },
            "summary": "Well-structured market with tight spreads and adequate depth.",
        },
        total_research_cost_usd=0.08,
        agents_invoked=["evidence_research", "counter_case", "resolution_review",
                        "timing_catalyst", "market_structure_summary"],
    )


@pytest.fixture
def sample_entry_impact() -> EntryImpactResult:
    """Pre-built entry impact result."""
    return EntryImpactResult(
        estimated_impact_bps=5.0,
        levels_consumed=2,
        total_fill_size_usd=600.0,
        avg_fill_price=0.5503,
        reference_price=0.55,
    )


@pytest.fixture
def sample_base_rate() -> BaseRateResult:
    """Pre-built base rate result."""
    return BaseRateResult(
        base_rate=0.50,
        market_type="macro_policy_rate_decision",
        category="macro_policy",
        sample_size=0,
        confidence_level="none",
        source="system_defaults",
        deviation_from_estimate=0.10,
    )


@pytest.fixture
def sample_rubric_score() -> CandidateRubricScore:
    """Pre-built rubric score above acceptance threshold."""
    score = CandidateRubricScore(
        evidence_quality=0.8,
        evidence_diversity=0.6,
        evidence_freshness=0.85,
        resolution_clarity=0.9,
        market_structure_quality=0.7,
        timing_clarity=0.85,
        counter_case_strength=0.4,
        ambiguity_level=0.1,
        expected_gross_edge=0.10,
        cluster_correlation_burden=0.1,
        category_quality_tier="standard",
        base_rate=0.50,
        market_implied_probability=0.45,
        entry_impact_estimate_bps=5.0,
        liquidity_adjusted_max_size_usd=600.0,
    )
    score.compute_composite()
    return score


@pytest.fixture
def sample_net_edge() -> NetEdgeCalculation:
    """Pre-built net edge calculation."""
    return NetEdgeCalculation(
        gross_edge=0.10,
        friction_adjusted_edge=0.09,
        impact_adjusted_edge=0.085,
        net_edge_after_cost=0.084,
    )


# ============================================================
# 1. Investigation Types Tests
# ============================================================

class TestInvestigationTypes:
    """Validate all investigation types construct and compute correctly."""

    def test_entry_impact_result_defaults(self):
        r = EntryImpactResult()
        assert r.estimated_impact_bps == 0.0
        assert r.levels_consumed == 0
        assert r.computed_at is not None

    def test_base_rate_result_defaults(self):
        r = BaseRateResult()
        assert r.base_rate == 0.5
        assert r.confidence_level == "none"
        assert r.source == "default"

    def test_evidence_item_construction(self):
        e = EvidenceItem(content="Test evidence", source="test", relevance_score=0.8)
        assert e.freshness == "unknown"
        assert e.url is None

    def test_domain_memo_construction(self):
        m = DomainMemo(category="politics", market_id="m1")
        assert m.recommended_proceed is False
        assert m.proceed_blocker_code is None
        assert m.proceed_blocker_detail is None
        assert m.confidence_level == "low"

    def test_research_pack_defaults(self):
        r = ResearchPackResult()
        assert len(r.evidence) == 0
        assert r.total_research_cost_usd == 0.0

    def test_candidate_context_defaults(self):
        c = CandidateContext(market_id="m1")
        assert c.category_quality_tier == "standard"
        assert c.urgency_rank == 0

    def test_thesis_card_data_full_fields(self):
        card = ThesisCardData(
            market_id="m1",
            workflow_run_id="wf-1",
            category="politics",
            proposed_side="yes",
            resolution_interpretation="Resolves YES if...",
            core_thesis="Market underprices probability",
            why_mispriced="Information asymmetry",
            supporting_evidence=[{"content": "A"}],
            opposing_evidence=[{"content": "B"}],
            invalidation_conditions=["If X happens"],
            gross_edge=0.10,
            net_edge_after_cost=0.08,
        )
        assert card.market_id == "m1"
        assert card.gross_edge == 0.10

    def test_no_trade_result(self):
        r = NoTradeResult(reason="No edge", reason_code="no_edge", stage="rubric")
        assert r.cost_spent_usd == 0.0

    def test_investigation_request(self):
        req = InvestigationRequest(
            workflow_run_id="wf-001",
            mode=InvestigationMode.SCHEDULED_SWEEP,
        )
        assert req.max_candidates == 3

    def test_investigation_result_properties(self):
        r = InvestigationResult(
            workflow_run_id="wf-001",
            mode=InvestigationMode.TRIGGER_BASED,
            outcome=InvestigationOutcome.NO_TRADE,
        )
        assert r.is_no_trade is True
        assert r.has_accepted_candidates is False


# ============================================================
# 2. Net Edge Calculation Tests
# ============================================================

class TestNetEdgeCalculation:
    """Verify the four-level net edge distinction per spec Section 14.3."""

    def test_viable_edge(self):
        edge = NetEdgeCalculation(
            gross_edge=0.10,
            friction_adjusted_edge=0.09,
            impact_adjusted_edge=0.08,
            net_edge_after_cost=0.07,
        )
        assert edge.is_viable is True
        assert edge.is_cost_efficient is True

    def test_non_viable_edge(self):
        edge = NetEdgeCalculation(
            gross_edge=0.05,
            friction_adjusted_edge=0.03,
            impact_adjusted_edge=0.001,  # below 0.2% paper-mode threshold
            net_edge_after_cost=0.0005,
        )
        assert edge.is_viable is False

    def test_cost_inefficient_edge(self):
        edge = NetEdgeCalculation(
            gross_edge=0.10,
            friction_adjusted_edge=0.08,
            impact_adjusted_edge=0.06,
            net_edge_after_cost=-0.01,  # negative after cost
        )
        assert edge.is_cost_efficient is False

    def test_zero_edge(self):
        edge = NetEdgeCalculation()
        assert edge.is_viable is False
        assert edge.is_cost_efficient is False


# ============================================================
# 3. Entry Impact Calculator Tests (Tier D)
# ============================================================

class TestEntryImpactCalculator:
    """Entry impact calculator — deterministic order book walking."""

    def test_empty_levels(self):
        calc = EntryImpactCalculator()
        result = calc.compute(ask_levels=[], order_size_usd=100.0)
        assert result.estimated_impact_bps == 0.0
        assert result.levels_consumed == 0

    def test_zero_order_size(self):
        calc = EntryImpactCalculator()
        levels = [OrderBookLevel(price=0.50, size=100)]
        result = calc.compute(ask_levels=levels, order_size_usd=0.0)
        assert result.estimated_impact_bps == 0.0

    def test_single_level_no_impact(self):
        calc = EntryImpactCalculator()
        levels = [OrderBookLevel(price=0.50, size=1000)]
        result = calc.compute(ask_levels=levels, order_size_usd=50.0)
        # All fills at same price → 0 impact
        assert result.estimated_impact_bps == 0.0
        assert result.levels_consumed == 1
        assert result.reference_price == 0.50

    def test_multi_level_impact(self, sample_ask_levels):
        calc = EntryImpactCalculator()
        result = calc.compute(ask_levels=sample_ask_levels, order_size_usd=500.0)
        # Walking the book: fills spread across multiple levels
        assert result.estimated_impact_bps > 0
        assert result.levels_consumed >= 1
        assert result.reference_price == 0.55
        assert result.avg_fill_price >= 0.55

    def test_large_order_exhausts_book(self, sample_ask_levels):
        calc = EntryImpactCalculator()
        total_book_value = sum(l.price * l.size for l in sample_ask_levels)
        result = calc.compute(
            ask_levels=sample_ask_levels,
            order_size_usd=total_book_value * 2,
        )
        assert result.levels_consumed == 5
        assert result.remaining_unfilled_usd > 0

    def test_impact_as_edge_fraction(self):
        calc = EntryImpactCalculator()
        # 50 bps impact with 0.10 (10%) gross edge
        fraction = calc.impact_as_edge_fraction(50.0, 0.10)
        # 50bps = 0.005 / 0.10 = 0.05 = 5%
        assert abs(fraction - 0.05) < 0.001

    def test_impact_as_edge_fraction_zero_edge(self):
        calc = EntryImpactCalculator()
        fraction = calc.impact_as_edge_fraction(50.0, 0.0)
        assert fraction == float("inf")

    def test_impact_as_edge_fraction_zero_impact(self):
        calc = EntryImpactCalculator()
        fraction = calc.impact_as_edge_fraction(0.0, 0.10)
        assert fraction == 0.0

    def test_negative_or_zero_price_levels(self):
        calc = EntryImpactCalculator()
        levels = [
            OrderBookLevel(price=0.0, size=100),
            OrderBookLevel(price=-0.5, size=100),
        ]
        result = calc.compute(ask_levels=levels, order_size_usd=50.0)
        assert result.estimated_impact_bps == 0.0

    def test_deterministic_reproducibility(self, sample_ask_levels):
        """Same input → same output (deterministic guarantee)."""
        calc = EntryImpactCalculator()
        r1 = calc.compute(ask_levels=sample_ask_levels, order_size_usd=300.0)
        r2 = calc.compute(ask_levels=sample_ask_levels, order_size_usd=300.0)
        assert r1.estimated_impact_bps == r2.estimated_impact_bps
        assert r1.levels_consumed == r2.levels_consumed
        assert r1.avg_fill_price == r2.avg_fill_price


# ============================================================
# 4. Base-Rate System Tests (Tier D)
# ============================================================

class TestBaseRateSystem:
    """Base-rate reference system — historical resolution rate lookup."""

    def test_default_rate_for_unknown_category(self):
        system = BaseRateSystem()
        result = system.lookup("nonexistent_category")
        assert result.base_rate == 0.5
        assert result.market_type == "unknown"
        assert result.source == "default"

    def test_specific_category_lookup(self):
        system = BaseRateSystem()
        result = system.lookup("politics", "election")
        assert result.base_rate == 0.50
        assert result.market_type == "politics_election"

    def test_general_category_fallback(self):
        system = BaseRateSystem()
        result = system.lookup("politics", "unknown_sub")
        assert result.market_type == "politics_general"
        assert result.base_rate == 0.50

    def test_clinical_trial_base_rate(self):
        system = BaseRateSystem()
        result = system.lookup("science_health", "clinical_trial")
        assert result.base_rate == 0.30  # most trials fail

    def test_sports_record_base_rate(self):
        system = BaseRateSystem()
        result = system.lookup("sports", "record")
        assert result.base_rate == 0.20  # records are rare

    def test_legislation_base_rate(self):
        system = BaseRateSystem()
        result = system.lookup("politics", "legislation")
        assert result.base_rate == 0.35  # most bills fail

    def test_deviation_computation(self):
        system = BaseRateSystem()
        result = system.lookup("politics", "election", system_estimate=0.65)
        assert result.deviation_from_estimate == 0.15  # 0.65 - 0.50

    def test_deviation_negative(self):
        system = BaseRateSystem()
        result = system.lookup("science_health", "clinical_trial", system_estimate=0.20)
        assert result.deviation_from_estimate == -0.10  # 0.20 - 0.30

    def test_custom_rates_override(self):
        system = BaseRateSystem(custom_rates={"politics_election": 0.60})
        result = system.lookup("politics", "election")
        assert result.base_rate == 0.60

    def test_confidence_thresholds(self):
        # With 0 samples, confidence is "none"
        system = BaseRateSystem()
        result = system.lookup("politics")
        assert result.confidence_level == "none"
        assert result.sample_size == 0

    def test_infer_subcategory_politics(self):
        system = BaseRateSystem()
        assert system.infer_subcategory("Will Biden win the 2026 election?", "politics") == "election"
        assert system.infer_subcategory("Will Congress pass the infrastructure bill?", "politics") == "legislation"

    def test_infer_subcategory_sports(self):
        system = BaseRateSystem()
        assert system.infer_subcategory("Will Team A win vs Team B?", "sports") == "match_outcome"
        assert system.infer_subcategory("Will player X break the all-time record?", "sports") == "record"

    def test_infer_subcategory_science(self):
        system = BaseRateSystem()
        assert system.infer_subcategory("Will the Phase 3 trial succeed?", "science_health") == "clinical_trial"
        assert system.infer_subcategory("Will FDA approve the drug?", "science_health") == "clinical_trial"

    def test_infer_subcategory_no_match(self):
        system = BaseRateSystem()
        assert system.infer_subcategory("Something very generic", "politics") is None

    def test_infer_subcategory_macro(self):
        system = BaseRateSystem()
        assert system.infer_subcategory("Will the Fed raise the interest rate?", "macro_policy") == "rate_decision"
        assert system.infer_subcategory("Will GDP growth exceed 3%?", "macro_policy") == "economic_indicator"

    def test_deterministic_reproducibility(self):
        system = BaseRateSystem()
        r1 = system.lookup("technology", "product_launch", system_estimate=0.60)
        r2 = system.lookup("technology", "product_launch", system_estimate=0.60)
        assert r1.base_rate == r2.base_rate
        assert r1.deviation_from_estimate == r2.deviation_from_estimate


# ============================================================
# 5. Candidate Rubric Tests (Tier D)
# ============================================================

class TestCandidateRubric:
    """Multi-dimensional candidate scoring."""

    def test_composite_score_basic(self):
        score = CandidateRubricScore(
            evidence_quality=0.8,
            evidence_diversity=0.5,
            evidence_freshness=0.7,
            resolution_clarity=0.9,
            market_structure_quality=0.6,
            timing_clarity=0.7,
            expected_gross_edge=0.10,
            ambiguity_level=0.1,
            counter_case_strength=0.3,
            cluster_correlation_burden=0.1,
        )
        composite = score.compute_composite()
        assert 0.0 <= composite <= 1.0
        assert composite > 0  # with good scores, should be positive

    def test_composite_score_all_zeros(self):
        score = CandidateRubricScore()
        composite = score.compute_composite()
        assert composite == 0.0

    def test_composite_score_high_ambiguity_penalty(self):
        good = CandidateRubricScore(
            evidence_quality=0.8,
            resolution_clarity=0.9,
            expected_gross_edge=0.10,
            ambiguity_level=0.0,
            counter_case_strength=0.0,
        )
        bad = CandidateRubricScore(
            evidence_quality=0.8,
            resolution_clarity=0.9,
            expected_gross_edge=0.10,
            ambiguity_level=1.0,
            counter_case_strength=1.0,
        )
        good.compute_composite()
        bad.compute_composite()
        assert good.composite_score > bad.composite_score

    def test_rubric_scorer_with_candidate(self, sample_candidate, sample_research_pack):
        rubric = CandidateRubric()
        score = rubric.score(
            candidate=sample_candidate,
            research=sample_research_pack,
            gross_edge=0.10,
        )
        assert 0.0 <= score.composite_score <= 1.0
        assert score.evidence_quality > 0

    def test_rubric_scorer_empty_research(self, sample_candidate):
        rubric = CandidateRubric()
        score = rubric.score(
            candidate=sample_candidate,
            research=ResearchPackResult(),
            gross_edge=0.05,
        )
        assert score.evidence_quality == 0.0
        assert score.evidence_diversity == 0.0

    def test_rubric_scorer_with_domain_memo(
        self, sample_candidate, sample_domain_memo, sample_research_pack
    ):
        rubric = CandidateRubric()
        score = rubric.score(
            candidate=sample_candidate,
            domain_memo=sample_domain_memo,
            research=sample_research_pack,
            gross_edge=0.10,
        )
        assert score.composite_score > 0

    def test_rubric_scorer_with_impact(
        self, sample_candidate, sample_research_pack, sample_entry_impact
    ):
        rubric = CandidateRubric()
        score = rubric.score(
            candidate=sample_candidate,
            research=sample_research_pack,
            entry_impact=sample_entry_impact,
            gross_edge=0.08,
        )
        assert score.entry_impact_estimate_bps == 5.0

    def test_rubric_scorer_with_base_rate(
        self, sample_candidate, sample_research_pack, sample_base_rate
    ):
        rubric = CandidateRubric()
        score = rubric.score(
            candidate=sample_candidate,
            research=sample_research_pack,
            base_rate=sample_base_rate,
            gross_edge=0.08,
        )
        assert score.base_rate == 0.50
        assert score.base_rate_deviation == 0.10

    def test_market_structure_quality_scoring(self):
        """Score varies with spread, depth, volume, and price."""
        rubric = CandidateRubric()

        good_market = CandidateContext(
            market_id="m1", price=0.50, spread=0.02,
            visible_depth_usd=12000, volume_24h=60000,
        )
        bad_market = CandidateContext(
            market_id="m2", price=0.98, spread=0.18,
            visible_depth_usd=200, volume_24h=100,
        )

        good_score = rubric.score(candidate=good_market, gross_edge=0.05)
        bad_score = rubric.score(candidate=bad_market, gross_edge=0.05)

        assert good_score.market_structure_quality > bad_score.market_structure_quality

    def test_acceptance_threshold_constant(self):
        assert MIN_COMPOSITE_FOR_ACCEPTANCE > 0
        assert MIN_COMPOSITE_FOR_OPUS > MIN_COMPOSITE_FOR_ACCEPTANCE
        assert STRONG_CANDIDATE_THRESHOLD > MIN_COMPOSITE_FOR_OPUS


# ============================================================
# 6. Domain Manager Tests
# ============================================================

class TestDomainManagers:
    """Domain manager structure and factory."""

    def test_all_six_categories_have_managers(self):
        categories = ["politics", "geopolitics", "sports",
                       "technology", "science_health", "macro_policy"]
        for category in categories:
            cls = get_domain_manager_class(category)
            assert cls is not None, f"No domain manager for {category}"
            assert issubclass(cls, BaseDomainManager)

    def test_unknown_category_falls_back_to_general(self):
        from investigation.domain_managers import GeneralDomainManager
        assert get_domain_manager_class("crypto") is GeneralDomainManager
        assert get_domain_manager_class("weather") is GeneralDomainManager
        assert get_domain_manager_class("") is GeneralDomainManager

    def test_domain_manager_role_names(self):
        assert PoliticsDomainManager.role_name == "domain_manager_politics"
        assert GeopoliticsDomainManager.role_name == "domain_manager_geopolitics"
        assert SportsDomainManager.role_name == "domain_manager_sports"
        assert TechnologyDomainManager.role_name == "domain_manager_technology"
        assert ScienceHealthDomainManager.role_name == "domain_manager_science_health"
        assert MacroPolicyDomainManager.role_name == "domain_manager_macro_policy"

    def test_domain_managers_dict_keys(self):
        assert set(DOMAIN_MANAGERS.keys()) == {
            "politics", "geopolitics", "sports",
            "technology", "science_health", "macro_policy",
            None,
        }

    def test_domain_memo_parse_valid_json(self):
        """BaseDomainManager._parse_domain_memo parses valid JSON."""
        manager_cls = PoliticsDomainManager
        # Instantiate with a mock router
        router = MagicMock()
        manager = manager_cls(router=router)

        memo = manager._parse_domain_memo(
            json.dumps({
                "summary": "Test summary",
                "key_findings": ["Finding 1"],
                "concerns": ["Concern 1"],
                "recommended_proceed": True,
                "confidence_level": "high",
            }),
            market_id="m1",
            candidate={"category": "politics"},
        )
        assert memo.summary == "Test summary"
        assert memo.recommended_proceed is True
        assert memo.confidence_level == "high"

    def test_domain_memo_parse_invalid_json(self):
        """BaseDomainManager._parse_domain_memo handles invalid JSON gracefully."""
        router = MagicMock()
        manager = PoliticsDomainManager(router=router)

        memo = manager._parse_domain_memo(
            "Not valid JSON at all",
            market_id="m1",
            candidate={"category": "politics"},
        )
        assert memo.summary.startswith("Not valid JSON")
        # Invalid JSON fallback defaults to recommended_proceed=True to avoid
        # silently killing candidates when the LLM returns non-JSON output
        assert memo.recommended_proceed is True

    def test_sports_domain_prompt_contains_quality_gate(self):
        """Sports domain manager adds quality gate instructions."""
        router = MagicMock()
        manager = SportsDomainManager(router=router)
        prompt = manager._build_domain_prompt(
            {"title": "Test", "category": "sports"}, None,
        )
        assert "Quality-Gated" in prompt or "QUALITY_GATED" in prompt.upper()
        assert "ELEVATED CONSERVATISM" in prompt


# ============================================================
# 7. Research Pack Agent Tests
# ============================================================

class TestResearchAgents:
    """Research pack agent structure and role names."""

    def test_evidence_agent_role(self):
        assert EvidenceResearchAgent.role_name == "evidence_research"

    def test_counter_case_agent_role(self):
        assert CounterCaseAgent.role_name == "counter_case"

    def test_resolution_review_agent_role(self):
        assert ResolutionReviewAgent.role_name == "resolution_review"

    def test_timing_catalyst_agent_role(self):
        assert TimingCatalystAgent.role_name == "timing_catalyst"

    def test_market_structure_agent_role(self):
        assert MarketStructureAgent.role_name == "market_structure_summary"

    def test_optional_agent_roles(self):
        assert DataCrossCheckAgent.role_name == "evidence_research"
        assert SentimentDriftAgent.role_name == "evidence_research"
        assert SourceReliabilityAgent.role_name == "evidence_research"

    def test_market_structure_compute_metrics(self):
        """Market structure metrics are computed deterministically."""
        router = MagicMock()
        agent = MarketStructureAgent(router=router)
        metrics = agent._compute_structure_metrics({
            "price": 0.45,
            "spread": 0.01,
            "visible_depth_usd": 5000,
            "volume_24h": 30000,
        })
        assert metrics["spread_quality"] == "excellent"
        assert metrics["depth_adequate"] is True
        assert metrics["price_zone"] == "mid"

    def test_market_structure_extreme_price(self):
        router = MagicMock()
        agent = MarketStructureAgent(router=router)
        metrics = agent._compute_structure_metrics({
            "price": 0.02,
            "spread": 0.20,
            "visible_depth_usd": 100,
        })
        assert metrics["spread_quality"] == "poor"
        assert metrics["price_extreme"] is True

    def test_market_structure_no_data(self):
        router = MagicMock()
        agent = MarketStructureAgent(router=router)
        metrics = agent._compute_structure_metrics({})
        # Should not crash with missing data
        assert "price" in metrics
        assert metrics["price"] is None


# ============================================================
# 8. Thesis Card Builder Tests
# ============================================================

class TestThesisCardBuilder:
    """Thesis card builder — assembly from sub-outputs."""

    def test_build_complete_card(
        self,
        sample_candidate,
        sample_domain_memo,
        sample_research_pack,
        sample_entry_impact,
        sample_base_rate,
        sample_rubric_score,
        sample_net_edge,
    ):
        builder = ThesisCardBuilder()
        card = builder.build(
            candidate=sample_candidate,
            domain_memo=sample_domain_memo,
            research=sample_research_pack,
            entry_impact=sample_entry_impact,
            base_rate=sample_base_rate,
            rubric=sample_rubric_score,
            net_edge=sample_net_edge,
            orchestrator_output={
                "proposed_side": "yes",
                "core_thesis": "Fed will cut rates due to softening labor market",
                "why_mispriced": "Market underweights latest employment data",
                "probability_estimate": 0.60,
                "confidence_estimate": 0.65,
                "calibration_confidence": 0.50,
                "confidence_note": "Based on macro indicators",
                "invalidation_conditions": ["Strong jobs report", "Surprise CPI spike"],
            },
            workflow_run_id="wf-test-001",
            inference_cost_usd=0.08,
        )

        # Core thesis fields
        assert card.market_id == "mkt-001"
        assert card.workflow_run_id == "wf-test-001"
        assert card.category == "macro_policy"
        assert card.proposed_side == "yes"
        assert card.core_thesis == "Fed will cut rates due to softening labor market"

        # Net edge (Section 14.3)
        assert card.gross_edge == 0.10
        assert card.friction_adjusted_edge == 0.09
        assert card.impact_adjusted_edge == 0.085
        assert card.net_edge_after_cost == 0.084

        # Confidence (Section 23)
        assert card.probability_estimate == 0.60
        assert card.confidence_estimate == 0.65
        assert card.calibration_confidence == 0.50

        # Base rate
        assert card.base_rate == 0.50
        assert card.base_rate_deviation == 0.10

        # Entry impact
        assert card.entry_impact_estimate_bps == 5.0
        assert card.expected_inference_cost_usd == 0.08

        # Invalidation
        assert len(card.invalidation_conditions) == 2

        # Evidence
        assert len(card.supporting_evidence) <= 3
        assert len(card.opposing_evidence) <= 3

    def test_build_uses_orchestrator_evidence(
        self,
        sample_candidate,
        sample_domain_memo,
        sample_research_pack,
        sample_entry_impact,
        sample_base_rate,
        sample_rubric_score,
        sample_net_edge,
    ):
        builder = ThesisCardBuilder()
        card = builder.build(
            candidate=sample_candidate,
            domain_memo=sample_domain_memo,
            research=sample_research_pack,
            entry_impact=sample_entry_impact,
            base_rate=sample_base_rate,
            rubric=sample_rubric_score,
            net_edge=sample_net_edge,
            orchestrator_output={
                "proposed_side": "no",
                "core_thesis": "Test",
                "why_mispriced": "Test",
                "probability_estimate": 0.30,
                "supporting_evidence": [
                    {"content": "Custom evidence A", "source": "custom"}
                ],
                "opposing_evidence": [
                    {"content": "Custom counter B", "source": "custom"}
                ],
                "invalidation_conditions": [],
            },
            workflow_run_id="wf-002",
        )
        assert card.proposed_side == "no"
        assert card.supporting_evidence[0]["content"] == "Custom evidence A"
        assert card.opposing_evidence[0]["content"] == "Custom counter B"

    def test_build_normalizes_string_evidence(
        self,
        sample_candidate,
        sample_domain_memo,
        sample_research_pack,
        sample_entry_impact,
        sample_base_rate,
        sample_rubric_score,
        sample_net_edge,
    ):
        builder = ThesisCardBuilder()
        card = builder.build(
            candidate=sample_candidate,
            domain_memo=sample_domain_memo,
            research=sample_research_pack,
            entry_impact=sample_entry_impact,
            base_rate=sample_base_rate,
            rubric=sample_rubric_score,
            net_edge=sample_net_edge,
            orchestrator_output={
                "proposed_side": "yes",
                "core_thesis": "Test",
                "why_mispriced": "Test",
                "probability_estimate": 0.57,
                "supporting_evidence": ["Lineup news moved the true odds"],
                "opposing_evidence": ["Market may already reflect the injury report"],
                "invalidation_conditions": [],
            },
            workflow_run_id="wf-003",
        )
        assert card.supporting_evidence[0]["content"] == "Lineup news moved the true odds"
        assert card.supporting_evidence[0]["source"] == "orchestrator"
        assert card.opposing_evidence[0]["content"] == "Market may already reflect the injury report"

    def test_size_band_determination(self):
        builder = ThesisCardBuilder()

        large_edge = NetEdgeCalculation(impact_adjusted_edge=0.10)
        large_score = CandidateRubricScore(composite_score=0.7)
        assert builder._determine_size_band(large_edge, large_score) == "large"

        standard_edge = NetEdgeCalculation(impact_adjusted_edge=0.06)
        standard_score = CandidateRubricScore(composite_score=0.5)
        assert builder._determine_size_band(standard_edge, standard_score) == "standard"

        small_edge = NetEdgeCalculation(impact_adjusted_edge=0.03)
        small_score = CandidateRubricScore(composite_score=0.3)
        assert builder._determine_size_band(small_edge, small_score) == "small"

        min_edge = NetEdgeCalculation(impact_adjusted_edge=0.01)
        min_score = CandidateRubricScore(composite_score=0.2)
        assert builder._determine_size_band(min_edge, min_score) == "minimum"

    def test_urgency_determination(self):
        builder = ThesisCardBuilder()
        candidate = CandidateContext(market_id="m1")

        assert builder._determine_urgency(
            {"time_pressure": "high"}, candidate,
        ) == "immediate"
        assert builder._determine_urgency(
            {"time_pressure": "medium"}, candidate,
        ) == "within_hours"
        assert builder._determine_urgency(
            {"expected_time_horizon_hours": 96}, candidate,
        ) == "within_day"
        assert builder._determine_urgency(
            {"expected_time_horizon_hours": 500}, candidate,
        ) == "low"

    def test_calibration_status_determination(self):
        builder = ThesisCardBuilder()
        assert builder._determine_calibration_status(0, "none") == "no_data"
        assert builder._determine_calibration_status(5, "low") == "insufficient"
        assert builder._determine_calibration_status(50, "medium") == "preliminary"
        assert builder._determine_calibration_status(200, "high") == "reliable"


# ============================================================
# 9. Investigation Orchestrator Tests
# ============================================================

class TestInvestigationOrchestrator:
    """Integration tests for the full investigation pipeline using mocked LLM."""

    @pytest.fixture
    def mock_router(self):
        """Mock ProviderRouter that returns canned responses."""
        router = MagicMock()
        router.model_for_tier = MagicMock(return_value="test-model-v1")
        return router

    @pytest.fixture
    def mock_cost_governor(self):
        """Mock CostGovernor that approves everything."""
        governor = MagicMock()
        governor.estimate = MagicMock()
        governor.approve = MagicMock()

        from cost.types import CostApproval, CostDecision, CostEstimate, BudgetState, RunType
        governor.estimate.return_value = CostEstimate(
            workflow_run_id="wf-test",
            run_type=RunType.TRIGGER_BASED,
            expected_cost_min_usd=0.05,
            expected_cost_max_usd=0.50,
            budget_state=BudgetState(
                daily_budget_usd=25.0,
                daily_remaining_usd=20.0,
                lifetime_budget_usd=5000.0,
                lifetime_remaining_usd=4500.0,
            ),
        )
        governor.approve.return_value = CostApproval(
            decision=CostDecision.APPROVE_FULL,
            reason="Within budget",
            approved_max_tier=None,  # Allow all tiers
        )
        return governor

    @pytest.fixture
    def mock_cost_governor_reject(self):
        """Mock CostGovernor that rejects."""
        governor = MagicMock()
        from cost.types import CostApproval, CostDecision, CostEstimate, BudgetState, RunType
        governor.estimate.return_value = CostEstimate(
            workflow_run_id="wf-test",
            run_type=RunType.TRIGGER_BASED,
            expected_cost_min_usd=0.05,
            expected_cost_max_usd=0.50,
            budget_state=BudgetState(
                daily_budget_usd=25.0,
                daily_remaining_usd=0.0,
                lifetime_budget_usd=5000.0,
                lifetime_remaining_usd=0.0,
            ),
        )
        governor.approve.return_value = CostApproval(
            decision=CostDecision.REJECT,
            reason="Lifetime budget exhausted",
        )
        return governor

    @pytest.mark.asyncio
    async def test_no_candidates_returns_no_trade(self, mock_router):
        orchestrator = InvestigationOrchestrator(router=mock_router)
        request = InvestigationRequest(
            workflow_run_id="wf-001",
            mode=InvestigationMode.SCHEDULED_SWEEP,
            candidates=[],
        )
        result = await orchestrator.run(request)
        assert result.outcome == InvestigationOutcome.NO_TRADE
        assert len(result.no_trade_results) == 1
        assert result.no_trade_results[0].reason_code == "no_candidates"

    @pytest.mark.asyncio
    async def test_cost_governor_rejection(
        self, mock_router, mock_cost_governor_reject, sample_candidate,
    ):
        orchestrator = InvestigationOrchestrator(
            router=mock_router,
            cost_governor=mock_cost_governor_reject,
        )
        request = InvestigationRequest(
            workflow_run_id="wf-002",
            mode=InvestigationMode.TRIGGER_BASED,
            candidates=[sample_candidate],
        )
        result = await orchestrator.run(request)
        assert result.outcome == InvestigationOutcome.COST_REJECTED
        assert "budget" in result.no_trade_results[0].reason.lower()

    @pytest.mark.asyncio
    async def test_candidate_ranking(self, mock_router):
        orchestrator = InvestigationOrchestrator(router=mock_router)

        c1 = CandidateContext(
            market_id="m1", trigger_level="A", edge_discovery_score=0.3,
        )
        c2 = CandidateContext(
            market_id="m2", trigger_level="C", edge_discovery_score=0.8,
        )
        c3 = CandidateContext(
            market_id="m3", trigger_level="D", edge_discovery_score=0.5,
        )

        ranked = orchestrator._rank_candidates([c1, c2, c3])
        # D triggers are highest priority (0), then C (1), then A (3)
        assert ranked[0].market_id == "m3"  # Level D
        assert ranked[1].market_id == "m2"  # Level C
        assert ranked[2].market_id == "m1"  # Level A

    @pytest.mark.asyncio
    async def test_max_candidates_limit(self, mock_router):
        orchestrator = InvestigationOrchestrator(router=mock_router)

        candidates = [
            CandidateContext(market_id=f"m{i}", trigger_level="C")
            for i in range(10)
        ]
        request = InvestigationRequest(
            workflow_run_id="wf-003",
            mode=InvestigationMode.SCHEDULED_SWEEP,
            candidates=candidates,
            max_candidates=2,
        )

        # Patch _investigate_candidate to avoid real LLM calls
        with patch.object(
            orchestrator, "_investigate_candidate",
            new_callable=AsyncMock,
            return_value=None,
        ) as mock_investigate:
            result = await orchestrator.run(request)
            # Should only call _investigate_candidate for max_candidates (2)
            assert mock_investigate.call_count == 2

    @pytest.mark.asyncio
    async def test_probability_estimation_proceed(self, mock_router):
        orchestrator = InvestigationOrchestrator(router=mock_router)

        proceed_memo = DomainMemo(
            category="politics",
            market_id="m1",
            recommended_proceed=True,
            confidence_level="high",
        )
        prob = orchestrator._estimate_probability_from_domain(proceed_memo, 0.50)
        assert prob > 0.50  # Should adjust upward
        assert prob <= 0.95  # Capped

    @pytest.mark.asyncio
    async def test_probability_estimation_no_proceed(self, mock_router):
        orchestrator = InvestigationOrchestrator(router=mock_router)

        no_proceed_memo = DomainMemo(
            category="politics",
            market_id="m1",
            recommended_proceed=False,
        )
        prob = orchestrator._estimate_probability_from_domain(no_proceed_memo, 0.50)
        # Small exploratory offset applied even for no-proceed (Priority 4)
        assert prob == 0.52

    def test_non_structural_domain_reject_is_normalized_to_proceed(
        self,
        mock_router,
        sample_candidate,
    ):
        orchestrator = InvestigationOrchestrator(router=mock_router)
        memo = DomainMemo(
            category="macro_policy",
            market_id=sample_candidate.market_id,
            summary="Coverage is dense and calibration is still thin.",
            concerns=["Market may already be efficient"],
            recommended_proceed=False,
            proceed_blocker_code="insufficient_calibration",
            proceed_blocker_detail="Limited resolved samples in this segment",
            confidence_level="medium",
        )

        normalized = orchestrator._normalize_domain_memo(sample_candidate, memo)

        assert normalized.recommended_proceed is True
        assert normalized.confidence_level == "low"
        assert normalized.domain_specific_data["normalized_non_structural_reject"] is True
        assert any("Original blocker detail" in concern for concern in normalized.concerns)

    def test_structural_domain_reject_still_blocks(
        self,
        mock_router,
        sample_candidate,
    ):
        orchestrator = InvestigationOrchestrator(router=mock_router)
        memo = DomainMemo(
            category="macro_policy",
            market_id=sample_candidate.market_id,
            summary="The market has already resolved.",
            recommended_proceed=False,
            proceed_blocker_code="resolved",
            proceed_blocker_detail="Resolution source already published the final outcome",
            confidence_level="high",
        )

        normalized = orchestrator._normalize_domain_memo(sample_candidate, memo)

        assert normalized.recommended_proceed is False
        assert normalized.proceed_blocker_code == "resolved"

    @pytest.mark.asyncio
    async def test_investigation_result_structure(self, mock_router):
        """Verify InvestigationResult has correct structure after execution."""
        result = InvestigationResult(
            workflow_run_id="wf-test",
            mode=InvestigationMode.SCHEDULED_SWEEP,
            outcome=InvestigationOutcome.CANDIDATE_ACCEPTED,
            candidates_evaluated=2,
            candidates_accepted=1,
        )
        result.thesis_cards.append(
            ThesisCardData(
                market_id="m1",
                workflow_run_id="wf-test",
                category="politics",
                proposed_side="yes",
                resolution_interpretation="Resolves YES if...",
                core_thesis="Test thesis",
                why_mispriced="Test mispricing",
                supporting_evidence=[],
                opposing_evidence=[],
                invalidation_conditions=[],
            )
        )
        assert result.has_accepted_candidates is True
        assert result.is_no_trade is False

    @pytest.mark.asyncio
    async def test_domain_manager_none_returns_no_trade(
        self, mock_router, mock_cost_governor, sample_candidate,
    ):
        """When no domain manager exists for category, candidate is rejected."""
        bad_candidate = sample_candidate.model_copy(update={"category": "crypto"})

        orchestrator = InvestigationOrchestrator(
            router=mock_router,
            cost_governor=mock_cost_governor,
        )
        request = InvestigationRequest(
            workflow_run_id="wf-004",
            mode=InvestigationMode.TRIGGER_BASED,
            candidates=[bad_candidate],
        )
        result = await orchestrator.run(request)
        # Candidate should be rejected (no domain manager for "crypto")
        assert result.outcome == InvestigationOutcome.NO_TRADE
        assert len(result.no_trade_results) >= 1

    @pytest.mark.asyncio
    async def test_orchestrator_without_cost_governor(
        self, mock_router, sample_candidate,
    ):
        """No cost governor → cost_approval is None → no cost rejection."""
        orchestrator = InvestigationOrchestrator(
            router=mock_router,
            cost_governor=None,  # No cost governor
        )

        # Patch the candidate investigation to avoid real LLM calls
        with patch.object(
            orchestrator, "_investigate_candidate",
            new_callable=AsyncMock,
            return_value=None,
        ):
            request = InvestigationRequest(
                workflow_run_id="wf-005",
                mode=InvestigationMode.SCHEDULED_SWEEP,
                candidates=[sample_candidate],
            )
            result = await orchestrator.run(request)
            assert result.outcome != InvestigationOutcome.COST_REJECTED

    @pytest.mark.asyncio
    async def test_actual_cost_includes_rejected_candidate_spend(
        self, mock_router, mock_cost_governor, sample_candidate,
    ):
        orchestrator = InvestigationOrchestrator(
            router=mock_router,
            cost_governor=mock_cost_governor,
        )

        async def fake_investigate_candidate(*args, **kwargs):
            agent_costs = kwargs["agent_costs"]
            agent_costs["domain_manager_macro_policy"] = 0.022596
            agent_costs["evidence_research"] = 0.0035
            return None

        with patch.object(
            orchestrator,
            "_investigate_candidate",
            new=AsyncMock(side_effect=fake_investigate_candidate),
        ):
            request = InvestigationRequest(
                workflow_run_id="wf-006",
                mode=InvestigationMode.TRIGGER_BASED,
                candidates=[sample_candidate],
                max_candidates=1,
            )
            result = await orchestrator.run(request)

        assert result.outcome == InvestigationOutcome.NO_TRADE
        assert result.actual_cost_usd == 0.026096
        assert result.agent_costs == {
            "domain_manager_macro_policy": 0.022596,
            "evidence_research": 0.0035,
        }


# ============================================================
# 10. Integration: Full Module Import Test
# ============================================================

class TestModuleImports:
    """Verify that all public exports from investigation/__init__.py work."""

    def test_import_orchestrator(self):
        from investigation import InvestigationOrchestrator
        assert InvestigationOrchestrator is not None

    def test_import_domain_managers(self):
        from investigation import (
            PoliticsDomainManager,
            GeopoliticsDomainManager,
            SportsDomainManager,
            TechnologyDomainManager,
            ScienceHealthDomainManager,
            MacroPolicyDomainManager,
        )
        assert len({
            PoliticsDomainManager, GeopoliticsDomainManager,
            SportsDomainManager, TechnologyDomainManager,
            ScienceHealthDomainManager, MacroPolicyDomainManager,
        }) == 6

    def test_import_research_agents(self):
        from investigation import (
            EvidenceResearchAgent,
            CounterCaseAgent,
            ResolutionReviewAgent,
            TimingCatalystAgent,
            MarketStructureAgent,
        )
        agents = [EvidenceResearchAgent, CounterCaseAgent,
                  ResolutionReviewAgent, TimingCatalystAgent, MarketStructureAgent]
        assert all(a is not None for a in agents)

    def test_import_core_components(self):
        from investigation import (
            EntryImpactCalculator,
            BaseRateSystem,
            CandidateRubric,
            ThesisCardBuilder,
        )
        assert all(c is not None for c in [
            EntryImpactCalculator, BaseRateSystem,
            CandidateRubric, ThesisCardBuilder,
        ])

    def test_import_types(self):
        from investigation import (
            InvestigationMode,
            InvestigationOutcome,
            InvestigationRequest,
            InvestigationResult,
            CandidateContext,
            ThesisCardData,
            DomainMemo,
            EvidenceItem,
            NetEdgeCalculation,
            NoTradeResult,
        )
        assert InvestigationMode.SCHEDULED_SWEEP.value == "scheduled_sweep"
        assert InvestigationOutcome.NO_TRADE.value == "no_trade"


# ============================================================
# 11. Enum Value Tests
# ============================================================

class TestEnumValues:
    """Verify all investigation enums have expected values."""

    def test_investigation_modes(self):
        assert InvestigationMode.SCHEDULED_SWEEP == "scheduled_sweep"
        assert InvestigationMode.TRIGGER_BASED == "trigger_based"
        assert InvestigationMode.OPERATOR_FORCED == "operator_forced"

    def test_investigation_outcomes(self):
        assert InvestigationOutcome.NO_TRADE == "no_trade"
        assert InvestigationOutcome.CANDIDATE_ACCEPTED == "candidate_accepted"
        assert InvestigationOutcome.DEFERRED == "deferred"
        assert InvestigationOutcome.COST_REJECTED == "cost_rejected"
        assert InvestigationOutcome.ERROR == "error"

    def test_calibration_source_status(self):
        assert CalibrationSourceStatus.NO_DATA == "no_data"
        assert CalibrationSourceStatus.INSUFFICIENT == "insufficient"
        assert CalibrationSourceStatus.PRELIMINARY == "preliminary"
        assert CalibrationSourceStatus.RELIABLE == "reliable"

    def test_entry_urgency(self):
        assert EntryUrgency.IMMEDIATE == "immediate"
        assert EntryUrgency.WITHIN_HOURS == "within_hours"
        assert EntryUrgency.WITHIN_DAY == "within_day"
        assert EntryUrgency.LOW == "low"

    def test_size_band(self):
        assert SizeBand.MINIMUM == "minimum"
        assert SizeBand.SMALL == "small"
        assert SizeBand.STANDARD == "standard"
        assert SizeBand.LARGE == "large"
