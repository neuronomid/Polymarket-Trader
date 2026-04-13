"""Tests for BudgetTracker."""

import pytest

from config.settings import CostConfig
from core.enums import CostClass, ModelTier
from cost.budget import BudgetTracker
from cost.types import CostRecordInput, LifetimeBudgetAlert


@pytest.fixture
def config():
    return CostConfig()


@pytest.fixture
def tracker(config):
    t = BudgetTracker(config)
    t.reset_day()
    return t


def _make_record(
    cost: float,
    tier: ModelTier = ModelTier.B,
    workflow_run_id: str = "w1",
    position_id: str | None = None,
) -> CostRecordInput:
    from core.constants import TIER_COST_CLASS
    return CostRecordInput(
        workflow_run_id=workflow_run_id,
        agent_role="test_agent",
        model="test-model",
        provider="test-provider",
        tier=tier,
        cost_class=TIER_COST_CLASS[tier],
        input_tokens=1000,
        output_tokens=500,
        estimated_cost_usd=cost,
        actual_cost_usd=cost,
        position_id=position_id,
    )


# --- Basic tracking ---

def test_initial_state(tracker):
    state = tracker.state
    assert state.daily_spent_usd == 0.0
    assert state.daily_budget_usd == 25.0
    assert state.daily_remaining_usd == 25.0
    assert state.daily_pct_remaining == 1.0
    assert state.lifetime_spent_usd == 0.0


def test_record_spend_updates_daily(tracker):
    tracker.record_spend(_make_record(1.50))
    state = tracker.state
    assert state.daily_spent_usd == 1.50
    assert state.daily_remaining_usd == 23.50


def test_record_spend_accumulates(tracker):
    tracker.record_spend(_make_record(1.0))
    tracker.record_spend(_make_record(2.0))
    tracker.record_spend(_make_record(0.5))
    assert tracker.daily_spent == 3.5


def test_record_spend_updates_lifetime(tracker):
    tracker.record_spend(_make_record(1.0))
    assert tracker.lifetime_spent == 1.0
    tracker.record_spend(_make_record(2.0))
    assert tracker.lifetime_spent == 3.0


def test_opus_spend_tracked_separately(tracker):
    tracker.record_spend(_make_record(1.0, tier=ModelTier.B))
    tracker.record_spend(_make_record(0.5, tier=ModelTier.A))
    state = tracker.state
    assert state.daily_spent_usd == 1.5
    assert state.daily_opus_spent_usd == 0.5


def test_position_daily_spend(tracker):
    tracker.record_spend(_make_record(0.5, position_id="p1"))
    tracker.record_spend(_make_record(0.3, position_id="p1"))
    tracker.record_spend(_make_record(1.0, position_id="p2"))
    assert tracker.get_position_daily_spend("p1") == pytest.approx(0.8)
    assert tracker.get_position_daily_spend("p2") == pytest.approx(1.0)
    assert tracker.get_position_daily_spend("p3") == 0.0


def test_workflow_spend(tracker):
    tracker.record_spend(_make_record(0.5, workflow_run_id="w1"))
    tracker.record_spend(_make_record(0.3, workflow_run_id="w1"))
    tracker.record_spend(_make_record(1.0, workflow_run_id="w2"))
    assert tracker.get_workflow_spend("w1") == pytest.approx(0.8)
    assert tracker.get_workflow_spend("w2") == pytest.approx(1.0)


# --- Day reset ---

def test_reset_day_clears_daily_not_lifetime(tracker):
    tracker.record_spend(_make_record(5.0))
    assert tracker.daily_spent == 5.0
    assert tracker.lifetime_spent == 5.0

    tracker.reset_day()
    assert tracker.daily_spent == 0.0
    assert tracker.lifetime_spent == 5.0  # lifetime preserved


def test_reset_day_clears_position_daily(tracker):
    tracker.record_spend(_make_record(1.0, position_id="p1"))
    tracker.reset_day()
    assert tracker.get_position_daily_spend("p1") == 0.0


# --- Budget checks ---

def test_check_workflow_budget_within(tracker):
    tracker.record_spend(_make_record(2.0, workflow_run_id="w1"))
    assert tracker.check_workflow_budget("w1") is True


def test_check_workflow_budget_exceeded(tracker):
    tracker.record_spend(_make_record(6.0, workflow_run_id="w1"))
    assert tracker.check_workflow_budget("w1") is False


def test_check_position_daily_budget_within(tracker):
    tracker.record_spend(_make_record(1.0, position_id="p1"))
    assert tracker.check_position_daily_budget("p1") is True


def test_check_position_daily_budget_exceeded(tracker):
    tracker.record_spend(_make_record(3.0, position_id="p1"))
    assert tracker.check_position_daily_budget("p1") is False


def test_check_opus_budget_within(tracker):
    tracker.record_spend(_make_record(2.0, tier=ModelTier.A))
    assert tracker.check_opus_budget() is True


def test_check_opus_budget_exceeded(tracker):
    tracker.record_spend(_make_record(6.0, tier=ModelTier.A))
    assert tracker.check_opus_budget() is False


# --- Lifetime alerts ---

def test_lifetime_alert_none(tracker):
    assert tracker.check_lifetime_alert() == LifetimeBudgetAlert.NONE


def test_lifetime_alert_50pct():
    config = CostConfig(lifetime_experiment_budget_usd=100.0)
    tracker = BudgetTracker(config)
    tracker.load_lifetime_spent(55.0)
    assert tracker.check_lifetime_alert() == LifetimeBudgetAlert.PCT_50


def test_lifetime_alert_75pct():
    config = CostConfig(lifetime_experiment_budget_usd=100.0)
    tracker = BudgetTracker(config)
    tracker.load_lifetime_spent(80.0)
    assert tracker.check_lifetime_alert() == LifetimeBudgetAlert.PCT_75


def test_lifetime_alert_100pct():
    config = CostConfig(lifetime_experiment_budget_usd=100.0)
    tracker = BudgetTracker(config)
    tracker.load_lifetime_spent(100.0)
    assert tracker.check_lifetime_alert() == LifetimeBudgetAlert.PCT_100


# --- Load lifetime ---

def test_load_lifetime_spent(tracker):
    tracker.load_lifetime_spent(500.0)
    assert tracker.lifetime_spent == 500.0
    state = tracker.state
    assert state.lifetime_pct_consumed == pytest.approx(0.10)
