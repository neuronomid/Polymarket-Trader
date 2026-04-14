from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from calibration.accumulation import AccumulationTracker
from calibration.brier import BrierEngine
from calibration.friction import FrictionCalibrator
from calibration.segments import SegmentManager
from calibration.sizing import CalibrationSizer
from calibration.store import CalibrationStore
from calibration.types import (
    HorizonBucket,
    SegmentState,
    SegmentType,
    ShadowForecastInput,
    ShadowForecastResolution,
)
from config.settings import CalibrationConfig, ExecutionConfig, RiskConfig
from core.enums import CalibrationRegime, Category


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
    market_type: str = "binary_event",
    ambiguity_band: str = "low",
    evidence_quality_class: str = "high",
) -> str:
    forecast_at = resolved_at - timedelta(days=2)
    forecast_id = store.record_forecast(
        ShadowForecastInput(
            market_id=market_id,
            workflow_run_id=f"wf-{market_id}",
            system_probability=system_probability,
            market_implied_probability=market_probability,
            base_rate_probability=base_rate_probability,
            category=category,
            horizon_bucket=horizon_bucket,
            market_type=market_type,
            ambiguity_band=ambiguity_band,
            evidence_quality_class=evidence_quality_class,
            thesis_context={"market_id": market_id},
            forecast_at=forecast_at,
        )
    )
    store.resolve_forecast(
        ShadowForecastResolution(
            market_id=market_id,
            resolution_outcome=outcome,
            resolved_at=resolved_at,
        )
    )
    return forecast_id


@pytest.fixture
def base_now() -> datetime:
    return datetime(2026, 4, 13, 12, 0, tzinfo=UTC)


@pytest.fixture
def store() -> CalibrationStore:
    return CalibrationStore()


class TestCalibrationStore:
    def test_store_records_resolves_and_queries_segmented_forecasts(
        self,
        store: CalibrationStore,
        base_now: datetime,
    ) -> None:
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
        store.record_forecast(
            ShadowForecastInput(
                market_id="mkt-2",
                system_probability=0.55,
                market_implied_probability=0.57,
                category="macro_policy",
                horizon_bucket=HorizonBucket.LONG,
            )
        )

        resolved = store.get_resolved()
        unresolved = store.get_unresolved()
        politics = store.get_resolved_by_segment(SegmentType.CATEGORY, "politics")
        short = store.get_resolved_by_segment(SegmentType.HORIZON, "short")

        assert store.get_total_count() == 2
        assert store.get_resolved_count() == 1
        assert len(resolved) == 1
        assert len(unresolved) == 1
        assert politics[0].market_id == "mkt-1"
        assert short[0].horizon_bucket == "short"
        assert resolved[0].system_brier == pytest.approx(0.04)
        assert resolved[0].market_brier == pytest.approx(0.16)
        assert resolved[0].base_rate_brier == pytest.approx(0.25)

    def test_store_resolves_multiple_forecasts_for_same_market(
        self,
        store: CalibrationStore,
        base_now: datetime,
    ) -> None:
        first = store.record_forecast(
            ShadowForecastInput(
                market_id="shared-market",
                system_probability=0.75,
                market_implied_probability=0.55,
                category="politics",
            )
        )
        second = store.record_forecast(
            ShadowForecastInput(
                market_id="shared-market",
                system_probability=0.65,
                market_implied_probability=0.50,
                category="politics",
            )
        )

        results = store.resolve_forecast(
            ShadowForecastResolution(
                market_id="shared-market",
                resolution_outcome=1.0,
                resolved_at=base_now,
            )
        )
        repeat_results = store.resolve_forecast(
            ShadowForecastResolution(
                market_id="shared-market",
                resolution_outcome=1.0,
                resolved_at=base_now + timedelta(hours=1),
            )
        )

        assert {result.forecast_id for result in results} == {first, second}
        assert repeat_results == []


class TestBrierEngine:
    def test_weekly_comparison_aggregates_overall_category_and_horizon(
        self,
        store: CalibrationStore,
        base_now: datetime,
    ) -> None:
        record_resolved_forecast(
            store,
            market_id="pol-1",
            resolved_at=base_now - timedelta(days=2),
            system_probability=0.8,
            market_probability=0.6,
            outcome=1.0,
            category="politics",
            horizon_bucket=HorizonBucket.SHORT,
        )
        record_resolved_forecast(
            store,
            market_id="macro-1",
            resolved_at=base_now - timedelta(days=1),
            system_probability=0.2,
            market_probability=0.4,
            outcome=0.0,
            category="macro_policy",
            horizon_bucket=HorizonBucket.MEDIUM,
        )

        comparisons = BrierEngine(store).compute_weekly_comparison(base_now)
        by_scope = {(comparison.scope, comparison.scope_label): comparison for comparison in comparisons}

        overall = by_scope[("overall", "all")]
        assert overall.system_brier == pytest.approx(0.04)
        assert overall.market_brier == pytest.approx(0.16)
        assert overall.base_rate_brier == pytest.approx(0.25)
        assert overall.system_advantage == pytest.approx(0.12)
        assert overall.system_is_better is True
        assert ("category", "politics") in by_scope
        assert ("category", "macro_policy") in by_scope
        assert ("horizon", "short") in by_scope
        assert ("horizon", "medium") in by_scope

    def test_cumulative_comparison_returns_none_when_no_resolved_forecasts(
        self,
        store: CalibrationStore,
    ) -> None:
        assert BrierEngine(store).compute_cumulative_comparison() is None


