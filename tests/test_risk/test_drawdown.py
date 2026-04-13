"""Tests for the drawdown defense ladder."""

import pytest

from config.settings import RiskConfig
from core.enums import DrawdownLevel
from risk.drawdown import DrawdownTracker


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
    # 3% drawdown = $300 loss → equity $9700
    state = tracker.update(9700.0)
    assert state.level == DrawdownLevel.SOFT_WARNING
    assert state.entries_allowed is True
    assert state.size_multiplier == 0.75
    assert state.min_evidence_score == 0.6


def test_risk_reduction_threshold(tracker):
    # 5% drawdown = $500 loss → equity $9500
    state = tracker.update(9500.0)
    assert state.level == DrawdownLevel.RISK_REDUCTION
    assert state.entries_allowed is True
    assert state.size_multiplier == 0.40


def test_entries_disabled_threshold(tracker):
    # 6.5% drawdown = $650 loss → equity $9350
    state = tracker.update(9350.0)
    assert state.level == DrawdownLevel.ENTRIES_DISABLED
    assert state.entries_allowed is False
    assert state.size_multiplier == 0.0


def test_hard_kill_switch(tracker):
    # 8% drawdown = $800 loss → equity $9200
    state = tracker.update(9200.0)
    assert state.level == DrawdownLevel.HARD_KILL_SWITCH
    assert state.entries_allowed is False
    assert state.size_multiplier == 0.0


def test_recovery_reduces_level(tracker):
    # Go to risk reduction
    tracker.update(9500.0)
    assert tracker.level == DrawdownLevel.RISK_REDUCTION

    # Recover to soft warning range
    state = tracker.update(9700.0)
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

    # Exactly at 3% boundary
    state = tracker.update(9700.0)
    assert state.level == DrawdownLevel.SOFT_WARNING

    # Exactly at 5% boundary
    state = tracker.update(9500.0)
    assert state.level == DrawdownLevel.RISK_REDUCTION

    # Exactly at 6.5% boundary
    state = tracker.update(9350.0)
    assert state.level == DrawdownLevel.ENTRIES_DISABLED

    # Exactly at 8% boundary
    state = tracker.update(9200.0)
    assert state.level == DrawdownLevel.HARD_KILL_SWITCH


def test_level_property(tracker):
    assert tracker.level == DrawdownLevel.NORMAL
    tracker.update(9500.0)
    assert tracker.level == DrawdownLevel.RISK_REDUCTION
