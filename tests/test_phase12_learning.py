from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from calibration.accumulation import AccumulationTracker
from calibration.brier import BrierEngine
from calibration.friction import FrictionCalibrator
from calibration.segments import SegmentManager
from calibration.store import CalibrationStore
from calibration.types import (
    BrierComparison,
    FrictionFeedback,
    HorizonBucket,
    SegmentState,
    SegmentType,
    ShadowForecastInput,
    ShadowForecastResolution,
)
from learning.category_ledger import CategoryLedgerBuilder
from learning.fast_loop import FastLearningLoop
from learning.no_trade_monitor import NoTradeMonitor
from learning.patience_budget import PatienceBudgetTracker
from learning.performance_review import PerformanceReviewWorkflow
from learning.policy_review import PolicyReviewEngine
from learning.slow_loop import SlowLearningLoop
from learning.types import (
    CategoryLedgerEntry,
    CategoryLedgerReport,
    FastLoopInput,
    NoTradeRateSignal,
    PatienceDecision,
    PolicyChangeStatus,
    SlowLoopInput,
)


def record_resolved_forecast(
    store: CalibrationStore,
    *,
    market_id: str,
    resolved_at: datetime,
    system_probability: float,
    market_probability: float,
    outcome: float,
    category: str = "politics",
    horizon_bucket: HorizonBucket = HorizonBucket.MEDIUM,
    base_rate_probability: float | None = 0.5,
) -> None:
    store.record_forecast(
        ShadowForecastInput(
            market_id=market_id,
            workflow_run_id=f"wf-{market_id}",
            system_probability=system_probability,
            market_implied_probability=market_probability,
            base_rate_probability=base_rate_probability,
            category=category,
            horizon_bucket=horizon_bucket,
            thesis_context={"market_id": market_id},
            forecast_at=resolved_at - timedelta(days=2),
        )
    )
    store.resolve_forecast(
        ShadowForecastResolution(
            market_id=market_id,
            resolution_outcome=outcome,
            resolved_at=resolved_at,
        )
    )


@pytest.fixture
def base_now() -> datetime:
    return datetime(2026, 4, 13, 12, 0, tzinfo=UTC)


class TestCategoryLedgerBuilder:
    def test_builds_complete_report_with_totals(self, base_now: datetime) -> None:
        builder = CategoryLedgerBuilder()
        builder.set_period(base_now - timedelta(days=7), base_now)
        builder.add_trade_metrics(
            "politics",
            trades_count=4,
            wins=3,
            gross_pnl=12.0,
            net_pnl=9.0,
            average_edge=0.08,
            average_holding_hours=36.0,
        )
        builder.add_cost_metrics(
            "politics",
            inference_cost_usd=1.5,
            cost_of_selectivity=0.3,
            slippage_ratio=1.1,
            entry_impact_pct=0.12,
        )
        builder.add_quality_metrics(
            "politics",
            rejection_rate=0.4,
            no_trade_rate=0.55,
            brier_score=0.14,
            system_vs_market_brier=0.06,
        )
        builder.add_exit_distribution(
            "politics",
            {"profit_protection": 2, "time_decay": 1},
        )

        report = builder.build()
        politics = next(entry for entry in report.entries if entry.category == "politics")

        assert len(report.entries) == 6
        assert politics.win_rate == pytest.approx(0.75)
        assert politics.net_pnl == pytest.approx(9.0)
        assert politics.exit_distribution == {"profit_protection": 2, "time_decay": 1}
        assert report.total_trades == 4
        assert report.total_pnl == pytest.approx(9.0)
        assert report.total_cost == pytest.approx(1.5)


class TestNoTradeMonitor:
    def test_low_no_trade_rate_triggers_quality_warning(self) -> None:
        monitor = NoTradeMonitor()
        for idx in range(10):
            monitor.record_run(had_no_trade=idx < 2, record_date=date.today())

        metrics = monitor.compute_metrics()

        assert metrics.no_trade_rate == pytest.approx(0.2)
        assert metrics.signal == NoTradeRateSignal.LOW_RATE_WARNING
        assert "quality erosion" in metrics.signal_reason

    def test_high_no_trade_rate_triggers_overfiltering_warning(self) -> None:
        monitor = NoTradeMonitor()
        for _ in range(10):
            monitor.record_run(had_no_trade=True, record_date=date.today())

        metrics = monitor.compute_metrics()

        assert metrics.no_trade_rate == pytest.approx(1.0)
        assert metrics.signal == NoTradeRateSignal.HIGH_RATE_WARNING
        assert "over-filtering" in metrics.signal_reason


class TestPatienceBudgetTracker:
    def test_expiry_requires_decision_and_continue_extends_budget(self, base_now: datetime) -> None:
        start = base_now - timedelta(days=31)
        tracker = PatienceBudgetTracker(start, budget_months=1)

        state = tracker.compute_state(base_now)
        assert state.is_expired is True
        assert state.needs_decision is True

        old_expiry = tracker.expiry_date
        tracker.record_decision(PatienceDecision.CONTINUE, decided_at=base_now)
        continued_state = tracker.compute_state(base_now + timedelta(days=1))

        assert tracker.expiry_date > old_expiry
        assert continued_state.operator_decision == PatienceDecision.CONTINUE
        assert continued_state.needs_decision is False


