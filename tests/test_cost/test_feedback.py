"""Tests for EstimateAccuracyTracker."""

import pytest

from cost.feedback import EstimateAccuracyTracker
from cost.types import RunType


@pytest.fixture
def tracker():
    return EstimateAccuracyTracker(history_limit=10)


# --- Basic recording ---

def test_record_within_bounds(tracker):
    record = tracker.record("w1", RunType.TRIGGER_BASED, 0.01, 0.05, 0.03)
    assert record.within_bounds is True
    assert record.accuracy_ratio == pytest.approx(1.0)  # 0.03 / 0.03 midpoint


def test_record_overestimate(tracker):
    record = tracker.record("w1", RunType.TRIGGER_BASED, 0.10, 0.20, 0.05)
    assert record.within_bounds is False
    assert record.actual_usd < record.estimated_min_usd


def test_record_underestimate(tracker):
    record = tracker.record("w1", RunType.TRIGGER_BASED, 0.01, 0.05, 0.10)
    assert record.within_bounds is False
    assert record.actual_usd > record.estimated_max_usd


# --- Statistics ---

def test_stats_empty(tracker):
    stats = tracker.get_stats(RunType.TRIGGER_BASED)
    assert stats["count"] == 0
    assert stats["within_bounds_pct"] == 0.0


def test_stats_all_within(tracker):
    tracker.record("w1", RunType.TRIGGER_BASED, 0.01, 0.05, 0.03)
    tracker.record("w2", RunType.TRIGGER_BASED, 0.01, 0.05, 0.02)
    tracker.record("w3", RunType.TRIGGER_BASED, 0.01, 0.05, 0.04)
    stats = tracker.get_stats(RunType.TRIGGER_BASED)
    assert stats["count"] == 3
    assert stats["within_bounds_pct"] == 1.0
    assert stats["overestimate_count"] == 0
    assert stats["underestimate_count"] == 0


def test_stats_mixed(tracker):
    tracker.record("w1", RunType.TRIGGER_BASED, 0.02, 0.04, 0.03)  # within
    tracker.record("w2", RunType.TRIGGER_BASED, 0.02, 0.04, 0.01)  # over
    tracker.record("w3", RunType.TRIGGER_BASED, 0.02, 0.04, 0.10)  # under
    stats = tracker.get_stats(RunType.TRIGGER_BASED)
    assert stats["count"] == 3
    assert stats["within_bounds_pct"] == pytest.approx(1 / 3, abs=1e-2)
    assert stats["overestimate_count"] == 1
    assert stats["underestimate_count"] == 1


# --- Separate tracking per run type ---

def test_separate_run_types(tracker):
    tracker.record("w1", RunType.TRIGGER_BASED, 0.01, 0.05, 0.03)
    tracker.record("w2", RunType.SCHEDULED_SWEEP, 0.10, 0.30, 0.20)
    tracker.record("w3", RunType.POSITION_REVIEW, 0.005, 0.02, 0.01)

    assert tracker.get_stats(RunType.TRIGGER_BASED)["count"] == 1
    assert tracker.get_stats(RunType.SCHEDULED_SWEEP)["count"] == 1
    assert tracker.get_stats(RunType.POSITION_REVIEW)["count"] == 1
    assert tracker.get_stats(RunType.OPERATOR_FORCED)["count"] == 0


def test_get_all_stats(tracker):
    tracker.record("w1", RunType.TRIGGER_BASED, 0.01, 0.05, 0.03)
    all_stats = tracker.get_all_stats()
    assert "trigger_based" in all_stats
    assert "scheduled_sweep" in all_stats
    assert all_stats["trigger_based"]["count"] == 1


# --- History limit ---

def test_history_limit():
    tracker = EstimateAccuracyTracker(history_limit=3)
    for i in range(5):
        tracker.record(f"w{i}", RunType.TRIGGER_BASED, 0.01, 0.05, 0.03)
    stats = tracker.get_stats(RunType.TRIGGER_BASED)
    assert stats["count"] == 3  # only last 3 kept
