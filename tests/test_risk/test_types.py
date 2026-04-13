"""Tests for risk types."""

from core.enums import DrawdownLevel, OperatorMode, RiskApproval
from risk.types import (
    CorrelationAssessment,
    DrawdownState,
    LiquidityCheck,
    PortfolioState,
    RiskAssessment,
    RiskRuleResult,
    SizingRequest,
    SizingResult,
)


def test_portfolio_state_defaults():
    ps = PortfolioState(
        account_balance_usd=10000.0,
        start_of_day_equity_usd=10000.0,
        current_equity_usd=9800.0,
    )
    assert ps.total_open_exposure_usd == 0.0
    assert ps.open_position_count == 0
    assert ps.operator_mode == OperatorMode.PAPER


def test_sizing_request_defaults():
    req = SizingRequest(
        market_id="m1",
        token_id="tok1",
        category="politics",
        gross_edge=0.05,
        probability_estimate=0.6,
        confidence_estimate=0.7,
    )
    assert req.ambiguity_score == 0.0
    assert req.correlation_burden_score == 0.0
    assert req.cluster_ids == []


def test_sizing_result():
    sr = SizingResult(
        recommended_size_usd=500.0,
        max_size_usd=1000.0,
        size_factors={"edge_factor": 0.5},
        penalties_applied={"ambiguity": 0.9},
        capped_by="liquidity_depth",
    )
    assert sr.recommended_size_usd == 500.0
    assert sr.capped_by == "liquidity_depth"


def test_liquidity_check():
    lc = LiquidityCheck(
        max_order_usd=1200.0,
        depth_at_top_levels_usd=10000.0,
    )
    assert lc.passes_depth_check is True
    assert lc.passes_impact_check is True


def test_correlation_assessment():
    ca = CorrelationAssessment(
        burden_score=0.3,
        passes=True,
        reason="Within limits",
    )
    assert ca.cluster_violations == []
    assert ca.total_correlated_exposure_usd == 0.0


def test_drawdown_state_defaults():
    ds = DrawdownState()
    assert ds.level == DrawdownLevel.NORMAL
    assert ds.entries_allowed is True
    assert ds.size_multiplier == 1.0


def test_risk_rule_result():
    rr = RiskRuleResult(
        rule_name="test_rule",
        passed=True,
        reason="OK",
        threshold_value=0.08,
        actual_value=0.05,
    )
    assert rr.metadata == {}


def test_risk_assessment_is_approved():
    drawdown = DrawdownState()

    approved = RiskAssessment(
        approval=RiskApproval.APPROVE_NORMAL,
        drawdown_state=drawdown,
        reason="All passed",
    )
    assert approved.is_approved is True

    reduced = RiskAssessment(
        approval=RiskApproval.APPROVE_REDUCED,
        drawdown_state=drawdown,
        reason="Reduced",
    )
    assert reduced.is_approved is True

    special = RiskAssessment(
        approval=RiskApproval.APPROVE_SPECIAL,
        drawdown_state=drawdown,
        reason="Special",
    )
    assert special.is_approved is True

    rejected = RiskAssessment(
        approval=RiskApproval.REJECT,
        drawdown_state=drawdown,
        reason="Rejected",
    )
    assert rejected.is_approved is False

    delayed = RiskAssessment(
        approval=RiskApproval.DELAY,
        drawdown_state=drawdown,
        reason="Delayed",
    )
    assert delayed.is_approved is False
