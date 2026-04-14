from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from agents.types import AgentResult
from config.settings import RiskConfig
from core.enums import DrawdownLevel, OperatorMode
from execution.engine import ExecutionEngine
from execution.friction import FrictionModelCalibrator
from execution.slippage import SlippageTracker
from execution.types import (
    EntryMode,
    ExecutionOutcome,
    ExecutionRequest,
    RevalidationCheck,
    RevalidationCheckName,
    RevalidationResult,
)
from market_data.types import OrderBookLevel
from tradeability.resolution_parser import ResolutionParser
from tradeability.synthesizer import TradeabilitySynthesizer
from tradeability.types import (
    HardRejectionReason,
    ResolutionClarity,
    ResolutionParseInput,
    ResolutionParseOutput,
    TradeabilityInput,
    TradeabilityOutcome,
)


def make_parse_input(**overrides) -> ResolutionParseInput:
    data = {
        "market_id": "market-1",
        "title": "Will the official result be announced by June 1?",
        "description": "Official Reuters coverage and commission updates determine outcome.",
        "resolution_source": None,
        "resolution_deadline": datetime.now(tz=UTC) + timedelta(days=7),
        "contract_wording": (
            "This market resolves based on official commission results as reported by Reuters."
        ),
        "previous_wording": None,
        "end_date_hours": None,
        "spread": 0.03,
        "depth_usd": 500.0,
        "min_position_size_usd": 50.0,
    }
    data.update(overrides)
    return ResolutionParseInput(**data)


def make_parse_output(
    clarity: ResolutionClarity = ResolutionClarity.CLEAR,
    **overrides,
) -> ResolutionParseOutput:
    data = {
        "market_id": "market-1",
        "clarity": clarity,
        "checks": [],
        "has_named_source": True,
        "has_explicit_deadline": True,
        "has_ambiguous_wording": False,
        "has_undefined_terms": False,
        "has_multi_step_deps": False,
        "has_unclear_jurisdiction": False,
        "has_counter_intuitive_risk": False,
        "wording_changed": False,
        "ambiguous_phrases": [],
        "undefined_terms": [],
        "flagged_items": [],
        "rejection_reason": None,
        "rejection_detail": None,
    }
    data.update(overrides)
    return ResolutionParseOutput(**data)


def make_tradeability_input(**overrides) -> TradeabilityInput:
    data = {
        "market_id": "market-1",
        "workflow_run_id": "wf-1",
        "title": "Test market",
        "description": "Test description",
        "resolution_parse": make_parse_output(),
        "spread": 0.03,
        "visible_depth_usd": 1000.0,
        "liquidity_usd": 5000.0,
        "best_bid": 0.54,
        "best_ask": 0.56,
        "mid_price": 0.55,
        "gross_edge": 0.05,
        "net_edge": 0.03,
        "entry_impact_bps": 15.0,
        "min_position_size_usd": 50.0,
        "depth_fraction_limit": 0.12,
    }
    data.update(overrides)
    return TradeabilityInput(**data)


def make_request(**overrides) -> ExecutionRequest:
    data = {
        "workflow_run_id": "wf-1",
        "market_id": "market-1",
        "token_id": "token-1",
        "thesis_card_id": "thesis-1",
        "position_id": "position-1",
        "side": "buy",
        "price": 0.55,
        "size_usd": 100.0,
        "order_type": "limit",
        "current_spread": 0.03,
        "current_depth_usd": 5000.0,
        "current_best_bid": 0.54,
        "current_best_ask": 0.56,
        "current_mid_price": 0.55,
        "market_status": "active",
        "risk_approval": "approve_normal",
        "risk_conditions": ["spread_ok", "depth_ok"],
        "cost_approval": "within_budget",
        "tradeability_outcome": "tradable_normal",
        "entry_impact_bps": 10.0,
        "gross_edge": 0.05,
        "liquidity_relative_size_pct": 0.02,
        "preferred_entry_mode": EntryMode.IMMEDIATE,
        "drawdown_level": DrawdownLevel.NORMAL.value,
        "operator_mode": OperatorMode.PAPER.value,
        "approved_at": datetime.now(tz=UTC),
        "max_staleness_seconds": 300,
        "existing_order_ids": set(),
        "max_spread": 0.15,
        "max_order_depth_fraction": 0.12,
        "max_entry_impact_edge_fraction": 0.25,
        "depth_levels_for_sizing": 3,
    }
    data.update(overrides)
    return ExecutionRequest(**data)


