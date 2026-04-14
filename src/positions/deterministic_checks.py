"""Deterministic position review checks — Tier D.

Seven deterministic checks run at every scheduled review:
1. Price vs entry/thesis range
2. Spread vs limits
3. Depth vs minimums
4. Catalyst date proximity
5. Drawdown state
6. Position age vs horizon
7. Cumulative review cost vs cap

Per spec Section 11.2:
- Step 2: ALL pass → DETERMINISTIC_REVIEW_CLEAR, no LLM cost (~65% of reviews)
- Step 3: ANY flags → escalate to LLM review focused on flagged issues

Fully deterministic. No LLM calls. No agent/provider imports.
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog

from config.settings import PositionReviewConfig, RiskConfig
from core.enums import DrawdownLevel, ExitClass, ReviewTier
from positions.types import (
    DeterministicCheckName,
    DeterministicCheckResult,
    DeterministicReviewResult,
    PositionAction,
    PositionSnapshot,
    ReviewMode,
)

_log = structlog.get_logger(component="deterministic_position_review")


class DeterministicReviewEngine:
    """Runs seven deterministic checks on a position.

    This is the first phase of every position review. If all checks
    pass, the review completes at zero LLM cost (~65% of reviews).

    Usage:
        engine = DeterministicReviewEngine(review_config, risk_config)
        result = engine.review(position_snapshot)
        if result.all_passed:
            # DETERMINISTIC_REVIEW_CLEAR — no LLM needed
            pass
        else:
            # Escalate to LLM review
            pass
    """

    def __init__(
        self,
        review_config: PositionReviewConfig,
        risk_config: RiskConfig,
    ) -> None:
        self._review_config = review_config
        self._risk_config = risk_config

    def review(
        self,
        position: PositionSnapshot,
        *,
        review_mode: ReviewMode = ReviewMode.SCHEDULED,
    ) -> DeterministicReviewResult:
        """Run all seven deterministic checks on a position.

        Args:
            position: Current position snapshot with market data.
            review_mode: The mode triggering this review.

        Returns:
            DeterministicReviewResult with pass/fail for each check.
        """
        checks: list[DeterministicCheckResult] = [
            self._check_price_vs_thesis(position),
            self._check_spread_vs_limits(position),
            self._check_depth_vs_minimums(position),
            self._check_catalyst_proximity(position),
            self._check_drawdown_state(position),
            self._check_position_age_vs_horizon(position),
            self._check_cumulative_review_cost(position),
        ]

        # Collect flagged checks
        flagged = [c.check_name for c in checks if not c.passed]
        all_passed = len(flagged) == 0

        # Determine suggested action from most severe flag
        suggested_action = PositionAction.HOLD
        suggested_exit = None

        if not all_passed:
            suggested_action, suggested_exit = self._determine_suggested_action(checks, position)

        result = DeterministicReviewResult(
            all_passed=all_passed,
            checks=checks,
            flagged_checks=flagged,
            suggested_action=suggested_action,
            suggested_exit_class=suggested_exit,
            review_mode=review_mode,
        )

        _log.info(
            "deterministic_review_complete",
            position_id=position.position_id,
            all_passed=all_passed,
            flagged_count=len(flagged),
            flagged_checks=[c.value for c in flagged],
            suggested_action=suggested_action.value,
        )

        return result

    # --- Individual Checks ---

    def _check_price_vs_thesis(self, position: PositionSnapshot) -> DeterministicCheckResult:
        """Check 1: Price vs entry/thesis range.

        Flags if price has moved significantly against the thesis
        or has broken through invalidation levels.
        """
        passed = True
        detail_parts: list[str] = []
        severity = "info"
        suggests_action = None
        suggests_exit = None

        # Check price deviation from entry
        if position.entry_price > 0:
            price_change_pct = (
                (position.current_price - position.entry_price) / position.entry_price
            )
            # Adjust sign for side: positive is good for buy, negative for sell
            if position.entry_side == "sell":
                price_change_pct = -price_change_pct

            detail_parts.append(f"Price change: {price_change_pct:.1%} from entry")

            # Large adverse move
            if price_change_pct < -self._review_config.price_adverse_move_threshold:
                passed = False
                severity = "warning"
                detail_parts.append("Significant adverse move")
                suggests_action = PositionAction.WATCH_AND_REVIEW

            # Very large adverse move
            if price_change_pct < -(self._review_config.price_adverse_move_threshold * 2):
                severity = "critical"
                suggests_action = PositionAction.TRIM
                suggests_exit = ExitClass.THESIS_INVALIDATED

        # Check against thesis price floor
        if position.thesis_price_floor is not None:
            if position.current_price < position.thesis_price_floor:
                passed = False
                severity = "critical"
                detail_parts.append(
                    f"Price {position.current_price:.4f} below thesis floor "
                    f"{position.thesis_price_floor:.4f}"
                )
                suggests_action = PositionAction.FULL_CLOSE
                suggests_exit = ExitClass.THESIS_INVALIDATED

        return DeterministicCheckResult(
            check_name=DeterministicCheckName.PRICE_VS_THESIS,
            passed=passed,
            detail="; ".join(detail_parts) if detail_parts else "Price in range",
            severity=severity,
            actual_value=position.current_price,
            threshold_value=position.thesis_price_floor,
            suggests_action=suggests_action,
            suggests_exit_class=suggests_exit,
        )

    def _check_spread_vs_limits(self, position: PositionSnapshot) -> DeterministicCheckResult:
        """Check 2: Spread vs configured limits.

        Flags if the current spread has widened beyond acceptable bounds,
        indicating potential liquidity deterioration.
        """
        max_spread = self._review_config.max_spread_for_hold
        passed = position.current_spread <= max_spread
        severity = "info" if passed else "warning"
        suggests_action = None
        suggests_exit = None

        if not passed:
            if position.current_spread > max_spread * 2:
                severity = "critical"
                suggests_action = PositionAction.PARTIAL_CLOSE
                suggests_exit = ExitClass.LIQUIDITY_COLLAPSE
            else:
                suggests_action = PositionAction.WATCH_AND_REVIEW

        return DeterministicCheckResult(
            check_name=DeterministicCheckName.SPREAD_VS_LIMITS,
            passed=passed,
            detail=f"Spread: {position.current_spread:.4f}, max: {max_spread:.4f}",
            severity=severity,
            actual_value=position.current_spread,
            threshold_value=max_spread,
            suggests_action=suggests_action,
            suggests_exit_class=suggests_exit,
        )

    def _check_depth_vs_minimums(self, position: PositionSnapshot) -> DeterministicCheckResult:
        """Check 3: Depth vs minimum requirements.

        Flags if available depth has deteriorated below the minimum
        needed for position management (exit capability).
        """
        min_depth = self._review_config.min_depth_for_exit_usd
        passed = position.current_depth_usd >= min_depth
        severity = "info" if passed else "warning"
        suggests_action = None
        suggests_exit = None

        if not passed:
            if position.current_depth_usd < min_depth * 0.3:
                severity = "critical"
                suggests_action = PositionAction.PARTIAL_CLOSE
                suggests_exit = ExitClass.LIQUIDITY_COLLAPSE
            else:
                suggests_action = PositionAction.WATCH_AND_REVIEW

        return DeterministicCheckResult(
            check_name=DeterministicCheckName.DEPTH_VS_MINIMUMS,
            passed=passed,
            detail=(
                f"Depth: ${position.current_depth_usd:.2f}, "
                f"min: ${min_depth:.2f}"
            ),
            severity=severity,
            actual_value=position.current_depth_usd,
            threshold_value=min_depth,
            suggests_action=suggests_action,
            suggests_exit_class=suggests_exit,
        )

    def _check_catalyst_proximity(self, position: PositionSnapshot) -> DeterministicCheckResult:
        """Check 4: Catalyst date proximity.

        Flags when approaching or past the expected catalyst date,
        requiring heightened attention.
        """
        passed = True
        severity = "info"
        detail = "No catalyst date set"
        suggests_action = None
        suggests_exit = None

        if position.expected_catalyst_date is not None:
            now = datetime.now(tz=UTC)
            hours_until_catalyst = (
                position.expected_catalyst_date - now
            ).total_seconds() / 3600

            detail = f"Hours until catalyst: {hours_until_catalyst:.1f}"

            if hours_until_catalyst < 0:
                # Past catalyst date
                passed = False
                severity = "warning"
                detail = f"Catalyst date passed {abs(hours_until_catalyst):.1f} hours ago"
                suggests_action = PositionAction.WATCH_AND_REVIEW

            elif hours_until_catalyst < self._review_config.catalyst_proximity_hours:
                # Approaching catalyst
                passed = False
                severity = "info"
                detail = (
                    f"Catalyst approaching in {hours_until_catalyst:.1f} hours "
                    f"(threshold: {self._review_config.catalyst_proximity_hours}h)"
                )
                suggests_action = PositionAction.WATCH_AND_REVIEW

        return DeterministicCheckResult(
            check_name=DeterministicCheckName.CATALYST_PROXIMITY,
            passed=passed,
            detail=detail,
            severity=severity,
            suggests_action=suggests_action,
            suggests_exit_class=suggests_exit,
        )

    def _check_drawdown_state(self, position: PositionSnapshot) -> DeterministicCheckResult:
        """Check 5: Drawdown state.

        Flags if the portfolio drawdown level has escalated, which may
        require position reduction or exit.
        """
        drawdown = position.drawdown_level
        passed = drawdown in (DrawdownLevel.NORMAL, DrawdownLevel.SOFT_WARNING)
        severity = "info"
        suggests_action = None
        suggests_exit = None

        if drawdown == DrawdownLevel.RISK_REDUCTION:
            passed = False
            severity = "warning"
            suggests_action = PositionAction.TRIM

        elif drawdown == DrawdownLevel.ENTRIES_DISABLED:
            passed = False
            severity = "critical"
            suggests_action = PositionAction.TRIM
            suggests_exit = ExitClass.PORTFOLIO_DEFENSE

        elif drawdown == DrawdownLevel.HARD_KILL_SWITCH:
            passed = False
            severity = "critical"
            suggests_action = PositionAction.FORCED_RISK_REDUCTION
            suggests_exit = ExitClass.PORTFOLIO_DEFENSE

        return DeterministicCheckResult(
            check_name=DeterministicCheckName.DRAWDOWN_STATE,
            passed=passed,
            detail=f"Drawdown level: {drawdown.value}",
            severity=severity,
            suggests_action=suggests_action,
            suggests_exit_class=suggests_exit,
        )

    def _check_position_age_vs_horizon(
        self,
        position: PositionSnapshot,
    ) -> DeterministicCheckResult:
        """Check 6: Position age vs expected holding horizon.

        Flags if the position has been held beyond its expected horizon,
        indicating potential time decay risk.
        """
        passed = True
        severity = "info"
        detail = "No horizon set"
        suggests_action = None
        suggests_exit = None

        if position.expected_horizon_hours is not None:
            now = datetime.now(tz=UTC)
            hours_held = (now - position.entered_at).total_seconds() / 3600
            horizon_pct = hours_held / position.expected_horizon_hours if position.expected_horizon_hours > 0 else 0

            detail = (
                f"Held {hours_held:.1f}h of {position.expected_horizon_hours}h "
                f"horizon ({horizon_pct:.0%})"
            )

            # Warning at 80% of horizon
            if horizon_pct >= self._review_config.horizon_warning_pct:
                passed = False
                severity = "warning"
                suggests_action = PositionAction.WATCH_AND_REVIEW

            # Critical past 100% of horizon
            if horizon_pct >= 1.0:
                severity = "critical"
                suggests_action = PositionAction.PARTIAL_CLOSE
                suggests_exit = ExitClass.TIME_DECAY

            # Extreme: 150%+ of horizon
            if horizon_pct >= 1.5:
                suggests_action = PositionAction.FULL_CLOSE
                suggests_exit = ExitClass.TIME_DECAY

        return DeterministicCheckResult(
            check_name=DeterministicCheckName.POSITION_AGE_VS_HORIZON,
            passed=passed,
            detail=detail,
            severity=severity,
            suggests_action=suggests_action,
            suggests_exit_class=suggests_exit,
        )

    def _check_cumulative_review_cost(
        self,
        position: PositionSnapshot,
    ) -> DeterministicCheckResult:
        """Check 7: Cumulative review cost vs cap.

        Per spec Section 11.8:
        - 8% of position value → flag for cost-inefficiency exit review
        - 15% of remaining expected value → deterministic-only, no LLM
        """
        passed = True
        severity = "info"
        suggests_action = None
        suggests_exit = None
        detail = f"Review cost: {position.cost_pct_of_value:.1%} of position value"

        if position.review_cost_cap_hit:
            passed = False
            severity = "warning"
            detail += " (cap hit — deterministic only)"
            suggests_action = PositionAction.REDUCE_TO_MINIMUM
            suggests_exit = ExitClass.COST_INEFFICIENCY

        elif position.review_cost_warning_hit:
            passed = False
            severity = "info"
            detail += " (warning threshold hit)"
            suggests_action = PositionAction.WATCH_AND_REVIEW

        return DeterministicCheckResult(
            check_name=DeterministicCheckName.CUMULATIVE_REVIEW_COST,
            passed=passed,
            detail=detail,
            severity=severity,
            actual_value=position.cost_pct_of_value,
            suggests_action=suggests_action,
            suggests_exit_class=suggests_exit,
        )

    # --- Aggregate action determination ---

    def _determine_suggested_action(
        self,
        checks: list[DeterministicCheckResult],
        position: PositionSnapshot,
    ) -> tuple[PositionAction, ExitClass | None]:
        """Determine the most severe suggested action from all flagged checks.

        Action priority (most severe first):
        1. FORCED_RISK_REDUCTION
        2. FULL_CLOSE
        3. PARTIAL_CLOSE
        4. TRIM
        5. REDUCE_TO_MINIMUM
        6. WATCH_AND_REVIEW
        7. HOLD
        """
        action_priority = {
            PositionAction.FORCED_RISK_REDUCTION: 7,
            PositionAction.FULL_CLOSE: 6,
            PositionAction.PARTIAL_CLOSE: 5,
            PositionAction.TRIM: 4,
            PositionAction.REDUCE_TO_MINIMUM: 3,
            PositionAction.WATCH_AND_REVIEW: 2,
            PositionAction.HOLD: 1,
        }

        max_priority = 0
        best_action = PositionAction.HOLD
        best_exit: ExitClass | None = None

        for check in checks:
            if check.suggests_action is not None:
                priority = action_priority.get(check.suggests_action, 0)
                if priority > max_priority:
                    max_priority = priority
                    best_action = check.suggests_action
                    best_exit = check.suggests_exit_class

        return best_action, best_exit