class TestSegmentManager:
    def test_compute_segment_state_marks_sufficient_and_sports_remains_insufficient(
        self,
        store: CalibrationStore,
        base_now: datetime,
    ) -> None:
        for idx in range(30):
            record_resolved_forecast(
                store,
                market_id=f"pol-{idx}",
                resolved_at=base_now - timedelta(days=idx),
                system_probability=0.9,
                market_probability=0.6,
                outcome=1.0,
                category="politics",
                horizon_bucket=HorizonBucket.MEDIUM,
            )
        for idx in range(30):
            record_resolved_forecast(
                store,
                market_id=f"sports-{idx}",
                resolved_at=base_now - timedelta(days=idx),
                system_probability=0.9,
                market_probability=0.6,
                outcome=1.0,
                category="sports",
                horizon_bucket=HorizonBucket.SHORT,
            )

        manager = SegmentManager(store)
        politics = manager.compute_segment_state(SegmentType.CATEGORY, "politics")
        sports = manager.compute_segment_state(SegmentType.CATEGORY, "sports")

        assert politics.threshold_met is True
        assert politics.regime == CalibrationRegime.SUFFICIENT
        assert politics.source_status.value == "preliminary"
        assert politics.system_advantage > 0
        assert sports.threshold_met is False
        assert sports.min_threshold == 40
        assert sports.regime == CalibrationRegime.INSUFFICIENT

    def test_compute_segment_state_marks_viability_uncertain_when_system_worse_than_market(
        self,
        store: CalibrationStore,
        base_now: datetime,
    ) -> None:
        for idx in range(30):
            record_resolved_forecast(
                store,
                market_id=f"macro-{idx}",
                resolved_at=base_now - timedelta(days=idx),
                system_probability=0.2,
                market_probability=0.8,
                outcome=1.0,
                category="macro_policy",
                horizon_bucket=HorizonBucket.LONG,
            )

        state = SegmentManager(store).compute_segment_state(
            SegmentType.CATEGORY,
            "macro_policy",
        )

        assert state.threshold_met is True
        assert state.system_advantage < 0
        assert state.regime == CalibrationRegime.VIABILITY_UNCERTAIN

    def test_cross_category_pool_filters_on_shared_horizon_and_applies_penalty(
        self,
        store: CalibrationStore,
        base_now: datetime,
    ) -> None:
        for idx in range(8):
            record_resolved_forecast(
                store,
                market_id=f"pol-short-{idx}",
                resolved_at=base_now - timedelta(days=idx),
                system_probability=0.8,
                market_probability=0.6,
                outcome=1.0,
                category="politics",
                horizon_bucket=HorizonBucket.SHORT,
            )
        for idx in range(5):
            record_resolved_forecast(
                store,
                market_id=f"pol-long-{idx}",
                resolved_at=base_now - timedelta(days=idx + 20),
                system_probability=0.8,
                market_probability=0.6,
                outcome=1.0,
                category="politics",
                horizon_bucket=HorizonBucket.LONG,
            )
        for idx in range(7):
            record_resolved_forecast(
                store,
                market_id=f"tech-short-{idx}",
                resolved_at=base_now - timedelta(days=idx + 1),
                system_probability=0.8,
                market_probability=0.6,
                outcome=1.0,
                category="technology",
                horizon_bucket=HorizonBucket.SHORT,
            )
        for idx in range(5):
            record_resolved_forecast(
                store,
                market_id=f"tech-long-{idx}",
                resolved_at=base_now - timedelta(days=idx + 30),
                system_probability=0.8,
                market_probability=0.6,
                outcome=1.0,
                category="technology",
                horizon_bucket=HorizonBucket.LONG,
            )

        pool = SegmentManager(store).attempt_cross_category_pool(
            "politics",
            "technology",
            "short",
        )

        assert pool is not None
        assert pool.combined_resolved == 15
        assert pool.individual_counts == {"politics": 8, "technology": 7}
        assert pool.pool_minimum_met is True
        assert pool.individual_minimums_met is True
        assert pool.is_valid is True
        assert pool.pooled_system_brier == pytest.approx(0.052)
        assert pool.pooled_market_brier == pytest.approx(0.16)
        assert pool.pooled_advantage == pytest.approx(0.108)

    def test_cross_category_pool_rejects_incompatible_categories(
        self,
        store: CalibrationStore,
    ) -> None:
        pool = SegmentManager(store).attempt_cross_category_pool(
            "politics",
            "sports",
            "medium",
        )

        assert pool is None

    def test_size_penalty_eligible_requires_minimum_trades_and_base_rate_improvement(
        self,
        store: CalibrationStore,
        base_now: datetime,
    ) -> None:
        for idx in range(30):
            record_resolved_forecast(
                store,
                market_id=f"tech-{idx}",
                resolved_at=base_now - timedelta(days=idx),
                system_probability=0.9,
                market_probability=0.7,
                base_rate_probability=0.5,
                outcome=1.0,
                category="technology",
                horizon_bucket=HorizonBucket.MEDIUM,
            )

        eligible = SegmentManager(store).get_size_penalty_eligible(
            SegmentType.CATEGORY,
            "technology",
        )

        assert eligible is True


