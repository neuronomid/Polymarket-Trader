from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from agents.providers import LLMResponse
from config.settings import CostConfig, PositionReviewConfig, RiskConfig
from core.enums import (
    DrawdownLevel,
    ExitClass,
    OperatorMode,
    ReviewTier,
    TriggerClass,
    TriggerLevel,
)
from positions.deterministic_checks import DeterministicReviewEngine
from positions.exit_classifier import classify_exit, validate_exit_classification
from positions.manager import PositionReviewManager
from positions.review_agents import PositionReviewOrchestrator
from positions.scheduler import ReviewScheduler, classify_review_tier
from positions.types import (
    DeterministicCheckName,
    DeterministicReviewResult,
    LLMReviewInput,
    LLMReviewResult,
    PositionAction,
    PositionSnapshot,
    ReviewMode,
    ReviewOutcome,
    SubAgentResult,
    TriggerPromotionEvent,
)


def make_position(**overrides) -> PositionSnapshot:
    now = datetime.now(tz=UTC)
    data = {
        "position_id": "pos-1",
        "market_id": "market-1",
        "token_id": "token-1",
        "entry_price": 0.50,
        "entry_size_usd": 500.0,
        "entry_side": "buy",
        "entered_at": now - timedelta(hours=72),
        "current_price": 0.55,
        "current_size_usd": 500.0,
        "current_value_usd": 500.0,
        "unrealized_pnl_usd": 25.0,
        "unrealized_pnl_pct": 0.10,
        "current_spread": 0.05,
        "current_depth_usd": 1000.0,
        "current_best_bid": 0.54,
        "current_best_ask": 0.56,
        "thesis_card_id": "thesis-1",
        "proposed_side": "yes",
        "thesis_price_target": 0.70,
        "thesis_price_floor": 0.40,
        "core_thesis": "A durable informational edge remains.",
        "invalidation_conditions": ["Resolution source changes", "core catalyst invalidated"],
        "expected_catalyst": "Official update",
        "expected_catalyst_date": now + timedelta(days=5),
        "expected_horizon_hours": 200,
        "category": "politics",
        "category_quality_tier": "standard",
        "event_cluster_id": "cluster-1",
        "cluster_ids": ["cluster-1"],
        "review_tier": ReviewTier.STABLE,
        "last_review_at": now - timedelta(hours=8),
        "total_reviews": 3,
        "last_trigger_at": None,
        "cumulative_review_cost_usd": 0.0,
        "cost_pct_of_value": 0.0,
        "review_cost_warning_hit": False,
        "review_cost_cap_hit": False,
        "drawdown_level": DrawdownLevel.NORMAL,
        "operator_mode": OperatorMode.PAPER.value,
        "workflow_run_id": "wf-1",
    }
    data.update(overrides)
    return PositionSnapshot(**data)


@pytest.fixture
def review_config() -> PositionReviewConfig:
    return PositionReviewConfig()


@pytest.fixture
def risk_config() -> RiskConfig:
    return RiskConfig()


@pytest.fixture
def cost_config() -> CostConfig:
    return CostConfig(
        cumulative_review_cost_warning_pct=0.08,
        cumulative_review_cost_cap_pct=0.15,
    )


