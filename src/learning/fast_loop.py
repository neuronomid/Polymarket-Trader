"""Daily fast learning loop.

Updates calibration, cost metrics, slippage, budget, and absence status daily.
All updates are deterministic (Tier D) — no LLM calls.

Per spec Section 15.9.
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog

from calibration.brier import BrierEngine
from calibration.friction import FrictionCalibrator
from calibration.segments import SegmentManager
from calibration.store import CalibrationStore
from learning.no_trade_monitor import NoTradeMonitor
from learning.types import FastLoopInput, FastLoopResult, NoTradeRateSignal

_log = structlog.get_logger(component="fast_learning_loop")


class FastLearningLoop:
    """Daily learning loop — updates calibration, cost, friction, budget.

    Per spec Section 15.9:
    - Update calibration data from new resolutions
    - Update cost metrics and selectivity
    - Check slippage divergence for friction recalibration
    - Update budget status and absence state

    Usage:
        loop = FastLearningLoop(store, brier, segments, friction, no_trade)
        result = loop.execute(input_data)
    """

    def __init__(
        self,
        store: CalibrationStore,
        brier_engine: BrierEngine,
        segment_manager: SegmentManager,
        friction_calibrator: FrictionCalibrator,
        no_trade_monitor: NoTradeMonitor,
    ) -> None:
        self._store = store
        self._brier = brier_engine
        self._segments = segment_manager
        self._friction = friction_calibrator
        self._no_trade = no_trade_monitor

    def execute(self, inp: FastLoopInput) -> FastLoopResult:
        """Execute the daily fast learning loop.

        Processes all deterministic updates in a single pass.
        """
        _log.info(
            "fast_loop_started",
            as_of=inp.as_of.isoformat(),
            new_resolutions=inp.new_resolutions,
        )

        result = FastLoopResult(executed_at=inp.as_of)

        # 1. Update calibration segments if new resolutions
        if inp.new_resolutions > 0:
            states = self._segments.compute_all_segment_states()
            result.calibration_updated = True
            result.segments_updated = [
                f"{s.segment_type.value}:{s.segment_label}"
                for s in states
                if s.resolved_count > 0
            ]

            _log.info(
                "calibration_segments_updated",
                new_resolutions=inp.new_resolutions,
                segments_refreshed=len(result.segments_updated),
            )

        # 2. Friction model check
        if inp.trades_since_friction_check >= self._friction._window_size:
            feedback = self._friction.evaluate()
            if feedback.needs_tightening or feedback.can_relax:
                result.friction_recalibration_triggered = True
                result.warnings.append(
                    f"Friction model recalibration: ratio={feedback.mean_slippage_ratio:.4f}, "
                    f"{'tighten' if feedback.needs_tightening else 'relax'}"
                )

                _log.info(
                    "friction_recalibration_needed",
                    mean_ratio=feedback.mean_slippage_ratio,
                    action="tighten" if feedback.needs_tightening else "relax",
                )

        # 3. Cost metrics
        result.metrics["daily_spend_usd"] = round(inp.daily_spend_usd, 4)
        result.metrics["trades_entered"] = inp.trades_entered_today
        if inp.cost_selectivity_ratio is not None:
            result.metrics["cost_selectivity_ratio"] = round(inp.cost_selectivity_ratio, 4)

        # 4. Budget alerts
        if inp.daily_budget_remaining_pct < 0.10:
            result.budget_alerts.append("daily_budget_critically_low")
            result.warnings.append(
                f"Daily budget below 10%: {inp.daily_budget_remaining_pct:.1%} remaining"
            )

        if inp.lifetime_budget_consumed_pct > 0.50:
            level = "50%"
            if inp.lifetime_budget_consumed_pct > 0.75:
                level = "75%"
            if inp.lifetime_budget_consumed_pct >= 1.0:
                level = "100%"
            result.budget_alerts.append(f"lifetime_budget_{level}")

        # 5. No-trade rate
        no_trade_metrics = self._no_trade.compute_metrics()
        result.no_trade_signal = no_trade_metrics.signal
        if no_trade_metrics.signal != NoTradeRateSignal.NORMAL:
            result.warnings.append(
                f"No-trade rate signal: {no_trade_metrics.signal.value} — "
                f"{no_trade_metrics.signal_reason}"
            )

        # 6. Absence status
        if inp.operator_absent:
            result.metrics["absence_hours"] = inp.absence_hours
            result.warnings.append(
                f"Operator absent for {inp.absence_hours:.1f} hours"
            )

        _log.info(
            "fast_loop_completed",
            calibration_updated=result.calibration_updated,
            friction_triggered=result.friction_recalibration_triggered,
            budget_alerts=result.budget_alerts,
            no_trade_signal=result.no_trade_signal.value,
            warnings_count=len(result.warnings),
        )

        return result
