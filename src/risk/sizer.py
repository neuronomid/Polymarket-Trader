"""Position sizer — computes recommended position size.

Size ∝ Edge × Confidence × Evidence Quality × Liquidity Quality × Remaining Budget
with downward penalties for ambiguity, correlation, weak sources, and timing.

Also applies: drawdown multiplier, sports quality gate, category caps.

Fully deterministic (Tier D). No LLM calls.
"""

from __future__ import annotations

import structlog

from config.settings import RiskConfig
from core.constants import SPORTS_CALIBRATION_THRESHOLD
from core.enums import CategoryQualityTier
from risk.types import (
    DrawdownState,
    LiquidityCheck,
    PortfolioState,
    SizingRequest,
    SizingResult,
)


class PositionSizer:
    """Computes position size from edge, confidence, quality, and penalties."""

    def __init__(self, config: RiskConfig) -> None:
        self._config = config
        self._log = structlog.get_logger(component="position_sizer")

    def compute(
        self,
        request: SizingRequest,
        portfolio: PortfolioState,
        drawdown: DrawdownState,
        liquidity: LiquidityCheck | None = None,
    ) -> SizingResult:
        """Compute recommended position size.

        Returns SizingResult with recommended_size_usd, max_size_usd,
        factor breakdown, and applied penalties.
        """
        cfg = self._config
        balance = portfolio.account_balance_usd

        # Base size as fraction of account balance
        base_size = balance * cfg.sizing_base_fraction

        # Positive factors (multiplicative)
        edge_factor = self._edge_factor(request)
        confidence_factor = self._confidence_factor(request)
        evidence_factor = self._evidence_factor(request)
        liquidity_factor = self._liquidity_factor(request)

        # Budget remaining factor — scale by how much deployment budget remains
        max_daily = balance * cfg.max_daily_deployment_pct
        remaining_daily = max(0.0, max_daily - portfolio.daily_deployment_used_usd)
        budget_factor = min(1.0, remaining_daily / max_daily) if max_daily > 0 else 0.0

        # Raw size before penalties
        raw_size = (
            base_size
            * edge_factor
            * confidence_factor
            * evidence_factor
            * liquidity_factor
            * budget_factor
        )

        factors = {
            "base_size_usd": base_size,
            "edge_factor": edge_factor,
            "confidence_factor": confidence_factor,
            "evidence_factor": evidence_factor,
            "liquidity_factor": liquidity_factor,
            "budget_factor": budget_factor,
        }

        # Penalties (multiplicative reductions)
        penalties: dict[str, float] = {}
        penalty_multiplier = 1.0

        # Ambiguity penalty
        if request.ambiguity_score > 0:
            p = 1.0 - (request.ambiguity_score * cfg.ambiguity_penalty_weight)
            p = max(0.1, p)
            penalties["ambiguity"] = p
            penalty_multiplier *= p

        # Correlation burden penalty
        if request.correlation_burden_score > 0:
            p = 1.0 - (request.correlation_burden_score * cfg.correlation_penalty_weight)
            p = max(0.1, p)
            penalties["correlation"] = p
            penalty_multiplier *= p

        # Weak source penalty
        if request.weak_source_score > 0:
            p = 1.0 - (request.weak_source_score * cfg.weak_source_penalty_weight)
            p = max(0.1, p)
            penalties["weak_source"] = p
            penalty_multiplier *= p

        # Timing uncertainty penalty
        if request.timing_uncertainty_score > 0:
            p = 1.0 - (request.timing_uncertainty_score * cfg.timing_penalty_weight)
            p = max(0.1, p)
            penalties["timing"] = p
            penalty_multiplier *= p

        # Drawdown size multiplier
        dd_mult = drawdown.size_multiplier
        if dd_mult < 1.0:
            penalties["drawdown"] = dd_mult
            penalty_multiplier *= dd_mult

        # Sports quality gate
        if request.category_quality_tier == CategoryQualityTier.QUALITY_GATED:
            if request.category_resolved_trades < SPORTS_CALIBRATION_THRESHOLD:
                sg = cfg.sports_quality_gate_multiplier
                penalties["sports_quality_gate"] = sg
                penalty_multiplier *= sg

        sized = raw_size * penalty_multiplier

        # Hard caps
        capped_by: str | None = None

        # Cap 1: liquidity max
        max_from_liquidity = liquidity.max_order_usd if liquidity else float("inf")

        # Cap 2: remaining daily deployment
        max_from_daily = remaining_daily

        # Cap 3: remaining total exposure headroom
        exposure_headroom = max(
            0.0, cfg.max_total_open_exposure_usd - portfolio.total_open_exposure_usd
        )

        hard_max = min(max_from_liquidity, max_from_daily, exposure_headroom)

        if sized > hard_max:
            if hard_max == max_from_liquidity:
                capped_by = "liquidity_depth"
            elif hard_max == max_from_daily:
                capped_by = "daily_deployment"
            else:
                capped_by = "exposure_headroom"
            sized = hard_max

        sized = max(0.0, sized)

        return SizingResult(
            recommended_size_usd=round(sized, 2),
            max_size_usd=round(hard_max, 2),
            size_factors=factors,
            penalties_applied=penalties,
            capped_by=capped_by,
        )

    def _edge_factor(self, request: SizingRequest) -> float:
        """Scale by edge magnitude. Higher edge → larger position."""
        edge = request.net_edge_after_cost or request.gross_edge
        # Clamp to [0, 1] — edge of 10%+ maps to factor 1.0
        return min(1.0, max(0.0, edge * 10.0))

    def _confidence_factor(self, request: SizingRequest) -> float:
        """Scale by confidence estimate (0-1)."""
        return max(0.1, min(1.0, request.confidence_estimate))

    def _evidence_factor(self, request: SizingRequest) -> float:
        """Scale by evidence quality and diversity."""
        quality = max(0.1, min(1.0, request.evidence_quality_score))
        diversity = max(0.1, min(1.0, request.evidence_diversity_score))
        return (quality + diversity) / 2.0

    def _liquidity_factor(self, request: SizingRequest) -> float:
        """Scale by liquidity quality (spread tightness)."""
        if request.spread is None or request.spread <= 0:
            return 0.5  # unknown liquidity → conservative
        # Tight spread (< 2%) → 1.0, wide spread (> 15%) → 0.3
        if request.spread < 0.02:
            return 1.0
        if request.spread > 0.15:
            return 0.3
        # Linear interpolation
        return 1.0 - 0.7 * ((request.spread - 0.02) / 0.13)