class TestReviewScheduler:
    def test_classify_review_tier_returns_new_inside_first_48_hours(
        self,
        review_config: PositionReviewConfig,
    ) -> None:
        position = make_position(
            entered_at=datetime.now(tz=UTC) - timedelta(hours=12),
            review_tier=ReviewTier.NEW,
        )

        assert classify_review_tier(position, config=review_config) == ReviewTier.NEW

    def test_classify_review_tier_returns_stable_when_position_meets_all_criteria(
        self,
        review_config: PositionReviewConfig,
    ) -> None:
        position = make_position()

        assert classify_review_tier(position, config=review_config) == ReviewTier.STABLE

    def test_classify_review_tier_returns_low_value_for_bottom_percentile_stable_position(
        self,
        review_config: PositionReviewConfig,
    ) -> None:
        position = make_position(current_value_usd=100.0)

        tier = classify_review_tier(
            position,
            all_position_values=[100.0, 250.0, 400.0, 600.0, 1000.0],
            config=review_config,
        )

        assert tier == ReviewTier.LOW_VALUE

    def test_promote_to_tier_1_preserves_trigger_review_mode(
        self,
        review_config: PositionReviewConfig,
    ) -> None:
        scheduler = ReviewScheduler(review_config)
        position = make_position()
        scheduler.register_position(position)

        event = TriggerPromotionEvent(
            position_id=position.position_id,
            trigger_class=TriggerClass.PROFIT_PROTECTION,
            trigger_level=TriggerLevel.C,
            reason="Large favorable repricing",
        )

        entry = scheduler.promote_to_tier_1(event)
        due = scheduler.get_due_reviews()

        assert entry is not None
        assert entry.review_tier == ReviewTier.NEW
        assert entry.review_mode == ReviewMode.PROFIT_PROTECTION
        assert due[0].position_id == position.position_id
        assert due[0].promoted_by_trigger is True
        assert due[0].review_mode == ReviewMode.PROFIT_PROTECTION

    def test_record_review_completed_reclassifies_and_clears_trigger_promotion(
        self,
        review_config: PositionReviewConfig,
    ) -> None:
        scheduler = ReviewScheduler(review_config)
        position = make_position()
        scheduler.register_position(position)
        scheduler.promote_to_tier_1(
            TriggerPromotionEvent(
                position_id=position.position_id,
                trigger_class=TriggerClass.POSITION_STRESS,
                trigger_level=TriggerLevel.D,
                reason="Acute adverse move",
            )
        )

        next_entry = scheduler.record_review_completed(
            position.position_id,
            position=position,
            all_position_values=[100.0, 500.0, 1000.0],
        )

        assert next_entry is not None
        assert next_entry.review_tier == ReviewTier.STABLE
        assert scheduler.get_position_tier(position.position_id) == ReviewTier.STABLE
        assert scheduler.get_due_reviews() == []

    def test_get_due_reviews_prioritizes_promoted_positions_then_oldest_scheduled(
        self,
        review_config: PositionReviewConfig,
    ) -> None:
        scheduler = ReviewScheduler(review_config)
        first = make_position(position_id="pos-1")
        second = make_position(position_id="pos-2")
        third = make_position(position_id="pos-3")
        scheduler.register_position(first)
        scheduler.register_position(second)
        scheduler.register_position(third)

        now = datetime.now(tz=UTC)
        scheduler._positions["pos-1"].next_review_at = now - timedelta(minutes=10)
        scheduler._positions["pos-2"].next_review_at = now - timedelta(hours=1)
        scheduler._positions["pos-3"].next_review_at = now + timedelta(hours=1)
        scheduler.promote_to_tier_1(
            TriggerPromotionEvent(
                position_id="pos-1",
                trigger_class=TriggerClass.CATALYST_WINDOW,
                trigger_level=TriggerLevel.C,
                reason="Catalyst approaching",
            )
        )

        due = scheduler.get_due_reviews()

        assert [entry.position_id for entry in due] == ["pos-1", "pos-2"]
        assert due[0].promoted_by_trigger is True
        assert due[0].review_mode == ReviewMode.CATALYST
        assert due[1].review_mode == ReviewMode.SCHEDULED


