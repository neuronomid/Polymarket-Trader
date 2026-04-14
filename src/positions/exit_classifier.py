"""Exit classifier — maps all exits to explicit exit classes.

Per spec Section 11.6, every position exit must be explicitly classified
with one of the 11 exit types. No unclassified exits are permitted.

This module provides deterministic classification logic that evaluates
the review context to determine the appropriate exit class.

Fully deterministic (Tier D). No LLM calls.
"""

from __future__ import annotations

import structlog

from core.enums import DrawdownLevel, ExitClass, OperatorMode
from positions.types import (
    DeterministicCheckName,
    DeterministicReviewResult,
    PositionAction,
    PositionSnapshot,
    ReviewMode,
)

_log = structlog.get_logger(component="exit_classifier")


def classify_exit(
    position: PositionSnapshot,
    action: PositionAction,
    *,
    deterministic_result: DeterministicReviewResult | None = None,
    llm_exit_class: ExitClass | None = None,
    review_mode: ReviewMode = ReviewMode.SCHEDULED,
) -> ExitClass:
    """Classify an exit with one of the 11 exit types.

    Priority order for classification:
    1. LLM-provided exit class (if from LLM review)
    2. Deterministic check-driven classification
    3. Review mode-driven classification
    4. Context-driven classification (operator mode, drawdown, etc.)

    Every exit MUST have an explicit exit class — this function
    always returns a classification.

    Args:
        position: Current position snapshot.
        action: The position action being taken (close, trim, etc.).
        deterministic_result: Result from deterministic checks if available.
        llm_exit_class: Exit class from LLM review if available.
        review_mode: The mode under which this review was conducted.

    Returns:
        ExitClass classification for the exit.
    """
    # 1. If LLM review provided a classification, trust it
    if llm_exit_class is not None:
        _log.info(
            "exit_classified_by_llm",
            position_id=position.position_id,
            exit_class=llm_exit_class.value,
        )
        return llm_exit_class

    # 2. If forced risk reduction, it's always portfolio defense
    if action == PositionAction.FORCED_RISK_REDUCTION:
        return ExitClass.PORTFOLIO_DEFENSE

    # 3. Classify based on deterministic check flags
    if deterministic_result is not None and deterministic_result.suggested_exit_class is not None:
        return deterministic_result.suggested_exit_class

    # 4. Classify based on review mode
    if review_mode == ReviewMode.PROFIT_PROTECTION:
        return ExitClass.PROFIT_PROTECTION

    if review_mode == ReviewMode.COST_EFFICIENCY:
        return ExitClass.COST_INEFFICIENCY

    # 5. Classify based on flagged deterministic checks
    if deterministic_result is not None:
        exit_class = _classify_from_flags(
            deterministic_result.flagged_checks, position,
        )
        if exit_class is not None:
            return exit_class

    # 6. Classify from operator/system context
    if position.operator_mode == OperatorMode.OPERATOR_ABSENT.value:
        return ExitClass.OPERATOR_ABSENCE

    if position.operator_mode == OperatorMode.SCANNER_DEGRADED.value:
        return ExitClass.SCANNER_DEGRADATION

    if position.drawdown_level in (
        DrawdownLevel.ENTRIES_DISABLED,
        DrawdownLevel.HARD_KILL_SWITCH,
    ):
        return ExitClass.PORTFOLIO_DEFENSE

    # 7. Fallback: thesis invalidated (most conservative classification)
    _log.warning(
        "exit_classified_fallback",
        position_id=position.position_id,
        action=action.value,
    )
    return ExitClass.THESIS_INVALIDATED


def _classify_from_flags(
    flagged_checks: list[DeterministicCheckName],
    position: PositionSnapshot,
) -> ExitClass | None:
    """Attempt to classify exit from deterministic check flags."""
    flagged_set = set(flagged_checks)

    # Price moved against thesis → thesis invalidated
    if DeterministicCheckName.PRICE_VS_THESIS in flagged_set:
        return ExitClass.THESIS_INVALIDATED

    # Spread or depth issues → liquidity collapse
    if flagged_set & {
        DeterministicCheckName.SPREAD_VS_LIMITS,
        DeterministicCheckName.DEPTH_VS_MINIMUMS,
    }:
        return ExitClass.LIQUIDITY_COLLAPSE

    # Position age exceeded horizon → time decay
    if DeterministicCheckName.POSITION_AGE_VS_HORIZON in flagged_set:
        return ExitClass.TIME_DECAY

    # Drawdown state critical → portfolio defense
    if DeterministicCheckName.DRAWDOWN_STATE in flagged_set:
        return ExitClass.PORTFOLIO_DEFENSE

    # Review cost cap hit → cost inefficiency
    if DeterministicCheckName.CUMULATIVE_REVIEW_COST in flagged_set:
        return ExitClass.COST_INEFFICIENCY

    return None


def validate_exit_classification(
    action: PositionAction,
    exit_class: ExitClass | None,
) -> tuple[bool, str]:
    """Validate that the exit has a proper classification.

    Per spec: every exit must have an explicit exit class.
    Non-exit actions (hold, watch) do not require exit class.

    Returns:
        (is_valid, reason) tuple.
    """
    exit_actions = {
        PositionAction.FULL_CLOSE,
        PositionAction.PARTIAL_CLOSE,
        PositionAction.TRIM,
        PositionAction.FORCED_RISK_REDUCTION,
    }

    if action in exit_actions:
        if exit_class is None:
            return False, f"Action {action.value} requires an explicit exit class"
        return True, f"Exit classified as {exit_class.value}"

    # Non-exit actions don't need classification
    return True, f"Action {action.value} does not require exit classification"
