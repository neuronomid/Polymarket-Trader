"""Tests for the capital rules engine."""

import pytest

from config.settings import RiskConfig
from core.enums import DrawdownLevel, OperatorMode
from risk.capital_rules import CapitalRulesEngine
from risk.types import DrawdownState, PortfolioState, SizingRequest


@pytest.fixture
def config():
    return RiskConfig()


@pytest.fixture
def engine(config):
    return CapitalRulesEngine(config)


@pytest.fixture
def portfolio():
    return PortfolioState(
        account_balance_usd=10000.0,
        start_of_day_equity_usd=10000.0,
        current_equity_usd=9800.0,
        total_open_exposure_usd=3000.0,
        daily_deployment_used_usd=500.0,
        open_position_count=5,
    )


@pytest.fixture
def drawdown():
    return DrawdownState(
        level=DrawdownLevel.NORMAL,
        entries_allowed=True,
    )


@pytest.fixture
def sizing_request():
    return SizingRequest(
        market_id="m1",
        token_id="tok1",
        category="politics",
        gross_edge=0.05,
        probability_estimate=0.6,
        confidence_estimate=0.7,
        evidence_quality_score=0.8,
    )


def test_all_rules_pass(engine, sizing_request, portfolio, drawdown):
    results = engine.evaluate_all(sizing_request, portfolio, drawdown)
    assert all(r.passed for r in results)


def test_drawdown_blocks_entries(engine, sizing_request, portfolio):
    drawdown = DrawdownState(
        level=DrawdownLevel.ENTRIES_DISABLED,
        entries_allowed=False,
        current_drawdown_pct=0.07,
    )
    results = engine.evaluate_all(sizing_request, portfolio, drawdown)
    dd_rule = next(r for r in results if r.rule_name == "drawdown_entries_allowed")
    assert dd_rule.passed is False


def test_daily_deployment_exhausted(engine, sizing_request, drawdown):
    portfolio = PortfolioState(
        account_balance_usd=10000.0,
        start_of_day_equity_usd=10000.0,
        current_equity_usd=10000.0,
        daily_deployment_used_usd=1000.0,  # 10% of 10000 = limit
    )
    results = engine.evaluate_all(sizing_request, portfolio, drawdown)
    dd_rule = next(r for r in results if r.rule_name == "daily_deployment_limit")
    assert dd_rule.passed is False


def test_daily_deployment_within_limit(engine, sizing_request, drawdown):
    portfolio = PortfolioState(
        account_balance_usd=10000.0,
        start_of_day_equity_usd=10000.0,
        current_equity_usd=10000.0,
        daily_deployment_used_usd=500.0,
    )
    results = engine.evaluate_all(sizing_request, portfolio, drawdown)
    dd_rule = next(r for r in results if r.rule_name == "daily_deployment_limit")
    assert dd_rule.passed is True


def test_total_exposure_cap_exceeded(engine, sizing_request, drawdown):
    portfolio = PortfolioState(
        account_balance_usd=10000.0,
        start_of_day_equity_usd=10000.0,
        current_equity_usd=10000.0,
        total_open_exposure_usd=10000.0,  # at cap
    )
    results = engine.evaluate_all(sizing_request, portfolio, drawdown)
    rule = next(r for r in results if r.rule_name == "total_exposure_cap")
    assert rule.passed is False


def test_position_count_at_limit(engine, sizing_request, drawdown):
    portfolio = PortfolioState(
        account_balance_usd=10000.0,
        start_of_day_equity_usd=10000.0,
        current_equity_usd=10000.0,
        open_position_count=20,  # at limit
    )
    results = engine.evaluate_all(sizing_request, portfolio, drawdown)
    rule = next(r for r in results if r.rule_name == "position_count_limit")
    assert rule.passed is False


def test_category_exposure_sports(engine, drawdown):
    """Sports has a lower cap than default."""
    req = SizingRequest(
        market_id="m1",
        token_id="tok1",
        category="sports",
        gross_edge=0.05,
        probability_estimate=0.6,
        confidence_estimate=0.7,
    )
    portfolio = PortfolioState(
        account_balance_usd=10000.0,
        start_of_day_equity_usd=10000.0,
        current_equity_usd=10000.0,
        category_exposure_usd={"sports": 2000.0},  # at sports cap
    )
    results = engine.evaluate_all(req, portfolio, drawdown)
    rule = next(r for r in results if r.rule_name == "category_exposure_cap")
    assert rule.passed is False
    assert "sports" in rule.reason


def test_category_exposure_default(engine, drawdown):
    """Default category cap should be higher than sports."""
    req = SizingRequest(
        market_id="m1",
        token_id="tok1",
        category="politics",
        gross_edge=0.05,
        probability_estimate=0.6,
        confidence_estimate=0.7,
    )
    portfolio = PortfolioState(
        account_balance_usd=10000.0,
        start_of_day_equity_usd=10000.0,
        current_equity_usd=10000.0,
        category_exposure_usd={"politics": 2000.0},  # below default cap of 5000
    )
    results = engine.evaluate_all(req, portfolio, drawdown)
    rule = next(r for r in results if r.rule_name == "category_exposure_cap")
    assert rule.passed is True


def test_operator_mode_emergency_halt(engine, sizing_request, drawdown):
    portfolio = PortfolioState(
        account_balance_usd=10000.0,
        start_of_day_equity_usd=10000.0,
        current_equity_usd=10000.0,
        operator_mode=OperatorMode.EMERGENCY_HALT,
    )
    results = engine.evaluate_all(sizing_request, portfolio, drawdown)
    rule = next(r for r in results if r.rule_name == "operator_mode_restriction")
    assert rule.passed is False


def test_operator_mode_absent(engine, sizing_request, drawdown):
    portfolio = PortfolioState(
        account_balance_usd=10000.0,
        start_of_day_equity_usd=10000.0,
        current_equity_usd=10000.0,
        operator_mode=OperatorMode.OPERATOR_ABSENT,
    )
    results = engine.evaluate_all(sizing_request, portfolio, drawdown)
    rule = next(r for r in results if r.rule_name == "operator_mode_restriction")
    assert rule.passed is False


def test_operator_mode_paper_allowed(engine, sizing_request, drawdown, portfolio):
    results = engine.evaluate_all(sizing_request, portfolio, drawdown)
    rule = next(r for r in results if r.rule_name == "operator_mode_restriction")
    assert rule.passed is True


def test_evidence_threshold_under_soft_warning(engine, portfolio):
    """Under soft warning, low evidence should fail."""
    drawdown = DrawdownState(
        level=DrawdownLevel.SOFT_WARNING,
        entries_allowed=True,
        min_evidence_score=0.6,
    )
    req = SizingRequest(
        market_id="m1",
        token_id="tok1",
        category="politics",
        gross_edge=0.05,
        probability_estimate=0.6,
        confidence_estimate=0.7,
        evidence_quality_score=0.4,  # below 0.6 threshold
    )
    results = engine.evaluate_all(req, portfolio, drawdown)
    rule = next(r for r in results if r.rule_name == "evidence_threshold")
    assert rule.passed is False


def test_evidence_threshold_normal_drawdown(engine, sizing_request, portfolio, drawdown):
    """Under normal drawdown, no evidence threshold enforced."""
    results = engine.evaluate_all(sizing_request, portfolio, drawdown)
    rule = next(r for r in results if r.rule_name == "evidence_threshold")
    assert rule.passed is True
