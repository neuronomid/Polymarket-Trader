"""Cost-of-selectivity monitor.

Tracks the ratio of inference cost to trades entered (7-day rolling),
cost-to-edge ratio, and emits warnings when the ratio exceeds the target.
Fully deterministic (Tier D).
"""

from __future__ import annotations

from collections import deque
from datetime import UTC, date, datetime

import structlog

from config.settings import CostConfig
from cost.types import SelectivitySnapshot

_log = structlog.get_logger(component="selectivity_monitor")


class DailyRecord:
    """A single day's cost and trade data."""

    __slots__ = ("record_date", "inference_spend_usd", "trades_entered", "gross_edge_usd")

    def __init__(
        self,
        record_date: date,
        inference_spend_usd: float = 0.0,
        trades_entered: int = 0,
        gross_edge_usd: float = 0.0,
    ) -> None:
        self.record_date = record_date
        self.inference_spend_usd = inference_spend_usd
        self.trades_entered = trades_entered
        self.gross_edge_usd = gross_edge_usd


class SelectivityMonitor:
    """Tracks cost-of-selectivity over a 7-day rolling window.

    Usage:
        monitor = SelectivityMonitor(config)
        monitor.record_daily_spend(5.0)
        monitor.record_trade_entered()
        monitor.record_gross_edge(0.15)
        snapshot = monitor.compute_snapshot()
    """

    ROLLING_WINDOW_DAYS = 7

    def __init__(self, config: CostConfig) -> None:
        self._config = config
        self._history: deque[DailyRecord] = deque(maxlen=self.ROLLING_WINDOW_DAYS)
        self._today: DailyRecord | None = None

    # --- Day lifecycle ---

    def start_day(self, record_date: date | None = None) -> None:
        """Begin tracking for a new day. Pushes previous day into history."""
        today = record_date or date.today()

        if self._today is not None:
            self._history.append(self._today)

        self._today = DailyRecord(record_date=today)

    def load_history(self, records: list[SelectivitySnapshot]) -> None:
        """Load historical selectivity data from persistent storage."""
        self._history.clear()
        for r in records[-self.ROLLING_WINDOW_DAYS:]:
            self._history.append(
                DailyRecord(
                    record_date=r.record_date.date() if isinstance(r.record_date, datetime) else r.record_date,
                    inference_spend_usd=r.daily_inference_spend_usd,
                    trades_entered=r.trades_entered,
                )
            )

    # --- Recording ---

    def record_daily_spend(self, amount_usd: float) -> None:
        """Add inference spend for today."""
        self._ensure_today()
        self._today.inference_spend_usd += amount_usd

    def record_trade_entered(self, count: int = 1) -> None:
        """Record trades entered today."""
        self._ensure_today()
        self._today.trades_entered += count

    def record_gross_edge(self, edge_usd: float) -> None:
        """Record realized gross edge for today."""
        self._ensure_today()
        self._today.gross_edge_usd += edge_usd

    # --- Computation ---

    def compute_snapshot(self) -> SelectivitySnapshot:
        """Compute current cost-of-selectivity metrics.

        Returns a snapshot with 7-day rolling averages and warning status.
        """
        self._ensure_today()

        all_days = list(self._history) + [self._today]

        total_spend = sum(d.inference_spend_usd for d in all_days)
        total_trades = sum(d.trades_entered for d in all_days)
        total_edge = sum(d.gross_edge_usd for d in all_days)

        rolling_cost_per_trade = (
            total_spend / total_trades if total_trades > 0 else None
        )

        cost_to_edge = (
            total_spend / total_edge if total_edge > 0 else None
        )

        # Selectivity ratio = cost / edge (target is the configured threshold)
        rolling_selectivity = cost_to_edge

        warning = False
        if cost_to_edge is not None:
            warning = cost_to_edge > self._config.cost_of_selectivity_target_ratio

        if warning:
            _log.warning(
                "COST_SELECTIVITY_WARNING",
                cost_to_edge_ratio=round(cost_to_edge, 4) if cost_to_edge else None,
                target=self._config.cost_of_selectivity_target_ratio,
                rolling_7d_spend=round(total_spend, 4),
                rolling_7d_trades=total_trades,
            )

        snapshot = SelectivitySnapshot(
            record_date=datetime.combine(self._today.record_date, datetime.min.time(), tzinfo=UTC),
            daily_inference_spend_usd=round(self._today.inference_spend_usd, 6),
            trades_entered=self._today.trades_entered,
            rolling_7d_cost_per_trade=round(rolling_cost_per_trade, 6) if rolling_cost_per_trade is not None else None,
            cost_to_edge_ratio=round(cost_to_edge, 6) if cost_to_edge is not None else None,
            rolling_7d_selectivity_ratio=round(rolling_selectivity, 6) if rolling_selectivity is not None else None,
            warning_triggered=warning,
        )

        return snapshot

    def compute_opus_escalation_threshold(self, standard_minimum: float) -> float:
        """Compute adjusted Opus escalation threshold based on selectivity.

        Formula: standard_minimum * (1 + selectivity_ratio_excess / target_ratio)

        When cost-of-selectivity exceeds target, Opus requires higher
        minimum net-edge to justify the premium cost.
        """
        snapshot = self.compute_snapshot()
        target = self._config.cost_of_selectivity_target_ratio

        if snapshot.cost_to_edge_ratio is None or snapshot.cost_to_edge_ratio <= target:
            return standard_minimum

        excess = snapshot.cost_to_edge_ratio - target
        multiplier = 1.0 + (excess / target)

        adjusted = standard_minimum * multiplier
        _log.info(
            "opus_threshold_adjusted",
            standard=standard_minimum,
            adjusted=round(adjusted, 6),
            selectivity_ratio=round(snapshot.cost_to_edge_ratio, 4),
            multiplier=round(multiplier, 4),
        )
        return adjusted

    # --- Private ---

    def _ensure_today(self) -> None:
        if self._today is None:
            self.start_day()
