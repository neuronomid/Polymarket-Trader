"""Entry Impact Calculator — Tier D deterministic.

Walks visible order book at top N levels, computes levels consumed
by a proposed order, and estimates mid-price movement in basis points.

This is a deterministic-only component (Tier D, Cost Class Z).
No LLM calls permitted.
"""

from __future__ import annotations

import structlog

from market_data.types import OrderBookLevel
from investigation.types import EntryImpactResult

_log = structlog.get_logger(component="entry_impact_calculator")


class EntryImpactCalculator:
    """Computes estimated entry price impact by walking the order book.

    Usage:
        calculator = EntryImpactCalculator()
        result = calculator.compute(
            ask_levels=ask_levels,
            order_size_usd=500.0,
        )
        print(f"Impact: {result.estimated_impact_bps:.1f} bps")
    """

    def compute(
        self,
        ask_levels: list[OrderBookLevel],
        order_size_usd: float,
    ) -> EntryImpactResult:
        """Compute entry impact by walking the order book.

        Args:
            ask_levels: Sorted ask levels (ascending by price) from the order book.
            order_size_usd: Proposed order size in USD.

        Returns:
            EntryImpactResult with estimated impact in basis points.
        """
        if not ask_levels or order_size_usd <= 0:
            return EntryImpactResult(
                estimated_impact_bps=0.0,
                levels_consumed=0,
                total_fill_size_usd=0.0,
            )

        reference_price = ask_levels[0].price
        if reference_price <= 0:
            return EntryImpactResult(
                estimated_impact_bps=0.0,
                levels_consumed=0,
                reference_price=0.0,
            )

        remaining = order_size_usd
        weighted_price_sum = 0.0
        filled_size = 0.0
        levels_consumed = 0

        for level in ask_levels:
            if level.price <= 0 or level.size <= 0:
                continue

            level_value_usd = level.price * level.size
            fill_at_level = min(remaining, level_value_usd)
            fill_size = fill_at_level / level.price

            weighted_price_sum += level.price * fill_size
            filled_size += fill_size
            remaining -= fill_at_level
            levels_consumed += 1

            if remaining <= 0:
                break

        if filled_size <= 0:
            return EntryImpactResult(
                estimated_impact_bps=0.0,
                levels_consumed=levels_consumed,
                reference_price=reference_price,
                remaining_unfilled_usd=remaining,
            )

        avg_fill_price = weighted_price_sum / filled_size
        impact_bps = max(0.0, (avg_fill_price - reference_price) / reference_price * 10_000)
        total_fill_usd = filled_size * avg_fill_price

        result = EntryImpactResult(
            estimated_impact_bps=round(impact_bps, 2),
            levels_consumed=levels_consumed,
            total_fill_size_usd=round(total_fill_usd, 4),
            avg_fill_price=round(avg_fill_price, 6),
            reference_price=reference_price,
            remaining_unfilled_usd=round(max(0.0, remaining), 4),
        )

        _log.debug(
            "entry_impact_computed",
            order_size_usd=order_size_usd,
            impact_bps=result.estimated_impact_bps,
            levels_consumed=result.levels_consumed,
            avg_fill=result.avg_fill_price,
            reference=result.reference_price,
        )

        return result

    def impact_as_edge_fraction(
        self,
        impact_bps: float,
        gross_edge: float,
    ) -> float:
        """Convert impact in bps to a fraction of gross edge.

        If impact fraction > 25%, the entry should be rejected or
        sized down per Risk Governor rules.

        Args:
            impact_bps: Entry impact in basis points.
            gross_edge: Expected gross edge as a fraction (e.g., 0.05 for 5%).

        Returns:
            Impact as a fraction of gross edge.
        """
        if gross_edge <= 0:
            return float("inf") if impact_bps > 0 else 0.0

        impact_fraction = (impact_bps / 10_000) / gross_edge
        return round(impact_fraction, 6)
