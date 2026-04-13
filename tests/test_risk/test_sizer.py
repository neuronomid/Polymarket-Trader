"""Tests for the position sizer."""

import pytest

from config.settings import RiskConfig
from core.enums import CategoryQualityTier, DrawdownLevel
from risk.sizer import PositionSizer
from risk.types import DrawdownState, LiquidityCheck, PortfolioState, SizingRequest


@pytest.fixture
def config():
    return RiskConfig()


@pytest.fixture
def sizer(config):
    return PositionSizer(config)


@pytest.fixture
def portfolio():
    return PortfolioState(
        account_balance_usd=10000.0,
        start_of_day_equity_usd=10000.0,
        current_equity_usd=10000.0,
        daily_deployment_used_usd=0.0,
    )


@pytest.fixture
def drawdown():
    return DrawdownState(level=DrawdownLevel.NORMAL, size_multiplier=1.0)


@pytest.fixture
def liquidity():
    return LiquidityCheck(
        max_order_usd=1200.0,
        depth_at_top_levels_usd=10000.0,
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
        spread=0.05,
    )
    defaults.update(kwargs)
    return SizingRequest(**defaults)


def test_basic_sizing(sizer, portfolio, drawdown, liquidity):
    request = _make_request()
    result = sizer.compute(request, portfolio, drawdown, liquidity)
    assert result.recommended_size_usd > 0
    assert result.max_size_usd > 0


def test_higher_edge_larger_size(sizer, portfolio, drawdown, liquidity):
    req_low = _make_request(gross_edge=0.02)
    req_high = _make_request(gross_edge=0.08)
    r_low = sizer.compute(req_low, portfolio, drawdown, liquidity)
    r_high = sizer.compute(req_high, portfolio, drawdown, liquidity)
    assert r_high.recommended_size_usd > r_low.recommended_size_usd


def test_higher_confidence_larger_size(sizer, portfolio, drawdown, liquidity):
    req_low = _make_request(confidence_estimate=0.3)
    req_high = _make_request(confidence_estimate=0.9)
    r_low = sizer.compute(req_low, portfolio, drawdown, liquidity)
    r_high = sizer.compute(req_high, portfolio, drawdown, liquidity)
    assert r_high.recommended_size_usd > r_low.recommended_size_usd


def test_ambiguity_penalty_reduces_size(sizer, portfolio, drawdown, liquidity):
    req_clean = _make_request(ambiguity_score=0.0)
    req_ambig = _make_request(ambiguity_score=0.8)
    r_clean = sizer.compute(req_clean, portfolio, drawdown, liquidity)
    r_ambig = sizer.compute(req_ambig, portfolio, drawdown, liquidity)
    assert r_ambig.recommended_size_usd < r_clean.recommended_size_usd
    assert "ambiguity" in r_ambig.penalties_applied


def test_correlation_penalty(sizer, portfolio, drawdown, liquidity):
    req_uncorr = _make_request(correlation_burden_score=0.0)
    req_corr = _make_request(correlation_burden_score=0.8)
    r_uncorr = sizer.compute(req_uncorr, portfolio, drawdown, liquidity)
    r_corr = sizer.compute(req_corr, portfolio, drawdown, liquidity)
    assert r_corr.recommended_size_usd < r_uncorr.recommended_size_usd


def test_weak_source_penalty(sizer, portfolio, drawdown, liquidity):
    req_strong = _make_request(weak_source_score=0.0)
    req_weak = _make_request(weak_source_score=0.8)
    r_strong = sizer.compute(req_strong, portfolio, drawdown, liquidity)
    r_weak = sizer.compute(req_weak, portfolio, drawdown, liquidity)
    assert r_weak.recommended_size_usd < r_strong.recommended_size_usd


def test_timing_penalty(sizer, portfolio, drawdown, liquidity):
    req_clear = _make_request(timing_uncertainty_score=0.0)
    req_unclear = _make_request(timing_uncertainty_score=0.8)
    r_clear = sizer.compute(req_clear, portfolio, drawdown, liquidity)
    r_unclear = sizer.compute(req_unclear, portfolio, drawdown, liquidity)
    assert r_unclear.recommended_size_usd < r_clear.recommended_size_usd


def test_drawdown_multiplier_reduces_size(sizer, portfolio, liquidity):
    drawdown_normal = DrawdownState(level=DrawdownLevel.NORMAL, size_multiplier=1.0)
    drawdown_warn = DrawdownState(level=DrawdownLevel.SOFT_WARNING, size_multiplier=0.75)
    request = _make_request()

    r_normal = sizer.compute(request, portfolio, drawdown_normal, liquidity)
    r_warn = sizer.compute(request, portfolio, drawdown_warn, liquidity)
    assert r_warn.recommended_size_usd < r_normal.recommended_size_usd
    assert "drawdown" in r_warn.penalties_applied


