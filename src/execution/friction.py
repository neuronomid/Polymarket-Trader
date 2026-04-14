"""Friction Model Calibrator — Tier D deterministic.

Tracks and adjusts friction model parameters based on realized vs
estimated slippage across recent trades. Statistical deviation
triggers parameter adjustment.

From spec Section 12.6 / Plan Phase 10 Step 7:
- Spread estimate, depth assumption, impact coefficient
- Statistical deviation triggers parameter adjustment
- Changes logged in weekly review

No LLM calls permitted. Fully deterministic (Tier D, Cost Class Z).
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog

from execution.slippage import SlippageTracker
from execution.types import FrictionModelState, SlippageRecord

_log = structlog.get_logger(component="friction_model_calibrator")

# Default parameters
_DEFAULT_SPREAD_ESTIMATE = 0.02  # 2% default spread
_DEFAULT_DEPTH_ASSUMPTION = 5000.0  # $5000 depth assumption
_DEFAULT_IMPACT_COEFFICIENT = 0.5  # impact scaling factor

# Calibration thresholds
_RECALIBRATION_RATIO_THRESHOLD = 1.5  # recalibrate if mean ratio > 1.5x
_MIN_TRADES_FOR_CALIBRATION = 10  # minimum trades before calibration
_SMOOTHING_FACTOR = 0.3  # exponential smoothing for parameter updates


class FrictionModelCalibrator:
    """Deterministic friction model calibrator — Tier D.

    Maintains and adjusts the three friction model parameters:
    1. Spread estimate: estimated half-spread cost
    2. Depth assumption: expected available depth at top levels
    3. Impact coefficient: scaling factor for entry impact

    Updates are triggered when realized slippage consistently
    exceeds estimated slippage over a rolling window.

    Usage:
        calibrator = FrictionModelCalibrator()
        state = calibrator.current_state

        # After each trade:
        calibrator.record_trade(slippage_record)

        if calibrator.should_recalibrate():
            new_state = calibrator.recalibrate(recent_records)
    """

    def __init__(
        self,
        *,
        spread_estimate: float = _DEFAULT_SPREAD_ESTIMATE,
        depth_assumption: float = _DEFAULT_DEPTH_ASSUMPTION,
        impact_coefficient: float = _DEFAULT_IMPACT_COEFFICIENT,
        smoothing_factor: float = _SMOOTHING_FACTOR,
    ) -> None:
        self._state = FrictionModelState(
            spread_estimate=spread_estimate,
            depth_assumption=depth_assumption,
            impact_coefficient=impact_coefficient,
            last_calibrated_at=datetime.now(tz=UTC),
        )
        self._smoothing = smoothing_factor
        self._slippage_tracker = SlippageTracker()

    @property
    def current_state(self) -> FrictionModelState:
        """Get the current friction model state."""
        return self._state.model_copy()

    @property
    def slippage_tracker(self) -> SlippageTracker:
        """Get the underlying slippage tracker."""
        return self._slippage_tracker

    def record_trade(
        self,
        *,
        order_id: str,
        position_id: str,
        estimated_slippage_bps: float,
        realized_slippage_bps: float,
        order_size_usd: float,
        mid_price_at_submission: float,
        fill_price: float,
        liquidity_relative_size_pct: float | None = None,
    ) -> SlippageRecord:
        """Record a trade's slippage data and update calibration state.

        Args:
            order_id: Order identifier.
            position_id: Position identifier.
            estimated_slippage_bps: Pre-trade slippage estimate.
            realized_slippage_bps: Actual slippage.
            order_size_usd: Order size in USD.
            mid_price_at_submission: Mid-price at submission.
            fill_price: Actual fill price.
            liquidity_relative_size_pct: Order as % of visible depth.

        Returns:
            SlippageRecord with computed ratio.
        """
        record = self._slippage_tracker.record(
            order_id=order_id,
            position_id=position_id,
            estimated_slippage_bps=estimated_slippage_bps,
            realized_slippage_bps=realized_slippage_bps,
            order_size_usd=order_size_usd,
            mid_price_at_submission=mid_price_at_submission,
            fill_price=fill_price,
            liquidity_relative_size_pct=liquidity_relative_size_pct,
        )

        self._state.trades_since_calibration += 1
        self._state.mean_slippage_ratio = self._slippage_tracker.mean_slippage_ratio()
        self._state.needs_recalibration = self.should_recalibrate()

        return record

    def should_recalibrate(self) -> bool:
        """Check if friction model parameters need recalibration.

        Recalibrate when:
        - At least MIN_TRADES trades since last calibration
        - Mean slippage ratio exceeds RECALIBRATION_RATIO_THRESHOLD
        """
        if self._state.trades_since_calibration < _MIN_TRADES_FOR_CALIBRATION:
            return False

        return self._slippage_tracker.needs_recalibration()

    def recalibrate(
        self,
        records: list[SlippageRecord] | None = None,
    ) -> FrictionModelState:
        """Recalibrate friction model parameters from recent data.

        Uses exponential smoothing to update parameters toward
        realized values.

        Args:
            records: Slippage records to calibrate from. If None,
                     uses the slippage tracker's recent records.

        Returns:
            Updated FrictionModelState.
        """
        if records is None:
            records = self._slippage_tracker.recent_records

        if not records:
            return self._state

        # Compute observed metrics
        mean_ratio = self._compute_mean_ratio(records)
        mean_realized_bps = self._compute_mean_realized_bps(records)
        mean_order_size = self._compute_mean_order_size(records)

        # Update spread estimate (smoothed)
        if mean_realized_bps > 0:
            observed_spread = mean_realized_bps / 10_000 * 2  # half-spread → spread
            self._state.spread_estimate = self._smooth(
                self._state.spread_estimate, observed_spread
            )

        # Update impact coefficient based on ratio
        if mean_ratio is not None and mean_ratio > 0:
            adjustment = mean_ratio / 1.0  # normalized to target ratio of 1.0
            new_coefficient = self._state.impact_coefficient * adjustment
            self._state.impact_coefficient = self._smooth(
                self._state.impact_coefficient, new_coefficient
            )

        # Update depth assumption based on order sizes
        if mean_order_size > 0:
            # If we're consistently filling at sizes that cause higher slippage,
            # our depth assumption may be too optimistic
            if mean_ratio is not None and mean_ratio > _RECALIBRATION_RATIO_THRESHOLD:
                reduced_depth = self._state.depth_assumption * 0.9
                self._state.depth_assumption = max(100.0, reduced_depth)

        # Update state
        self._state.last_calibrated_at = datetime.now(tz=UTC)
        self._state.trades_since_calibration = 0
        self._state.mean_slippage_ratio = mean_ratio
        self._state.needs_recalibration = False
        self._state.version += 1

        _log.info(
            "friction_model_recalibrated",
            version=self._state.version,
            spread_estimate=self._state.spread_estimate,
            depth_assumption=self._state.depth_assumption,
            impact_coefficient=self._state.impact_coefficient,
            mean_ratio=mean_ratio,
            records_used=len(records),
        )

        return self._state.model_copy()

    def estimate_slippage_bps(
        self,
        order_size_usd: float,
        visible_depth_usd: float = 0.0,
    ) -> float:
        """Estimate slippage for a proposed order using current model.

        Args:
            order_size_usd: Proposed order size in USD.
            visible_depth_usd: Current visible depth in USD.

        Returns:
            Estimated slippage in basis points.
        """
        if order_size_usd <= 0:
            return 0.0

        # Base slippage from spread
        base_spread_bps = self._state.spread_estimate * 10_000 / 2  # half-spread

        # Impact component from depth consumption
        depth = visible_depth_usd if visible_depth_usd > 0 else self._state.depth_assumption
        depth_fraction = min(1.0, order_size_usd / depth) if depth > 0 else 1.0
        impact_bps = depth_fraction * self._state.impact_coefficient * 100  # scale to bps

        total_bps = base_spread_bps + impact_bps
        return round(max(0.0, total_bps), 2)

    # --- Private helpers ---

    def _smooth(self, old_value: float, new_value: float) -> float:
        """Apply exponential smoothing."""
        return round(
            old_value * (1 - self._smoothing) + new_value * self._smoothing,
            6,
        )

    @staticmethod
    def _compute_mean_ratio(records: list[SlippageRecord]) -> float | None:
        """Compute mean slippage ratio from records."""
        ratios = [
            r.slippage_ratio
            for r in records
            if r.slippage_ratio != float("inf")
        ]
        if not ratios:
            return None
        return sum(ratios) / len(ratios)

    @staticmethod
    def _compute_mean_realized_bps(records: list[SlippageRecord]) -> float:
        """Compute mean realized slippage in bps."""
        if not records:
            return 0.0
        return sum(r.realized_slippage_bps for r in records) / len(records)

    @staticmethod
    def _compute_mean_order_size(records: list[SlippageRecord]) -> float:
        """Compute mean order size in USD."""
        if not records:
            return 0.0
        return sum(r.order_size_usd for r in records) / len(records)
