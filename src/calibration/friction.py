"""Friction model calibration feedback.

Compares realized vs estimated slippage over a rolling window of trades
and proposes parameter adjustments when divergence exceeds thresholds.

Per spec Section 14.14:
- Divergence > 50% over 20 trades → recalibrate (tighten)
- Below by > 30% → relax slightly
- Changes logged in weekly review

Fully deterministic (Tier D).
"""

from __future__ import annotations

from collections import deque
from datetime import UTC, datetime

import structlog

from calibration.types import FrictionFeedback
from config.settings import ExecutionConfig

_log = structlog.get_logger(component="friction_model")

# Thresholds
TIGHTEN_RATIO_THRESHOLD = 1.5    # realized/estimated > 1.5 → tighten
RELAX_RATIO_THRESHOLD = 0.7      # realized/estimated < 0.7 → relax
TIGHTEN_ADJUSTMENT = 1.20        # increase estimates by 20%
RELAX_ADJUSTMENT = 0.90          # decrease estimates by 10%


class _SlippageObservation:
    """Single slippage observation."""

    __slots__ = ("estimated_bps", "realized_bps", "recorded_at")

    def __init__(self, estimated_bps: float, realized_bps: float) -> None:
        self.estimated_bps = estimated_bps
        self.realized_bps = realized_bps
        self.recorded_at = datetime.now(tz=UTC)


class FrictionCalibrator:
    """Calibrates friction model parameters based on observed slippage.

    Maintains a rolling window of slippage observations and triggers
    parameter adjustments when divergence exceeds thresholds.

    Usage:
        calibrator = FrictionCalibrator(config)
        calibrator.record_slippage(estimated=5.0, realized=8.0)
        feedback = calibrator.evaluate()
        if feedback.needs_tightening:
            # apply feedback.proposed_* parameters
    """

    def __init__(
        self,
        config: ExecutionConfig | None = None,
        *,
        window_size: int = 20,
    ) -> None:
        self._config = config or ExecutionConfig()
        self._window_size = window_size
        self._observations: deque[_SlippageObservation] = deque(maxlen=window_size)

        # Current parameters
        self._spread_estimate = self._config.default_spread_estimate
        self._depth_assumption = self._config.default_depth_assumption
        self._impact_coefficient = self._config.default_impact_coefficient
        self._last_calibrated_at: datetime | None = None
        self._version = 1

    # --- Recording ---

    def record_slippage(
        self,
        estimated_bps: float,
        realized_bps: float,
    ) -> None:
        """Record a slippage observation."""
        obs = _SlippageObservation(estimated_bps, realized_bps)
        self._observations.append(obs)

        _log.debug(
            "slippage_observed",
            estimated_bps=round(estimated_bps, 2),
            realized_bps=round(realized_bps, 2),
            ratio=round(realized_bps / estimated_bps, 4) if estimated_bps > 0 else 0.0,
            window_filled=len(self._observations),
        )

    # --- Evaluation ---

    def evaluate(self) -> FrictionFeedback:
        """Evaluate friction model accuracy over the observation window.

        Returns feedback with adjustment proposals if warranted.
        """
        if not self._observations:
            return FrictionFeedback(
                mean_slippage_ratio=1.0,
                trades_in_window=0,
                window_size=self._window_size,
                current_spread_estimate=self._spread_estimate,
                current_depth_assumption=self._depth_assumption,
                current_impact_coefficient=self._impact_coefficient,
            )

        # Compute mean ratio
        ratios = []
        for obs in self._observations:
            if obs.estimated_bps > 0:
                ratios.append(obs.realized_bps / obs.estimated_bps)

        if not ratios:
            mean_ratio = 1.0
        else:
            mean_ratio = sum(ratios) / len(ratios)

        count = len(self._observations)
        needs_tightening = mean_ratio > TIGHTEN_RATIO_THRESHOLD and count >= self._window_size
        can_relax = mean_ratio < RELAX_RATIO_THRESHOLD and count >= self._window_size

        # Determine adjustment
        adjustment = 1.0
        proposed_spread = None
        proposed_depth = None
        proposed_impact = None

        if needs_tightening:
            adjustment = TIGHTEN_ADJUSTMENT
            proposed_spread = round(self._spread_estimate * adjustment, 6)
            proposed_depth = round(self._depth_assumption / adjustment, 2)  # reduce depth assumption
            proposed_impact = round(self._impact_coefficient * adjustment, 6)

            _log.warning(
                "friction_model_needs_tightening",
                mean_ratio=round(mean_ratio, 4),
                threshold=TIGHTEN_RATIO_THRESHOLD,
                trades=count,
                adjustment=adjustment,
            )
        elif can_relax:
            adjustment = RELAX_ADJUSTMENT
            proposed_spread = round(self._spread_estimate * adjustment, 6)
            proposed_depth = round(self._depth_assumption / adjustment, 2)
            proposed_impact = round(self._impact_coefficient * adjustment, 6)

            _log.info(
                "friction_model_can_relax",
                mean_ratio=round(mean_ratio, 4),
                threshold=RELAX_RATIO_THRESHOLD,
                trades=count,
                adjustment=adjustment,
            )

        return FrictionFeedback(
            mean_slippage_ratio=round(mean_ratio, 6),
            trades_in_window=count,
            window_size=self._window_size,
            needs_tightening=needs_tightening,
            can_relax=can_relax,
            adjustment_factor=adjustment,
            current_spread_estimate=self._spread_estimate,
            current_depth_assumption=self._depth_assumption,
            current_impact_coefficient=self._impact_coefficient,
            proposed_spread_estimate=proposed_spread,
            proposed_depth_assumption=proposed_depth,
            proposed_impact_coefficient=proposed_impact,
        )

    def apply_adjustment(self, feedback: FrictionFeedback) -> None:
        """Apply proposed parameter adjustments from feedback.

        Only applies if feedback has valid proposals. Increments version.
        """
        if feedback.proposed_spread_estimate is not None:
            old_spread = self._spread_estimate
            self._spread_estimate = feedback.proposed_spread_estimate
            self._depth_assumption = feedback.proposed_depth_assumption or self._depth_assumption
            self._impact_coefficient = feedback.proposed_impact_coefficient or self._impact_coefficient
            self._last_calibrated_at = datetime.now(tz=UTC)
            self._version += 1

            _log.info(
                "friction_model_adjusted",
                old_spread=old_spread,
                new_spread=self._spread_estimate,
                new_depth=self._depth_assumption,
                new_impact=self._impact_coefficient,
                version=self._version,
                adjustment_type="tighten" if feedback.needs_tightening else "relax",
            )

    # --- Current Parameters ---

    @property
    def spread_estimate(self) -> float:
        return self._spread_estimate

    @property
    def depth_assumption(self) -> float:
        return self._depth_assumption

    @property
    def impact_coefficient(self) -> float:
        return self._impact_coefficient

    @property
    def version(self) -> int:
        return self._version

    @property
    def observations_count(self) -> int:
        return len(self._observations)