class TestAccumulationTracker:
    def test_compute_weekly_projections_uses_recent_resolution_rate(
        self,
        store: CalibrationStore,
        base_now: datetime,
    ) -> None:
        for idx, days_ago in enumerate((7, 14, 21, 28)):
            record_resolved_forecast(
                store,
                market_id=f"pol-{idx}",
                resolved_at=base_now - timedelta(days=days_ago),
                system_probability=0.9,
                market_probability=0.6,
                outcome=1.0,
                category="politics",
                horizon_bucket=HorizonBucket.SHORT,
            )

        tracker = AccumulationTracker(store, SegmentManager(store))
        report = tracker.compute_weekly_projections(base_now)
        politics = next(
            projection
            for projection in report.projections
            if projection.segment_type == SegmentType.CATEGORY
            and projection.segment_label == "politics"
        )

        assert politics.resolved_per_week == pytest.approx(1.0)
        assert politics.weeks_to_threshold == pytest.approx(26.0)
        assert politics.is_bottleneck is False
        assert report.overall_pace in {"slow", "critical"}

    def test_compute_weekly_projections_recommends_action_when_majority_beyond_patience(
        self,
        base_now: datetime,
    ) -> None:
        segment_manager = MagicMock()
        segment_manager.compute_all_segment_states.return_value = [
            SegmentState(
                segment_type=SegmentType.CATEGORY,
                segment_label="politics",
                resolved_count=5,
                total_forecasts=5,
                min_threshold=30,
            ),
            SegmentState(
                segment_type=SegmentType.CATEGORY,
                segment_label="technology",
                resolved_count=10,
                total_forecasts=10,
                min_threshold=30,
            ),
            SegmentState(
                segment_type=SegmentType.CATEGORY,
                segment_label="macro_policy",
                resolved_count=28,
                total_forecasts=28,
                min_threshold=30,
            ),
        ]

        tracker = AccumulationTracker(CalibrationStore(), segment_manager, patience_months=1)
        rates = {
            (SegmentType.CATEGORY, "politics"): 0.0,
            (SegmentType.CATEGORY, "technology"): 0.1,
            (SegmentType.CATEGORY, "macro_policy"): 10.0,
        }
        tracker._compute_resolution_rate = lambda segment_type, segment_label, as_of: rates[(segment_type, segment_label)]  # type: ignore[method-assign]

        report = tracker.compute_weekly_projections(base_now)

        assert report.majority_beyond_patience is True
        assert report.overall_pace == "critical"
        assert report.recommendation is not None
        assert "Majority of segments project beyond patience budget" in report.recommendation