class TestDeterministicReviewEngine:
    def test_review_all_clear_returns_hold(
        self,
        review_config: PositionReviewConfig,
        risk_config: RiskConfig,
    ) -> None:
        engine = DeterministicReviewEngine(review_config, risk_config)

        result = engine.review(make_position())

        assert result.all_passed is True
        assert result.flagged_checks == []
        assert result.suggested_action == PositionAction.HOLD
        assert result.needs_llm_escalation is False

    def test_price_floor_breach_forces_full_close_and_thesis_invalidated(
        self,
        review_config: PositionReviewConfig,
        risk_config: RiskConfig,
    ) -> None:
        engine = DeterministicReviewEngine(review_config, risk_config)
        position = make_position(current_price=0.35, thesis_price_floor=0.40)

        result = engine.review(position)

        assert result.all_passed is False
        assert result.flagged_checks == [DeterministicCheckName.PRICE_VS_THESIS]
        assert result.suggested_action == PositionAction.FULL_CLOSE
        assert result.suggested_exit_class == ExitClass.THESIS_INVALIDATED

    def test_spread_collapse_flags_liquidity_exit(
        self,
        review_config: PositionReviewConfig,
        risk_config: RiskConfig,
    ) -> None:
        engine = DeterministicReviewEngine(review_config, risk_config)
        position = make_position(current_spread=0.45)

        result = engine.review(position)

        assert DeterministicCheckName.SPREAD_VS_LIMITS in result.flagged_checks
        assert result.suggested_action == PositionAction.PARTIAL_CLOSE
        assert result.suggested_exit_class == ExitClass.LIQUIDITY_COLLAPSE

    def test_depth_collapse_flags_liquidity_exit(
        self,
        review_config: PositionReviewConfig,
        risk_config: RiskConfig,
    ) -> None:
        engine = DeterministicReviewEngine(review_config, risk_config)
        position = make_position(current_depth_usd=20.0)

        result = engine.review(position)

        assert DeterministicCheckName.DEPTH_VS_MINIMUMS in result.flagged_checks
        assert result.suggested_action == PositionAction.PARTIAL_CLOSE
        assert result.suggested_exit_class == ExitClass.LIQUIDITY_COLLAPSE

    def test_catalyst_proximity_flags_watch_and_review(
        self,
        review_config: PositionReviewConfig,
        risk_config: RiskConfig,
    ) -> None:
        engine = DeterministicReviewEngine(review_config, risk_config)
        position = make_position(
            expected_catalyst_date=datetime.now(tz=UTC) + timedelta(hours=6),
        )

        result = engine.review(position)

        assert DeterministicCheckName.CATALYST_PROXIMITY in result.flagged_checks
        assert result.suggested_action == PositionAction.WATCH_AND_REVIEW
        assert result.suggested_exit_class is None

    def test_drawdown_hard_kill_switch_forces_risk_reduction(
        self,
        review_config: PositionReviewConfig,
        risk_config: RiskConfig,
    ) -> None:
        engine = DeterministicReviewEngine(review_config, risk_config)
        position = make_position(drawdown_level=DrawdownLevel.HARD_KILL_SWITCH)

        result = engine.review(position)

        assert DeterministicCheckName.DRAWDOWN_STATE in result.flagged_checks
        assert result.suggested_action == PositionAction.FORCED_RISK_REDUCTION
        assert result.suggested_exit_class == ExitClass.PORTFOLIO_DEFENSE

    def test_position_age_beyond_horizon_forces_time_decay_close(
        self,
        review_config: PositionReviewConfig,
        risk_config: RiskConfig,
    ) -> None:
        engine = DeterministicReviewEngine(review_config, risk_config)
        position = make_position(
            entered_at=datetime.now(tz=UTC) - timedelta(hours=160),
            expected_horizon_hours=100,
        )

        result = engine.review(position)

        assert DeterministicCheckName.POSITION_AGE_VS_HORIZON in result.flagged_checks
        assert result.suggested_action == PositionAction.FULL_CLOSE
        assert result.suggested_exit_class == ExitClass.TIME_DECAY

    def test_review_cost_cap_suggests_reduce_to_minimum_monitoring(
        self,
        review_config: PositionReviewConfig,
        risk_config: RiskConfig,
    ) -> None:
        engine = DeterministicReviewEngine(review_config, risk_config)
        position = make_position(
            cost_pct_of_value=0.16,
            review_cost_cap_hit=True,
        )

        result = engine.review(position)

        assert DeterministicCheckName.CUMULATIVE_REVIEW_COST in result.flagged_checks
        assert result.suggested_action == PositionAction.REDUCE_TO_MINIMUM
        assert result.suggested_exit_class == ExitClass.COST_INEFFICIENCY

    def test_aggregate_action_uses_highest_priority_flag(
        self,
        review_config: PositionReviewConfig,
        risk_config: RiskConfig,
    ) -> None:
        engine = DeterministicReviewEngine(review_config, risk_config)
        position = make_position(
            drawdown_level=DrawdownLevel.HARD_KILL_SWITCH,
            review_cost_cap_hit=True,
            cost_pct_of_value=0.20,
        )

        result = engine.review(position)

        assert result.suggested_action == PositionAction.FORCED_RISK_REDUCTION
        assert result.suggested_exit_class == ExitClass.PORTFOLIO_DEFENSE


