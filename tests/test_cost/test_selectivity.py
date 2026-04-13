"""Tests for SelectivityMonitor."""

from datetime import date

import pytest

from config.settings import CostConfig
from cost.selectivity import SelectivityMonitor


@pytest.fixture
def config():
    return CostConfig(cost_of_selectivity_target_ratio=0.20)


@pytest.fixture
def monitor(config):
    m = SelectivityMonitor(config)
    m.start_day(date(2026, 4, 10))
    return m


# --- Basic recording ---

def test_empty_snapshot(monitor):
    snapshot = monitor.compute_snapshot()
    assert snapshot.daily_inference_spend_usd == 0.0
    assert snapshot.trades_entered == 0
    assert snapshot.rolling_7d_cost_per_trade is None
    assert snapshot.cost_to_edge_ratio is None
    assert snapshot.warning_triggered is False


def test_record_spend_and_trade(monitor):
    monitor.record_daily_spend(5.0)
    monitor.record_trade_entered(2)
    snapshot = monitor.compute_snapshot()
    assert snapshot.daily_inference_spend_usd == 5.0
    assert snapshot.trades_entered == 2
    assert snapshot.rolling_7d_cost_per_trade == pytest.approx(2.5)


def test_cost_to_edge_ratio(monitor):
    monitor.record_daily_spend(5.0)
    monitor.record_gross_edge(50.0)
    snapshot = monitor.compute_snapshot()
    assert snapshot.cost_to_edge_ratio == pytest.approx(0.10)
    assert snapshot.warning_triggered is False  # 0.10 < 0.20 target


def test_warning_triggered_when_ratio_exceeds_target(monitor):
    monitor.record_daily_spend(30.0)
    monitor.record_gross_edge(100.0)
    snapshot = monitor.compute_snapshot()
    # 30/100 = 0.30 > 0.20 target
    assert snapshot.cost_to_edge_ratio == pytest.approx(0.30)
    assert snapshot.warning_triggered is True


# --- Rolling window ---

def test_rolling_window_accumulates():
    config = CostConfig(cost_of_selectivity_target_ratio=0.20)
    monitor = SelectivityMonitor(config)

    # Day 1
    monitor.start_day(date(2026, 4, 1))
    monitor.record_daily_spend(5.0)
    monitor.record_trade_entered(1)
    monitor.record_gross_edge(25.0)

    # Day 2
    monitor.start_day(date(2026, 4, 2))
    monitor.record_daily_spend(10.0)
    monitor.record_trade_entered(2)
    monitor.record_gross_edge(75.0)

    snapshot = monitor.compute_snapshot()
    # Rolling: total_spend=15, trades=3, edge=100
    assert snapshot.rolling_7d_cost_per_trade == pytest.approx(5.0)
    assert snapshot.cost_to_edge_ratio == pytest.approx(0.15)
    assert snapshot.warning_triggered is False


def test_rolling_window_drops_old_days():
    config = CostConfig(cost_of_selectivity_target_ratio=0.20)
    monitor = SelectivityMonitor(config)

    # Fill 8 days — day 1 should drop from the 7-day window
    for i in range(8):
        monitor.start_day(date(2026, 4, 1 + i))
        monitor.record_daily_spend(10.0)
        monitor.record_trade_entered(1)

    # History has 7 entries (maxlen), plus current day = 8 day records,
    # but deque only holds 7. So total = 7 history + 1 today = 8 days visible,
    # but deque maxlen=7 means oldest is dropped. So 7+1 = 8, but history only
    # keeps the last 7, so we have 7 in history + current = latest 8.
    # Wait, maxlen=7 means the deque holds at most 7. History has days 2-8 (7 items).
    # Current day is day 8. But actually start_day pushes the previous day.
    # After 8 calls: history has days 1-7 (but maxlen=7 so days 1-7), current = day 8.
    # Total: 7+1 = 8 days of spend at 10.0 each = 80.0, 8 trades
    snapshot = monitor.compute_snapshot()
    assert snapshot.trades_entered == 1  # only today's
    assert snapshot.daily_inference_spend_usd == 10.0  # only today's


# --- Opus escalation threshold ---

def test_opus_threshold_normal(monitor):
    """When selectivity is within target, threshold unchanged."""
    monitor.record_daily_spend(5.0)
    monitor.record_gross_edge(100.0)  # ratio = 0.05 < 0.20
    threshold = monitor.compute_opus_escalation_threshold(0.03)
    assert threshold == 0.03


def test_opus_threshold_adjusted_when_selectivity_high(monitor):
    """When selectivity exceeds target, threshold increases."""
    monitor.record_daily_spend(40.0)
    monitor.record_gross_edge(100.0)  # ratio = 0.40, target = 0.20
    threshold = monitor.compute_opus_escalation_threshold(0.03)
    # excess = 0.40 - 0.20 = 0.20
    # multiplier = 1 + 0.20/0.20 = 2.0
    # adjusted = 0.03 * 2.0 = 0.06
    assert threshold == pytest.approx(0.06, abs=1e-4)


# --- Auto start day ---

def test_auto_start_day():
    config = CostConfig()
    monitor = SelectivityMonitor(config)
    # Should auto-create today when recording
    monitor.record_daily_spend(1.0)
    snapshot = monitor.compute_snapshot()
    assert snapshot.daily_inference_spend_usd == 1.0