def make_revalidation_result(
    *,
    all_passed: bool,
    failed_checks: list[str] | None = None,
) -> RevalidationResult:
    checks = [
        RevalidationCheck(
            check_name=RevalidationCheckName.MARKET_OPEN,
            passed=all_passed,
            detail="stubbed",
        )
    ]
    return RevalidationResult(
        all_passed=all_passed,
        checks=checks,
        failed_checks=failed_checks or [],
    )


class TestResolutionParser:
    def test_parse_clear_contract_with_source_heuristics_and_deadline(self):
        parser = ResolutionParser()

        result = parser.parse(make_parse_input())

        assert result.clarity == ResolutionClarity.CLEAR
        assert result.has_named_source is True
        assert result.has_explicit_deadline is True
        assert result.flagged_items == []
        assert len(result.checks) == 9
        assert result.is_rejected is False

    def test_parse_rejects_missing_source_and_deadline(self):
        parser = ResolutionParser()

        result = parser.parse(
            make_parse_input(
                description="No named source is specified anywhere.",
                contract_wording="This market resolves when the event happens.",
                resolution_deadline=None,
                end_date_hours=None,
            )
        )

        assert result.clarity == ResolutionClarity.REJECT
        assert result.rejection_reason == HardRejectionReason.UNSTABLE_RESOLUTION_SOURCE
        assert result.has_named_source is False
        assert result.has_explicit_deadline is False
        assert any("named_resolution_source" in item for item in result.flagged_items)
        assert any("explicit_deadline" in item for item in result.flagged_items)

    def test_parse_rejects_heavily_ambiguous_wording(self):
        parser = ResolutionParser()

        result = parser.parse(
            make_parse_input(
                contract_wording=(
                    "Resolution may depend on what officials could decide, might vary by "
                    "circumstances, and remains subject to interpretation."
                )
            )
        )

        assert result.clarity == ResolutionClarity.REJECT
        assert result.rejection_reason == HardRejectionReason.AMBIGUOUS_WORDING
        assert result.has_ambiguous_wording is True
        assert len(result.ambiguous_phrases) >= 4

    def test_parse_marks_single_issue_as_marginal(self):
        parser = ResolutionParser()

        result = parser.parse(
            make_parse_input(
                contract_wording=(
                    'This market resolves based on official Reuters reporting of the '
                    '"Qualified Result".'
                )
            )
        )

        assert result.clarity == ResolutionClarity.MARGINAL
        assert result.undefined_terms == ["Qualified Result"]
        assert result.has_residual_ambiguity is True

    def test_parse_marks_multiple_issues_as_ambiguous_and_tracks_jurisdiction(self):
        parser = ResolutionParser()

        result = parser.parse(
            make_parse_input(
                contract_wording=(
                    'Official Reuters reporting applies only if applicable jurisdiction '
                    'may validate the "Qualified Event".'
                )
            )
        )

        assert result.clarity == ResolutionClarity.AMBIGUOUS
        assert result.has_multi_step_deps is True
        assert result.has_unclear_jurisdiction is True
        assert result.has_ambiguous_wording is True
        assert "Qualified Event" in result.undefined_terms

    def test_parse_rejects_wording_changes(self):
        parser = ResolutionParser()

        result = parser.parse(
            make_parse_input(
                contract_wording="Current wording with official Reuters language.",
                previous_wording="Older wording with different language.",
            )
        )

        assert result.clarity == ResolutionClarity.REJECT
        assert result.rejection_reason == HardRejectionReason.WORDING_CHANGED
        assert result.wording_changed is True

    def test_parse_rejects_spread_depth_hard_limit(self):
        parser = ResolutionParser(max_spread=0.15)

        result = parser.parse(make_parse_input(spread=0.20))

        assert result.clarity == ResolutionClarity.REJECT
        assert result.rejection_reason == HardRejectionReason.SPREAD_DEPTH_HARD_LIMIT


