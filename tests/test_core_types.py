"""Tests for core types."""

from core.types import CostEstimate, MarketRef, PositionRef, RuleDecisionRecord, WorkflowRunID


def test_workflow_run_id_generates_unique():
    id1 = WorkflowRunID()
    id2 = WorkflowRunID()
    assert id1.id != id2.id


def test_market_ref():
    ref = MarketRef(market_id="mkt-1", title="Will X happen?")
    assert ref.market_id == "mkt-1"
    assert ref.condition_id is None


def test_position_ref():
    ref = PositionRef(position_id="pos-1", market_id="mkt-1")
    assert ref.position_id == "pos-1"


def test_cost_estimate():
    est = CostEstimate(
        tier="A", cost_class="H", estimated_cost_usd=0.15, description="Final synthesis"
    )
    assert est.estimated_cost_usd == 0.15


def test_rule_decision_record():
    rec = RuleDecisionRecord(rule_name="max_spread", passed=False, reason="Spread 0.20 > 0.15")
    assert not rec.passed
    assert rec.timestamp is not None
