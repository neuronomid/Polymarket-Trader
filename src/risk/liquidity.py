"""Liquidity-relative sizing — depth and entry impact enforcement.

Hard cap: no order > 12% of visible depth at top N levels.
Entry impact: if estimated impact > 25% of gross edge → reduce or reject.

Fully deterministic (Tier D). No LLM calls.
"""

from __future__ import annotations

import structlog

from config.settings import RiskConfig
from market_data.types import OrderBookLevel
from risk.types import LiquidityCheck, SizingRequest


class LiquiditySizer:
    """Computes liquidity-relative order size limits.

    Uses order book depth data to enforce hard caps on order sizing
    and estimate entry price impact.
    """

    def __init__(self, config: RiskConfig) -> None:
        self._config = config
        self._log = structlog.get_logger(component="liquidity_sizer")

    def check(
        self,
        request: SizingRequest,
        ask_levels: list[OrderBookLevel] | None = None,
    ) -> LiquidityCheck:
        """Evaluate liquidity constraints for a candidate order.

        Args:
            request: The sizing request with visible_depth_usd and edge data.
            ask_levels: Sorted ask levels (ascending by price) for impact estimation.
        """
        depth_usd = request.visible_depth_usd
        max_fraction = self._config.max_order_depth_fraction

        # Hard cap from depth
        max_order_usd = depth_usd * max_fraction if depth_usd > 0 else 0.0

        passes_depth = depth_usd > 0
        depth_reason = ""
        if not passes_depth:
            depth_reason = "No visible depth data available"

        # Entry impact estimation
        impact_bps = 0.0
        impact_edge_fraction = 0.0
        passes_impact = True

        if ask_levels and request.best_ask is not None and max_order_usd > 0:
            impact_bps = self._estimate_impact_bps(ask_levels, max_order_usd)
            if request.gross_edge > 0:
                # Convert impact bps to fraction of edge
                # impact_bps is in basis points (1bp = 0.01%)
                impact_as_fraction = impact_bps / 10000.0
                impact_edge_fraction = impact_as_fraction / request.gross_edge
                if impact_edge_fraction > self._config.max_entry_impact_edge_fraction:
                    passes_impact = False

        reason_parts = []
        if not passes_depth:
            reason_parts.append(depth_reason)
        if not passes_impact:
            reason_parts.append(
                f"Entry impact {impact_bps:.1f}bps = {impact_edge_fraction:.1%} of gross edge "
                f"(max {self._config.max_entry_impact_edge_fraction:.0%})"
            )

        return LiquidityCheck(
            max_order_usd=max_order_usd,
            depth_at_top_levels_usd=depth_usd,
            entry_impact_bps=impact_bps,
            entry_impact_edge_fraction=impact_edge_fraction,
            passes_depth_check=passes_depth,
            passes_impact_check=passes_impact,
            reason="; ".join(reason_parts) if reason_parts else "Liquidity checks passed",
        )

    def _estimate_impact_bps(
        self,
        ask_levels: list[OrderBookLevel],
        order_size_usd: float,
    ) -> float:
        """Estimate price impact in basis points by walking the order book.

        Walks ask levels consuming liquidity until order is filled.
        Returns estimated mid-price movement in basis points.
        """
        if not ask_levels:
            return 0.0

        reference_price = ask_levels[0].price
        if reference_price <= 0:
            return 0.0

        remaining = order_size_usd
        weighted_price_sum = 0.0
        filled_size = 0.0

        for level in ask_levels:
            level_value_usd = level.price * level.size
            fill_at_level = min(remaining, level_value_usd)
            fill_size = fill_at_level / level.price if level.price > 0 else 0.0

            weighted_price_sum += level.price * fill_size
            filled_size += fill_size
            remaining -= fill_at_level

            if remaining <= 0:
                break

        if filled_size <= 0:
            return 0.0

        avg_fill_price = weighted_price_sum / filled_size
        impact = (avg_fill_price - reference_price) / reference_price * 10000.0
        return max(0.0, impact)