class TestTradeabilitySynthesizer:
    @pytest.fixture
    def synthesizer(self) -> TradeabilitySynthesizer:
        return TradeabilitySynthesizer(router=SimpleNamespace())

    @pytest.mark.asyncio
    async def test_assess_passes_through_parser_hard_reject(
        self,
        synthesizer: TradeabilitySynthesizer,
    ):
        parse_result = make_parse_output(
            clarity=ResolutionClarity.REJECT,
            rejection_reason=HardRejectionReason.WORDING_CHANGED,
            rejection_detail="Contract wording changed",
        )

        result = await synthesizer.assess(
            make_tradeability_input(resolution_parse=parse_result)
        )

        assert result.outcome == TradeabilityOutcome.REJECT
        assert result.reason_code == HardRejectionReason.WORDING_CHANGED.value
        assert result.hard_rejection_reasons == [HardRejectionReason.WORDING_CHANGED]

    @pytest.mark.asyncio
    async def test_assess_clear_resolution_returns_normal_size(
        self,
        synthesizer: TradeabilitySynthesizer,
    ):
        result = await synthesizer.assess(
            make_tradeability_input(
                visible_depth_usd=2000.0,
                depth_fraction_limit=0.10,
            )
        )

        assert result.outcome == TradeabilityOutcome.TRADABLE_NORMAL
        assert result.reason_code == "clear_resolution"
        assert result.liquidity_adjusted_max_size_usd == pytest.approx(200.0)
        assert result.is_tradable is True

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("overrides", "expected_reason", "expected_rejection"),
        [
            ({"spread": 0.18}, "spread_hard_limit", HardRejectionReason.SPREAD_DEPTH_HARD_LIMIT),
            (
                {"visible_depth_usd": 25.0, "min_position_size_usd": 50.0},
                "depth_below_min",
                HardRejectionReason.DEPTH_BELOW_MINIMUM,
            ),
        ],
    )
    async def test_assess_enforces_hard_limits_before_synthesis(
        self,
        synthesizer: TradeabilitySynthesizer,
        overrides: dict,
        expected_reason: str,
        expected_rejection: HardRejectionReason,
    ):
        result = await synthesizer.assess(make_tradeability_input(**overrides))

        assert result.outcome == TradeabilityOutcome.REJECT
        assert result.reason_code == expected_reason
        assert result.hard_rejection_reasons == [expected_rejection]

    @pytest.mark.asyncio
    async def test_assess_rejects_severe_ambiguity_without_synthesis(
        self,
        synthesizer: TradeabilitySynthesizer,
    ):
        parse_result = make_parse_output(
            clarity=ResolutionClarity.AMBIGUOUS,
            flagged_items=["multi_step_dependencies", "undefined_terms"],
        )

        result = await synthesizer.assess(
            make_tradeability_input(resolution_parse=parse_result)
        )

        assert result.outcome == TradeabilityOutcome.REJECT
        assert result.reason_code == "severe_ambiguity"
        assert result.residual_ambiguity_issues == ["multi_step_dependencies", "undefined_terms"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("synthesis_result", "cost_usd", "expected_outcome", "expected_code", "expected_size"),
        [
            (
                {
                    "tradable": False,
                    "size_recommendation": "reject",
                    "confidence": "low",
                    "residual_risks": ["unclear appeals process"],
                    "reasoning": "Resolution remains too subjective.",
                },
                0.42,
                TradeabilityOutcome.REJECT,
                "synthesizer_reject",
                0.0,
            ),
            (
                {
                    "tradable": True,
                    "size_recommendation": "reduced",
                    "confidence": "medium",
                    "residual_risks": ["deadline wording narrow"],
                    "reasoning": "Tradable with a haircut.",
                },
                0.15,
                TradeabilityOutcome.TRADABLE_REDUCED,
                "synthesizer_reduced",
                60.0,
            ),
            (
                {
                    "tradable": True,
                    "size_recommendation": "normal",
                    "confidence": "high",
                    "residual_risks": [],
                    "reasoning": "Ambiguity is operationally minor.",
                },
                0.08,
                TradeabilityOutcome.TRADABLE_NORMAL,
                "synthesizer_normal",
                120.0,
            ),
        ],
    )
    async def test_assess_interprets_synthesis_outputs(
        self,
        monkeypatch: pytest.MonkeyPatch,
        synthesizer: TradeabilitySynthesizer,
        synthesis_result: dict,
        cost_usd: float,
        expected_outcome: TradeabilityOutcome,
        expected_code: str,
        expected_size: float,
    ):
        async def fake_run(agent_input, regime=None):
            return AgentResult(
                agent_role="tradeability_synthesizer",
                success=True,
                result=synthesis_result,
                total_cost_usd=cost_usd,
            )

        monkeypatch.setattr(synthesizer, "run", fake_run)

        result = await synthesizer.assess(
            make_tradeability_input(
                resolution_parse=make_parse_output(
                    clarity=ResolutionClarity.MARGINAL,
                    flagged_items=["undefined_terms: one quoted term"],
                )
            )
        )

        assert result.outcome == expected_outcome
        assert result.reason_code == expected_code
        assert result.liquidity_adjusted_max_size_usd == pytest.approx(expected_size)
        assert result.synthesizer_cost_usd == pytest.approx(cost_usd)

    @pytest.mark.asyncio
    async def test_assess_falls_back_to_reduced_size_when_synthesis_fails(
        self,
        monkeypatch: pytest.MonkeyPatch,
        synthesizer: TradeabilitySynthesizer,
    ):
        async def fake_run(agent_input, regime=None):
            raise RuntimeError("router unavailable")

        monkeypatch.setattr(synthesizer, "run", fake_run)

        result = await synthesizer.assess(
            make_tradeability_input(
                resolution_parse=make_parse_output(
                    clarity=ResolutionClarity.MARGINAL,
                    flagged_items=["undefined_terms: one quoted term"],
                )
            )
        )

        assert result.outcome == TradeabilityOutcome.TRADABLE_REDUCED
        assert result.reason_code == "synthesis_fallback"
        assert result.liquidity_adjusted_max_size_usd == pytest.approx(60.0)


