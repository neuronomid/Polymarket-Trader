"""Tests for the drawdown defense ladder."""

import pytest

from config.settings import RiskConfig
from core.enums import DrawdownLevel
from risk.drawdown import DrawdownTracker


def _equity_for_drawdown(config: RiskConfig, pct: float) -> float:
    return 10000.0 * (1.0 - pct)


@pytest.fixture
def config():
    return RiskConfig()


@pytest.fixture
def tracker(config):
    t = DrawdownTracker(config)
    t.reset_day(10000.0)
    return t


def test_reset_day(tracker):
    state = tracker.state
    assert state.level == DrawdownLevel.NORMAL
    assert state.start_of_day_equity == 10000.0
    assert state.current_equity == 10000.0
    assert state.entries_allowed is True
    assert state.size_multiplier == 1.0


def test_no_drawdown(tracker):
    state = tracker.update(10000.0)
    assert state.level == DrawdownLevel.NORMAL
    assert state.current_drawdown_pct == 0.0


def test_soft_warning_threshold(tracker):
    # 1% drawdown = $100 loss → equity $9900
    state = tracker.update(_equity_for_drawdown(tracker._config, tracker._config.soft_warning_pct))
    assert state.level == DrawdownLevel.SOFT_WARNING
    assert state.entries_allowed is True
    assert state.size_multiplier == 0.75
    assert state.min_evidence_score == 0.6


def test_risk_reduction_threshold(tracker):
    # 2% drawdown = $200 loss → equity $9800
    state = tracker.update(_equity_for_drawdown(tracker._config, tracker._config.risk_reduction_pct))
    assert state.level == DrawdownLevel.RISK_REDUCTION
    assert state.entries_allowed is True
    assert state.size_multiplier == 0.40


def test_entries_disabled_threshold(tracker):
    # 3.5% drawdown = $350 loss → equity $9650
    state = tracker.update(_equity_for_drawdown(tracker._config, tracker._config.entries_disabled_pct))
    assert state.level == DrawdownLevel.ENTRIES_DISABLED
    assert state.entries_allowed is False
    assert state.size_multiplier == 0.0


def test_hard_kill_switch(tracker):
    # 4% drawdown = $400 loss → equity $9600
    state = tracker.update(_equity_for_drawdown(tracker._config, tracker._config.hard_kill_switch_pct))
    assert state.level == DrawdownLevel.HARD_KILL_SWITCH
    assert state.entries_allowed is False
    assert state.size_multiplier == 0.0


def test_recovery_reduces_level(tracker):
    # Go to risk reduction
    tracker.update(_equity_for_drawdown(tracker._config, tracker._config.risk_reduction_pct))
    assert tracker.level == DrawdownLevel.RISK_REDUCTION

    # Recover to soft warning range
    state = tracker.update(_equity_for_drawdown(tracker._config, tracker._config.soft_warning_pct))
    assert state.level == DrawdownLevel.SOFT_WARNING

    # Recover fully
    state = tracker.update(10000.0)
    assert state.level == DrawdownLevel.NORMAL
    assert state.size_multiplier == 1.0


def test_equity_above_start(tracker):
    """Profit should keep us at NORMAL with 0% drawdown."""
    state = tracker.update(10500.0)
    assert state.level == DrawdownLevel.NORMAL
    assert state.current_drawdown_pct == 0.0


def test_zero_start_of_day_equity():
    """Edge case: zero start equity should not divide by zero."""
    config = RiskConfig()
    tracker = DrawdownTracker(config)
    tracker.reset_day(0.0)
    state = tracker.update(100.0)
    # Should remain in whatever state since sod is 0
    assert state.level == DrawdownLevel.NORMAL


def test_exact_boundary_values(config):
    """Test that exact threshold values trigger the level."""
    tracker = DrawdownTracker(config)
    tracker.reset_day(10000.0)

    # Exactly at 1% boundary
    state = tracker.update(_equity_for_drawdown(config, config.soft_warning_pct))
    assert state.level == DrawdownLevel.SOFT_WARNING

    # Exactly at 2% boundary
    state = tracker.update(_equity_for_drawdown(config, config.risk_reduction_pct))
    assert state.level == DrawdownLevel.RISK_REDUCTION

    # Exactly at 3.5% boundary
    state = tracker.update(_equity_for_drawdown(config, config.entries_disabled_pct))
    assert state.level == DrawdownLevel.ENTRIES_DISABLED

    # Exactly at 4% boundary
    state = tracker.update(_equity_for_drawdown(config, config.hard_kill_switch_pct))
    assert state.level == DrawdownLevel.HARD_KILL_SWITCH


def test_level_property(tracker):
    assert tracker.level == DrawdownLevel.NORMAL
    tracker.update(_equity_for_drawdown(tracker._config, tracker._config.risk_reduction_pct))
    assert tracker.level == DrawdownLevel.RISK_REDUCTION
