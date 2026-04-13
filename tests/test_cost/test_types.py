"""Tests for Cost Governor runtime types."""

from cost.types import (
    AgentCostSpec,
    BudgetState,
    CostApproval,
    CostDecision,
    CostEstimate,
    CostEstimateRequest,
    CostRecordInput,
    EstimateAccuracy,
    ReviewCostStatus,
    RunType,
    SelectivitySnapshot,
)
from core.enums import CostClass, ModelTier


def test_budget_state_daily_critically_low():
    state = BudgetState(
        daily_spent_usd=23.0,
        daily_budget_usd=25.0,
        daily_remaining_usd=2.0,
        daily_pct_remaining=0.08,
    )
    assert state.daily_budget_critically_low is True


def test_budget_state_daily_not_critically_low():
    state = BudgetState(
        daily_spent_usd=10.0,
        daily_budget_usd=25.0,
        daily_remaining_usd=15.0,
        daily_pct_remaining=0.60,
    )
    assert state.daily_budget_critically_low is False


def test_budget_state_lifetime_heavily_consumed():
    state = BudgetState(
        lifetime_spent_usd=4000.0,
        lifetime_budget_usd=5000.0,
        lifetime_remaining_usd=1000.0,
        lifetime_pct_consumed=0.80,
    )
    assert state.lifetime_heavily_consumed is True


def test_budget_state_lifetime_not_heavily_consumed():
    state = BudgetState(
        lifetime_spent_usd=1000.0,
        lifetime_budget_usd=5000.0,
        lifetime_remaining_usd=4000.0,
        lifetime_pct_consumed=0.20,
    )
    assert state.lifetime_heavily_consumed is False


def test_cost_approval_is_approved():
    approval = CostApproval(
        decision=CostDecision.APPROVE_FULL,
        reason="ok",
    )
    assert approval.is_approved is True

    reduced = CostApproval(
        decision=CostDecision.APPROVE_REDUCED,
        reason="reduced",
    )
    assert reduced.is_approved is True


def test_cost_approval_not_approved():
    defer = CostApproval(decision=CostDecision.DEFER, reason="deferred")
    assert defer.is_approved is False

    reject = CostApproval(decision=CostDecision.REJECT, reason="rejected")
    assert reject.is_approved is False


def test_review_cost_status_allows_opus():
    status = ReviewCostStatus(
        position_id="p1",
        total_review_cost_usd=1.0,
        position_value_usd=500.0,
        cost_pct_of_value=0.002,
        total_reviews=5,
        deterministic_reviews=4,
        llm_reviews=1,
        cap_threshold_hit=False,
    )
    assert status.allows_opus_escalation is True


def test_review_cost_status_blocks_opus_at_cap():
    status = ReviewCostStatus(
        position_id="p1",
        total_review_cost_usd=80.0,
        position_value_usd=500.0,
        cost_pct_of_value=0.16,
        total_reviews=50,
        deterministic_reviews=30,
        llm_reviews=20,
        cap_threshold_hit=True,
    )
    assert status.allows_opus_escalation is False


def test_estimate_accuracy_within_bounds():
    acc = EstimateAccuracy(
        workflow_run_id="w1",
        run_type=RunType.TRIGGER_BASED,
        estimated_min_usd=0.01,
        estimated_max_usd=0.05,
        actual_usd=0.03,
        accuracy_ratio=1.0,
        within_bounds=True,
    )
    assert acc.within_bounds is True


def test_agent_cost_spec_defaults():
    spec = AgentCostSpec(
        agent_role="test",
        tier=ModelTier.B,
        cost_class=CostClass.M,
    )
    assert spec.estimated_input_tokens == 0
    assert spec.estimated_cost_min_usd == 0.0


def test_cost_estimate_request_defaults():
    req = CostEstimateRequest(
        workflow_run_id="w1",
        run_type=RunType.TRIGGER_BASED,
    )
    assert req.candidate_count == 1
    assert req.expected_net_edge is None
    assert req.agent_specs == []