class TestExecutionEngine:
    @pytest.fixture
    def engine(self) -> ExecutionEngine:
        return ExecutionEngine(risk_config=RiskConfig())

    def test_revalidate_collects_failed_checks(self, engine: ExecutionEngine):
        request = make_request(
            side="hold",
            current_spread=0.25,
            current_depth_usd=5.0,
            market_status="closed",
            drawdown_level=DrawdownLevel.ENTRIES_DISABLED.value,
            tradeability_outcome="reject",
            approved_at=datetime.now(tz=UTC) - timedelta(minutes=10),
            max_staleness_seconds=60,
            entry_impact_bps=100.0,
            gross_edge=0.01,
            operator_mode=OperatorMode.OPERATOR_ABSENT.value,
        )

        result = engine._revalidate(
            request,
            portfolio_exposure_usd=9950.0,
            is_wind_down_action=False,
        )

        assert result.all_passed is False
        assert set(result.failed_checks) == {
            RevalidationCheckName.MARKET_OPEN.value,
            RevalidationCheckName.SIDE_CORRECT.value,
            RevalidationCheckName.SPREAD_WITHIN_BOUNDS.value,
            RevalidationCheckName.DEPTH_ACCEPTABLE.value,
            RevalidationCheckName.DRAWDOWN_NOT_WORSENED.value,
            RevalidationCheckName.EXPOSURE_BUDGET_AVAILABLE.value,
            RevalidationCheckName.NO_NEW_AMBIGUITY.value,
            RevalidationCheckName.APPROVAL_NOT_STALE.value,
            RevalidationCheckName.LIQUIDITY_RELATIVE_LIMIT.value,
            RevalidationCheckName.ENTRY_IMPACT_WITHIN_BOUNDS.value,
            RevalidationCheckName.NOT_IN_OPERATOR_ABSENT.value,
        }

    def test_revalidate_allows_wind_down_action_in_absent_mode(self, engine: ExecutionEngine):
        request = make_request(operator_mode=OperatorMode.OPERATOR_ABSENT.value)

        result = engine._revalidate(request, is_wind_down_action=True)

        absent_check = next(
            c for c in result.checks if c.check_name == RevalidationCheckName.NOT_IN_OPERATOR_ABSENT
        )
        assert absent_check.passed is True

    @pytest.mark.asyncio
    async def test_execute_places_immediate_order_on_first_pass(self, engine: ExecutionEngine):
        result = await engine.execute(
            make_request(),
            ask_levels=[
                OrderBookLevel(price=0.55, size=1000.0),
                OrderBookLevel(price=0.56, size=1000.0),
            ],
        )

        assert result.outcome == ExecutionOutcome.EXECUTED
        assert result.retry_attempted is False
        assert result.entry_mode == EntryMode.IMMEDIATE
        assert result.submitted_size == pytest.approx(100.0)
        assert result.order_id
        assert result.revalidation is not None and result.revalidation.all_passed is True

    @pytest.mark.asyncio
    async def test_execute_retries_once_and_then_succeeds(
        self,
        monkeypatch: pytest.MonkeyPatch,
        engine: ExecutionEngine,
    ):
        request = make_request()
        results = iter([
            make_revalidation_result(
                all_passed=False,
                failed_checks=[RevalidationCheckName.SPREAD_WITHIN_BOUNDS.value],
            ),
            make_revalidation_result(all_passed=True),
        ])

        def fake_revalidate(*args, **kwargs):
            return next(results)

        monkeypatch.setattr(engine, "_revalidate", fake_revalidate)

        result = await engine.execute(request)

        assert result.outcome == ExecutionOutcome.EXECUTED
        assert result.retry_attempted is True
        assert result.revalidation is not None
        assert result.revalidation.failed_checks == [RevalidationCheckName.SPREAD_WITHIN_BOUNDS.value]
        assert result.retry_revalidation is not None
        assert result.retry_revalidation.all_passed is True

    @pytest.mark.asyncio
    async def test_execute_cancels_after_second_failed_revalidation(
        self,
        monkeypatch: pytest.MonkeyPatch,
        engine: ExecutionEngine,
    ):
        request = make_request()
        results = iter([
            make_revalidation_result(
                all_passed=False,
                failed_checks=[RevalidationCheckName.DEPTH_ACCEPTABLE.value],
            ),
            make_revalidation_result(
                all_passed=False,
                failed_checks=[RevalidationCheckName.DEPTH_ACCEPTABLE.value],
            ),
        ])

        def fake_revalidate(*args, **kwargs):
            return next(results)

        monkeypatch.setattr(engine, "_revalidate", fake_revalidate)

        result = await engine.execute(request)

        assert result.outcome == ExecutionOutcome.CANCELLED
        assert result.retry_attempted is True
        assert result.rejection_reason is not None
        assert RevalidationCheckName.DEPTH_ACCEPTABLE.value in result.rejection_reason

    def test_place_order_forces_resize_and_uses_staged_entry(self, engine: ExecutionEngine):
        request = make_request(size_usd=700.0, current_depth_usd=5000.0)
        result = engine._place_order(
            request,
            make_revalidation_result(all_passed=True),
            ask_levels=[
                OrderBookLevel(price=0.55, size=1000.0),
                OrderBookLevel(price=0.56, size=1000.0),
            ],
        )

        assert result.outcome == ExecutionOutcome.EXECUTED
        assert result.entry_mode == EntryMode.STAGED
        assert result.forced_resize is True
        assert result.submitted_size == pytest.approx(600.0)
        assert result.entry_impact_bps is not None and result.entry_impact_bps > 0

    def test_determine_entry_mode_respects_non_immediate_preference(self, engine: ExecutionEngine):
        request = make_request(preferred_entry_mode=EntryMode.PRICE_IMPROVEMENT)

        assert engine._determine_entry_mode(request) == EntryMode.PRICE_IMPROVEMENT

    def test_build_log_entry_captures_execution_context(self, engine: ExecutionEngine):
        request = make_request()
        result = engine._place_order(request, make_revalidation_result(all_passed=True))
        log_entry = engine.build_log_entry(
            request,
            result,
            estimated_slippage_bps=7.5,
            realized_slippage_bps=9.0,
        )

        assert log_entry.workflow_run_id == request.workflow_run_id
        assert log_entry.market_id == request.market_id
        assert log_entry.order_id == result.order_id
        assert log_entry.revalidation_passed is True
        assert log_entry.entry_mode == result.entry_mode.value
        assert log_entry.estimated_slippage_bps == pytest.approx(7.5)
        assert log_entry.realized_slippage_bps == pytest.approx(9.0)


