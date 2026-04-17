"""Tests for the Risk Governor orchestrator."""

import pytest

from config.settings import RiskConfig
from core.enums import DrawdownLevel, OperatorMode, RiskApproval
from market_data.types import OrderBookLevel
from risk.correlation import CorrelationType
from risk.governor import RiskGovernor
from risk.types import PortfolioState, SizingRequest


def _equity_for_drawdown(config: RiskConfig, pct: float) -> float:
    return 10000.0 * (1.0 - pct)


@pytest.fixture
def config():
    return RiskConfig()


@pytest.fixture
def governor(config):
    g = RiskGovernor(config)
    g.reset_day(10000.0)
    return g


@pytest.fixture
def portfolio():
    return PortfolioState(
        account_balance_usd=10000.0,
        start_of_day_equity_usd=10000.0,
        current_equity_usd=10000.0,
        total_open_exposure_usd=2000.0,
        daily_deployment_used_usd=200.0,
        open_position_count=3,
    )


def _make_request(**kwargs) -> SizingRequest:
    defaults = dict(
        market_id="m1",
        token_id="tok1",
        category="politics",
        gross_edge=0.05,
        probability_estimate=0.6,
        confidence_estimate=0.7,
        evidence_quality_score=0.8,
        evidence_diversity_score=0.8,
        visible_depth_usd=10000.0,
        best_ask=0.60,
        spread=0.05,
    )
    defaults.update(kwargs)
    return SizingRequest(**defaults)


# --- Happy path ---

def test_approve_normal(governor, portfolio):
    request = _make_request()
    assessment = governor.assess(request, portfolio)
    assert assessment.approval == RiskApproval.APPROVE_NORMAL
    assert assessment.is_approved is True
    assert assessment.sizing is not None
    assert assessment.sizing.recommended_size_usd > 0
    assert assessment.reason == "All rules passed"


def test_assess_returns_all_rule_results(governor, portfolio):
    request = _make_request()
    assessment = governor.assess(request, portfolio)
    assert len(assessment.rule_results) >= 7  # 7 capital rules + liquidity + impact


# --- Drawdown blocks ---

def test_reject_drawdown_entries_disabled(governor, portfolio, config):
    """Entries disabled at 3.5% drawdown."""
    governor.update_equity(_equity_for_drawdown(config, config.entries_disabled_pct))
    request = _make_request()
    assessment = governor.assess(request, portfolio)
    assert assessment.approval == RiskApproval.REJECT
    assert assessment.is_approved is False
    assert assessment.sizing is None


def test_reject_hard_kill_switch(governor, portfolio, config):
    governor.update_equity(_equity_for_drawdown(config, config.hard_kill_switch_pct))
    request = _make_request()
    assessment = governor.assess(request, portfolio)
    assert assessment.approval == RiskApproval.REJECT


def test_reduced_at_soft_warning(governor, portfolio, config):
    """Soft warning should approve with reduced size."""
    governor.update_equity(_equity_for_drawdown(config, config.soft_warning_pct))
    request = _make_request()
    assessment = governor.assess(request, portfolio)
    assert assessment.approval == RiskApproval.APPROVE_REDUCED
    assert assessment.sizing is not None


def test_reduced_at_risk_reduction(governor, portfolio, config):
    governor.update_equity(_equity_for_drawdown(config, config.risk_reduction_pct))
    request = _make_request()
    assessment = governor.assess(request, portfolio)
    assert assessment.approval == RiskApproval.APPROVE_REDUCED


# --- Exposure caps ---

def test_reject_total_exposure_exceeded(governor):
    portfolio = PortfolioState(
        account_balance_usd=10000.0,
        start_of_day_equity_usd=10000.0,
        current_equity_usd=10000.0,
        total_open_exposure_usd=10000.0,  # at cap
    )
    request = _make_request()
    assessment = governor.assess(request, portfolio)
    assert assessment.approval == RiskApproval.REJECT


def test_reject_position_count_exceeded(governor):
    portfolio = PortfolioState(
        account_balance_usd=10000.0,
        start_of_day_equity_usd=10000.0,
        current_equity_usd=10000.0,
        open_position_count=20,  # at limit
    )
    request = _make_request()
    assessment = governor.assess(request, portfolio)
    assert assessment.approval == RiskApproval.REJECT


# --- Operator mode ---

def test_reject_emergency_halt(governor):
    portfolio = PortfolioState(
        account_balance_usd=10000.0,
        start_of_day_equity_usd=10000.0,
        current_equity_usd=10000.0,
        operator_mode=OperatorMode.EMERGENCY_HALT,
    )
    request = _make_request()
    assessment = governor.assess(request, portfolio)
    assert assessment.approval == RiskApproval.REJECT


def test_reject_operator_absent(governor):
    portfolio = PortfolioState(
        account_balance_usd=10000.0,
        start_of_day_equity_usd=10000.0,
        current_equity_usd=10000.0,
        operator_mode=OperatorMode.OPERATOR_ABSENT,
    )
    request = _make_request()
    assessment = governor.assess(request, portfolio)
    assert assessment.approval == RiskApproval.REJECT


# --- Liquidity ---

def test_reject_zero_depth(governor, portfolio):
    request = _make_request(visible_depth_usd=0.0)
    assessment = governor.assess(request, portfolio)
    assert assessment.approval == RiskApproval.REJECT