class TestExitClassifier:
    def test_classify_exit_prefers_llm_classification(self) -> None:
        det_result = DeterministicReviewResult(
            all_passed=False,
            flagged_checks=[DeterministicCheckName.PRICE_VS_THESIS],
            suggested_action=PositionAction.FULL_CLOSE,
            suggested_exit_class=ExitClass.THESIS_INVALIDATED,
        )

        exit_class = classify_exit(
            make_position(),
            PositionAction.FULL_CLOSE,
            deterministic_result=det_result,
            llm_exit_class=ExitClass.RESOLUTION_RISK,
        )

        assert exit_class == ExitClass.RESOLUTION_RISK

    def test_classify_exit_uses_review_mode_and_operator_context_fallbacks(self) -> None:
        profit_class = classify_exit(
            make_position(),
            PositionAction.PARTIAL_CLOSE,
            review_mode=ReviewMode.PROFIT_PROTECTION,
        )
        absent_class = classify_exit(
            make_position(operator_mode=OperatorMode.OPERATOR_ABSENT.value),
            PositionAction.FULL_CLOSE,
        )

        assert profit_class == ExitClass.PROFIT_PROTECTION
        assert absent_class == ExitClass.OPERATOR_ABSENCE

    def test_validate_exit_classification_requires_exit_class_for_exit_actions(self) -> None:
        invalid, invalid_reason = validate_exit_classification(PositionAction.TRIM, None)
        valid, valid_reason = validate_exit_classification(
            PositionAction.WATCH_AND_REVIEW,
            None,
        )

        assert invalid is False
        assert "requires an explicit exit class" in invalid_reason
        assert valid is True
        assert "does not require exit classification" in valid_reason