class TestFastLearningLoop:
    def test_execute_updates_calibration_triggers_friction_and_emits_alerts(
        self,
        base_now: datetime,
    ) -> None:
        store = CalibrationStore()
        record_resolved_forecast(
            store,
            market_id="mkt-1",
            resolved_at=base_now - timedelta(days=1),
            system_probability=0.8,
            market_probability=0.6,
            outcome=1.0,
            category="politics",
            horizon_bucket=HorizonBucket.SHORT,
        )
        segment_manager = SegmentManager(store)
        brier_engine = BrierEngine(store)
        friction = FrictionCalibrator(window_size=3)
        for _ in range(3):
            friction.record_slippage(estimated_bps=10.0, realized_bps=18.0)

        no_trade = NoTradeMonitor()
        for idx in range(10):
            no_trade.record_run(had_no_trade=idx < 2, record_date=date.today())

        loop = FastLearningLoop(
            store,
            brier_engine,
            segment_manager,
            friction,
            no_trade,
        )

        result = loop.execute(
            FastLoopInput(
                as_of=base_now,
                new_resolutions=1,
                daily_spend_usd=3.25,
                trades_entered_today=2,
                cost_selectivity_ratio=0.33,
                trades_since_friction_check=3,
                daily_budget_remaining_pct=0.05,
                lifetime_budget_consumed_pct=0.8,
                operator_absent=True,
                absence_hours=52.0,
            )
        )

        assert result.calibration_updated is True
        assert "overall:all" in result.segments_updated
        assert "category:politics" in result.segments_updated
        assert result.friction_recalibration_triggered is True
        assert result.budget_alerts == ["daily_budget_critically_low", "lifetime_budget_75%"]
        assert result.no_trade_signal == NoTradeRateSignal.LOW_RATE_WARNING
        assert result.metrics["daily_spend_usd"] == pytest.approx(3.25)
        assert result.metrics["cost_selectivity_ratio"] == pytest.approx(0.33)
        assert result.metrics["absence_hours"] == pytest.approx(52.0)
        assert any("Friction model recalibration" in warning for warning in result.warnings)
        assert any("No-trade rate signal" in warning for warning in result.warnings)
        assert any("Operator absent for 52.0 hours" in warning for warning in result.warnings)


class TestPolicyReviewEngine:
    def test_generates_threshold_and_category_proposals_and_tracks_status(self) -> None:
        engine = PolicyReviewEngine()
        threshold_proposals = engine.evaluate_thresholds(
            [
                {
                    "segment_label": "politics",
                    "resolved_count": 35,
                    "min_threshold": 30,
                    "system_brier": 0.22,
                    "market_brier": 0.18,
                }
            ],
            [],
        )
        category_proposals = engine.evaluate_category_performance(
            [
                {
                    "category": "politics",
                    "trades_count": 35,
                    "net_pnl": -12.5,
                    "brier_score": 0.22,
                    "system_vs_market_brier": -0.04,
                }
            ]
        )

        assert len(threshold_proposals) == 1
        assert len(category_proposals) == 1
        assert "Calibration review needed" in threshold_proposals[0].title
        assert "negative net PnL" in category_proposals[0].description

        manual = engine.propose_change(
            area="risk",
            title="Raise evidence threshold",
            description="Observed quality drift.",
            rationale="Too many low-quality approvals.",
            evidence={"signal": "quality_drift"},
            sample_size=10,
            persistence_weeks=2,
        )
        approved = engine.approve_proposal(threshold_proposals[0])
        rejected = engine.reject_proposal(category_proposals[0])

        assert manual.requires_operator_review is True
        assert manual.min_threshold_met is False
        assert approved.status == PolicyChangeStatus.APPROVED
        assert rejected.status == PolicyChangeStatus.REJECTED
        assert all(proposal.status == PolicyChangeStatus.PENDING for proposal in engine.get_pending_proposals())


