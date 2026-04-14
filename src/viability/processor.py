"""Strategy viability checkpoint processor.

Evaluates viability at scheduled checkpoints (weeks 4, 8, 12) and
budget thresholds (50%, 75%, 100%). All determination is by
deterministic threshold comparison (Tier D), not LLM.

Checkpoint logic:
- Week 4 (Preliminary): Insufficient data likely, no decisions.
- Week 8 (Intermediate): If 20+ resolved, compare system vs. market.
  VIABILITY_CONCERN if system is worse.
- Week 12 (Decision): If 50+ resolved and system worse →
  VIABILITY_WARNING, operator must acknowledge.
- Budget 50/75/100: Alert on consumption milestones.

Fully deterministic (Tier D).
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog

from config.settings import CalibrationConfig, CostConfig
from viability.types import (
    LifetimeBudgetState,
    ViabilityAlert,
    ViabilityAlertType,
    ViabilityCheckpointInput,
    ViabilityCheckpointResult,
    ViabilityCheckpointType,
    ViabilityMetrics,
    ViabilityStatus,
)

_log = structlog.get_logger(component="viability_processor")

# --- Thresholds ---

WEEK_8_MIN_RESOLVED = 20
WEEK_12_MIN_RESOLVED = 50


class ViabilityProcessor:
    """Strategy viability checkpoint processor.

    Evaluates viability metrics at scheduled checkpoints and generates
    alerts when thresholds are crossed. All logic is deterministic.

    Usage:
        processor = ViabilityProcessor(calibration_config, cost_config)
        result = processor.evaluate_checkpoint(input)
        budget_state = processor.evaluate_lifetime_budget(consumed, total)
    """

    def __init__(
        self,
        calibration_config: CalibrationConfig,
        cost_config: CostConfig,
    ) -> None:
        self._cal_config = calibration_config
        self._cost_config = cost_config

        # Track which budget alerts have already been triggered
        self._budget_alerts_triggered: set[str] = set()

    def evaluate_checkpoint(
        self, inp: ViabilityCheckpointInput
    ) -> ViabilityCheckpointResult:
        """Evaluate a viability checkpoint.

        Routes to the appropriate checkpoint handler based on type.
        """
        _log.info(
            "viability_checkpoint_starting",
            checkpoint_type=inp.checkpoint_type.value,
            week=inp.system_week_number,
            resolved=inp.metrics.resolved_forecasts,
        )

        if inp.checkpoint_type == ViabilityCheckpointType.WEEK_4:
            result = self._evaluate_week_4(inp)
        elif inp.checkpoint_type == ViabilityCheckpointType.WEEK_8:
            result = self._evaluate_week_8(inp)
        elif inp.checkpoint_type == ViabilityCheckpointType.WEEK_12:
            result = self._evaluate_week_12(inp)
        elif inp.checkpoint_type in (
            ViabilityCheckpointType.BUDGET_50,
            ViabilityCheckpointType.BUDGET_75,
            ViabilityCheckpointType.BUDGET_100,
        ):
            result = self._evaluate_budget_checkpoint(inp)
        else:
            result = ViabilityCheckpointResult(
                checkpoint_type=inp.checkpoint_type,
                system_week_number=inp.system_week_number,
                status=ViabilityStatus.INSUFFICIENT_DATA,
                status_note="Unknown checkpoint type.",
                metrics=inp.metrics,
            )

        _log.info(
            "viability_checkpoint_complete",
            checkpoint_type=result.checkpoint_type.value,
            status=result.status.value,
            alerts=len(result.alerts),
            requires_ack=result.requires_acknowledgment,
        )

        return result

    def evaluate_lifetime_budget(
        self,
        consumed_usd: float,
        total_budget_usd: float,
    ) -> LifetimeBudgetState:
        """Evaluate lifetime experiment budget and generate alerts.

        Continuous tracking. Alerts at 50%, 75%, 100%.
        Level D operations never blocked.
        """
        remaining = max(0.0, total_budget_usd - consumed_usd)
        consumed_pct = (
            consumed_usd / total_budget_usd
            if total_budget_usd > 0 else 1.0
        )

        alert_50 = consumed_pct >= 0.50
        alert_75 = consumed_pct >= 0.75
        alert_100 = consumed_pct >= 1.0
        paused = consumed_pct >= 1.0

        state = LifetimeBudgetState(
            total_budget_usd=round(total_budget_usd, 2),
            consumed_usd=round(consumed_usd, 2),
            remaining_usd=round(remaining, 2),
            consumed_pct=round(consumed_pct, 4),
            alert_50_triggered=alert_50,
            alert_75_triggered=alert_75,
            alert_100_triggered=alert_100,
            investigations_paused=paused,
        )

        # Log threshold crossings
        if alert_100 and "100" not in self._budget_alerts_triggered:
            self._budget_alerts_triggered.add("100")
            _log.warning(
                "lifetime_budget_exhausted",
                consumed_pct=round(consumed_pct, 4),
                investigations_paused=True,
            )
        elif alert_75 and "75" not in self._budget_alerts_triggered:
            self._budget_alerts_triggered.add("75")
            _log.warning(
                "lifetime_budget_75pct",
                consumed_pct=round(consumed_pct, 4),
            )
        elif alert_50 and "50" not in self._budget_alerts_triggered:
            self._budget_alerts_triggered.add("50")
            _log.info(
                "lifetime_budget_50pct",
                consumed_pct=round(consumed_pct, 4),
            )

        return state

    def should_run_checkpoint(
        self,
        system_week_number: int,
        budget_consumed_pct: float,
    ) -> list[ViabilityCheckpointType]:
        """Determine which checkpoints should run this week.

        Returns a list of checkpoint types that should be evaluated.
        """
        checkpoints: list[ViabilityCheckpointType] = []

        if system_week_number == self._cal_config.preliminary_week:
            checkpoints.append(ViabilityCheckpointType.WEEK_4)
        elif system_week_number == self._cal_config.intermediate_week:
            checkpoints.append(ViabilityCheckpointType.WEEK_8)
        elif system_week_number == self._cal_config.decision_week:
            checkpoints.append(ViabilityCheckpointType.WEEK_12)

        # Budget checkpoints
        if budget_consumed_pct >= 1.0 and "budget_100" not in self._budget_alerts_triggered:
            checkpoints.append(ViabilityCheckpointType.BUDGET_100)
        elif budget_consumed_pct >= 0.75 and "budget_75" not in self._budget_alerts_triggered:
            checkpoints.append(ViabilityCheckpointType.BUDGET_75)
        elif budget_consumed_pct >= 0.50 and "budget_50" not in self._budget_alerts_triggered:
            checkpoints.append(ViabilityCheckpointType.BUDGET_50)

        return checkpoints

    # --- Private Checkpoint Handlers ---

    def _evaluate_week_4(
        self, inp: ViabilityCheckpointInput
    ) -> ViabilityCheckpointResult:
        """Week 4: Preliminary — insufficient data likely, no decisions."""
        result = ViabilityCheckpointResult(
            checkpoint_type=ViabilityCheckpointType.WEEK_4,
            system_week_number=inp.system_week_number,
            status=ViabilityStatus.INSUFFICIENT_DATA,
            status_note=(
                f"Preliminary checkpoint. {inp.metrics.resolved_forecasts} resolved "
                f"forecasts collected. Insufficient for viability determination."
            ),
            metrics=inp.metrics,
        )

        result.alerts.append(
            ViabilityAlert(
                alert_type=ViabilityAlertType.VIABILITY_CHECKPOINT,
                checkpoint_type=ViabilityCheckpointType.WEEK_4,
                status=ViabilityStatus.INSUFFICIENT_DATA,
                message=f"Week 4 preliminary checkpoint: {inp.metrics.resolved_forecasts} resolved forecasts.",
            )
        )

        return result

    def _evaluate_week_8(
        self, inp: ViabilityCheckpointInput
    ) -> ViabilityCheckpointResult:
        """Week 8: Intermediate — compare system vs. market if 20+ resolved."""
        metrics = inp.metrics

        if metrics.resolved_forecasts < WEEK_8_MIN_RESOLVED:
            return ViabilityCheckpointResult(
                checkpoint_type=ViabilityCheckpointType.WEEK_8,
                system_week_number=inp.system_week_number,
                status=ViabilityStatus.INSUFFICIENT_DATA,
                status_note=(
                    f"Intermediate checkpoint. Only {metrics.resolved_forecasts} resolved "
                    f"(need {WEEK_8_MIN_RESOLVED}+). Cannot assess viability yet."
                ),
                metrics=metrics,
                alerts=[
                    ViabilityAlert(
                        alert_type=ViabilityAlertType.VIABILITY_CHECKPOINT,
                        checkpoint_type=ViabilityCheckpointType.WEEK_8,
                        status=ViabilityStatus.INSUFFICIENT_DATA,
                        message=(
                            f"Week 8 intermediate: {metrics.resolved_forecasts} resolved "
                            f"forecasts, need {WEEK_8_MIN_RESOLVED}+ for comparison."
                        ),
                    )
                ],
            )

        # Compare system vs. market
        system_is_worse = self._system_is_worse(metrics)

        if system_is_worse:
            return ViabilityCheckpointResult(
                checkpoint_type=ViabilityCheckpointType.WEEK_8,
                system_week_number=inp.system_week_number,
                status=ViabilityStatus.CONCERN,
                status_note=(
                    f"System Brier ({metrics.system_brier:.4f}) is worse than "
                    f"market Brier ({metrics.market_brier:.4f}). "
                    f"System advantage: {metrics.system_advantage:.4f}. "
                    f"Based on {metrics.resolved_forecasts} resolved forecasts."
                ),
                metrics=metrics,
                alerts=[
                    ViabilityAlert(
                        alert_type=ViabilityAlertType.VIABILITY_CONCERN,
                        checkpoint_type=ViabilityCheckpointType.WEEK_8,
                        status=ViabilityStatus.CONCERN,
                        message=(
                            f"VIABILITY_CONCERN: System Brier worse than market "
                            f"at week 8 ({metrics.resolved_forecasts} resolved)."
                        ),
                        details={
                            "system_brier": metrics.system_brier,
                            "market_brier": metrics.market_brier,
                            "system_advantage": metrics.system_advantage,
                        },
                    )
                ],
            )

        return ViabilityCheckpointResult(
            checkpoint_type=ViabilityCheckpointType.WEEK_8,
            system_week_number=inp.system_week_number,
            status=ViabilityStatus.VIABLE,
            status_note=(
                f"System outperforming market. "
                f"System Brier: {metrics.system_brier:.4f}, "
                f"Market Brier: {metrics.market_brier:.4f}. "
                f"Advantage: {metrics.system_advantage:.4f}."
            ),
            metrics=metrics,
            alerts=[
                ViabilityAlert(
                    alert_type=ViabilityAlertType.VIABILITY_CHECKPOINT,
                    checkpoint_type=ViabilityCheckpointType.WEEK_8,
                    status=ViabilityStatus.VIABLE,
                    message=f"Week 8: System outperforming market ({metrics.resolved_forecasts} resolved).",
                )
            ],
        )

    def _evaluate_week_12(
        self, inp: ViabilityCheckpointInput
    ) -> ViabilityCheckpointResult:
        """Week 12: Decision — if 50+ resolved and system worse, VIABILITY_WARNING."""
        metrics = inp.metrics

        if metrics.resolved_forecasts < WEEK_12_MIN_RESOLVED:
            return ViabilityCheckpointResult(
                checkpoint_type=ViabilityCheckpointType.WEEK_12,
                system_week_number=inp.system_week_number,
                status=ViabilityStatus.INSUFFICIENT_DATA,
                status_note=(
                    f"Decision checkpoint. Only {metrics.resolved_forecasts} resolved "
                    f"(need {WEEK_12_MIN_RESOLVED}+). Cannot make viability decision."
                ),
                metrics=metrics,
                alerts=[
                    ViabilityAlert(
                        alert_type=ViabilityAlertType.VIABILITY_CHECKPOINT,
                        checkpoint_type=ViabilityCheckpointType.WEEK_12,
                        status=ViabilityStatus.INSUFFICIENT_DATA,
                        message=(
                            f"Week 12 decision: {metrics.resolved_forecasts} resolved, "
                            f"need {WEEK_12_MIN_RESOLVED}+ for viability decision."
                        ),
                    )
                ],
            )

        system_is_worse = self._system_is_worse(metrics)

        if system_is_worse:
            return ViabilityCheckpointResult(
                checkpoint_type=ViabilityCheckpointType.WEEK_12,
                system_week_number=inp.system_week_number,
                status=ViabilityStatus.WARNING,
                status_note=(
                    f"VIABILITY_WARNING: System worse than market after "
                    f"{metrics.resolved_forecasts} resolved forecasts. "
                    f"System Brier: {metrics.system_brier:.4f}, "
                    f"Market Brier: {metrics.market_brier:.4f}. "
                    f"Operator must acknowledge."
                ),
                metrics=metrics,
                requires_acknowledgment=True,
                alerts=[
                    ViabilityAlert(
                        alert_type=ViabilityAlertType.VIABILITY_WARNING,
                        checkpoint_type=ViabilityCheckpointType.WEEK_12,
                        status=ViabilityStatus.WARNING,
                        message=(
                            f"VIABILITY_WARNING: System Brier worse than market "
                            f"at week 12 ({metrics.resolved_forecasts} resolved). "
                            f"Operator must acknowledge."
                        ),
                        details={
                            "system_brier": metrics.system_brier,
                            "market_brier": metrics.market_brier,
                            "system_advantage": metrics.system_advantage,
                            "hypothetical_pnl": metrics.hypothetical_pnl,
                        },
                        requires_acknowledgment=True,
                    )
                ],
            )

        return ViabilityCheckpointResult(
            checkpoint_type=ViabilityCheckpointType.WEEK_12,
            system_week_number=inp.system_week_number,
            status=ViabilityStatus.VIABLE,
            status_note=(
                f"System viable at week 12. "
                f"System Brier: {metrics.system_brier:.4f}, "
                f"Market Brier: {metrics.market_brier:.4f}. "
                f"Advantage: {metrics.system_advantage:.4f}."
            ),
            metrics=metrics,
            alerts=[
                ViabilityAlert(
                    alert_type=ViabilityAlertType.VIABILITY_CHECKPOINT,
                    checkpoint_type=ViabilityCheckpointType.WEEK_12,
                    status=ViabilityStatus.VIABLE,
                    message=f"Week 12: System viable ({metrics.resolved_forecasts} resolved).",
                )
            ],
        )

    def _evaluate_budget_checkpoint(
        self, inp: ViabilityCheckpointInput
    ) -> ViabilityCheckpointResult:
        """Budget threshold checkpoint (50%, 75%, 100%)."""
        metrics = inp.metrics
        pct = metrics.lifetime_budget_consumed_pct
        tag = inp.checkpoint_type.value  # e.g., "budget_50"

        triggered_tags = {tag}
        if inp.checkpoint_type == ViabilityCheckpointType.BUDGET_100:
            triggered_tags.update(
                {
                    ViabilityCheckpointType.BUDGET_50.value,
                    ViabilityCheckpointType.BUDGET_75.value,
                }
            )
        elif inp.checkpoint_type == ViabilityCheckpointType.BUDGET_75:
            triggered_tags.add(ViabilityCheckpointType.BUDGET_50.value)

        self._budget_alerts_triggered.update(triggered_tags)

        investigations_paused = pct >= 1.0

        status_note = (
            f"Lifetime budget {round(pct * 100)}% consumed. "
            f"Resolved forecasts: {metrics.resolved_forecasts}."
        )
        if investigations_paused:
            status_note += " Investigations paused (Level D never blocked)."

        return ViabilityCheckpointResult(
            checkpoint_type=inp.checkpoint_type,
            system_week_number=inp.system_week_number,
            status=ViabilityStatus.CONCERN if pct >= 0.75 else ViabilityStatus.VIABLE,
            status_note=status_note,
            metrics=metrics,
            alerts=[
                ViabilityAlert(
                    alert_type=ViabilityAlertType.BUDGET_THRESHOLD,
                    checkpoint_type=inp.checkpoint_type,
                    status=ViabilityStatus.CONCERN if pct >= 0.75 else ViabilityStatus.VIABLE,
                    message=f"Lifetime budget {round(pct * 100)}% consumed.",
                    details={
                        "consumed_pct": pct,
                        "investigations_paused": investigations_paused,
                    },
                )
            ],
        )

    # --- Helpers ---

    @staticmethod
    def _system_is_worse(metrics: ViabilityMetrics) -> bool:
        """Determine if system is worse than market by Brier score.

        Lower Brier is better. System is worse when system_advantage < 0.
        """
        if metrics.system_advantage is not None:
            return metrics.system_advantage < 0.0

        if metrics.system_brier is not None and metrics.market_brier is not None:
            return metrics.system_brier > metrics.market_brier

        return False
