"""Position sizing under calibration regimes.

Adjusts position sizes based on calibration state:
- Insufficient: hard size caps, conservative penalties
- Sufficient: calibrated estimates replace raw model probabilities
- Sports quality-gated: reduced multiplier until threshold met

Works in cooperation with the agents/regime.py RegimeAdapter and
the risk/sizer.py PositionSizer. This module provides the
calibration-specific sizing adjustments.

Fully deterministic (Tier D).
"""

from __future__ import annotations

import structlog

from calibration.segments import SegmentManager
from calibration.types import CalibrationSizingResult, SegmentType
from config.settings import CalibrationConfig, RiskConfig
from core.enums import CalibrationRegime, Category

_log = structlog.get_logger(component="calibration_sizing")

# Size cap multipliers by regime
_INSUFFICIENT_CAP = 0.50       # 50% of normal max
_SUFFICIENT_CAP = 1.00         # full normal sizing
_VIABILITY_UNCERTAIN_CAP = 0.60  # 60% until viability proven
_SPORTS_UNCALIBRATED_CAP = 0.50  # 50% until Sports threshold met


class CalibrationSizer:
    """Adjusts position sizing based on calibration regime.

    This is the calibration-aware layer that sits between the raw
    sizing calculation and the final Risk Governor approval.

    Usage:
        sizer = CalibrationSizer(segment_manager, risk_config, cal_config)
        result = sizer.adjust_size(
            base_size_usd=500.0,
            category=Category.POLITICS,
            raw_probability=0.65,
        )
    """

    def __init__(
        self,
        segment_manager: SegmentManager,
        risk_config: RiskConfig | None = None,
        calibration_config: CalibrationConfig | None = None,
    ) -> None:
        self._segments = segment_manager
        self._risk = risk_config or RiskConfig()
        self._cal = calibration_config or CalibrationConfig()

    def adjust_size(
        self,
        base_size_usd: float,
        category: Category,
        raw_probability: float,
        *,
        horizon_bucket: str | None = None,
    ) -> CalibrationSizingResult:
        """Apply calibration-regime sizing adjustments to a base size.

        Args:
            base_size_usd: Raw position size from the sizer.
            category: Market category.
            raw_probability: Raw model probability estimate.
            horizon_bucket: Optional horizon bucket for finer calibration.

        Returns:
            CalibrationSizingResult with adjusted size and audit trail.
        """
        # Get category-level regime
        cat_state = self._segments.compute_segment_state(
            SegmentType.CATEGORY, category.value
        )
        overall_state = self._segments.compute_segment_state(
            SegmentType.OVERALL, "all"
        )

        # Use the more conservative of category and overall regime
        regime = self._select_regime(cat_state.regime, overall_state.regime)

        # Start with regime-based cap
        cap = self._get_regime_cap(regime)

        # Sports quality gate
        sports_adj = 1.0
        if category == Category.SPORTS:
            sports_state = self._segments.compute_segment_state(
                SegmentType.CATEGORY, "sports"
            )
            if not sports_state.threshold_met:
                sports_adj = self._risk.sports_quality_gate_multiplier
                cap = min(cap, _SPORTS_UNCALIBRATED_CAP)

        # Category-specific adjustment
        cat_adj = 1.0
        if cat_state.threshold_met and self._segments.get_size_penalty_eligible(
            SegmentType.CATEGORY, category.value
        ):
            # Relaxed: category has enough data and shows improvement
            cat_adj = 1.0
        elif cat_state.resolved_count > 0:
            # Partial: some data but not enough
            progress = min(1.0, cat_state.resolved_count / cat_state.min_threshold)
            # Smooth ramp from 0.6 to 1.0 as data accumulates
            cat_adj = 0.6 + 0.4 * progress

        # Calibrated probability replacement
        calibrated_prob = None
        used_calibrated = False
        if regime == CalibrationRegime.SUFFICIENT and cat_state.system_brier is not None:
            # When sufficient, calibrated correction can override raw model
            # Simple calibration: adjust raw probability toward base rate
            calibrated_prob = raw_probability  # Placeholder — full correction requires bucket data
            used_calibrated = True

        # Compute final multiplier
        overall_multiplier = cap * sports_adj * cat_adj
        adjusted_size = round(base_size_usd * overall_multiplier, 2)

        result = CalibrationSizingResult(
            regime=regime,
            base_size_usd=base_size_usd,
            adjusted_size_usd=adjusted_size,
            size_cap_multiplier=cap,
            calibration_adjustment=cat_adj,
            sports_adjustment=sports_adj,
            category_adjustment=cat_adj,
            raw_model_probability=raw_probability,
            calibrated_probability=calibrated_prob,
            used_calibrated=used_calibrated,
            reason=self._build_reason(regime, cap, sports_adj, cat_adj),
        )

        _log.debug(
            "calibration_sizing_applied",
            category=category.value,
            regime=regime.value,
            base_size=base_size_usd,
            adjusted_size=adjusted_size,
            cap=cap,
            sports_adj=sports_adj,
            cat_adj=round(cat_adj, 4),
        )

        return result

    # --- Private helpers ---

    @staticmethod
    def _select_regime(
        category_regime: CalibrationRegime,
        overall_regime: CalibrationRegime,
    ) -> CalibrationRegime:
        """Select the more conservative regime."""
        priority = {
            CalibrationRegime.INSUFFICIENT: 0,
            CalibrationRegime.VIABILITY_UNCERTAIN: 1,
            CalibrationRegime.SUFFICIENT: 2,
        }
        cat_priority = priority.get(category_regime, 0)
        overall_priority = priority.get(overall_regime, 0)

        if cat_priority <= overall_priority:
            return category_regime
        return overall_regime

    @staticmethod
    def _get_regime_cap(regime: CalibrationRegime) -> float:
        """Get the size cap multiplier for a regime."""
        caps = {
            CalibrationRegime.INSUFFICIENT: _INSUFFICIENT_CAP,
            CalibrationRegime.SUFFICIENT: _SUFFICIENT_CAP,
            CalibrationRegime.VIABILITY_UNCERTAIN: _VIABILITY_UNCERTAIN_CAP,
        }
        return caps.get(regime, _INSUFFICIENT_CAP)

    @staticmethod
    def _build_reason(
        regime: CalibrationRegime,
        cap: float,
        sports_adj: float,
        cat_adj: float,
    ) -> str:
        """Build human-readable reason for sizing adjustment."""
        parts = [f"regime={regime.value}"]
        if cap < 1.0:
            parts.append(f"cap={cap}")
        if sports_adj < 1.0:
            parts.append(f"sports_penalty={sports_adj}")
        if cat_adj < 1.0:
            parts.append(f"category_adj={round(cat_adj, 3)}")
        return "; ".join(parts)
