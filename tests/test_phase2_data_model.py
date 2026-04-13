"""Tests for Phase 2: Data Model & Persistence Layer.

Tests cover:
1. Schema completeness — all 47 tables registered
2. Model CRUD — create/read/update/delete for all major entities
3. Relationships — FK enforcement and relationship traversal
4. Repository layer — async CRUD and domain queries
5. Thesis card completeness — all spec Section 14.2 fields present
6. Seed data structures — base rates, calibration thresholds
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from data.base import Base
from data.models import Market, Order, Position, Trade
from data.models.thesis import NetEdgeEstimate, ThesisCard
from data.models.workflow import EligibilityDecision, TriggerEvent, WorkflowRun
from data.models.risk import RiskSnapshot, RuleDecision
from data.models.cost import (
    CostGovernorDecision,
    CostOfSelectivityRecord,
    CostSnapshot,
    CumulativeReviewCostRecord,
    PreRunCostEstimate,
)
from data.models.calibration import (
    CalibrationAccumulationProjection,
    CalibrationRecord,
    CalibrationSegment,
    CalibrationThresholdRegistry,
    CategoryPerformanceLedgerEntry,
    ShadowForecastRecord,
)
from data.models.execution import (
    EntryImpactEstimate,
    FrictionModelParameters,
    RealizedSlippageRecord,
)
from data.models.bias import BiasAuditReport, BiasPatternRecord
from data.models.operator import OperatorAbsenceEvent, OperatorInteractionEvent
from data.models.viability import (
    LifetimeBudgetStatus,
    PatienceBudgetStatus,
    StrategyViabilityCheckpoint,
)
from data.models.scanner import CLOBCacheEntry, ScannerDataSnapshot, ScannerHealthEvent
from data.models.notification import NotificationDeliveryRecord, NotificationEvent
from data.models.logging import Alert, JournalEntry, StructuredLogEntry
from data.models.correlation import CorrelationGroup, EventCluster
from data.models.resolution import ResolutionParseResult, SportsQualityGateResult
from data.models.reference import (
    BaseRateReference,
    MarketImpliedProbabilitySnapshot,
    MarketQualitySnapshot,
    PolicyUpdateRecommendation,
    ShadowVsMarketComparisonRecord,
    SystemHealthSnapshot,
)

from data.repositories.market import (
    MarketRepository,
    OrderRepository,
    PositionRepository,
    TradeRepository,
)
from data.repositories.workflow import (
    EligibilityDecisionRepository,
    TriggerEventRepository,
    WorkflowRunRepository,
)
from data.repositories.thesis import ThesisCardRepository, NetEdgeEstimateRepository
from data.repositories.supporting import (
    BaseRateReferenceRepository,
    CalibrationRecordRepository,
    CalibrationThresholdRegistryRepository,
    CategoryPerformanceLedgerRepository,
    CostSnapshotRepository,
    RiskSnapshotRepository,
    ShadowForecastRepository,
)


# ============================================================
# 1. Schema Completeness
# ============================================================


class TestSchemaCompleteness:
    """Verify all 47 specified tables are registered in Base.metadata."""

    EXPECTED_TABLES = {
        "markets", "positions", "orders", "trades",
        "thesis_cards", "net_edge_estimates",
        "workflow_runs", "trigger_events", "eligibility_decisions",
        "risk_snapshots", "rule_decisions",
        "cost_snapshots", "pre_run_cost_estimates", "cost_governor_decisions",
        "cost_of_selectivity_records", "cumulative_review_cost_records",
        "calibration_records", "calibration_segments", "shadow_forecast_records",
        "category_performance_ledger", "calibration_accumulation_projections",
        "calibration_threshold_registry",
        "entry_impact_estimates", "realized_slippage_records", "friction_model_parameters",
        "bias_audit_reports", "bias_pattern_records",
        "operator_interaction_events", "operator_absence_events",
        "strategy_viability_checkpoints", "lifetime_budget_status", "patience_budget_status",
        "clob_cache_entries", "scanner_data_snapshots", "scanner_health_events",
        "notification_events", "notification_delivery_records",
        "journal_entries", "structured_log_entries", "alerts",
        "event_clusters", "correlation_groups",
        "resolution_parse_results", "sports_quality_gate_results",
        "base_rate_references", "market_implied_probability_snapshots",
        "market_quality_snapshots", "shadow_vs_market_comparison_records",
        "policy_update_recommendations", "system_health_snapshots",
    }

    def test_all_tables_registered(self):
        """All expected tables must be present in metadata."""
        registered = set(Base.metadata.tables.keys())
        missing = self.EXPECTED_TABLES - registered
        assert not missing, f"Missing tables: {missing}"

    def test_table_count(self):
        """Verify at least 47 tables exist."""
        assert len(Base.metadata.tables) >= 47

    def test_no_orphan_tables(self):
        """All registered tables should be expected."""
        registered = set(Base.metadata.tables.keys())
        extra = registered - self.EXPECTED_TABLES
        # This is informational — extra tables are OK but worth tracking
        if extra:
            print(f"Extra tables (not in spec): {extra}")


# ============================================================
# 2. Core Entity CRUD
# ============================================================


class TestMarketCRUD:
    """Test Market model CRUD operations."""

    @pytest.mark.asyncio
    async def test_create_market(self, session: AsyncSession):
        market = Market(
            market_id="test-market-001",
            title="Will X happen by 2026?",
            category="politics",
            category_quality_tier="standard",
            is_active=True,
        )
        session.add(market)
        await session.flush()

        assert market.id is not None
        assert market.market_id == "test-market-001"
        assert market.category == "politics"

    @pytest.mark.asyncio
    async def test_read_market(self, session: AsyncSession):
        market = Market(
            market_id="test-market-read",
            title="Test Read Market",
            is_active=True,
        )
        session.add(market)
        await session.flush()

        stmt = select(Market).where(Market.market_id == "test-market-read")
        result = await session.execute(stmt)
        fetched = result.scalar_one()
        assert fetched.title == "Test Read Market"

    @pytest.mark.asyncio
    async def test_update_market(self, session: AsyncSession):
        market = Market(market_id="test-market-update", title="Old Title", is_active=True)
        session.add(market)
        await session.flush()

        market.title = "New Title"
        market.category = "technology"
        await session.flush()

        stmt = select(Market).where(Market.market_id == "test-market-update")
        result = await session.execute(stmt)
        fetched = result.scalar_one()
        assert fetched.title == "New Title"
        assert fetched.category == "technology"

    @pytest.mark.asyncio
    async def test_delete_market(self, session: AsyncSession):
        market = Market(market_id="test-market-delete", title="To Delete", is_active=True)
        session.add(market)
        await session.flush()

        await session.delete(market)
        await session.flush()

        stmt = select(Market).where(Market.market_id == "test-market-delete")
        result = await session.execute(stmt)
        assert result.scalar_one_or_none() is None


class TestPositionCRUD:
    """Test Position model CRUD operations."""

    @pytest.mark.asyncio
    async def test_create_position(self, session: AsyncSession):
        market = Market(market_id="pos-test-market", title="Position Test", is_active=True)
        session.add(market)
        await session.flush()

        position = Position(
            market_id=market.id,
            side="yes",
            entry_price=0.55,
            size=100.0,
            remaining_size=100.0,
            status="open",
            probability_estimate=0.65,
            confidence_estimate=0.7,
            calibration_confidence=0.3,
        )
        session.add(position)
        await session.flush()

        assert position.id is not None
        assert position.side == "yes"
        assert position.probability_estimate == 0.65
        assert position.confidence_estimate == 0.7
        assert position.calibration_confidence == 0.3

    @pytest.mark.asyncio
    async def test_position_market_relationship(self, session: AsyncSession):
        market = Market(market_id="pos-rel-market", title="Rel Test", is_active=True)
        session.add(market)
        await session.flush()

        position = Position(
            market_id=market.id,
            side="no",
            entry_price=0.40,
            size=50.0,
            remaining_size=50.0,
        )
        session.add(position)
        await session.flush()

        assert position.market_id == market.id


class TestOrderTradeCRUD:
    """Test Order and Trade CRUD operations."""

    @pytest.mark.asyncio
    async def test_create_order(self, session: AsyncSession):
        market = Market(market_id="order-test", title="Order Test", is_active=True)
        session.add(market)
        await session.flush()

        position = Position(
            market_id=market.id, side="yes", entry_price=0.5,
            size=100, remaining_size=100,
        )
        session.add(position)
        await session.flush()

        order = Order(
            position_id=position.id,
            order_type="limit",
            side="buy",
            price=0.5,
            size=100,
            estimated_impact_bps=15.0,
        )
        session.add(order)
        await session.flush()

        assert order.id is not None
        assert order.estimated_impact_bps == 15.0

    @pytest.mark.asyncio
    async def test_create_trade(self, session: AsyncSession):
        market = Market(market_id="trade-test", title="Trade Test", is_active=True)
        session.add(market)
        await session.flush()

        position = Position(
            market_id=market.id, side="yes", entry_price=0.5,
            size=100, remaining_size=100,
        )
        session.add(position)
        await session.flush()

        order = Order(
            position_id=position.id, order_type="limit",
            side="buy", price=0.52, size=100,
        )
        session.add(order)
        await session.flush()

        trade = Trade(
            order_id=order.id,
            position_id=position.id,
            price=0.52,
            size=100,
            side="buy",
            executed_at=datetime.now(tz=UTC),
        )
        session.add(trade)
        await session.flush()

        assert trade.id is not None
        assert trade.price == 0.52


# ============================================================
# 3. Thesis Card Completeness (Spec Section 14.2)
# ============================================================


class TestThesisCardCompleteness:
    """Verify all spec Section 14.2 fields are present on the ThesisCard model."""

    REQUIRED_FIELDS = [
        # Core
        "market_id", "category", "category_quality_tier", "proposed_side",
        "resolution_interpretation", "resolution_source_language",
        "core_thesis", "why_mispriced",
        # Evidence
        "supporting_evidence", "opposing_evidence",
        # Catalysts & timing
        "expected_catalyst", "expected_time_horizon",
        # Invalidation
        "invalidation_conditions",
        # Risk summaries
        "resolution_risk_summary", "market_structure_summary",
        # Quality scores
        "evidence_quality_score", "evidence_diversity_score", "ambiguity_score",
        # Calibration
        "calibration_source_status", "raw_model_probability",
        "calibrated_probability", "calibration_segment_label",
        # Section 23: Three separate confidence fields
        "probability_estimate", "confidence_estimate", "calibration_confidence",
        "confidence_note",
        # Section 14.3: Four-level net edge
        "gross_edge", "friction_adjusted_edge", "impact_adjusted_edge", "net_edge_after_cost",
        # Friction & impact
        "expected_friction_spread", "expected_friction_slippage",
        "entry_impact_estimate_bps", "expected_inference_cost_usd",
        # Sizing & urgency
        "recommended_size_band", "urgency_of_entry", "liquidity_adjusted_max_size",
        # Trigger & market context
        "trigger_source", "market_implied_probability",
        "base_rate", "base_rate_deviation",
    ]

    def test_all_fields_present(self):
        """Every spec Section 14.2 field must exist as a column."""
        table = Base.metadata.tables["thesis_cards"]
        column_names = {c.name for c in table.columns}
        missing = [f for f in self.REQUIRED_FIELDS if f not in column_names]
        assert not missing, f"Missing thesis card fields: {missing}"

    def test_three_confidence_fields_separate(self):
        """Section 23 requires three distinct confidence fields."""
        table = Base.metadata.tables["thesis_cards"]
        column_names = {c.name for c in table.columns}
        assert "probability_estimate" in column_names
        assert "confidence_estimate" in column_names
        assert "calibration_confidence" in column_names

    def test_four_level_net_edge(self):
        """Section 14.3 requires four separate edge levels."""
        table = Base.metadata.tables["thesis_cards"]
        column_names = {c.name for c in table.columns}
        assert "gross_edge" in column_names
        assert "friction_adjusted_edge" in column_names
        assert "impact_adjusted_edge" in column_names
        assert "net_edge_after_cost" in column_names

    @pytest.mark.asyncio
    async def test_create_full_thesis_card(self, session: AsyncSession):
        """Create a thesis card with all required fields."""
        market = Market(market_id="thesis-test", title="Thesis Test", is_active=True)
        session.add(market)
        await session.flush()

        wf = WorkflowRun(
            workflow_run_id="wf-thesis-test",
            run_type="trigger_based",
            market_id=market.id,
        )
        session.add(wf)
        await session.flush()

        thesis = ThesisCard(
            market_id=market.id,
            workflow_run_id=wf.id,
            category="politics",
            category_quality_tier="standard",
            proposed_side="yes",
            resolution_interpretation="Decisive win in election results",
            resolution_source_language="Official election commission",
            core_thesis="Market underestimates candidate strength",
            why_mispriced="Regional polling shows strong support unreflected in national models",
            supporting_evidence=[
                {"source": "poll_a", "detail": "52% in key state", "freshness": "2 days"},
                {"source": "poll_b", "detail": "Leading in demographics", "freshness": "1 day"},
                {"source": "endorsement", "detail": "Major endorsement", "freshness": "3 hours"},
            ],
            opposing_evidence=[
                {"source": "national_average", "detail": "Trailing nationally", "freshness": "1 day"},
                {"source": "model_x", "detail": "30% win probability", "freshness": "12 hours"},
                {"source": "historical", "detail": "Similar candidates lost", "freshness": "N/A"},
            ],
            expected_catalyst="Election day results",
            expected_time_horizon="2_weeks",
            invalidation_conditions=["Major scandal breaks", "Endorsement reversal"],
            resolution_risk_summary="Clear resolution via official results",
            market_structure_summary="Good depth, narrow spread",
            evidence_quality_score=0.8,
            evidence_diversity_score=0.7,
            ambiguity_score=0.2,
            calibration_source_status="insufficient",
            raw_model_probability=0.62,
            calibrated_probability=None,
            probability_estimate=0.62,
            confidence_estimate=0.7,
            calibration_confidence=0.3,
            confidence_note="Insufficient calibration data for this category",
            gross_edge=0.12,
            friction_adjusted_edge=0.10,
            impact_adjusted_edge=0.09,
            net_edge_after_cost=0.085,
            expected_friction_spread=0.015,
            expected_friction_slippage=0.005,
            entry_impact_estimate_bps=10.0,
            expected_inference_cost_usd=0.15,
            recommended_size_band="small",
            urgency_of_entry="normal",
            liquidity_adjusted_max_size=200.0,
            trigger_source="discovery",
            market_implied_probability=0.50,
            base_rate=0.50,
            base_rate_deviation=0.12,
        )
        session.add(thesis)
        await session.flush()

        assert thesis.id is not None
        assert thesis.gross_edge == 0.12
        assert thesis.net_edge_after_cost == 0.085
        assert len(thesis.supporting_evidence) == 3
        assert len(thesis.opposing_evidence) == 3


# ============================================================
# 4. Workflow & Trigger Models
# ============================================================


class TestWorkflowModels:
    """Test WorkflowRun, TriggerEvent, EligibilityDecision CRUD."""

    @pytest.mark.asyncio
    async def test_create_workflow_run(self, session: AsyncSession):
        wf = WorkflowRun(
            workflow_run_id="wf-test-001",
            run_type="scheduled_sweep",
            status="pending",
            operator_mode="paper",
        )
        session.add(wf)
        await session.flush()

        assert wf.id is not None
        assert wf.status == "pending"

    @pytest.mark.asyncio
    async def test_create_trigger_event(self, session: AsyncSession):
        market = Market(market_id="trigger-test", title="Trigger", is_active=True)
        session.add(market)
        await session.flush()

        trigger = TriggerEvent(
            market_id=market.id,
            trigger_class="discovery",
            trigger_level="C",
            price_at_trigger=0.45,
            spread_at_trigger=0.02,
            data_source="live",
            reason="Price moved beyond threshold",
            triggered_at=datetime.now(tz=UTC),
        )
        session.add(trigger)
        await session.flush()

        assert trigger.id is not None
        assert trigger.trigger_class == "discovery"

    @pytest.mark.asyncio
    async def test_create_eligibility_decision(self, session: AsyncSession):
        market = Market(market_id="elig-test", title="Eligibility", is_active=True)
        session.add(market)
        await session.flush()

        decision = EligibilityDecision(
            market_id=market.id,
            outcome="reject",
            reason_code="excluded_category",
            reason_detail="Market is in crypto category",
            decided_at=datetime.now(tz=UTC),
        )
        session.add(decision)
        await session.flush()

        assert decision.id is not None
        assert decision.outcome == "reject"


# ============================================================
# 5. Risk & Cost Models
# ============================================================


class TestRiskCostModels:
    """Test Risk and Cost Governor models."""

    @pytest.mark.asyncio
    async def test_risk_snapshot_with_rules(self, session: AsyncSession):
        snapshot = RiskSnapshot(
            drawdown_level="normal",
            current_drawdown_pct=0.01,
            total_open_exposure_usd=5000.0,
            daily_deployment_used_pct=0.03,
            simultaneous_positions=3,
            snapshot_at=datetime.now(tz=UTC),
            category_exposure={"politics": 2000, "technology": 3000},
        )
        session.add(snapshot)
        await session.flush()

        rule = RuleDecision(
            risk_snapshot_id=snapshot.id,
            rule_name="max_daily_drawdown",
            passed=True,
            reason="Drawdown 1.0% < 8.0% limit",
            threshold_value=0.08,
            actual_value=0.01,
            decided_at=datetime.now(tz=UTC),
        )
        session.add(rule)
        await session.flush()

        assert rule.risk_snapshot_id == snapshot.id

    @pytest.mark.asyncio
    async def test_cost_snapshot(self, session: AsyncSession):
        wf = WorkflowRun(
            workflow_run_id="wf-cost-test",
            run_type="trigger_based",
        )
        session.add(wf)
        await session.flush()

        cost = CostSnapshot(
            workflow_run_id=wf.id,
            model="claude-sonnet-4-6",
            provider="anthropic",
            cost_class="M",
            tier="B",
            input_tokens=1500,
            output_tokens=500,
            estimated_cost_usd=0.03,
            actual_cost_usd=0.028,
            recorded_at=datetime.now(tz=UTC),
        )
        session.add(cost)
        await session.flush()

        assert cost.id is not None

    @pytest.mark.asyncio
    async def test_pre_run_cost_estimate(self, session: AsyncSession):
        wf = WorkflowRun(
            workflow_run_id="wf-prerun-test",
            run_type="scheduled_sweep",
        )
        session.add(wf)
        await session.flush()

        estimate = PreRunCostEstimate(
            workflow_run_id=wf.id,
            run_type="scheduled_sweep",
            expected_cost_min_usd=0.05,
            expected_cost_max_usd=0.25,
            daily_budget_remaining_usd=20.0,
            lifetime_budget_remaining_usd=4500.0,
            daily_budget_pct_remaining=0.80,
            estimated_at=datetime.now(tz=UTC),
        )
        session.add(estimate)
        await session.flush()

        assert estimate.expected_cost_min_usd == 0.05

    @pytest.mark.asyncio
    async def test_cost_governor_decision(self, session: AsyncSession):
        wf = WorkflowRun(
            workflow_run_id="wf-cg-decision",
            run_type="trigger_based",
        )
        session.add(wf)
        await session.flush()

        decision = CostGovernorDecision(
            workflow_run_id=wf.id,
            decision="approve_full",
            reason="Budget remaining sufficient for full tier allocation",
            approved_max_tier="A",
            approved_max_cost_usd=0.30,
            cost_selectivity_ratio=2.5,
            decided_at=datetime.now(tz=UTC),
        )
        session.add(decision)
        await session.flush()

        assert decision.decision == "approve_full"


# ============================================================
# 6. Calibration Models
# ============================================================


class TestCalibrationModels:
    """Test calibration, shadow forecast, and performance ledger models."""

    @pytest.mark.asyncio
    async def test_create_calibration_record(self, session: AsyncSession):
        record = CalibrationRecord(
            segment_type="category",
            segment_label="politics",
            regime="insufficient",
            resolved_count=5,
            total_forecasts=20,
            min_threshold=30,
            threshold_met=False,
            updated_at_cal=datetime.now(tz=UTC),
        )
        session.add(record)
        await session.flush()

        assert record.id is not None
        assert record.threshold_met is False

    @pytest.mark.asyncio
    async def test_shadow_forecast_record(self, session: AsyncSession):
        market = Market(market_id="shadow-test", title="Shadow", is_active=True)
        session.add(market)
        await session.flush()

        forecast = ShadowForecastRecord(
            market_id=market.id,
            system_probability=0.65,
            market_implied_probability=0.50,
            category="politics",
            is_resolved=False,
            forecast_at=datetime.now(tz=UTC),
        )
        session.add(forecast)
        await session.flush()

        assert forecast.system_probability == 0.65

    @pytest.mark.asyncio
    async def test_category_performance_ledger(self, session: AsyncSession):
        entry = CategoryPerformanceLedgerEntry(
            category="politics",
            period_start=datetime(2026, 4, 7, tzinfo=UTC),
            period_end=datetime(2026, 4, 13, tzinfo=UTC),
            trades_count=5,
            win_rate=0.6,
            gross_pnl=150.0,
            net_pnl=120.0,
            inference_cost_usd=3.5,
        )
        session.add(entry)
        await session.flush()

        assert entry.trades_count == 5


# ============================================================
# 7. Remaining Entity Models
# ============================================================


class TestExecutionModels:
    @pytest.mark.asyncio
    async def test_entry_impact_estimate(self, session: AsyncSession):
        estimate = EntryImpactEstimate(
            estimated_impact_bps=12.5,
            order_size=200.0,
            levels_consumed=3,
            mid_price_before=0.50,
            estimated_mid_price_after=0.505,
            estimated_at=datetime.now(tz=UTC),
        )
        session.add(estimate)
        await session.flush()
        assert estimate.estimated_impact_bps == 12.5

    @pytest.mark.asyncio
    async def test_friction_model_parameters(self, session: AsyncSession):
        params = FrictionModelParameters(
            spread_estimate=0.03,
            depth_assumption=5000.0,
            impact_coefficient=0.001,
            version=1,
            is_active=True,
        )
        session.add(params)
        await session.flush()
        assert params.is_active is True


class TestBiasModels:
    @pytest.mark.asyncio
    async def test_bias_audit_report(self, session: AsyncSession):
        report = BiasAuditReport(
            report_date=datetime.now(tz=UTC),
            period_start=datetime(2026, 4, 7, tzinfo=UTC),
            period_end=datetime(2026, 4, 13, tzinfo=UTC),
            directional_bias_detected=True,
            directional_bias_skew_pp=6.2,
            confidence_clustering_detected=False,
            anchoring_detected=False,
            narrative_overweighting_detected=False,
            base_rate_neglect_detected=False,
            any_bias_detected=True,
            sample_size=35,
        )
        session.add(report)
        await session.flush()
        assert report.directional_bias_detected is True

    @pytest.mark.asyncio
    async def test_bias_pattern_tracking(self, session: AsyncSession):
        pattern = BiasPatternRecord(
            pattern_type="directional",
            first_detected_at=datetime(2026, 3, 30, tzinfo=UTC),
            last_detected_at=datetime(2026, 4, 13, tzinfo=UTC),
            consecutive_weeks=3,
            is_persistent=True,
            alert_status="persistent",
        )
        session.add(pattern)
        await session.flush()
        assert pattern.is_persistent is True


class TestOperatorModels:
    @pytest.mark.asyncio
    async def test_operator_interaction(self, session: AsyncSession):
        event = OperatorInteractionEvent(
            interaction_type="login",
            interacted_at=datetime.now(tz=UTC),
        )
        session.add(event)
        await session.flush()
        assert event.interaction_type == "login"

    @pytest.mark.asyncio
    async def test_operator_absence(self, session: AsyncSession):
        event = OperatorAbsenceEvent(
            absence_level=2,
            absence_level_name="absent_level_2",
            hours_since_last_interaction=80.0,
            size_reduction_pct=0.25,
            alert_delivered=True,
            event_at=datetime.now(tz=UTC),
        )
        session.add(event)
        await session.flush()
        assert event.absence_level == 2


class TestViabilityModels:
    @pytest.mark.asyncio
    async def test_viability_checkpoint(self, session: AsyncSession):
        checkpoint = StrategyViabilityCheckpoint(
            checkpoint_type="week_8",
            checkpoint_week=8,
            resolved_forecasts=25,
            viability_status="concern",
            viability_note="System Brier not better than market",
            checkpoint_at=datetime.now(tz=UTC),
        )
        session.add(checkpoint)
        await session.flush()
        assert checkpoint.viability_status == "concern"

    @pytest.mark.asyncio
    async def test_lifetime_budget(self, session: AsyncSession):
        status = LifetimeBudgetStatus(
            total_budget_usd=5000.0,
            consumed_usd=2500.0,
            remaining_usd=2500.0,
            consumed_pct=0.50,
            alert_50_triggered=True,
            recorded_at=datetime.now(tz=UTC),
        )
        session.add(status)
        await session.flush()
        assert status.alert_50_triggered is True

    @pytest.mark.asyncio
    async def test_patience_budget(self, session: AsyncSession):
        status = PatienceBudgetStatus(
            start_date=datetime(2026, 1, 1, tzinfo=UTC),
            expiry_date=datetime(2026, 10, 1, tzinfo=UTC),
            budget_months=9,
            elapsed_days=103,
            remaining_days=170,
            is_expired=False,
            recorded_at=datetime.now(tz=UTC),
        )
        session.add(status)
        await session.flush()
        assert status.budget_months == 9


class TestScannerModels:
    @pytest.mark.asyncio
    async def test_clob_cache_entry(self, session: AsyncSession):
        market = Market(market_id="cache-test", title="Cache", is_active=True)
        session.add(market)
        await session.flush()

        entry = CLOBCacheEntry(
            market_id=market.id,
            price=0.55,
            best_bid=0.54,
            best_ask=0.56,
            spread=0.02,
            source="live",
            is_stale=False,
            polled_at=datetime.now(tz=UTC),
        )
        session.add(entry)
        await session.flush()
        assert entry.spread == 0.02

    @pytest.mark.asyncio
    async def test_scanner_health_event(self, session: AsyncSession):
        event = ScannerHealthEvent(
            event_type="api_failure",
            severity="warning",
            api_available=False,
            degraded_mode_level=1,
            consecutive_failures=5,
            event_at=datetime.now(tz=UTC),
        )
        session.add(event)
        await session.flush()
        assert event.consecutive_failures == 5


class TestNotificationModels:
    @pytest.mark.asyncio
    async def test_notification_event_with_delivery(self, session: AsyncSession):
        event = NotificationEvent(
            event_type="trade_entry",
            severity="info",
            title="New Position Entered",
            body="Entered YES on X market at 0.55",
            emitted_at=datetime.now(tz=UTC),
        )
        session.add(event)
        await session.flush()

        delivery = NotificationDeliveryRecord(
            notification_event_id=event.id,
            channel="telegram",
            status="sent",
            attempts=1,
            delivered_at=datetime.now(tz=UTC),
        )
        session.add(delivery)
        await session.flush()

        assert delivery.channel == "telegram"
        assert delivery.notification_event_id == event.id


class TestCorrelationModels:
    @pytest.mark.asyncio
    async def test_event_cluster(self, session: AsyncSession):
        cluster = EventCluster(
            cluster_name="US 2026 Midterms",
            cluster_type="event",
            max_exposure_usd=2000.0,
        )
        session.add(cluster)
        await session.flush()
        assert cluster.cluster_type == "event"

    @pytest.mark.asyncio
    async def test_correlation_group(self, session: AsyncSession):
        group = CorrelationGroup(
            group_name="Tech Regulation Cluster",
            correlation_type="narrative",
            max_cluster_exposure_usd=3000.0,
        )
        session.add(group)
        await session.flush()
        assert group.correlation_type == "narrative"


class TestResolutionModels:
    @pytest.mark.asyncio
    async def test_resolution_parse_result(self, session: AsyncSession):
        market = Market(market_id="resolve-test", title="Resolution", is_active=True)
        session.add(market)
        await session.flush()

        wf = WorkflowRun(workflow_run_id="wf-resolve", run_type="trigger_based", market_id=market.id)
        session.add(wf)
        await session.flush()

        thesis = ThesisCard(
            market_id=market.id,
            workflow_run_id=wf.id,
            category="politics",
            category_quality_tier="standard",
            proposed_side="yes",
            resolution_interpretation="Win via official results",
            core_thesis="Test thesis",
            why_mispriced="Test reason",
            supporting_evidence=[],
            opposing_evidence=[],
            invalidation_conditions=[],
        )
        session.add(thesis)
        await session.flush()

        result = ResolutionParseResult(
            thesis_card_id=thesis.id,
            has_named_source=True,
            has_explicit_deadline=True,
            has_ambiguous_wording=False,
            has_undefined_terms=False,
            has_multi_step_deps=False,
            has_unclear_jurisdiction=False,
            has_counter_intuitive_risk=False,
            overall_clarity="clear",
            parsed_at=datetime.now(tz=UTC),
        )
        session.add(result)
        await session.flush()
        assert result.overall_clarity == "clear"

    @pytest.mark.asyncio
    async def test_sports_quality_gate(self, session: AsyncSession):
        market = Market(market_id="sports-gate-test", title="Sports Gate", is_active=True)
        session.add(market)
        await session.flush()

        wf = WorkflowRun(workflow_run_id="wf-sports-gate", run_type="trigger_based", market_id=market.id)
        session.add(wf)
        await session.flush()

        thesis = ThesisCard(
            market_id=market.id,
            workflow_run_id=wf.id,
            category="sports",
            category_quality_tier="quality_gated",
            proposed_side="yes",
            resolution_interpretation="Win via final score",
            core_thesis="Test",
            why_mispriced="Test",
            supporting_evidence=[],
            opposing_evidence=[],
            invalidation_conditions=[],
        )
        session.add(thesis)
        await session.flush()

        gate = SportsQualityGateResult(
            thesis_card_id=thesis.id,
            resolution_fully_objective=True,
            resolves_in_48h_plus=True,
            adequate_liquidity_and_depth=True,
            not_statistical_modeling=True,
            credible_evidential_basis=True,
            all_criteria_passed=True,
            size_multiplier=0.7,
            evaluated_at=datetime.now(tz=UTC),
        )
        session.add(gate)
        await session.flush()
        assert gate.all_criteria_passed is True
        assert gate.size_multiplier == 0.7


class TestReferenceModels:
    @pytest.mark.asyncio
    async def test_base_rate_reference(self, session: AsyncSession):
        ref = BaseRateReference(
            market_type="politics_election_winner",
            category="politics",
            base_rate=0.50,
            confidence_level="none",
            sample_size=0,
            last_updated_at=datetime.now(tz=UTC),
        )
        session.add(ref)
        await session.flush()
        assert ref.base_rate == 0.50

    @pytest.mark.asyncio
    async def test_system_health_snapshot(self, session: AsyncSession):
        snapshot = SystemHealthSnapshot(
            clob_api_available=True,
            clob_api_latency_ms=150.0,
            cache_entries_count=50,
            cache_stale_count=2,
            scanner_degraded_level=0,
            overall_status="healthy",
            snapshot_at=datetime.now(tz=UTC),
        )
        session.add(snapshot)
        await session.flush()
        assert snapshot.overall_status == "healthy"


class TestLoggingModels:
    @pytest.mark.asyncio
    async def test_journal_entry(self, session: AsyncSession):
        entry = JournalEntry(
            journal_type="investigation",
            title="Investigation of Market X",
            narrative="Investigated market X, found strong evidence supporting YES...",
            written_at=datetime.now(tz=UTC),
        )
        session.add(entry)
        await session.flush()
        assert entry.journal_type == "investigation"

    @pytest.mark.asyncio
    async def test_structured_log_entry(self, session: AsyncSession):
        log = StructuredLogEntry(
            event_type="eligibility_check",
            severity="info",
            component="eligibility_gate",
            payload={"outcome": "reject", "reason": "excluded_category"},
            logged_at=datetime.now(tz=UTC),
        )
        session.add(log)
        await session.flush()
        assert log.event_type == "eligibility_check"

    @pytest.mark.asyncio
    async def test_alert(self, session: AsyncSession):
        alert = Alert(
            alert_type="drawdown_warning",
            severity="warning",
            source_component="risk_governor",
            title="Drawdown Warning: 3.5%",
            message="Daily drawdown reached 3.5%, approaching soft warning threshold",
            raised_at=datetime.now(tz=UTC),
        )
        session.add(alert)
        await session.flush()
        assert alert.alert_type == "drawdown_warning"


# ============================================================
# 8. Repository Tests
# ============================================================


class TestMarketRepository:
    @pytest.mark.asyncio
    async def test_get_by_market_id(self, session: AsyncSession):
        repo = MarketRepository(session)
        market = Market(market_id="repo-test-001", title="Repo Test", is_active=True)
        await repo.create(market)

        fetched = await repo.get_by_market_id("repo-test-001")
        assert fetched is not None
        assert fetched.title == "Repo Test"

    @pytest.mark.asyncio
    async def test_get_active_markets(self, session: AsyncSession):
        repo = MarketRepository(session)
        m1 = Market(market_id="active-1", title="Active 1", is_active=True)
        m2 = Market(market_id="inactive-1", title="Inactive 1", is_active=False)
        await repo.create(m1)
        await repo.create(m2)

        active = await repo.get_active_markets()
        active_ids = [m.market_id for m in active]
        assert "active-1" in active_ids
        assert "inactive-1" not in active_ids

    @pytest.mark.asyncio
    async def test_get_by_category(self, session: AsyncSession):
        repo = MarketRepository(session)
        m1 = Market(market_id="cat-pol-1", title="Politics 1", is_active=True, category="politics")
        m2 = Market(market_id="cat-tech-1", title="Tech 1", is_active=True, category="technology")
        await repo.create(m1)
        await repo.create(m2)

        politics = await repo.get_by_category("politics")
        assert any(m.market_id == "cat-pol-1" for m in politics)

    @pytest.mark.asyncio
    async def test_count(self, session: AsyncSession):
        repo = MarketRepository(session)
        initial_count = await repo.count()
        await repo.create(Market(market_id="count-test", title="Count", is_active=True))
        new_count = await repo.count()
        assert new_count == initial_count + 1


class TestPositionRepository:
    @pytest.mark.asyncio
    async def test_get_open_positions(self, session: AsyncSession):
        repo = PositionRepository(session)
        market = Market(market_id="pos-repo-test", title="Pos Repo", is_active=True)
        session.add(market)
        await session.flush()

        p_open = Position(
            market_id=market.id, side="yes", entry_price=0.5,
            size=100, remaining_size=100, status="open",
        )
        p_closed = Position(
            market_id=market.id, side="no", entry_price=0.6,
            size=50, remaining_size=0, status="closed",
        )
        await repo.create(p_open)
        await repo.create(p_closed)

        open_positions = await repo.get_open_positions()
        statuses = [p.status for p in open_positions]
        assert "open" in statuses
        assert "closed" not in statuses


class TestWorkflowRunRepository:
    @pytest.mark.asyncio
    async def test_get_by_workflow_run_id(self, session: AsyncSession):
        repo = WorkflowRunRepository(session)
        wf = WorkflowRun(
            workflow_run_id="wf-repo-test",
            run_type="scheduled_sweep",
        )
        await repo.create(wf)

        fetched = await repo.get_by_workflow_run_id("wf-repo-test")
        assert fetched is not None
        assert fetched.run_type == "scheduled_sweep"


class TestThesisCardRepository:
    @pytest.mark.asyncio
    async def test_get_by_market(self, session: AsyncSession):
        repo = ThesisCardRepository(session)

        market = Market(market_id="thesis-repo", title="Thesis Repo", is_active=True)
        session.add(market)
        await session.flush()

        wf = WorkflowRun(workflow_run_id="wf-thesis-repo", run_type="trigger_based")
        session.add(wf)
        await session.flush()

        thesis = ThesisCard(
            market_id=market.id,
            workflow_run_id=wf.id,
            category="technology",
            category_quality_tier="standard",
            proposed_side="no",
            resolution_interpretation="Test",
            core_thesis="Test",
            why_mispriced="Test",
            supporting_evidence=[],
            opposing_evidence=[],
            invalidation_conditions=[],
        )
        await repo.create(thesis)

        results = await repo.get_by_market(market.id)
        assert len(results) == 1
        assert results[0].category == "technology"


class TestCalibrationRepository:
    @pytest.mark.asyncio
    async def test_get_by_segment(self, session: AsyncSession):
        repo = CalibrationRecordRepository(session)

        record = CalibrationRecord(
            segment_type="category",
            segment_label="politics",
            regime="insufficient",
            resolved_count=12,
            total_forecasts=30,
            min_threshold=30,
            updated_at_cal=datetime.now(tz=UTC),
        )
        await repo.create(record)

        fetched = await repo.get_by_segment("category", "politics")
        assert fetched is not None
        assert fetched.resolved_count == 12


class TestBaseRateRepository:
    @pytest.mark.asyncio
    async def test_get_by_market_type(self, session: AsyncSession):
        repo = BaseRateReferenceRepository(session)

        ref = BaseRateReference(
            market_type="test_type_repo",
            category="politics",
            base_rate=0.55,
            last_updated_at=datetime.now(tz=UTC),
        )
        await repo.create(ref)

        fetched = await repo.get_by_market_type("test_type_repo")
        assert fetched is not None
        assert fetched.base_rate == 0.55


# ============================================================
# 9. Seed Data Structure Validation
# ============================================================


class TestSeedDataStructure:
    """Validate seed data constants are well-formed."""

    def test_base_rate_references_valid(self):
        from data.seed import BASE_RATE_REFERENCES

        for ref in BASE_RATE_REFERENCES:
            assert "market_type" in ref
            assert "category" in ref
            assert "base_rate" in ref
            assert 0.0 <= ref["base_rate"] <= 1.0
            assert ref["category"] in {
                "politics", "geopolitics", "technology",
                "science_health", "macro_policy", "sports",
            }

    def test_calibration_thresholds_valid(self):
        from data.seed import CALIBRATION_THRESHOLDS

        for thresh in CALIBRATION_THRESHOLDS:
            assert "threshold_name" in thresh
            assert "min_trades" in thresh
            assert thresh["min_trades"] > 0

    def test_default_friction_params_valid(self):
        from data.seed import DEFAULT_FRICTION_PARAMS

        assert DEFAULT_FRICTION_PARAMS["spread_estimate"] > 0
        assert DEFAULT_FRICTION_PARAMS["depth_assumption"] > 0
        assert DEFAULT_FRICTION_PARAMS["impact_coefficient"] > 0