class TestPositionReviewOrchestrator:
    @pytest.mark.asyncio
    async def test_run_review_invokes_flagged_agents_and_escalates_to_opus(self) -> None:
        orchestrator = PositionReviewOrchestrator(router=MagicMock())
        position = make_position(current_value_usd=500.0)
        det_result = DeterministicReviewResult(
            all_passed=False,
            flagged_checks=[
                DeterministicCheckName.PRICE_VS_THESIS,
                DeterministicCheckName.SPREAD_VS_LIMITS,
                DeterministicCheckName.CATALYST_PROXIMITY,
            ],
            suggested_action=PositionAction.WATCH_AND_REVIEW,
        )
        review_input = LLMReviewInput(
            position=position,
            deterministic_result=det_result,
            flagged_issues=[flag.value for flag in det_result.flagged_checks],
            allows_opus_escalation=True,
            workflow_run_id="wf-1",
        )

        async def fake_run_agent(agent, context, input_, regime):
            findings_map = {
                "update_evidence": ({"new_supporting": ["signal"]}, 0.01),
                "thesis_integrity": (
                    {"invalidation_triggered": True, "updated_confidence": 0.2},
                    0.04,
                ),
                "opposing_signal": ({"signal_severity": "high"}, 0.02),
                "liquidity_deterioration_summary": (
                    {"recommended_action": "partial_close"},
                    0.01,
                ),
                "catalyst_shift": ({"urgency_level": "high"}, 0.01),
            }
            findings, cost = findings_map[agent.role_name]
            return SubAgentResult(
                agent_role=agent.role_name,
                success=True,
                findings=findings,
                cost_usd=cost,
            )

        async def fake_call_llm(agent_input, **kwargs):
            result = kwargs.get("result")
            if result is not None:
                result.total_cost_usd = 0.03
            return LLMResponse(
                content=json.dumps(
                    {
                        "action": "full_close",
                        "exit_class": "liquidity_collapse",
                        "reasoning": "Liquidity and thesis both deteriorated.",
                    }
                ),
                input_tokens=120,
                output_tokens=60,
                model="claude-opus-4-6",
                provider="anthropic",
            )

        orchestrator._run_agent = AsyncMock(side_effect=fake_run_agent)
        orchestrator.call_llm = AsyncMock(side_effect=fake_call_llm)

        result = await orchestrator.run_review(review_input)

        assert result.agents_invoked == [
            "update_evidence",
            "thesis_integrity",
            "opposing_signal",
            "liquidity_deterioration_summary",
            "catalyst_shift",
        ]
        assert result.opus_escalated is True
        assert result.opus_escalation_reason == "Large position ($500.00); Near thesis invalidation; Catalyst proximity concerns"
        assert result.recommended_action == PositionAction.FULL_CLOSE
        assert result.recommended_exit_class == ExitClass.LIQUIDITY_COLLAPSE
        assert result.total_review_cost_usd == pytest.approx(0.12)
        orchestrator.call_llm.assert_awaited_once()
        assert orchestrator.call_llm.await_args.kwargs["tier"].value == "A"

    @pytest.mark.asyncio
    async def test_run_review_falls_back_to_watch_when_synthesis_fails(self) -> None:
        orchestrator = PositionReviewOrchestrator(router=MagicMock())
        det_result = DeterministicReviewResult(
            all_passed=False,
            flagged_checks=[DeterministicCheckName.CATALYST_PROXIMITY],
            suggested_action=PositionAction.WATCH_AND_REVIEW,
        )
        review_input = LLMReviewInput(
            position=make_position(current_value_usd=100.0),
            deterministic_result=det_result,
            flagged_issues=[DeterministicCheckName.CATALYST_PROXIMITY.value],
            workflow_run_id="wf-1",
        )

        orchestrator._run_agent = AsyncMock(
            return_value=SubAgentResult(
                agent_role="update_evidence",
                success=True,
                findings={"summary": "minor change"},
                cost_usd=0.01,
            )
        )
        orchestrator.call_llm = AsyncMock(side_effect=RuntimeError("synthesis broke"))

        result = await orchestrator.run_review(review_input)

        assert result.opus_escalated is False
        assert result.recommended_action == PositionAction.WATCH_AND_REVIEW
        assert result.recommended_exit_class is None
        assert result.synthesis["reasoning"] == "Synthesis failed: synthesis broke"