def test_sports_quality_gate(sizer, portfolio, drawdown, liquidity):
    """Sports with insufficient calibration data should get reduced sizing."""
    req = _make_request(
        category="sports",
        category_quality_tier=CategoryQualityTier.QUALITY_GATED,
        category_resolved_trades=10,  # below 40 threshold
    )
    r = sizer.compute(req, portfolio, drawdown, liquidity)
    assert "sports_quality_gate" in r.penalties_applied
    assert r.penalties_applied["sports_quality_gate"] == 0.5


def test_sports_calibrated_no_gate(sizer, portfolio, drawdown, liquidity):
    """Sports with sufficient calibration should not be penalized."""
    req = _make_request(
        category="sports",
        category_quality_tier=CategoryQualityTier.QUALITY_GATED,
        category_resolved_trades=50,  # above 40 threshold
    )
    r = sizer.compute(req, portfolio, drawdown, liquidity)
    assert "sports_quality_gate" not in r.penalties_applied


def test_capped_by_liquidity(sizer, portfolio, drawdown):
    """When liquidity is very tight, size should be capped by depth."""
    small_liq = LiquidityCheck(max_order_usd=10.0, depth_at_top_levels_usd=100.0)
    request = _make_request(gross_edge=0.10, confidence_estimate=0.9)
    r = sizer.compute(request, portfolio, drawdown, small_liq)
    assert r.recommended_size_usd <= 10.0
    assert r.capped_by == "liquidity_depth"


def test_capped_by_daily_deployment(sizer, drawdown, liquidity):
    """When daily deployment is nearly exhausted, size capped by remaining budget."""
    portfolio = PortfolioState(
        account_balance_usd=10000.0,
        start_of_day_equity_usd=10000.0,
        current_equity_usd=10000.0,
        daily_deployment_used_usd=990.0,  # only $10 remaining of $1000 limit
    )
    request = _make_request(gross_edge=0.10, confidence_estimate=0.9)
    r = sizer.compute(request, portfolio, drawdown, liquidity)
    assert r.recommended_size_usd <= 10.0


def test_capped_by_exposure_headroom(sizer, drawdown, liquidity):
    portfolio = PortfolioState(
        account_balance_usd=10000.0,
        start_of_day_equity_usd=10000.0,
        current_equity_usd=10000.0,
        total_open_exposure_usd=9990.0,  # $10 headroom
    )
    request = _make_request(gross_edge=0.10, confidence_estimate=0.9)
    r = sizer.compute(request, portfolio, drawdown, liquidity)
    assert r.recommended_size_usd <= 10.0


def test_size_factors_populated(sizer, portfolio, drawdown, liquidity):
    request = _make_request()
    r = sizer.compute(request, portfolio, drawdown, liquidity)
    assert "base_size_usd" in r.size_factors
    assert "edge_factor" in r.size_factors
    assert "confidence_factor" in r.size_factors
    assert "evidence_factor" in r.size_factors
    assert "liquidity_factor" in r.size_factors
    assert "budget_factor" in r.size_factors


def test_wide_spread_reduces_liquidity_factor(sizer, portfolio, drawdown, liquidity):
    req_tight = _make_request(spread=0.01)
    req_wide = _make_request(spread=0.14)
    r_tight = sizer.compute(req_tight, portfolio, drawdown, liquidity)
    r_wide = sizer.compute(req_wide, portfolio, drawdown, liquidity)
    assert r_wide.recommended_size_usd < r_tight.recommended_size_usd


def test_zero_edge_zero_size(sizer, portfolio, drawdown, liquidity):
    request = _make_request(gross_edge=0.0)
    r = sizer.compute(request, portfolio, drawdown, liquidity)
    assert r.recommended_size_usd == 0.0


def test_net_edge_used_when_available(sizer, portfolio, drawdown, liquidity):
    """net_edge_after_cost should be used over gross_edge when present."""
    req_gross_only = _make_request(gross_edge=0.05, net_edge_after_cost=None)
    req_with_net = _make_request(gross_edge=0.05, net_edge_after_cost=0.02)
    r_gross = sizer.compute(req_gross_only, portfolio, drawdown, liquidity)
    r_net = sizer.compute(req_with_net, portfolio, drawdown, liquidity)
    assert r_net.recommended_size_usd < r_gross.recommended_size_usd
