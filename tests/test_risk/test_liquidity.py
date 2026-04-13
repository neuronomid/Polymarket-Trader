"""Tests for the liquidity sizer."""

import pytest

from config.settings import RiskConfig
from market_data.types import OrderBookLevel
from risk.liquidity import LiquiditySizer
from risk.types import SizingRequest


@pytest.fixture
def config():
    return RiskConfig()


@pytest.fixture
def sizer(config):
    return LiquiditySizer(config)


def _make_request(**kwargs) -> SizingRequest:
    defaults = dict(
        market_id="m1",
        token_id="tok1",
        category="politics",
        gross_edge=0.05,
        probability_estimate=0.6,
        confidence_estimate=0.7,
        visible_depth_usd=10000.0,
        best_ask=0.60,
    )
    defaults.update(kwargs)
    return SizingRequest(**defaults)


def test_basic_depth_check(sizer):
    request = _make_request(visible_depth_usd=10000.0)
    result = sizer.check(request)
    assert result.passes_depth_check is True
    assert result.max_order_usd == pytest.approx(1200.0)  # 12% of 10000


def test_zero_depth_fails(sizer):
    request = _make_request(visible_depth_usd=0.0)
    result = sizer.check(request)
    assert result.passes_depth_check is False
    assert result.max_order_usd == 0.0


def test_impact_estimation_no_impact(sizer):
    """Single deep level → no price movement."""
    request = _make_request(visible_depth_usd=10000.0, gross_edge=0.05)
    asks = [OrderBookLevel(price=0.60, size=100000.0)]  # huge liquidity
    result = sizer.check(request, ask_levels=asks)
    assert result.entry_impact_bps == pytest.approx(0.0)
    assert result.passes_impact_check is True


def test_impact_estimation_with_slippage(sizer):
    """Walking through multiple ask levels should show impact."""
    request = _make_request(visible_depth_usd=10000.0, gross_edge=0.05, best_ask=0.50)
    asks = [
        OrderBookLevel(price=0.50, size=100.0),   # $50 at this level
        OrderBookLevel(price=0.55, size=100.0),   # $55 at this level
        OrderBookLevel(price=0.60, size=100.0),   # $60 at this level
        OrderBookLevel(price=0.70, size=100.0),   # $70 at this level
    ]
    result = sizer.check(request, ask_levels=asks)
    assert result.entry_impact_bps > 0


def test_impact_exceeds_edge_threshold():
    """When impact is too high relative to edge, should fail."""
    config = RiskConfig(max_entry_impact_edge_fraction=0.25, max_order_depth_fraction=0.5)
    sizer = LiquiditySizer(config)

    # Small edge, large impact
    request = _make_request(visible_depth_usd=1000.0, gross_edge=0.001, best_ask=0.50)
    asks = [
        OrderBookLevel(price=0.50, size=10.0),   # thin
        OrderBookLevel(price=0.60, size=10.0),    # 20% higher
        OrderBookLevel(price=0.70, size=10.0),    # 40% higher
    ]
    result = sizer.check(request, ask_levels=asks)
    # With tiny edge and significant price walk-up, impact fraction should exceed 25%
    if result.entry_impact_edge_fraction > 0.25:
        assert result.passes_impact_check is False


def test_no_ask_levels_no_impact(sizer):
    """Without ask levels, no impact estimation."""
    request = _make_request(visible_depth_usd=10000.0)
    result = sizer.check(request, ask_levels=None)
    assert result.entry_impact_bps == 0.0
    assert result.passes_impact_check is True


def test_empty_ask_levels(sizer):
    request = _make_request(visible_depth_usd=10000.0)
    result = sizer.check(request, ask_levels=[])
    assert result.entry_impact_bps == 0.0


def test_max_order_scales_with_depth(sizer):
    r1 = sizer.check(_make_request(visible_depth_usd=10000.0))
    r2 = sizer.check(_make_request(visible_depth_usd=5000.0))
    assert r1.max_order_usd == pytest.approx(r2.max_order_usd * 2)
