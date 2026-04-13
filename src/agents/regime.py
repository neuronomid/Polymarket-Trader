"""Calibration regime adapter — adapts agent behavior based on calibration state.

Agents behave differently depending on:
- Insufficient calibration: conservative, no-trade-willing
- Sufficient calibration: normal, calibrated estimates
- Sports quality-gated: elevated conservatism
- Viability uncertain: higher evidence thresholds, conservative sizing

This module provides the regime context assembly and agent behavior adaptation.
"""

from __future__ import annotations

import structlog

from core.enums import CalibrationRegime, Category, OperatorMode
from core.constants import SPORTS_CALIBRATION_THRESHOLD
from agents.types import CalibrationContext, RegimeContext

_log = structlog.get_logger(component="regime_adapter")


class RegimeAdapter:
    """Assembles regime context and adapts agent parameters.

    Usage:
        adapter = RegimeAdapter()
        context = adapter.build_context(
            calibration_regime=CalibrationRegime.INSUFFICIENT,
            operator_mode=OperatorMode.PAPER,
            ...
        )
        size_cap = adapter.get_size_cap_multiplier(context, Category.SPORTS)
    """

    # Size cap multipliers by regime
    _INSUFFICIENT_SIZE_CAP = 0.5
    _SUFFICIENT_SIZE_CAP = 1.0
    _VIABILITY_UNCERTAIN_SIZE_CAP = 0.6
    _SPORTS_UNCALIBRATED_SIZE_CAP = 0.5

    # Evidence thresholds by regime
    _INSUFFICIENT_EVIDENCE_THRESHOLD = 0.7  # higher = stricter
    _SUFFICIENT_EVIDENCE_THRESHOLD = 0.5
    _VIABILITY_UNCERTAIN_EVIDENCE_THRESHOLD = 0.75

    def build_context(
        self,
        *,
        calibration_regime: CalibrationRegime = CalibrationRegime.INSUFFICIENT,
        viability_proven: bool = False,
        sports_resolved_trades: int = 0,
        system_brier_score: float | None = None,
        market_brier_score: float | None = None,
        operator_mode: OperatorMode = OperatorMode.PAPER,
        cost_selectivity_ratio: float | None = None,
        daily_opus_budget_remaining: float | None = None,
        daily_budget_remaining: float | None = None,
        category: Category | None = None,
    ) -> RegimeContext:
        """Build the full regime context for agent execution.

        Args:
            calibration_regime: Current calibration state.
            viability_proven: Whether strategy viability is established.
            sports_resolved_trades: Number of resolved Sports trades.
            system_brier_score: System's calibration score.
            market_brier_score: Market's calibration score.
            operator_mode: Current operator mode.
            cost_selectivity_ratio: Current cost-of-selectivity ratio.
            daily_opus_budget_remaining: Remaining daily Opus budget.
            daily_budget_remaining: Remaining daily total budget.
            category: Market category (for Sports quality gate check).

        Returns:
            Fully assembled RegimeContext.
        """
        sports_quality_gated = (
            category == Category.SPORTS
            and sports_resolved_trades < SPORTS_CALIBRATION_THRESHOLD
        )

        calibration = CalibrationContext(
            regime=calibration_regime,
            viability_proven=viability_proven,
            sports_quality_gated=sports_quality_gated,
            sports_resolved_trades=sports_resolved_trades,
            sports_calibration_threshold=SPORTS_CALIBRATION_THRESHOLD,
            system_brier_score=system_brier_score,
            market_brier_score=market_brier_score,
        )

        return RegimeContext(
            calibration=calibration,
            operator_mode=operator_mode,
            cost_selectivity_ratio=cost_selectivity_ratio,
            daily_opus_budget_remaining=daily_opus_budget_remaining,
            daily_budget_remaining=daily_budget_remaining,
        )

    def get_size_cap_multiplier(
        self,
        context: RegimeContext,
        category: Category | None = None,
    ) -> float:
        """Get the position sizing cap multiplier for the current regime.

        Returns a value between 0.0 and 1.0 to multiply against the
        base position size.
        """
        cal = context.calibration
        multiplier = self._SUFFICIENT_SIZE_CAP

        if cal.is_insufficient:
            multiplier = min(multiplier, self._INSUFFICIENT_SIZE_CAP)

        if cal.is_viability_uncertain:
            multiplier = min(multiplier, self._VIABILITY_UNCERTAIN_SIZE_CAP)

        if cal.sports_quality_gated:
            multiplier = min(multiplier, self._SPORTS_UNCALIBRATED_SIZE_CAP)

        return multiplier

    def get_evidence_threshold(self, context: RegimeContext) -> float:
        """Get the minimum evidence quality threshold for the current regime.

        Higher values are stricter (require higher evidence quality).
        """
        cal = context.calibration

        if cal.is_viability_uncertain:
            return self._VIABILITY_UNCERTAIN_EVIDENCE_THRESHOLD

        if cal.is_insufficient:
            return self._INSUFFICIENT_EVIDENCE_THRESHOLD

        return self._SUFFICIENT_EVIDENCE_THRESHOLD

    def should_prefer_no_trade(self, context: RegimeContext) -> bool:
        """Whether the current regime should bias toward no-trade.

        Insufficient calibration and viability-uncertain regimes
        should be more willing to issue no-trade decisions.
        """
        cal = context.calibration
        return cal.is_insufficient or cal.is_viability_uncertain

    def allows_opus_escalation(
        self,
        context: RegimeContext,
        *,
        is_exceptional: bool = False,
    ) -> bool:
        """Whether the current regime allows Tier A (Opus) escalation.

        Sports quality-gated regime blocks Opus unless exceptional.
        Viability-uncertain regime requires stronger justification.
        """
        cal = context.calibration

        # Sports: no Opus unless exceptional
        if cal.sports_quality_gated and not is_exceptional:
            return False

        # Check budget
        if context.daily_opus_budget_remaining is not None:
            if context.daily_opus_budget_remaining <= 0:
                return False

        return True

    def get_confidence_adjustment(self, context: RegimeContext) -> str:
        """Get the confidence level adjustment instruction for agents.

        Returns a string to inject into agent prompts about
        confidence handling.
        """
        cal = context.calibration

        if cal.is_viability_uncertain:
            return (
                "CONFIDENCE: Strategy viability unproven. Apply elevated caution. "
                "Use conservative probability estimates. Require strong independent "
                "evidence for any positive thesis."
            )

        if cal.is_insufficient:
            return (
                "CONFIDENCE: Low calibration confidence. Use conservative thesis "
                "confidence. Report uncertainty ranges when possible."
            )

        return (
            "CONFIDENCE: Sufficient calibration. Calibrated estimates may replace "
            "raw model estimates where calibration data exists."
        )

    def get_regime_summary(self, context: RegimeContext) -> dict[str, str | float | bool]:
        """Get a summary of the current regime state for logging."""
        cal = context.calibration
        return {
            "calibration_regime": cal.regime.value,
            "viability_proven": cal.viability_proven,
            "sports_quality_gated": cal.sports_quality_gated,
            "sports_resolved_trades": cal.sports_resolved_trades,
            "operator_mode": context.operator_mode.value,
            "size_cap_multiplier": self.get_size_cap_multiplier(context),
            "evidence_threshold": self.get_evidence_threshold(context),
            "prefers_no_trade": self.should_prefer_no_trade(context),
        }
