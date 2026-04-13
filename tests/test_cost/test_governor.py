"""Tests for the CostGovernor orchestrator."""

import pytest

from config.settings import CostConfig
from core.enums import CostClass, ModelTier
from cost.governor import CostGovernor
from cost.types import (
    AgentCostSpec,
    CostDecision,
    CostEstimateRequest,
    CostRecordInput,
    RunType,
)


@pytest.fixture
def config():
    return CostConfig(
        daily_llm_budget_usd=25.0,
        daily_opus_escalation_budget_usd=5.0,
        max_single_workflow_usd=5.0,
        lifetime_experiment_budget_usd=5000.0,
        cost_of_selectivity_target_ratio=0.20,
        cost_inefficient_edge_fraction=0.20,
    )


@pytest.fixture
def governor(config):
    g = CostGovernor(config)
    g.reset_day()
    return g


def _make_request(
    run_type: RunType = RunType.TRIGGER_BASED,
    cost_min: float = 0.02,
    cost_max: float = 0.04,
    candidate_count: int = 1,
    workflow_run_id: str = "w1",
) -> CostEstimateRequest:
    return CostEstimateRequest(
        workflow_run_id=workflow_run_id,
        run_type=run_type,
        candidate_count=candidate_count,
        agent_specs=[
            AgentCostSpec(
                agent_role="domain_manager",
                tier=ModelTier.B,
                cost_class=CostClass.M,
                estimated_cost_min_usd=cost_min,
                estimated_cost_max_usd=cost_max,
            ),
        ],
    )


def _make_spend_record(cost: float, tier: ModelTier = ModelTier.B) -> CostRecordInput:
    from core.constants import TIER_COST_CLASS
    return CostRecordInput(
        workflow_run_id="w-spend",
        agent_role="test",
        model="test",
        provider="test",
        tier=tier,
        cost_class=TIER_COST_CLASS[tier],
        input_tokens=1000,
        output_tokens=500,
        estimated_cost_usd=cost,
        actual_cost_usd=cost,
    )


# --- Happy path ---

def test_approve_full_within_budget(governor):
    request = _make_request()
    estimate = governor.estimate(request)
    approval = governor.approve(estimate)
    assert approval.decision == CostDecision.APPROVE_FULL
    assert approval.is_approved is True
    assert approval.approved_max_tier == ModelTier.A
    assert "Within all budget constraints" in approval.reason


def test_can_start_workflow(governor):
    ok, reason = governor.can_start_workflow()
    assert ok is True
    assert reason == "Budget available"


# --- Daily budget exhaustion ---

def test_defer_when_min_exceeds_daily(governor):
    """When even minimum cost exceeds daily remaining → defer."""
    # Spend most of the daily budget
    for _ in range(24):
        governor.record_spend(_make_spend_record(1.0))

    # Now only $1 remaining, request min=$2
    request = _make_request(cost_min=2.0, cost_max=4.0)
    estimate = governor.estimate(request)
    approval = governor.approve(estimate)
    assert approval.decision == CostDecision.DEFER


def test_approve_reduced_when_max_exceeds_daily(governor):
    """When max exceeds daily but min doesn't → approve reduced."""
    # Spend $22, leaving $3
    for _ in range(22):
        governor.record_spend(_make_spend_record(1.0))

    request = _make_request(cost_min=1.0, cost_max=5.0)
    estimate = governor.estimate(request)
    approval = governor.approve(estimate)
    assert approval.decision == CostDecision.APPROVE_REDUCED
    assert approval.approved_max_tier == ModelTier.B


# --- Lifetime budget ---

def test_reject_when_lifetime_exhausted(config):
    """When lifetime budget exhausted → reject."""
    governor = CostGovernor(config)
    governor.reset_day()
    governor.budget_tracker.load_lifetime_spent(5000.0)

    request = _make_request()
    estimate = governor.estimate(request)
    approval = governor.approve(estimate)
    assert approval.decision == CostDecision.REJECT
    assert "Lifetime" in approval.reason


def test_can_start_workflow_lifetime_exhausted(config):
    governor = CostGovernor(config)
    governor.reset_day()
    governor.budget_tracker.load_lifetime_spent(5000.0)
    ok, reason = governor.can_start_workflow()
    assert ok is False
    assert "Lifetime" in reason


# --- Daily + lifetime combined restriction ---

def test_restrict_tier_b_when_daily_low_and_lifetime_high(config):
    """Daily < 10% AND lifetime > 75% → restrict to Tier B max."""
    governor = CostGovernor(config)
    governor.reset_day()
    governor.budget_tracker.load_lifetime_spent(3800.0)  # 76% of 5000

    # Spend to leave < 10% of daily ($2.50 remaining of $25)
    for _ in range(23):
        governor.record_spend(_make_spend_record(1.0))

    request = _make_request(cost_min=0.5, cost_max=1.0)
    estimate = governor.estimate(request)
    approval = governor.approve(estimate)
    assert approval.decision == CostDecision.APPROVE_REDUCED
    assert approval.approved_max_tier == ModelTier.B
    assert "critically low" in approval.reason


# --- Cost-inefficiency rejection ---

def test_reject_cost_exceeds_edge_fraction(governor):
    """When cost > 20% of net edge → reject as cost-inefficient."""
    request = _make_request(cost_min=0.10, cost_max=0.15)
    estimate = governor.estimate(request)
    # net edge $0.50 → 0.15/0.50 = 30% > 20%
    approval = governor.approve(estimate, expected_net_edge=0.50)
    assert approval.decision == CostDecision.REJECT
    assert "net edge" in approval.reason