class TestSlippageTracker:
    def test_needs_recalibration_after_full_window_exceeds_threshold(self):
        tracker = SlippageTracker(recalibration_ratio=1.5, window_size=3)

        for idx in range(3):
            tracker.record(
                order_id=f"order-{idx}",
                position_id=f"position-{idx}",
                estimated_slippage_bps=10.0,
                realized_slippage_bps=20.0,
                order_size_usd=100.0,
                mid_price_at_submission=0.50,
                fill_price=0.501,
            )

        assert tracker.record_count() == 3
        assert tracker.recent_count() == 3
        assert tracker.mean_slippage_ratio() == pytest.approx(2.0)
        assert tracker.needs_recalibration() is True

    def test_mean_ratio_excludes_infinite_records(self):
        tracker = SlippageTracker(window_size=3)

        tracker.record(
            order_id="order-1",
            position_id="position-1",
            estimated_slippage_bps=0.0,
            realized_slippage_bps=5.0,
            order_size_usd=100.0,
            mid_price_at_submission=0.50,
            fill_price=0.50025,
        )
        tracker.record(
            order_id="order-2",
            position_id="position-2",
            estimated_slippage_bps=10.0,
            realized_slippage_bps=10.0,
            order_size_usd=100.0,
            mid_price_at_submission=0.50,
            fill_price=0.5005,
        )

        assert tracker.mean_slippage_ratio() == pytest.approx(1.0)

    @pytest.mark.parametrize(
        ("mid_price", "fill_price", "side", "expected"),
        [
            (0.50, 0.505, "buy", 100.0),
            (0.50, 0.495, "sell", 100.0),
            (0.50, 0.495, "buy", 0.0),
            (0.0, 0.505, "buy", 0.0),
        ],
    )
    def test_compute_realized_slippage_bps(
        self,
        mid_price: float,
        fill_price: float,
        side: str,
        expected: float,
    ):
        assert (
            SlippageTracker.compute_realized_slippage_bps(
                mid_price=mid_price,
                fill_price=fill_price,
                side=side,
            )
            == expected
        )