class TestSlowLearningLoop:
    def test_execute_runs_full_deterministic_review_cycle(self, base_now: datetime) -> None:
        brier_engine = MagicMock()
        brier_engine.compute_weekly_comparison.return_value = [
            BrierComparison(
                scope="category",
                scope_label="politics",
                period_start=base_now - timedelta(days=7),
                period_end=base_now,
                system_brier=0.24,
                market_brier=0.18,
                base_rate_brier=0.3,
                system_advantage=-0.06,
                resolved_count=35,
            )
        ]

        accumulation = MagicMock(spec=AccumulationTracker)
        accumulation.compute_weekly_projections.return_value = MagicMock(
            bottleneck_segments=["category:politics"],
            overall_pace="critical",
        )

        friction = MagicMock(spec=FrictionCalibrator)
        friction.evaluate.return_value = FrictionFeedback(
            mean_slippage_ratio=1.8,
            trades_in_window=20,
            needs_tightening=True,
            current_spread_estimate=0.02,
            current_depth_assumption=5000.0,
            current_impact_coefficient=0.5,
            proposed_spread_estimate=0.024,
            proposed_depth_assumption=4166.67,
            proposed_impact_coefficient=0.6,
        )

        segment_manager = MagicMock(spec=SegmentManager)
        segment_manager.compute_all_segment_states.return_value = [
            SegmentState(
                segment_type=SegmentType.CATEGORY,
                segment_label="politics",
                regime="viability_uncertain",
                resolved_count=35,
                total_forecasts=35,
                min_threshold=30,
                system_brier=0.24,
                market_brier=0.18,
                threshold_met=True,
            )
        ]

        policy = PolicyReviewEngine()
        no_trade = NoTradeMonitor()
        ledger = CategoryLedgerReport(
            period_start=base_now - timedelta(days=7),
            period_end=base_now,
            entries=[
                CategoryLedgerEntry(
                    category="politics",
                    period_start=base_now - timedelta(days=7),
                    period_end=base_now,
                    trades_count=35,
                    net_pnl=-7.0,
                    brier_score=0.24,
                    system_vs_market_brier=-0.06,
                )
            ],
        )

        loop = SlowLearningLoop(
            brier_engine,
            segment_manager,
            accumulation,
            friction,
            policy,
            no_trade,
        )

        result = loop.execute(
            SlowLoopInput(
                as_of=base_now,
                category_ledger=ledger,
                agent_usage_by_role={
                    "performance_analyzer": {
                        "total_calls": 12,
                        "success_rate": 0.4,
                        "total_cost_usd": 8.0,
                    }
                },
            )
        )

        assert result.brier_comparison_included is True
        assert result.accumulation_projection_included is True
        assert result.friction_review_included is True
        assert result.threshold_review_complete is True
        assert result.category_analysis_complete is True
        assert result.agent_usefulness_reviewed is True
        assert result.categories_needing_attention == ["politics"]
        assert result.underperforming_agents == ["performance_analyzer"]
        assert result.policy_proposals_generated == 2
        assert any("Calibration bottleneck segments" in warning for warning in result.warnings)
        assert any("Friction model needs adjustment" in warning for warning in result.warnings)


class TestPerformanceReviewWorkflow:
    def test_prepare_input_builds_mandatory_outputs(self, base_now: datetime) -> None:
        store = CalibrationStore()
        record_resolved_forecast(
            store,
            market_id="pol-1",
            resolved_at=base_now - timedelta(days=2),
            system_probability=0.8,
            market_probability=0.6,
            outcome=1.0,
            category="politics",
        )
        workflow = PerformanceReviewWorkflow(store, BrierEngine(store))
        builder = CategoryLedgerBuilder()
        builder.set_period(base_now - timedelta(days=7), base_now)
        builder.add_trade_metrics("politics", trades_count=3, wins=2, net_pnl=5.0)
        builder.add_quality_metrics("politics", brier_score=0.12, system_vs_market_brier=0.04)
        builder.add_cost_metrics("politics", inference_cost_usd=1.2, cost_of_selectivity=0.3)

        prepared = workflow.prepare_input(
            base_now - timedelta(days=7),
            base_now,
            builder,
            system_week_number=6,
            operator_mode="shadow",
            cost_metrics={"daily_spend": 3.0},
            friction_feedback={"ratio": 1.2},
            accumulation_report={"pace": "slow"},
        )

        assert prepared.category_ledger.total_trades == 3
        assert prepared.operator_mode == "shadow"
        assert prepared.system_week_number == 6
        assert prepared.brier_comparisons[0]["scope"] == "overall"
        assert prepared.accumulation_report == {"pace": "slow"}
        assert prepared.cost_metrics == {"daily_spend": 3.0}

    def test_execute_returns_deterministic_only_without_agent_and_placeholder_with_callback(
        self,
        base_now: datetime,
    ) -> None:
        store = CalibrationStore()
        record_resolved_forecast(
            store,
            market_id="pol-1",
            resolved_at=base_now - timedelta(days=1),
            system_probability=0.8,
            market_probability=0.6,
            outcome=1.0,
            category="politics",
        )
        workflow = PerformanceReviewWorkflow(store, BrierEngine(store))
        builder = CategoryLedgerBuilder()
        builder.set_period(base_now - timedelta(days=7), base_now)
        builder.add_trade_metrics("politics", trades_count=2, wins=1, net_pnl=1.0)
        prepared = workflow.prepare_input(base_now - timedelta(days=7), base_now, builder)

        deterministic = workflow.execute(prepared)
        with_callback = workflow.execute(prepared, agent_callback=object())

        assert deterministic.opus_used is False
        assert deterministic.category_ledger.total_trades == 2
        assert with_callback.opus_used is True
        assert with_callback.strategic_synthesis == "Awaiting agent framework integration"
        compressed = workflow._compress_for_opus(prepared)
        assert compressed["week"] == 0
        assert compressed["mode"] == "paper"
        assert compressed["ledger"] == [{"cat": "politics", "n": 2, "wr": 0.5, "pnl": 1.0, "brier": None, "svmb": None, "cos": None}]