class TestCalibrationSizer:
    def test_adjust_size_applies_insufficient_and_sports_penalties(self) -> None:
        segment_manager = MagicMock()

        def compute_segment_state(segment_type, segment_label):
            if segment_type == SegmentType.CATEGORY and segment_label == "sports":
                return SegmentState(
                    segment_type=segment_type,
                    segment_label=segment_label,
                    regime=CalibrationRegime.INSUFFICIENT,
                    resolved_count=10,
                    total_forecasts=10,
                    min_threshold=40,
                    threshold_met=False,
                )
            return SegmentState(
                segment_type=segment_type,
                segment_label=segment_label,
                regime=CalibrationRegime.INSUFFICIENT,
                resolved_count=0,
                total_forecasts=0,
                min_threshold=20,
                threshold_met=False,
            )

        segment_manager.compute_segment_state.side_effect = compute_segment_state
        segment_manager.get_size_penalty_eligible.return_value = False

        sizer = CalibrationSizer(segment_manager, RiskConfig(), CalibrationConfig())
        result = sizer.adjust_size(400.0, Category.SPORTS, 0.62)

        assert result.regime == CalibrationRegime.INSUFFICIENT
        assert result.size_cap_multiplier == 0.5
        assert result.sports_adjustment == 0.5
        assert result.category_adjustment == pytest.approx(0.7)
        assert result.adjusted_size_usd == pytest.approx(70.0)
        assert "sports_penalty=0.5" in result.reason

    def test_adjust_size_uses_sufficient_regime_and_calibrated_probability(self) -> None:
        segment_manager = MagicMock()

        def compute_segment_state(segment_type, segment_label):
            return SegmentState(
                segment_type=segment_type,
                segment_label=segment_label,
                regime=CalibrationRegime.SUFFICIENT,
                resolved_count=35,
                total_forecasts=35,
                min_threshold=30,
                threshold_met=True,
                system_brier=0.05,
                market_brier=0.12,
                base_rate_brier=0.15,
                system_advantage=0.07,
            )

        segment_manager.compute_segment_state.side_effect = compute_segment_state
        segment_manager.get_size_penalty_eligible.return_value = True

        sizer = CalibrationSizer(segment_manager, RiskConfig(), CalibrationConfig())
        result = sizer.adjust_size(500.0, Category.POLITICS, 0.68)

        assert result.regime == CalibrationRegime.SUFFICIENT
        assert result.adjusted_size_usd == pytest.approx(500.0)
        assert result.used_calibrated is True
        assert result.calibrated_probability == pytest.approx(0.68)
        assert result.reason == "regime=sufficient"

    def test_adjust_size_chooses_more_conservative_overall_regime(self) -> None:
        segment_manager = MagicMock()

        def compute_segment_state(segment_type, segment_label):
            if segment_type == SegmentType.CATEGORY:
                return SegmentState(
                    segment_type=segment_type,
                    segment_label=segment_label,
                    regime=CalibrationRegime.SUFFICIENT,
                    resolved_count=35,
                    total_forecasts=35,
                    min_threshold=30,
                    threshold_met=True,
                    system_brier=0.05,
                    market_brier=0.12,
                    base_rate_brier=0.15,
                    system_advantage=0.07,
                )
            return SegmentState(
                segment_type=segment_type,
                segment_label=segment_label,
                regime=CalibrationRegime.INSUFFICIENT,
                resolved_count=5,
                total_forecasts=5,
                min_threshold=20,
                threshold_met=False,
            )

        segment_manager.compute_segment_state.side_effect = compute_segment_state
        segment_manager.get_size_penalty_eligible.return_value = True

        result = CalibrationSizer(segment_manager).adjust_size(
            300.0,
            Category.TECHNOLOGY,
            0.6,
        )

        assert result.regime == CalibrationRegime.INSUFFICIENT
        assert result.size_cap_multiplier == 0.5
        assert result.adjusted_size_usd == pytest.approx(150.0)


class TestFrictionCalibrator:
    def test_evaluate_and_apply_tightening_feedback(self) -> None:
        calibrator = FrictionCalibrator(ExecutionConfig(), window_size=5)
        for _ in range(5):
            calibrator.record_slippage(estimated_bps=10.0, realized_bps=20.0)

        feedback = calibrator.evaluate()
        calibrator.apply_adjustment(feedback)

        assert feedback.needs_tightening is True
        assert feedback.can_relax is False
        assert feedback.mean_slippage_ratio == pytest.approx(2.0)
        assert feedback.proposed_spread_estimate == pytest.approx(0.024)
        assert feedback.proposed_depth_assumption == pytest.approx(4166.67, rel=1e-3)
        assert feedback.proposed_impact_coefficient == pytest.approx(0.6)
        assert calibrator.spread_estimate == pytest.approx(0.024)
        assert calibrator.impact_coefficient == pytest.approx(0.6)
        assert calibrator.version == 2

    def test_evaluate_detects_relaxation_when_realized_is_well_below_estimate(self) -> None:
        calibrator = FrictionCalibrator(ExecutionConfig(), window_size=5)
        for _ in range(5):
            calibrator.record_slippage(estimated_bps=10.0, realized_bps=5.0)

        feedback = calibrator.evaluate()

        assert feedback.needs_tightening is False
        assert feedback.can_relax is True
        assert feedback.mean_slippage_ratio == pytest.approx(0.5)
        assert feedback.proposed_spread_estimate == pytest.approx(0.018)
        assert feedback.proposed_depth_assumption == pytest.approx(5555.56, rel=1e-3)
        assert feedback.proposed_impact_coefficient == pytest.approx(0.45)
