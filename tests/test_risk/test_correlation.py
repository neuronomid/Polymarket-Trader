"""Tests for the correlation engine."""

import pytest

from config.settings import RiskConfig
from risk.correlation import CorrelationEngine, CorrelationType
from risk.types import PortfolioState, SizingRequest


@pytest.fixture
def config():
    return RiskConfig()


@pytest.fixture
def engine(config):
    return CorrelationEngine(config)


@pytest.fixture
def portfolio():
    return PortfolioState(
        account_balance_usd=10000.0,
        start_of_day_equity_usd=10000.0,
        current_equity_usd=10000.0,
    )


def _make_request(**kwargs) -> SizingRequest:
    defaults = dict(
        market_id="m1",
        token_id="tok1",
        category="politics",
        gross_edge=0.05,
        probability_estimate=0.6,
        confidence_estimate=0.7,
    )
    defaults.update(kwargs)
    return SizingRequest(**defaults)


def test_no_clusters_passes(engine, portfolio):
    request = _make_request(cluster_ids=[])
    assessment = engine.assess(request, portfolio)
    assert assessment.passes is True
    assert assessment.burden_score == 0.0


def test_register_and_get_cluster(engine):
    engine.register_cluster("c1", CorrelationType.EVENT, "Election 2026")
    cluster = engine.get_cluster("c1")
    assert cluster is not None
    assert cluster.name == "Election 2026"
    assert cluster.cluster_type == CorrelationType.EVENT


def test_add_exposure(engine):
    engine.register_cluster("c1", CorrelationType.EVENT, "Test")
    engine.add_exposure("c1", "pos-1", 500.0)
    cluster = engine.get_cluster("c1")
    assert cluster.current_exposure_usd == 500.0
    assert "pos-1" in cluster.position_ids


def test_remove_exposure(engine):
    engine.register_cluster("c1", CorrelationType.EVENT, "Test")
    engine.add_exposure("c1", "pos-1", 500.0)
    engine.remove_exposure("c1", "pos-1", 200.0)
    cluster = engine.get_cluster("c1")
    assert cluster.current_exposure_usd == 300.0


def test_remove_exposure_clamps_to_zero(engine):
    engine.register_cluster("c1", CorrelationType.EVENT, "Test")
    engine.add_exposure("c1", "pos-1", 100.0)
    engine.remove_exposure("c1", "pos-1", 500.0)
    cluster = engine.get_cluster("c1")
    assert cluster.current_exposure_usd == 0.0


def test_cluster_exposure_violation(engine, portfolio):
    """Cluster at max exposure should trigger violation."""
    engine.register_cluster("c1", CorrelationType.EVENT, "Election", max_exposure_usd=1000.0)
    engine.add_exposure("c1", "pos-1", 1000.0)

    request = _make_request(cluster_ids=["c1"])
    assessment = engine.assess(request, portfolio)
    assert assessment.passes is False
    assert len(assessment.cluster_violations) == 1
    assert "Election" in assessment.cluster_violations[0]


def test_cluster_within_limits(engine, portfolio):
    engine.register_cluster("c1", CorrelationType.EVENT, "Election", max_exposure_usd=5000.0)
    engine.add_exposure("c1", "pos-1", 1000.0)

    request = _make_request(cluster_ids=["c1"])
    assessment = engine.assess(request, portfolio)
    assert assessment.passes is True
    assert assessment.burden_score > 0


def test_high_correlation_burden_fails(engine, portfolio):
    """Many clusters with high exposure → high burden → fail."""
    config = RiskConfig(max_total_open_exposure_usd=10000.0, max_correlation_burden_score=0.3)
    eng = CorrelationEngine(config)

    eng.register_cluster("c1", CorrelationType.EVENT, "A", max_exposure_usd=10000.0)
    eng.register_cluster("c2", CorrelationType.NARRATIVE, "B", max_exposure_usd=10000.0)
    eng.add_exposure("c1", "pos-1", 2000.0)
    eng.add_exposure("c2", "pos-2", 2000.0)

    request = _make_request(cluster_ids=["c1", "c2"])
    assessment = eng.assess(request, portfolio)
    # Total correlated = 4000, burden = 4000/10000 = 0.4 > 0.3
    assert assessment.passes is False
    assert assessment.burden_score == pytest.approx(0.4)


def test_evaluate_rules_returns_results(engine, portfolio):
    engine.register_cluster("c1", CorrelationType.CATALYST, "Ruling")
    engine.add_exposure("c1", "pos-1", 500.0)

    request = _make_request(cluster_ids=["c1"])
    results = engine.evaluate_rules(request, portfolio)
    assert len(results) >= 2  # burden + per-cluster
    rule_names = [r.rule_name for r in results]
    assert "correlation_burden" in rule_names


def test_unknown_cluster_id_ignored(engine, portfolio):
    """Request with unknown cluster IDs should not crash."""
    request = _make_request(cluster_ids=["nonexistent"])
    assessment = engine.assess(request, portfolio)
    assert assessment.passes is True
    assert assessment.burden_score == 0.0


def test_add_exposure_to_unknown_cluster(engine):
    """Adding exposure to unregistered cluster should be a no-op."""
    engine.add_exposure("nonexistent", "pos-1", 500.0)
    assert engine.get_cluster("nonexistent") is None


def test_five_correlation_types(engine):
    """All five correlation types can be registered."""
    for ct in CorrelationType:
        engine.register_cluster(f"c-{ct.value}", ct, f"Test {ct.value}")
    assert len(engine._clusters) == 5


def test_default_max_exposure_from_config(config):
    """Cluster without explicit max_exposure uses config default."""
    engine = CorrelationEngine(config)
    engine.register_cluster("c1", CorrelationType.EVENT, "Test")
    cluster = engine.get_cluster("c1")
    assert cluster.max_exposure_usd == config.max_cluster_exposure_usd
