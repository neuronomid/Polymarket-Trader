"""Slippage Tracker — Tier D deterministic.

Records realized slippage per order and checks whether friction
model recalibration is needed.

From spec Section 12.5:
- estimated_slippage_bps: pre-trade estimate
- realized_slippage_bps: actual fill vs mid-price at submission
- slippage_ratio: realized / estimated
- If ratio > 1.5x across last 20 trades → recalibrate friction model

No LLM calls permitted. Fully deterministic (Tier D, Cost Class Z).
"""

from __future__ import annotations

from collections import deque
from datetime import UTC, datetime

import structlog

from execution.types import SlippageRecord

_log = structlog.get_logger(component="slippage_tracker")

# Default thresholds
_DEFAULT_RECALIBRATION_RATIO = 1.5
_DEFAULT_RECALIBRATION_WINDOW = 20


class SlippageTracker:
    """Tracks realized vs estimated slippage across trades.

    Maintains a rolling window of recent slippage records and
    checks whether friction model parameters need recalibration.

    Usage:
        tracker = SlippageTracker()
        record = tracker.record(
            order_id="order-1",
            position_id="pos-1",
            estimated_slippage_bps=5.0,
            realized_slippage_bps=8.0,
            order_size_usd=500.0,
            mid_price_at_submission=0.55,
            fill_price=0.5505,
        )
        if tracker.needs_recalibration():
            # trigger friction model recalibration
            pass
    """

    def __init__(
        self,
        *,
        recalibration_ratio: float = _DEFAULT_RECALIBRATION_RATIO,
        window_size: int = _DEFAULT_RECALIBRATION_WINDOW,
    ) -> None:
        self._recalibration_ratio = recalibration_ratio
        self._window_size = window_size
        self._recent_records: deque[SlippageRecord] = deque(maxlen=window_size)
        self._all_records: list[SlippageRecord] = []

    def record(
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
        """Record a realized slippage measurement.

        Args:
            order_id: Order identifier.
            position_id: Position identifier.
            estimated_slippage_bps: Pre-trade slippage estimate.
            realized_slippage_bps: Actual slippage (fill vs mid-price).
            order_size_usd: Size of the order in USD.
            mid_price_at_submission: Mid-price at order submission time.
            fill_price: Actual fill price.
            liquidity_relative_size_pct: Order as % of visible depth.

        Returns:
            SlippageRecord with computed ratio.
        """
        # Compute slippage ratio
        if estimated_slippage_bps > 0:
            ratio = realized_slippage_bps / estimated_slippage_bps
        elif realized_slippage_bps > 0:
            ratio = float("inf")
        else:
            ratio = 1.0

        record = SlippageRecord(
            order_id=order_id,
            position_id=position_id,
            estimated_slippage_bps=estimated_slippage_bps,
            realized_slippage_bps=realized_slippage_bps,
            slippage_ratio=round(ratio, 4),
            order_size_usd=order_size_usd,
            mid_price_at_submission=mid_price_at_submission,
            fill_price=fill_price,
            liquidity_relative_size_pct=liquidity_relative_size_pct,
        )

        self._recent_records.append(record)
        self._all_records.append(record)

        _log.info(
            "slippage_recorded",
            order_id=order_id,
            estimated_bps=estimated_slippage_bps,
            realized_bps=realized_slippage_bps,
            ratio=record.slippage_ratio,
            window_size=len(self._recent_records),
        )

        return record

    def needs_recalibration(self) -> bool:
        """Check if friction model needs recalibration.

        Returns True if the mean slippage ratio across the last
        N trades exceeds the recalibration threshold.
        """
        if len(self._recent_records) < self._window_size:
            return False

        mean_ratio = self.mean_slippage_ratio()
        if mean_ratio is None:
            return False

        return mean_ratio > self._recalibration_ratio

    def mean_slippage_ratio(self) -> float | None:
        """Compute mean slippage ratio across the recent window."""
        if not self._recent_records:
            return None

        ratios = [
            r.slippage_ratio
            for r in self._recent_records
            if r.slippage_ratio != float("inf")
        ]
        if not ratios:
            return None

        return sum(ratios) / len(ratios)

    def record_count(self) -> int:
        """Total number of slippage records."""
        return len(self._all_records)

    def recent_count(self) -> int:
        """Number of records in the recent window."""
        return len(self._recent_records)

    @property
    def recent_records(self) -> list[SlippageRecord]:
        """Get recent slippage records."""
        return list(self._recent_records)

    @property
    def all_records(self) -> list[SlippageRecord]:
        """Get all slippage records."""
        return list(self._all_records)

    @staticmethod
    def compute_realized_slippage_bps(
        mid_price: float,
        fill_price: float,
        side: str = "buy",
    ) -> float:
        """Compute realized slippage in basis points.

        For buys: slippage = (fill_price - mid_price) / mid_price * 10000
        For sells: slippage = (mid_price - fill_price) / mid_price * 10000

        Args:
            mid_price: Mid-price at order submission.
            fill_price: Actual fill price.
            side: "buy" or "sell".

        Returns:
            Realized slippage in basis points (positive = unfavorable).
        """
        if mid_price <= 0:
            return 0.0

        if side == "buy":
            slippage = (fill_price - mid_price) / mid_price * 10_000
        else:
            slippage = (mid_price - fill_price) / mid_price * 10_000

        return round(max(0.0, slippage), 2)
