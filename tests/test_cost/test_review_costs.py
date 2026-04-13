"""Tests for CumulativeReviewTracker."""

import pytest

from config.settings import CostConfig
from cost.review_costs import CumulativeReviewTracker


@pytest.fixture
def config():
    return CostConfig(
        cumulative_review_cost_warning_pct=0.08,
        cumulative_review_cost_cap_pct=0.15,
    )


@pytest.fixture
def tracker(config):
    t = CumulativeReviewTracker(config)
    t.register_position("p1", position_value_usd=500.0)
    return t


# --- Basic tracking ---

def test_register_position(tracker):
    status = tracker.get_status("p1")
    assert status is not None
    assert status.total_review_cost_usd == 0.0
    assert status.total_reviews == 0


def test_unregistered_position_returns_none(tracker):
    assert tracker.get_status("unknown") is None


def test_record_deterministic_review(tracker):
    status = tracker.record_review("p1", cost_usd=0.0, is_deterministic=True)
    assert status.total_reviews == 1
    assert status.deterministic_reviews == 1
    assert status.llm_reviews == 0
    assert status.total_review_cost_usd == 0.0


def test_record_llm_review(tracker):
    status = tracker.record_review("p1", cost_usd=0.03, is_deterministic=False)
    assert status.total_reviews == 1
    assert status.deterministic_reviews == 0
    assert status.llm_reviews == 1
    assert status.total_review_cost_usd == pytest.approx(0.03)


def test_reviews_accumulate(tracker):
    tracker.record_review("p1", cost_usd=0.0, is_deterministic=True)
    tracker.record_review("p1", cost_usd=0.0, is_deterministic=True)
    tracker.record_review("p1", cost_usd=0.03, is_deterministic=False)
    status = tracker.record_review("p1", cost_usd=0.05, is_deterministic=False)
    assert status.total_reviews == 4
    assert status.deterministic_reviews == 2
    assert status.llm_reviews == 2
    assert status.total_review_cost_usd == pytest.approx(0.08)


# --- Threshold checks ---

def test_warning_threshold_not_hit(tracker):
    # 0.03 / 500 = 0.006 < 0.08
    status = tracker.record_review("p1", cost_usd=0.03, is_deterministic=False)
    assert status.warning_threshold_hit is False
    assert status.cap_threshold_hit is False


def test_warning_threshold_hit(tracker):
    # 40 / 500 = 0.08 → exactly at warning
    status = tracker.record_review("p1", cost_usd=40.0, is_deterministic=False)
    assert status.warning_threshold_hit is True
    assert status.cap_threshold_hit is False


def test_cap_threshold_hit(tracker):
    # 75 / 500 = 0.15 → exactly at cap
    status = tracker.record_review("p1", cost_usd=75.0, is_deterministic=False)
    assert status.warning_threshold_hit is True
    assert status.cap_threshold_hit is True


def test_should_force_deterministic(tracker):
    assert tracker.should_force_deterministic("p1") is False
    tracker.record_review("p1", cost_usd=80.0, is_deterministic=False)
    assert tracker.should_force_deterministic("p1") is True


def test_should_flag_for_exit_review(tracker):
    assert tracker.should_flag_for_exit_review("p1") is False
    tracker.record_review("p1", cost_usd=45.0, is_deterministic=False)
    assert tracker.should_flag_for_exit_review("p1") is True


# --- Position lifecycle ---

def test_remove_position(tracker):
    tracker.remove_position("p1")
    assert tracker.get_status("p1") is None


def test_update_position_value(tracker):
    tracker.record_review("p1", cost_usd=40.0, is_deterministic=False)
    # 40/500 = 0.08 → warning
    assert tracker.should_flag_for_exit_review("p1") is True

    # Update value so ratio drops: 40/1000 = 0.04 → no warning
    tracker.update_position_value("p1", 1000.0)
    assert tracker.should_flag_for_exit_review("p1") is False


def test_load_position(config):
    tracker = CumulativeReviewTracker(config)
    tracker.load_position(
        position_id="p1",
        position_value_usd=500.0,
        total_review_cost_usd=30.0,
        total_reviews=10,
        deterministic_reviews=7,
        llm_reviews=3,
    )
    status = tracker.get_status("p1")
    assert status.total_review_cost_usd == 30.0
    assert status.total_reviews == 10
    assert status.deterministic_reviews == 7


def test_record_review_unregistered_raises(tracker):
    with pytest.raises(ValueError, match="not registered"):
        tracker.record_review("unknown", cost_usd=0.01, is_deterministic=False)


def test_should_force_deterministic_unregistered(tracker):
    assert tracker.should_force_deterministic("unknown") is False
