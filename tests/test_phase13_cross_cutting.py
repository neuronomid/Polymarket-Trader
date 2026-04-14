"""Phase 13: Cross-Cutting Systems — comprehensive tests.

Tests cover:
1. Bias detection statistical checks, persistence, and weekly audit orchestration
2. Strategy viability checkpoints, scheduling, and lifetime budget tracking
3. Operator absence escalation, restrictions, wind-down, and return workflow
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from absence.manager import DEFAULT_ALERT_CHANNELS, WINDDOWN_TARGET_HOURS, AbsenceManager
from absence.types import (
    AbsenceAction,
    AbsenceActionRecord,
    AbsenceAlertType,
    AbsenceLevel,
    AbsenceRestriction,
    InteractionType,
    OperatorInteraction,
)
from bias.audit import BiasAuditRunner
from bias.detector import BiasDetector
from bias.types import (
    BiasAlertType,
    BiasAuditResult,
    BiasDetectionInput,
    BiasPatternType,
    ForecastDataPoint,
)
from calibration.store import CalibrationStore
from calibration.types import ShadowForecastInput, ShadowForecastResolution
from config.settings import AbsenceConfig, CalibrationConfig, CostConfig
from viability.processor import ViabilityProcessor
from viability.types import (
    ViabilityAlertType,
    ViabilityCheckpointInput,
    ViabilityCheckpointType,
    ViabilityMetrics,
    ViabilityStatus,
)


def make_bias_forecast(
    idx: int,
    *,
    system_probability: float,
    market_implied_probability: float,
    base_rate_probability: float | None = None,
    resolution_outcome: float = 1.0,
    evidence_quality_score: float | None = None,
    forecast_accuracy: float | None = None,
    resolved_at: datetime | None = None,
) -> ForecastDataPoint:
    if resolved_at is None:
        resolved_at = datetime(2026, 4, 13, 12, 0, tzinfo=UTC) - timedelta(days=idx)
    if forecast_accuracy is None:
        forecast_accuracy = abs(system_probability - resolution_outcome)

    return ForecastDataPoint(
        forecast_id=f"fc-{idx}",
        market_id=f"mkt-{idx}",
        category="politics",
        system_probability=system_probability,
        market_implied_probability=market_implied_probability,
        base_rate_probability=base_rate_probability,
        resolution_outcome=resolution_outcome,
        evidence_quality_score=evidence_quality_score,
        forecast_accuracy=forecast_accuracy,
        forecast_at=resolved_at - timedelta(days=2),
        resolved_at=resolved_at,
    )


def make_viability_metrics(**overrides) -> ViabilityMetrics:
    data = {
        "resolved_forecasts": 0,
        "system_brier": 0.18,
        "market_brier": 0.20,
        "base_rate_brier": 0.24,
        "system_advantage": 0.02,
        "hypothetical_pnl": 125.0,
        "cost_of_selectivity": 0.16,
        "total_inference_cost_usd": 42.0,
        "accumulation_rate_per_week": 6.0,
        "projected_50_resolved_date": datetime(2026, 6, 1, tzinfo=UTC),
        "lifetime_budget_consumed_pct": 0.0,
        "daily_budget_remaining_pct": 0.8,
    }
    data.update(overrides)
    return ViabilityMetrics(**data)


def record_resolved_forecast(
    store: CalibrationStore,
    *,
    market_id: str,
    resolved_at: datetime,
    system_probability: float,
    market_probability: float,
    outcome: float,
    base_rate_probability: float | None = 0.5,
    evidence_quality_score: float | None = None,
) -> None:
    store.record_forecast(
        ShadowForecastInput(
            market_id=market_id,
            workflow_run_id=f"wf-{market_id}",
            system_probability=system_probability,
            market_implied_probability=market_probability,
            base_rate_probability=base_rate_probability,
            category="politics",
            thesis_context={"evidence_quality_score": evidence_quality_score}
            if evidence_quality_score is not None
            else {},
            forecast_at=resolved_at - timedelta(days=1),
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


@pytest.fixture
def bias_detector() -> BiasDetector:
    return BiasDetector()


@pytest.fixture
def viability_processor() -> ViabilityProcessor:
    return ViabilityProcessor(CalibrationConfig(), CostConfig())


@pytest.fixture
def absence_manager() -> AbsenceManager:
    return AbsenceManager(AbsenceConfig())


class TestBiasDetector:
    def test_run_audit_returns_defaults_when_sample_below_minimum(
        self,
        bias_detector: BiasDetector,
        base_now: datetime,
    ) -> None:
        forecasts = [
            make_bias_forecast(
                idx,
                system_probability=0.55 + idx * 0.05,
                market_implied_probability=0.50 + idx * 0.05,
                base_rate_probability=0.55 + idx * 0.05,
                resolved_at=base_now - timedelta(days=idx),
            )
            for idx in range(4)
        ]

        result = bias_detector.run_audit(
            BiasDetectionInput(
                forecasts=forecasts,
                period_start=base_now - timedelta(days=7),
                period_end=base_now,
            )
        )

        assert result.sample_size == 4
        assert result.any_bias_detected is False
        assert result.detected_patterns == []
        assert result.alerts == []
        assert result.pattern_weeks == {}

    def test_detects_directional_bias_and_emits_new_pattern_alert(
        self,
        bias_detector: BiasDetector,
        base_now: datetime,
    ) -> None:
        forecasts = [
            make_bias_forecast(
                idx,
                system_probability=system_probability,
                market_implied_probability=market_probability,
                base_rate_probability=system_probability,
                resolved_at=base_now - timedelta(days=idx),
            )
            for idx, (system_probability, market_probability) in enumerate(
                [
                    (0.25, 0.10),
                    (0.45, 0.30),
                    (0.60, 0.45),
                    (0.75, 0.60),
                    (0.90, 0.75),
                ],
                start=1,
            )
        ]

        result = bias_detector.run_audit(
            BiasDetectionInput(
                forecasts=forecasts,
                period_start=base_now - timedelta(days=14),
                period_end=base_now,
            )
        )

        assert result.directional.detected is True
        assert result.directional.direction == "bullish"
        assert result.directional.skew_pp == pytest.approx(15.0)
        assert BiasPatternType.DIRECTIONAL in result.detected_patterns
        assert result.pattern_weeks["directional"] == 1
        assert result.alerts[0].alert_type == BiasAlertType.BIAS_PATTERN_DETECTED

    def test_detects_confidence_clustering(
        self,
        bias_detector: BiasDetector,
        base_now: datetime,
    ) -> None:
        forecasts = [
            make_bias_forecast(
                idx,
                system_probability=system_probability,
                market_implied_probability=market_probability,
                base_rate_probability=system_probability,
                resolved_at=base_now - timedelta(days=idx),
            )
            for idx, (system_probability, market_probability) in enumerate(
                [
                    (0.41, 0.30),
                    (0.44, 0.36),
                    (0.47, 0.54),
                    (0.50, 0.61),
                    (0.53, 0.45),
                    (0.80, 0.73),
                ],
                start=1,
            )
        ]

        result = bias_detector.run_audit(
            BiasDetectionInput(
                forecasts=forecasts,
                period_start=base_now - timedelta(days=14),
                period_end=base_now,
            )
        )

        assert result.confidence_clustering.detected is True
        assert result.confidence_clustering.pct_in_peak_band == pytest.approx(5 / 6, rel=1e-3)
        assert result.confidence_clustering.peak_band_start == pytest.approx(0.33, abs=0.02)
        assert BiasPatternType.CONFIDENCE_CLUSTERING in result.detected_patterns

    def test_detects_anchoring(
        self,
        bias_detector: BiasDetector,
        base_now: datetime,
    ) -> None:
        forecasts = [
            make_bias_forecast(
                idx,
                system_probability=system_probability,
                market_implied_probability=market_probability,
                base_rate_probability=system_probability,
                resolved_at=base_now - timedelta(days=idx),
            )
            for idx, (system_probability, market_probability) in enumerate(
                [
                    (0.32, 0.31),
                    (0.41, 0.40),
                    (0.57, 0.56),
                    (0.66, 0.65),
                    (0.74, 0.75),
                ],
                start=1,
            )
        ]

        result = bias_detector.run_audit(
            BiasDetectionInput(
                forecasts=forecasts,
                period_start=base_now - timedelta(days=14),
                period_end=base_now,
            )
        )

        assert result.anchoring.detected is True
        assert result.anchoring.mean_abs_diff_pp == pytest.approx(1.0)
        assert BiasPatternType.ANCHORING in result.detected_patterns

    def test_detects_narrative_overweighting(
        self,
        bias_detector: BiasDetector,
        base_now: datetime,
    ) -> None:
        evidence_quality_scores = [0.10, 0.20, 0.30, 0.80, 0.90, 1.00]
        forecast_errors = [0.05, 0.08, 0.10, 0.25, 0.30, 0.35]
        system_probs = [0.20, 0.30, 0.40, 0.60, 0.70, 0.80]
        market_probs = [0.35, 0.25, 0.55, 0.45, 0.85, 0.65]

        forecasts = [
            make_bias_forecast(
                idx,
                system_probability=system_probability,
                market_implied_probability=market_probability,
                base_rate_probability=system_probability,
                evidence_quality_score=evidence_quality_score,
                forecast_accuracy=forecast_error,
                resolved_at=base_now - timedelta(days=idx),
            )
            for idx, (
                system_probability,
                market_probability,
                evidence_quality_score,
                forecast_error,
            ) in enumerate(
                zip(system_probs, market_probs, evidence_quality_scores, forecast_errors),
                start=1,
            )
        ]

        result = bias_detector.run_audit(
            BiasDetectionInput(
                forecasts=forecasts,
                period_start=base_now - timedelta(days=14),
                period_end=base_now,
            )
        )

        assert result.narrative_overweighting.detected is True
        assert result.narrative_overweighting.correlation is not None
        assert result.narrative_overweighting.correlation > 0.1
        assert result.narrative_overweighting.high_quality_accuracy > result.narrative_overweighting.low_quality_accuracy
        assert BiasPatternType.NARRATIVE_OVERWEIGHTING in result.detected_patterns

    def test_detects_base_rate_neglect(
        self,
        bias_detector: BiasDetector,
        base_now: datetime,
    ) -> None:
        forecasts = [
            make_bias_forecast(
                idx,
                system_probability=system_probability,
                market_implied_probability=market_probability,
                base_rate_probability=base_rate_probability,
                resolved_at=base_now - timedelta(days=idx),
            )
            for idx, (system_probability, market_probability, base_rate_probability) in enumerate(
                [
                    (0.15, 0.30, 0.05),
                    (0.35, 0.20, 0.15),
                    (0.55, 0.60, 0.25),
                    (0.75, 0.70, 0.45),
                    (0.95, 0.95, 0.65),
                ],
                start=1,
            )
        ]

        result = bias_detector.run_audit(
            BiasDetectionInput(
                forecasts=forecasts,
                period_start=base_now - timedelta(days=14),
                period_end=base_now,
            )
        )

        assert result.base_rate_neglect.detected is True
        assert result.base_rate_neglect.systematically_directional is True
        assert result.base_rate_neglect.deviation_direction == "above"
        assert result.base_rate_neglect.mean_deviation == pytest.approx(0.24)
        assert BiasPatternType.BASE_RATE_NEGLECT in result.detected_patterns

    def test_promotes_persistent_patterns_and_emits_resolved_alert(
        self,
        bias_detector: BiasDetector,
        base_now: datetime,
    ) -> None:
        directional_forecasts = [
            make_bias_forecast(
                idx,
                system_probability=system_probability,
                market_implied_probability=market_probability,
                base_rate_probability=system_probability,
                resolved_at=base_now - timedelta(days=idx),
            )
            for idx, (system_probability, market_probability) in enumerate(
                [
                    (0.25, 0.10),
                    (0.45, 0.30),
                    (0.60, 0.45),
                    (0.75, 0.60),
                    (0.90, 0.75),
                ],
                start=1,
            )
        ]
        neutral_forecasts = [
            make_bias_forecast(
                idx + 10,
                system_probability=system_probability,
                market_implied_probability=system_probability,
                base_rate_probability=system_probability,
                resolved_at=base_now - timedelta(days=idx),
            )
            for idx, system_probability in enumerate(
                [0.05, 0.22, 0.41, 0.59, 0.78, 0.95],
                start=1,
            )
        ]

        result_1 = bias_detector.run_audit(
            BiasDetectionInput(
                forecasts=directional_forecasts,
                period_start=base_now - timedelta(days=14),
                period_end=base_now,
            )
        )
        result_2 = bias_detector.run_audit(
            BiasDetectionInput(
                forecasts=directional_forecasts,
                period_start=base_now - timedelta(days=7),
                period_end=base_now + timedelta(days=7),
                previous_patterns=result_1.pattern_weeks,
            )
        )
        result_3 = bias_detector.run_audit(
            BiasDetectionInput(
                forecasts=directional_forecasts,
                period_start=base_now,
                period_end=base_now + timedelta(days=14),
                previous_patterns=result_2.pattern_weeks,
            )
        )
        result_4 = bias_detector.run_audit(
            BiasDetectionInput(
                forecasts=neutral_forecasts,
                period_start=base_now + timedelta(days=7),
                period_end=base_now + timedelta(days=21),
                previous_patterns=result_3.pattern_weeks,
            )
        )

        assert result_2.pattern_weeks["directional"] == 2
        assert result_3.pattern_weeks["directional"] == 3
        assert any(
            alert.alert_type == BiasAlertType.BIAS_PATTERN_PERSISTENT
            and alert.pattern_type == BiasPatternType.DIRECTIONAL
            for alert in result_3.alerts
        )
        assert result_4.pattern_weeks["directional"] == 0
        assert any(
            alert.alert_type == BiasAlertType.BIAS_PATTERN_RESOLVED
            and alert.pattern_type == BiasPatternType.DIRECTIONAL
            for alert in result_4.alerts
        )


class CapturingDetector:
    def __init__(self) -> None:
        self.inputs: list[BiasDetectionInput] = []

    def run_audit(self, inp: BiasDetectionInput) -> BiasAuditResult:
        self.inputs.append(inp)
        pattern_weeks = dict(inp.previous_patterns)
        pattern_weeks["directional"] = inp.previous_patterns.get("directional", 0) + 1
        return BiasAuditResult(
            period_start=inp.period_start,
            period_end=inp.period_end,
            sample_size=len(inp.forecasts),
            any_bias_detected=True,
            detected_patterns=[BiasPatternType.DIRECTIONAL],
            pattern_weeks=pattern_weeks,
        )


class TestBiasAuditRunner:
    def test_collects_windowed_resolved_data_and_persists_pattern_state(
        self,
        base_now: datetime,
    ) -> None:
        store = CalibrationStore()
        capturing_detector = CapturingDetector()
        runner = BiasAuditRunner(capturing_detector, store, lookback_weeks=4)
        runner.load_pattern_state({"directional": 2})

        record_resolved_forecast(
            store,
            market_id="recent-1",
            resolved_at=base_now - timedelta(days=2),
            system_probability=0.80,
            market_probability=0.60,
            outcome=1.0,
            base_rate_probability=0.55,
            evidence_quality_score=0.85,
        )
        record_resolved_forecast(
            store,
            market_id="recent-2",
            resolved_at=base_now - timedelta(days=7),
            system_probability=0.35,
            market_probability=0.45,
            outcome=0.0,
            base_rate_probability=0.40,
            evidence_quality_score=0.25,
        )
        record_resolved_forecast(
            store,
            market_id="old",
            resolved_at=base_now - timedelta(days=40),
            system_probability=0.55,
            market_probability=0.50,
            outcome=1.0,
        )
        store.record_forecast(
            ShadowForecastInput(
                market_id="unresolved",
                workflow_run_id="wf-unresolved",
                system_probability=0.60,
                market_implied_probability=0.58,
                category="politics",
                forecast_at=base_now - timedelta(days=1),
            )
        )

        result = runner.run_weekly_audit(period_end=base_now)
        captured = capturing_detector.inputs[0]

        assert result.sample_size == 2
        assert captured.previous_patterns["directional"] == 2
        assert len(captured.forecasts) == 2
        assert {forecast.market_id for forecast in captured.forecasts} == {"recent-1", "recent-2"}
        assert captured.forecasts[0].forecast_accuracy == pytest.approx(0.20)
        assert captured.forecasts[0].evidence_quality_score == pytest.approx(0.85)
        assert runner.get_pattern_state()["directional"] == 3


class TestViabilityProcessor:
    def test_should_run_checkpoint_schedules_week_and_budget_thresholds(
        self,
        viability_processor: ViabilityProcessor,
    ) -> None:
        assert viability_processor.should_run_checkpoint(4, 0.0) == [ViabilityCheckpointType.WEEK_4]
        assert viability_processor.should_run_checkpoint(8, 0.0) == [ViabilityCheckpointType.WEEK_8]
        assert viability_processor.should_run_checkpoint(12, 0.0) == [ViabilityCheckpointType.WEEK_12]

        week_and_budget = viability_processor.should_run_checkpoint(8, 0.76)
        assert week_and_budget == [
            ViabilityCheckpointType.WEEK_8,
            ViabilityCheckpointType.BUDGET_75,
        ]

        viability_processor.evaluate_checkpoint(
            ViabilityCheckpointInput(
                checkpoint_type=ViabilityCheckpointType.BUDGET_75,
                system_week_number=8,
                metrics=make_viability_metrics(
                    resolved_forecasts=30,
                    lifetime_budget_consumed_pct=0.76,
                ),
            )
        )
        assert viability_processor.should_run_checkpoint(9, 0.80) == []

    def test_week_4_preliminary_checkpoint_is_informational_only(
        self,
        viability_processor: ViabilityProcessor,
    ) -> None:
        result = viability_processor.evaluate_checkpoint(
            ViabilityCheckpointInput(
                checkpoint_type=ViabilityCheckpointType.WEEK_4,
                system_week_number=4,
                metrics=make_viability_metrics(resolved_forecasts=12),
            )
        )

        assert result.status == ViabilityStatus.INSUFFICIENT_DATA
        assert result.requires_acknowledgment is False
        assert result.alerts[0].alert_type == ViabilityAlertType.VIABILITY_CHECKPOINT
        assert "Preliminary checkpoint" in result.status_note

    @pytest.mark.parametrize(
        ("metrics", "expected_status", "expected_alert_type"),
        [
            (
                make_viability_metrics(resolved_forecasts=19),
                ViabilityStatus.INSUFFICIENT_DATA,
                ViabilityAlertType.VIABILITY_CHECKPOINT,
            ),
            (
                make_viability_metrics(
                    resolved_forecasts=24,
                    system_brier=0.24,
                    market_brier=0.20,
                    system_advantage=-0.04,
                ),
                ViabilityStatus.CONCERN,
                ViabilityAlertType.VIABILITY_CONCERN,
            ),
            (
                make_viability_metrics(
                    resolved_forecasts=24,
                    system_brier=0.18,
                    market_brier=0.21,
                    system_advantage=0.03,
                ),
                ViabilityStatus.VIABLE,
                ViabilityAlertType.VIABILITY_CHECKPOINT,
            ),
        ],
    )
    def test_week_8_checkpoint_paths(
        self,
        viability_processor: ViabilityProcessor,
        metrics: ViabilityMetrics,
        expected_status: ViabilityStatus,
        expected_alert_type: ViabilityAlertType,
    ) -> None:
        result = viability_processor.evaluate_checkpoint(
            ViabilityCheckpointInput(
                checkpoint_type=ViabilityCheckpointType.WEEK_8,
                system_week_number=8,
                metrics=metrics,
            )
        )

        assert result.status == expected_status
        assert result.requires_acknowledgment is False
        assert result.alerts[0].alert_type == expected_alert_type

    @pytest.mark.parametrize(
        ("metrics", "expected_status", "requires_ack", "expected_alert_type"),
        [
            (
                make_viability_metrics(resolved_forecasts=49),
                ViabilityStatus.INSUFFICIENT_DATA,
                False,
                ViabilityAlertType.VIABILITY_CHECKPOINT,
            ),
            (
                make_viability_metrics(
                    resolved_forecasts=55,
                    system_brier=0.23,
                    market_brier=0.19,
                    system_advantage=-0.04,
                ),
                ViabilityStatus.WARNING,
                True,
                ViabilityAlertType.VIABILITY_WARNING,
            ),
            (
                make_viability_metrics(
                    resolved_forecasts=55,
                    system_brier=0.17,
                    market_brier=0.20,
                    system_advantage=0.03,
                ),
                ViabilityStatus.VIABLE,
                False,
                ViabilityAlertType.VIABILITY_CHECKPOINT,
            ),
        ],
    )
    def test_week_12_checkpoint_paths(
        self,
        viability_processor: ViabilityProcessor,
        metrics: ViabilityMetrics,
        expected_status: ViabilityStatus,
        requires_ack: bool,
        expected_alert_type: ViabilityAlertType,
    ) -> None:
        result = viability_processor.evaluate_checkpoint(
            ViabilityCheckpointInput(
                checkpoint_type=ViabilityCheckpointType.WEEK_12,
                system_week_number=12,
                metrics=metrics,
            )
        )

        assert result.status == expected_status
        assert result.requires_acknowledgment is requires_ack
        assert result.alerts[0].alert_type == expected_alert_type
        if requires_ack:
            assert result.alerts[0].requires_acknowledgment is True

    def test_budget_checkpoint_and_lifetime_budget_tracking(
        self,
        viability_processor: ViabilityProcessor,
    ) -> None:
        budget_result = viability_processor.evaluate_checkpoint(
            ViabilityCheckpointInput(
                checkpoint_type=ViabilityCheckpointType.BUDGET_100,
                system_week_number=13,
                metrics=make_viability_metrics(
                    resolved_forecasts=42,
                    lifetime_budget_consumed_pct=1.0,
                ),
            )
        )
        budget_state = viability_processor.evaluate_lifetime_budget(
            consumed_usd=5000.0,
            total_budget_usd=5000.0,
        )

        assert budget_result.status == ViabilityStatus.CONCERN
        assert budget_result.alerts[0].alert_type == ViabilityAlertType.BUDGET_THRESHOLD
        assert budget_result.alerts[0].details["investigations_paused"] is True
        assert budget_state.consumed_pct == pytest.approx(1.0)
        assert budget_state.remaining_usd == pytest.approx(0.0)
        assert budget_state.alert_50_triggered is True
        assert budget_state.alert_75_triggered is True
        assert budget_state.alert_100_triggered is True
        assert budget_state.investigations_paused is True
        assert budget_state.is_exhausted is True


class TestAbsenceManager:
    def test_escalates_through_levels_and_enforces_restrictions(
        self,
        absence_manager: AbsenceManager,
        base_now: datetime,
    ) -> None:
        absence_manager.set_last_interaction_time(base_now)

        normal = absence_manager.compute_state(now=base_now + timedelta(hours=47))
        level_1 = absence_manager.compute_state(now=base_now + timedelta(hours=48))
        level_2 = absence_manager.compute_state(now=base_now + timedelta(hours=72))
        level_3 = absence_manager.compute_state(now=base_now + timedelta(hours=96))

        assert normal.absence_level == AbsenceLevel.NORMAL
        assert normal.restrictions == []
        assert normal.total_size_reduction_pct == pytest.approx(0.0)

        assert level_1.absence_level == AbsenceLevel.ABSENT_LEVEL_1
        assert AbsenceRestriction.NO_NEW_POSITIONS in level_1.restrictions
        assert AbsenceRestriction.NO_SIZE_INCREASES in level_1.restrictions

        assert level_2.absence_level == AbsenceLevel.ABSENT_LEVEL_2
        assert level_2.total_size_reduction_pct == pytest.approx(0.25)

        assert level_3.absence_level == AbsenceLevel.ABSENT_LEVEL_3
        assert level_3.total_size_reduction_pct == pytest.approx(0.50)

    def test_starts_graceful_winddown_and_sends_dual_channel_alert(
        self,
        absence_manager: AbsenceManager,
        base_now: datetime,
    ) -> None:
        absence_manager.set_last_interaction_time(base_now)

        state = absence_manager.compute_state(now=base_now + timedelta(hours=120))

        assert state.absence_level == AbsenceLevel.GRACEFUL_WINDDOWN
        assert state.winddown_active is True
        assert state.total_size_reduction_pct == pytest.approx(1.0)
        assert state.winddown_started_at == base_now + timedelta(hours=120)
        assert state.winddown_target_zero_at == state.winddown_started_at + timedelta(hours=WINDDOWN_TARGET_HOURS)

        alert = absence_manager._alerts_sent[-1]
        assert alert.alert_type == AbsenceAlertType.ABSENCE_WINDDOWN_STARTED
        assert alert.channels == DEFAULT_ALERT_CHANNELS
        assert len(alert.channels) >= 2

    def test_return_summary_requires_acknowledgment_before_normal_operation_resumes(
        self,
        absence_manager: AbsenceManager,
        base_now: datetime,
    ) -> None:
        last_seen = base_now - timedelta(hours=130)
        absence_manager.set_last_interaction_time(last_seen)
        absence_manager.compute_state(now=base_now)

        absence_manager.record_action(
            AbsenceActionRecord(
                action=AbsenceAction.REDUCE_POSITIONS,
                absence_level=AbsenceLevel.ABSENT_LEVEL_2,
                description="Reduced two positions by 25%",
                positions_affected=["pos-2", "pos-1"],
                size_reduction_pct=0.25,
            )
        )
        absence_manager.record_action(
            AbsenceActionRecord(
                action=AbsenceAction.CLOSE_AT_TARGETS,
                absence_level=AbsenceLevel.GRACEFUL_WINDDOWN,
                description="Closed one position at target during wind-down",
                positions_affected=["pos-3"],
            )
        )

        return_state = absence_manager.record_interaction(
            OperatorInteraction(
                interaction_type=InteractionType.DASHBOARD_VIEW,
                interacted_at=base_now + timedelta(hours=1),
            )
        )
        summary = absence_manager.generate_return_summary()

        assert return_state.absence_level == AbsenceLevel.NORMAL
        assert return_state.restrictions
        assert absence_manager.can_enter_new_positions() is False
        assert absence_manager.can_increase_sizes() is False
        assert summary.acknowledged is False
        assert summary.absence_duration_hours == pytest.approx(131.0)
        assert summary.peak_absence_level == AbsenceLevel.GRACEFUL_WINDDOWN
        assert summary.positions_reduced == ["pos-1", "pos-2"]
        assert summary.positions_closed == ["pos-3"]
        assert summary.total_size_reduction_pct == pytest.approx(1.0)
        assert "NOT be automatically re-entered" in summary.note

        acknowledged_state = absence_manager.acknowledge_return(summary)

        assert summary.acknowledged is True
        assert summary.acknowledged_at is not None
        assert acknowledged_state.absence_level == AbsenceLevel.NORMAL
        assert acknowledged_state.restrictions == []
        assert absence_manager.can_enter_new_positions() is True
        assert absence_manager.can_increase_sizes() is True