def test_liquidity_check_populated(governor, portfolio):
    request = _make_request()
    asks = [OrderBookLevel(price=0.60, size=1000.0)]
    assessment = governor.assess(request, portfolio, ask_levels=asks)
    assert assessment.liquidity_check is not None
    assert assessment.liquidity_check.max_order_usd > 0


# --- Correlation ---

def test_correlation_cluster_violation_approve_special(governor, portfolio):
    """Cluster exposure violation should give APPROVE_SPECIAL."""
    governor.correlation_engine.register_cluster(
        "c1", CorrelationType.EVENT, "Election", max_exposure_usd=1000.0,
    )
    governor.correlation_engine.add_exposure("c1", "pos-1", 1000.0)

    request = _make_request(cluster_ids=["c1"])
    assessment = governor.assess(request, portfolio)
    assert assessment.approval == RiskApproval.APPROVE_SPECIAL
    assert assessment.correlation is not None


def test_no_correlation_issues(governor, portfolio):
    request = _make_request(cluster_ids=[])
    assessment = governor.assess(request, portfolio)
    assert assessment.correlation is not None
    assert assessment.correlation.passes is True


# --- Category exposure ---

def test_reject_category_cap_exceeded(governor):
    portfolio = PortfolioState(
        account_balance_usd=10000.0,
        start_of_day_equity_usd=10000.0,
        current_equity_usd=10000.0,
        category_exposure_usd={"politics": 5000.0},  # at default cap
    )
    request = _make_request(category="politics")
    assessment = governor.assess(request, portfolio)
    assert assessment.approval == RiskApproval.REJECT


# --- Evidence threshold ---

def test_delay_low_evidence_under_drawdown(governor, portfolio, config):
    """Low evidence under soft warning should delay."""
    governor.update_equity(_equity_for_drawdown(config, config.soft_warning_pct))
    request = _make_request(evidence_quality_score=0.3)
    assessment = governor.assess(request, portfolio)
    assert assessment.approval == RiskApproval.DELAY


# --- can_trade (no-trade authority) ---

def test_can_trade_normal(governor, portfolio):
    allowed, reason = governor.can_trade(portfolio)
    assert allowed is True


def test_can_trade_drawdown_blocks(governor, portfolio, config):
    governor.update_equity(_equity_for_drawdown(config, config.entries_disabled_pct))
    allowed, reason = governor.can_trade(portfolio)
    assert allowed is False
    assert "drawdown" in reason.lower()


def test_can_trade_emergency_halt(governor):
    portfolio = PortfolioState(
        account_balance_usd=10000.0,
        start_of_day_equity_usd=10000.0,
        current_equity_usd=10000.0,
        operator_mode=OperatorMode.EMERGENCY_HALT,
    )
    allowed, reason = governor.can_trade(portfolio)
    assert allowed is False


def test_can_trade_positions_full(governor):
    portfolio = PortfolioState(
        account_balance_usd=10000.0,
        start_of_day_equity_usd=10000.0,
        current_equity_usd=10000.0,
        open_position_count=20,
    )
    allowed, reason = governor.can_trade(portfolio)
    assert allowed is False


def test_can_trade_exposure_full(governor):
    portfolio = PortfolioState(
        account_balance_usd=10000.0,
        start_of_day_equity_usd=10000.0,
        current_equity_usd=10000.0,
        total_open_exposure_usd=10000.0,
    )
    allowed, reason = governor.can_trade(portfolio)
    assert allowed is False


def test_can_trade_daily_deployment_exhausted(governor):
    portfolio = PortfolioState(
        account_balance_usd=10000.0,
        start_of_day_equity_usd=10000.0,
        current_equity_usd=10000.0,
        daily_deployment_used_usd=1000.0,
    )
    allowed, reason = governor.can_trade(portfolio)
    assert allowed is False


# --- Special conditions ---

def test_special_conditions_under_drawdown(governor, portfolio, config):
    governor.update_equity(_equity_for_drawdown(config, config.soft_warning_pct))
    request = _make_request()
    assessment = governor.assess(request, portfolio)
    assert any("review interval" in c.lower() for c in assessment.special_conditions)


# --- Day lifecycle ---

def test_reset_day(governor, config):
    governor.update_equity(_equity_for_drawdown(config, config.hard_kill_switch_pct))
    assert governor.drawdown_state.level == DrawdownLevel.HARD_KILL_SWITCH

    governor.reset_day(10500.0)
    assert governor.drawdown_state.level == DrawdownLevel.NORMAL
    assert governor.drawdown_state.start_of_day_equity == 10500.0


def test_update_equity(governor, config):
    state = governor.update_equity(_equity_for_drawdown(config, config.soft_warning_pct))
    assert state.level == DrawdownLevel.SOFT_WARNING
    assert state.current_equity == _equity_for_drawdown(config, config.soft_warning_pct)


# --- Drawdown state tracked through assessment ---

def test_drawdown_state_in_assessment(governor, portfolio, config):
    governor.update_equity(_equity_for_drawdown(config, config.soft_warning_pct))
    request = _make_request()
    assessment = governor.assess(request, portfolio)
    assert assessment.drawdown_state.level == DrawdownLevel.SOFT_WARNING