class TestPositionReviewManager:
    @pytest.mark.asyncio
    async def test_review_position_completes_deterministically_when_all_checks_pass(
        self,
        review_config: PositionReviewConfig,
        risk_config: RiskConfig,
        cost_config: CostConfig,
    ) -> None:
        manager = PositionReviewManager(review_config, risk_config, cost_config)
        position = make_position()
        manager.register_position(position)

        result = await manager.review_position(
            position,
            all_position_values=[100.0, 500.0, 1000.0],
        )
        status = manager.get_review_cost_status(position.position_id)

        assert result.review_outcome == ReviewOutcome.DETERMINISTIC_CLEAR
        assert result.action == PositionAction.HOLD
        assert result.exit_class is None
        assert result.was_deterministic_only is True
        assert result.next_review_tier == ReviewTier.STABLE
        assert result.next_review_in_hours == review_config.stable_review_interval_hours
        assert status is not None
        assert status.total_reviews == 1
        assert status.deterministic_reviews == 1
        assert status.llm_reviews == 0

    @pytest.mark.asyncio
    async def test_review_position_falls_back_to_deterministic_when_llm_unavailable(
        self,
        review_config: PositionReviewConfig,
        risk_config: RiskConfig,
        cost_config: CostConfig,
    ) -> None:
        manager = PositionReviewManager(review_config, risk_config, cost_config)
        position = make_position(current_price=0.35, thesis_price_floor=0.40)
        manager.register_position(position)

        result = await manager.review_position(position)

        assert result.review_outcome == ReviewOutcome.DETERMINISTIC_CLEAR
        assert result.was_deterministic_only is True
        assert result.action == PositionAction.FULL_CLOSE
        assert result.exit_class == ExitClass.THESIS_INVALIDATED

    @pytest.mark.asyncio
    async def test_review_position_forces_deterministic_when_cost_cap_hit(
        self,
        review_config: PositionReviewConfig,
        risk_config: RiskConfig,
        cost_config: CostConfig,
    ) -> None:
        manager = PositionReviewManager(
            review_config,
            risk_config,
            cost_config,
            router=MagicMock(),
        )
        manager._llm_orchestrator = MagicMock()
        manager._llm_orchestrator.run_review = AsyncMock()

        position = make_position(
            cost_pct_of_value=0.20,
            review_cost_cap_hit=True,
        )
        manager.register_position(position)
        manager._review_cost_tracker.record_review(
            position.position_id,
            cost_usd=100.0,
            is_deterministic=False,
        )

        result = await manager.review_position(
            position,
            review_mode=ReviewMode.COST_EFFICIENCY,
        )

        assert result.review_outcome == ReviewOutcome.DETERMINISTIC_CLEAR
        assert result.action == PositionAction.REDUCE_TO_MINIMUM
        assert result.was_deterministic_only is True
        assert "cost cap" in result.action_reason
        manager._llm_orchestrator.run_review.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_review_position_uses_llm_result_and_backfills_exit_class(
        self,
        review_config: PositionReviewConfig,
        risk_config: RiskConfig,
        cost_config: CostConfig,
    ) -> None:
        manager = PositionReviewManager(
            review_config,
            risk_config,
            cost_config,
            router=MagicMock(),
        )
        position = make_position(current_price=0.42, thesis_price_floor=0.35)
        manager.register_position(position)
        manager._llm_orchestrator = MagicMock()
        manager._llm_orchestrator.run_review = AsyncMock(
            return_value=LLMReviewResult(
                position_id=position.position_id,
                workflow_run_id=position.workflow_run_id,
                synthesis={"reasoning": "Price action weakened the thesis."},
                recommended_action=PositionAction.TRIM,
                recommended_exit_class=None,
                total_review_cost_usd=0.07,
                agents_invoked=["update_evidence", "thesis_integrity"],
            )
        )

        result = await manager.review_position(position)
        status = manager.get_review_cost_status(position.position_id)

        assert result.review_outcome == ReviewOutcome.LLM_ESCALATED
        assert result.was_deterministic_only is False
        assert result.action == PositionAction.TRIM
        assert result.exit_class == ExitClass.THESIS_INVALIDATED
        assert result.review_cost_usd == pytest.approx(0.07)
        assert status is not None
        assert status.llm_reviews == 1
        assert status.total_review_cost_usd == pytest.approx(0.07)

    @pytest.mark.asyncio
    async def test_review_position_marks_opus_escalated_outcome(
        self,
        review_config: PositionReviewConfig,
        risk_config: RiskConfig,
        cost_config: CostConfig,
    ) -> None:
        manager = PositionReviewManager(
            review_config,
            risk_config,
            cost_config,
            router=MagicMock(),
        )
        position = make_position(current_spread=0.30)
        manager.register_position(position)
        manager._llm_orchestrator = MagicMock()
        manager._llm_orchestrator.run_review = AsyncMock(
            return_value=LLMReviewResult(
                position_id=position.position_id,
                workflow_run_id=position.workflow_run_id,
                synthesis={"reasoning": "Liquidity conditions have materially deteriorated."},
                recommended_action=PositionAction.FULL_CLOSE,
                recommended_exit_class=ExitClass.LIQUIDITY_COLLAPSE,
                total_review_cost_usd=0.20,
                agents_invoked=["update_evidence", "opposing_signal"],
                opus_escalated=True,
                opus_escalation_reason="Large position; conflicting evidence",
            )
        )

        result = await manager.review_position(position)

        assert result.review_outcome == ReviewOutcome.OPUS_ESCALATED
        assert result.action == PositionAction.FULL_CLOSE
        assert result.exit_class == ExitClass.LIQUIDITY_COLLAPSE
        assert result.review_cost_usd == pytest.approx(0.20)
