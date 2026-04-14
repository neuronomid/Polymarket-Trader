"""Position Review Manager — orchestrates the full review lifecycle.

Ties together:
- Review scheduling (tiered frequency)
- Deterministic-first review checks (Tier D)
- LLM-escalated review (when deterministic checks flag issues)
- Exit classification (all 11 exit types)
- Cumulative review cost tracking
- Next review scheduling

Per spec Section 11 acceptance criteria:
- Every review produces structured action result with explicit action class
- Exits always have explicit exit class
- Most scheduled reviews complete deterministic-only (no LLM cost)
- Cumulative cost cap triggers cost-inefficiency exit consideration
- Level C/D triggers immediately promote to Tier 1
"""

from __future__ import annotations

from typing import Any

import structlog

from agents.prompts import PromptManager
from agents.providers import ProviderRouter
from agents.types import RegimeContext
from config.settings import CostConfig, PositionReviewConfig, RiskConfig
from core.enums import ExitClass, ReviewTier
from cost.review_costs import CumulativeReviewTracker
from positions.deterministic_checks import DeterministicReviewEngine
from positions.exit_classifier import classify_exit, validate_exit_classification
from positions.review_agents import PositionReviewOrchestrator
from positions.scheduler import ReviewScheduler
from positions.types import (
    LLMReviewInput,
    PositionAction,
    PositionReviewResult,
    PositionSnapshot,
    ReviewMode,
    ReviewOutcome,
    ReviewScheduleEntry,
    TriggerPromotionEvent,
)

_log = structlog.get_logger(component="position_review_manager")