def test_approve_when_cost_within_edge_fraction(governor):
    """When cost < 20% of net edge → approve."""
    request = _make_request(cost_min=0.01, cost_max=0.02)
    estimate = governor.estimate(request)
    approval = governor.approve(estimate, expected_net_edge=1.0)
    assert approval.decision == CostDecision.APPROVE_FULL


# --- Opus sub-budget ---

def test_reduce_when_opus_budget_exhausted(governor):
    """When Opus daily budget exhausted → restrict to Tier B."""
    # Exhaust Opus budget ($5)
    for _ in range(6):
        governor.record_spend(_make_spend_record(1.0, tier=ModelTier.A))

    request = _make_request(cost_min=0.01, cost_max=0.02)
    estimate = governor.estimate(request)
    approval = governor.approve(estimate)
    assert approval.decision == CostDecision.APPROVE_REDUCED
    assert approval.approved_max_tier == ModelTier.B
    assert "Opus" in approval.reason


# --- Record spend flows through ---

def test_record_spend_updates_budget(governor):
    governor.record_spend(_make_spend_record(3.0))
    state = governor.budget_tracker.state
    assert state.daily_spent_usd == 3.0


# --- Selectivity integration ---

def test_selectivity_tracking(governor):
    governor.record_trade_entered(2)
    governor.record_gross_edge(10.0)
    governor.record_spend(_make_spend_record(1.0))

    snapshot = governor.get_selectivity_snapshot()
    assert snapshot.trades_entered == 2
    assert snapshot.daily_inference_spend_usd == 1.0


def test_opus_escalation_threshold(governor):
    governor.record_spend(_make_spend_record(5.0))
    governor.record_gross_edge(10.0)  # ratio = 0.5 > 0.2 target

    threshold = governor.get_opus_escalation_threshold(0.03)
    # excess = 0.5 - 0.2 = 0.3, multiplier = 1 + 0.3/0.2 = 2.5
    assert threshold == pytest.approx(0.075, abs=1e-3)


# --- Review cost integration ---

def test_review_cost_tracking(governor):
    governor.register_position("p1", position_value_usd=500.0)
    status = governor.record_review("p1", cost_usd=0.0, is_deterministic=True)
    assert status.total_reviews == 1
    assert status.deterministic_reviews == 1

    status = governor.record_review("p1", cost_usd=0.03, is_deterministic=False)
    assert status.total_reviews == 2
    assert status.llm_reviews == 1


def test_force_deterministic_review(governor):
    governor.register_position("p1", position_value_usd=100.0)
    assert governor.should_force_deterministic_review("p1") is False

    # Push past 15% cap: 15.0 / 100.0 = 0.15
    governor.record_review("p1", cost_usd=15.0, is_deterministic=False)
    assert governor.should_force_deterministic_review("p1") is True


def test_flag_exit_review(governor):
    governor.register_position("p1", position_value_usd=100.0)
    assert governor.should_flag_exit_review("p1") is False

    # Push past 8%: 8.0 / 100.0 = 0.08
    governor.record_review("p1", cost_usd=8.0, is_deterministic=False)
    assert governor.should_flag_exit_review("p1") is True


# --- Estimate accuracy integration ---

def test_estimate_accuracy_feedback(governor):
    governor.record_estimate_accuracy(
        workflow_run_id="w1",
        run_type=RunType.TRIGGER_BASED,
        estimated_min_usd=0.01,
        estimated_max_usd=0.05,
        actual_usd=0.03,
    )
    stats = governor.feedback_tracker.get_stats(RunType.TRIGGER_BASED)
    assert stats["count"] == 1
    assert stats["within_bounds_pct"] == 1.0


# --- Day reset ---

def test_reset_day(governor):
    governor.record_spend(_make_spend_record(10.0))
    assert governor.budget_tracker.daily_spent == 10.0

    governor.reset_day()
    assert governor.budget_tracker.daily_spent == 0.0
    # Lifetime persists
    assert governor.budget_tracker.lifetime_spent == 10.0


# --- Position review estimate ---

def test_position_review_estimate(governor):
    request = CostEstimateRequest(
        workflow_run_id="w-review",
        run_type=RunType.POSITION_REVIEW,
    )
    estimate = governor.estimate(request)
    assert estimate.run_type == RunType.POSITION_REVIEW
    # Should use effective cost profile, not worst-case
    assert estimate.expected_cost_min_usd < 0.05
    assert estimate.expected_cost_max_usd < 0.30


# --- Full workflow: estimate → approve → record → feedback ---

def test_full_workflow_lifecycle(governor):
    # 1. Estimate
    request = _make_request(cost_min=0.02, cost_max=0.04, workflow_run_id="w-full")
    estimate = governor.estimate(request)
    assert estimate.expected_cost_min_usd == 0.02

    # 2. Approve
    approval = governor.approve(estimate, expected_net_edge=1.0)
    assert approval.is_approved

    # 3. Record spend
    governor.record_spend(CostRecordInput(
        workflow_run_id="w-full",
        agent_role="domain_manager",
        model="claude-sonnet-4-6",
        provider="anthropic",
        tier=ModelTier.B,
        cost_class=CostClass.M,
        input_tokens=2000,
        output_tokens=1000,
        estimated_cost_usd=0.03,
        actual_cost_usd=0.025,
    ))

    # 4. Record accuracy
    governor.record_estimate_accuracy(
        workflow_run_id="w-full",
        run_type=RunType.TRIGGER_BASED,
        estimated_min_usd=0.02,
        estimated_max_usd=0.04,
        actual_usd=0.025,
    )

    # Verify state updated
    assert governor.budget_tracker.daily_spent == 0.025
    stats = governor.feedback_tracker.get_stats(RunType.TRIGGER_BASED)
    assert stats["count"] == 1
    assert stats["within_bounds_pct"] == 1.0