class TestFrictionModelCalibrator:
    def test_record_trade_sets_recalibration_flag_after_minimum_trades(self):
        calibrator = FrictionModelCalibrator()
        calibrator._slippage_tracker = SlippageTracker(window_size=3)

        for idx in range(9):
            calibrator.record_trade(
                order_id=f"order-{idx}",
                position_id=f"position-{idx}",
                estimated_slippage_bps=10.0,
                realized_slippage_bps=20.0,
                order_size_usd=100.0,
                mid_price_at_submission=0.50,
                fill_price=0.501,
            )

        assert calibrator.current_state.needs_recalibration is False

        calibrator.record_trade(
            order_id="order-10",
            position_id="position-10",
            estimated_slippage_bps=10.0,
            realized_slippage_bps=20.0,
            order_size_usd=100.0,
            mid_price_at_submission=0.50,
            fill_price=0.501,
        )

        state = calibrator.current_state
        assert state.trades_since_calibration == 10
        assert state.mean_slippage_ratio == pytest.approx(2.0)
        assert state.needs_recalibration is True

    def test_recalibrate_updates_parameters_and_resets_state(self):
        calibrator = FrictionModelCalibrator()
        calibrator._slippage_tracker = SlippageTracker(window_size=3)

        for idx in range(10):
            calibrator.record_trade(
                order_id=f"order-{idx}",
                position_id=f"position-{idx}",
                estimated_slippage_bps=10.0,
                realized_slippage_bps=20.0,
                order_size_usd=100.0,
                mid_price_at_submission=0.50,
                fill_price=0.501,
            )

        new_state = calibrator.recalibrate()

        assert new_state.version == 2
        assert new_state.trades_since_calibration == 0
        assert new_state.needs_recalibration is False
        assert new_state.mean_slippage_ratio == pytest.approx(2.0)
        assert new_state.spread_estimate == pytest.approx(0.0152)
        assert new_state.depth_assumption == pytest.approx(4500.0)
        assert new_state.impact_coefficient == pytest.approx(0.65)

    def test_estimate_slippage_uses_current_model_parameters(self):
        calibrator = FrictionModelCalibrator()

        assert calibrator.estimate_slippage_bps(order_size_usd=500.0, visible_depth_usd=5000.0) == pytest.approx(105.0)
        assert calibrator.estimate_slippage_bps(order_size_usd=0.0, visible_depth_usd=5000.0) == 0.0