class PositionReviewManager:
    """Top-level position review manager.

    Manages the complete lifecycle of position reviews:
    1. Scheduling reviews based on tier
    2. Running deterministic-first checks
    3. Escalating to LLM when needed
    4. Classifying exits
    5. Tracking review costs
    6. Scheduling next review

    Usage:
        manager = PositionReviewManager(
            review_config=config.review,
            risk_config=config.risk,
            cost_config=config.cost,
            router=provider_router,
        )

        # Register position
        manager.register_position(position_snapshot)

        # Run review
        result = await manager.review_position(position_snapshot)

        # Check for due reviews
        due = manager.get_due_reviews()
    """

    def __init__(
        self,
        review_config: PositionReviewConfig,
        risk_config: RiskConfig,
        cost_config: CostConfig,
        *,
        router: ProviderRouter | None = None,
        prompt_manager: PromptManager | None = None,
    ) -> None:
        self._review_config = review_config
        self._risk_config = risk_config
        self._cost_config = cost_config

        # Core components
        self._scheduler = ReviewScheduler(review_config)
        self._deterministic_engine = DeterministicReviewEngine(review_config, risk_config)
        self._review_cost_tracker = CumulativeReviewTracker(cost_config)

        # LLM review orchestrator (optional — only needed for escalated reviews)
        self._llm_orchestrator: PositionReviewOrchestrator | None = None
        if router is not None:
            self._llm_orchestrator = PositionReviewOrchestrator(
                router=router,
                prompt_manager=prompt_manager or PromptManager(),
            )

    # --- Position lifecycle ---

    def register_position(
        self,
        position: PositionSnapshot,
    ) -> ReviewScheduleEntry:
        """Register a new position for review management.

        Sets up review scheduling and cost tracking.
        """
        # Register with scheduler
        schedule_entry = self._scheduler.register_position(position)

        # Register with cost tracker
        self._review_cost_tracker.register_position(
            position.position_id,
            position_value_usd=position.current_value_usd,
        )

        _log.info(
            "position_registered_for_review",
            position_id=position.position_id,
            market_id=position.market_id,
            tier=schedule_entry.review_tier.value,
            value_usd=position.current_value_usd,
        )

        return schedule_entry

    def remove_position(self, position_id: str) -> None:
        """Remove a closed position from review management."""
        self._scheduler.remove_position(position_id)
        self._review_cost_tracker.remove_position(position_id)
        _log.info("position_removed_from_review", position_id=position_id)

    # --- Trigger promotion ---

    def promote_on_trigger(self, event: TriggerPromotionEvent) -> ReviewScheduleEntry | None:
        """Promote a position to Tier 1 on Level C/D trigger.

        Per spec Section 11.1: Level C/D triggers promote to Tier 1 immediately.
        """
        return self._scheduler.promote_to_tier_1(event)

    # --- Core review ---

    async def review_position(
        self,
        position: PositionSnapshot,
        *,
        review_mode: ReviewMode = ReviewMode.SCHEDULED,
        regime: RegimeContext | None = None,
        all_position_values: list[float] | None = None,
    ) -> PositionReviewResult:
        """Execute a full review cycle for a position.

        Flow per spec Section 11.2:
        1. Run deterministic checks (Tier D)
        2. If ALL pass → DETERMINISTIC_REVIEW_CLEAR (~65% of reviews)
        3. If ANY flags → escalate to LLM review
        4. Classify exit if closing
        5. Record review cost
        6. Schedule next review

        Args:
            position: Current position snapshot with market data.
            review_mode: The mode triggering this review.
            regime: Regime context for LLM agents.
            all_position_values: All position values for tier reclassification.

        Returns:
            PositionReviewResult with action and optional exit class.
        """
        _log.info(
            "position_review_start",
            position_id=position.position_id,
            market_id=position.market_id,
            review_tier=position.review_tier.value,
            review_mode=review_mode.value,
        )

        # Step 1: Deterministic checks
        det_result = self._deterministic_engine.review(
            position, review_mode=review_mode,
        )

        # Check if review cost cap forces deterministic-only
        force_deterministic = self._review_cost_tracker.should_force_deterministic(
            position.position_id,
        )

        if det_result.all_passed or force_deterministic:
            # Step 2: DETERMINISTIC_REVIEW_CLEAR
            return self._complete_deterministic_review(
                position=position,
                det_result=det_result,
                review_mode=review_mode,
                force_deterministic=force_deterministic,
                all_position_values=all_position_values,
            )

        # Step 3: Escalate to LLM review
        return await self._escalate_to_llm_review(
            position=position,
            det_result=det_result,
            review_mode=review_mode,
            regime=regime,
            all_position_values=all_position_values,
        )

    # --- Deterministic-only review ---

    def _complete_deterministic_review(
        self,
        position: PositionSnapshot,
        det_result: 'DeterministicReviewResult',
        review_mode: ReviewMode,
        force_deterministic: bool,
        all_position_values: list[float] | None,
    ) -> PositionReviewResult:
        """Complete a deterministic-only review (~65% of reviews)."""
        from positions.deterministic_checks import DeterministicReviewResult

        action = det_result.suggested_action
        exit_class: ExitClass | None = None

        # If deterministic checks suggest closing AND forced deterministic
        if force_deterministic and not det_result.all_passed:
            action = det_result.suggested_action
            if action in (
                PositionAction.FULL_CLOSE,
                PositionAction.PARTIAL_CLOSE,
                PositionAction.TRIM,
                PositionAction.FORCED_RISK_REDUCTION,
            ):
                exit_class = classify_exit(
                    position, action,
                    deterministic_result=det_result,
                    review_mode=review_mode,
                )
        elif det_result.all_passed:
            action = PositionAction.HOLD

        # Record the deterministic review cost
        self._review_cost_tracker.record_review(
            position.position_id,
            cost_usd=0.0,  # deterministic = zero LLM cost
            is_deterministic=True,
        )

        # Determine next review tier
        next_tier = self._determine_next_tier(
            position, action, all_position_values,
        )
        next_interval = self._scheduler._interval_hours(next_tier)

        # Record review with scheduler
        self._scheduler.record_review_completed(
            position.position_id,
            new_tier=next_tier,
            position=position,
            all_position_values=all_position_values,
        )

        outcome = ReviewOutcome.DETERMINISTIC_CLEAR

        result = PositionReviewResult(
            position_id=position.position_id,
            market_id=position.market_id,
            workflow_run_id=position.workflow_run_id,
            review_tier=position.review_tier,
            review_mode=review_mode,
            review_outcome=outcome,
            deterministic_result=det_result,
            llm_result=None,
            action=action,
            exit_class=exit_class,
            action_reason=(
                "Deterministic review clear — all checks passed"
                if det_result.all_passed
                else f"Deterministic-only (cost cap): {det_result.flag_summary}"
            ),
            next_review_tier=next_tier,
            next_review_in_hours=next_interval,
            review_cost_usd=0.0,
            was_deterministic_only=True,
        )

        # Validate exit classification
        if exit_class is not None:
            valid, reason = validate_exit_classification(action, exit_class)
            if not valid:
                _log.error(
                    "invalid_exit_classification",
                    position_id=position.position_id,
                    action=action.value,
                    reason=reason,
                )

        _log.info(
            "deterministic_review_complete",
            position_id=position.position_id,
            action=action.value,
            exit_class=exit_class.value if exit_class else None,
            was_forced_deterministic=force_deterministic,
        )

        return result

    # --- LLM-escalated review ---

    async def _escalate_to_llm_review(
        self,
        position: PositionSnapshot,
        det_result: 'DeterministicReviewResult',
        review_mode: ReviewMode,
        regime: RegimeContext | None,
        all_position_values: list[float] | None,
    ) -> PositionReviewResult:
        """Escalate to LLM review when deterministic checks flag issues."""
        from positions.deterministic_checks import DeterministicReviewResult

        if self._llm_orchestrator is None:
            # No LLM orchestrator — fall back to deterministic suggestion
            _log.warning(
                "llm_escalation_unavailable",
                position_id=position.position_id,
                reason="No ProviderRouter configured",
            )
            return self._complete_deterministic_review(
                position=position,
                det_result=det_result,
                review_mode=review_mode,
                force_deterministic=True,
                all_position_values=all_position_values,
            )

        # Check if Opus escalation is allowed
        review_cost_status = self._review_cost_tracker.get_status(position.position_id)
        allows_opus = (
            review_cost_status.allows_opus_escalation
            if review_cost_status else True
        )

        # Build LLM review input
        flagged_issues = [c.value for c in det_result.flagged_checks]
        llm_input = LLMReviewInput(
            position=position,
            deterministic_result=det_result,
            flagged_issues=flagged_issues,
            review_mode=review_mode,
            workflow_run_id=position.workflow_run_id,
            allows_opus_escalation=allows_opus,
            cumulative_review_cost_usd=position.cumulative_review_cost_usd,
            cost_pct_of_value=position.cost_pct_of_value,
        )

        # Run LLM review
        llm_result = await self._llm_orchestrator.run_review(
            llm_input, regime=regime,
        )

        # Record LLM review cost
        self._review_cost_tracker.record_review(
            position.position_id,
            cost_usd=llm_result.total_review_cost_usd,
            is_deterministic=False,
        )

        # Determine exit class
        action = llm_result.recommended_action
        exit_class = llm_result.recommended_exit_class

        # If LLM didn't provide exit class but action requires one
        if exit_class is None and action in (
            PositionAction.FULL_CLOSE,
            PositionAction.PARTIAL_CLOSE,
            PositionAction.TRIM,
            PositionAction.FORCED_RISK_REDUCTION,
        ):
            exit_class = classify_exit(
                position, action,
                deterministic_result=det_result,
                llm_exit_class=llm_result.recommended_exit_class,
                review_mode=review_mode,
            )

        # Determine next review tier
        next_tier = self._determine_next_tier(
            position, action, all_position_values,
        )
        next_interval = self._scheduler._interval_hours(next_tier)

        # Record review with scheduler
        self._scheduler.record_review_completed(
            position.position_id,
            new_tier=next_tier,
            position=position,
            all_position_values=all_position_values,
        )

        outcome = (
            ReviewOutcome.OPUS_ESCALATED if llm_result.opus_escalated
            else ReviewOutcome.LLM_ESCALATED
        )

        result = PositionReviewResult(
            position_id=position.position_id,
            market_id=position.market_id,
            workflow_run_id=position.workflow_run_id,
            review_tier=position.review_tier,
            review_mode=review_mode,
            review_outcome=outcome,
            deterministic_result=det_result,
            llm_result=llm_result,
            action=action,
            exit_class=exit_class,
            action_reason=llm_result.synthesis.get("reasoning", "LLM review"),
            action_detail=llm_result.synthesis,
            next_review_tier=next_tier,
            next_review_in_hours=next_interval,
            review_cost_usd=llm_result.total_review_cost_usd,
            was_deterministic_only=False,
        )

        # Validate exit classification
        if exit_class is not None:
            valid, reason = validate_exit_classification(action, exit_class)
            if not valid:
                _log.error(
                    "invalid_exit_classification",
                    position_id=position.position_id,
                    action=action.value,
                    reason=reason,
                )

        _log.info(
            "llm_review_result",
            position_id=position.position_id,
            action=action.value,
            exit_class=exit_class.value if exit_class else None,
            review_cost=round(llm_result.total_review_cost_usd, 4),
            opus_escalated=llm_result.opus_escalated,
            agents_used=llm_result.agents_invoked,
        )

        return result

    # --- Helper methods ---

    def _determine_next_tier(
        self,
        position: PositionSnapshot,
        action: PositionAction,
        all_position_values: list[float] | None,
    ) -> ReviewTier:
        """Determine next review tier based on action and position state."""
        # Watch-and-review promotes to Tier 1
        if action == PositionAction.WATCH_AND_REVIEW:
            return ReviewTier.NEW

        # Closing actions don't need tier reclassification
        if action in (
            PositionAction.FULL_CLOSE,
            PositionAction.FORCED_RISK_REDUCTION,
        ):
            return position.review_tier

        # Otherwise, reclassify based on position state
        from positions.scheduler import classify_review_tier
        return classify_review_tier(
            position,
            all_position_values=all_position_values,
            config=self._review_config,
        )

    # --- Delegation to sub-components ---

    def get_due_reviews(self) -> list[ReviewScheduleEntry]:
        """Get all positions due for review now."""
        return self._scheduler.get_due_reviews()

    def get_schedule_state(self):
        """Get overall scheduler state."""
        return self._scheduler.get_state()

    def get_review_cost_status(self, position_id: str):
        """Get cumulative review cost status for a position."""
        return self._review_cost_tracker.get_status(position_id)

    def update_position_value(self, position_id: str, new_value_usd: float) -> None:
        """Update position value for cost tracking."""
        self._review_cost_tracker.update_position_value(position_id, new_value_usd)
