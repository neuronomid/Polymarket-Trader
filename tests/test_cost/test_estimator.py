"""Tests for PreRunCostEstimator."""

import pytest

from config.settings import CostConfig
from core.enums import CostClass, ModelTier
from cost.estimator import PreRunCostEstimator
from cost.types import (
    AgentCostSpec,
    BudgetState,
    CostEstimateRequest,
    RunType,
)


@pytest.fixture
def config():
    return CostConfig()


@pytest.fixture
def estimator(config):
    return PreRunCostEstimator(config)


@pytest.fixture
def budget_state():
    return BudgetState(
        daily_spent_usd=5.0,
        daily_budget_usd=25.0,
        daily_remaining_usd=20.0,
        daily_pct_remaining=0.80,
        lifetime_spent_usd=100.0,
        lifetime_budget_usd=5000.0,
        lifetime_remaining_usd=4900.0,
        lifetime_pct_consumed=0.02,
    )


def _make_agent_spec(role: str, tier: ModelTier, cost_min: float = 0.0, cost_max: float = 0.0):
    from core.constants import TIER_COST_CLASS
    return AgentCostSpec(
        agent_role=role,
        tier=tier,
        cost_class=TIER_COST_CLASS[tier],
        estimated_cost_min_usd=cost_min,
        estimated_cost_max_usd=cost_max,
    )


# --- Standard estimation ---

def test_estimate_single_agent_with_explicit_costs(estimator, budget_state):
    request = CostEstimateRequest(
        workflow_run_id="w1",
        run_type=RunType.TRIGGER_BASED,
        agent_specs=[
            _make_agent_spec("domain_manager", ModelTier.B, cost_min=0.02, cost_max=0.04),
        ],
    )
    estimate = estimator.estimate(request, budget_state)
    assert estimate.expected_cost_min_usd == 0.02
    assert estimate.expected_cost_max_usd == 0.04
    assert "domain_manager" in estimate.agent_budgets


def test_estimate_multiple_agents(estimator, budget_state):
    request = CostEstimateRequest(
        workflow_run_id="w2",
        run_type=RunType.SCHEDULED_SWEEP,
        agent_specs=[
            _make_agent_spec("domain_manager", ModelTier.B, cost_min=0.02, cost_max=0.04),
            _make_agent_spec("orchestrator", ModelTier.A, cost_min=0.10, cost_max=0.25),
            _make_agent_spec("evidence_extractor", ModelTier.C, cost_min=0.002, cost_max=0.004),
        ],
    )
    estimate = estimator.estimate(request, budget_state)
    assert estimate.expected_cost_min_usd == pytest.approx(0.122, abs=1e-4)
    assert estimate.expected_cost_max_usd == pytest.approx(0.294, abs=1e-4)
    assert len(estimate.agent_budgets) == 3


def test_estimate_scales_by_candidate_count(estimator, budget_state):
    request = CostEstimateRequest(
        workflow_run_id="w3",
        run_type=RunType.SCHEDULED_SWEEP,
        candidate_count=3,
        agent_specs=[
            _make_agent_spec("domain_manager", ModelTier.B, cost_min=0.02, cost_max=0.04),
        ],
    )
    estimate = estimator.estimate(request, budget_state)
    assert estimate.expected_cost_min_usd == pytest.approx(0.06, abs=1e-4)
    assert estimate.expected_cost_max_usd == pytest.approx(0.12, abs=1e-4)


def test_estimate_falls_back_to_cost_class_ranges(estimator, budget_state):
    """When agent spec has no explicit costs, use cost class ranges."""
    request = CostEstimateRequest(
        workflow_run_id="w4",
        run_type=RunType.TRIGGER_BASED,
        agent_specs=[
            _make_agent_spec("some_agent", ModelTier.B),  # no explicit costs
        ],
    )
    estimate = estimator.estimate(request, budget_state)
    # Should use CostClass.M range: (0.01, 0.05)
    assert estimate.expected_cost_min_usd == pytest.approx(0.01, abs=1e-4)
    assert estimate.expected_cost_max_usd == pytest.approx(0.05, abs=1e-4)


def test_estimate_deterministic_agent_zero_cost(estimator, budget_state):
    request = CostEstimateRequest(
        workflow_run_id="w5",
        run_type=RunType.TRIGGER_BASED,
        agent_specs=[
            _make_agent_spec("risk_check", ModelTier.D),
        ],
    )
    estimate = estimator.estimate(request, budget_state)
    assert estimate.expected_cost_min_usd == 0.0
    assert estimate.expected_cost_max_usd == 0.0


# --- Position review estimation ---

def test_estimate_position_review_uses_effective_profile(estimator, budget_state):
    request = CostEstimateRequest(
        workflow_run_id="w6",
        run_type=RunType.POSITION_REVIEW,
    )
    estimate = estimator.estimate(request, budget_state)

    # Effective cost: 65%*0 + 25%*M_range + 10%*H_range
    # min: 0 + 0.25*0.01 + 0.10*0.05 = 0.0025 + 0.005 = 0.0075
    # max: 0 + 0.25*0.05 + 0.10*0.30 = 0.0125 + 0.030 = 0.0425
    assert estimate.expected_cost_min_usd == pytest.approx(0.0075, abs=1e-4)
    assert estimate.expected_cost_max_usd == pytest.approx(0.0425, abs=1e-4)
    assert estimate.run_type == RunType.POSITION_REVIEW


def test_estimate_preserves_budget_state(estimator, budget_state):
    request = CostEstimateRequest(
        workflow_run_id="w7",
        run_type=RunType.TRIGGER_BASED,
        agent_specs=[_make_agent_spec("test", ModelTier.B, 0.01, 0.03)],
    )
    estimate = estimator.estimate(request, budget_state)
    assert estimate.budget_state.daily_remaining_usd == 20.0
    assert estimate.budget_state.lifetime_pct_consumed == 0.02


def test_estimate_empty_agents_zero_cost(estimator, budget_state):
    request = CostEstimateRequest(
        workflow_run_id="w8",
        run_type=RunType.TRIGGER_BASED,
        agent_specs=[],
    )
    estimate = estimator.estimate(request, budget_state)
    assert estimate.expected_cost_min_usd == 0.0
    assert estimate.expected_cost_max_usd == 0.0
