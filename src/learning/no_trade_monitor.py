"""No-trade rate monitoring.

Tracks the ratio of investigation runs that end with no-trade vs
those that produce candidates. Neither extreme is desirable:
- Low no-trade rate → potential quality erosion (taking weak trades)
- High no-trade rate → potential over-filtering (missing valid opportunities)

Per spec Section 15.12: Not a failure metric. Both conditions flagged.
Tracked per run and rolling.

Fully deterministic (Tier D).
"""

from __future__ import annotations

from collections import deque
from datetime import UTC, date, datetime

import structlog

from learning.types import NoTradeRateMetrics, NoTradeRateSignal

_log = structlog.get_logger(component="no_trade_monitor")

# Default thresholds — operator can adjust via config
LOW_RATE_THRESHOLD = 0.30    # below 30% no-trade → quality concern
HIGH_RATE_THRESHOLD = 0.90   # above 90% no-trade → over-filtering concern


class _RunRecord:
    """Single investigation run record for no-trade tracking."""

    __slots__ = ("record_date", "had_no_trade")

    def __init__(self, record_date: date, had_no_trade: bool) -> None:
        self.record_date = record_date
        self.had_no_trade = had_no_trade


class NoTradeMonitor:
    """Monitors no-trade rate across investigation runs.

    Usage:
        monitor = NoTradeMonitor()
        monitor.record_run(had_no_trade=True)
        monitor.record_run(had_no_trade=False)
        metrics = monitor.compute_metrics()
    """

    MAX_HISTORY = 200  # keep last N runs

    def __init__(
        self,
        *,
        low_threshold: float = LOW_RATE_THRESHOLD,
        high_threshold: float = HIGH_RATE_THRESHOLD,
    ) -> None:
        self._low_threshold = low_threshold
        self._high_threshold = high_threshold
        self._runs: deque[_RunRecord] = deque(maxlen=self.MAX_HISTORY)

    def record_run(
        self,
        had_no_trade: bool,
        record_date: date | None = None,
    ) -> None:
        """Record the outcome of an investigation run."""
        d = record_date or date.today()
        self._runs.append(_RunRecord(record_date=d, had_no_trade=had_no_trade))

        _log.debug(
            "no_trade_run_recorded",
            had_no_trade=had_no_trade,
            total_runs=len(self._runs),
        )

    def compute_metrics(self) -> NoTradeRateMetrics:
        """Compute current no-trade rate metrics with signal assessment."""
        all_runs = list(self._runs)
        total = len(all_runs)

        if total == 0:
            return NoTradeRateMetrics()

        no_trade_count = sum(1 for r in all_runs if r.had_no_trade)
        rate = no_trade_count / total

        # Rolling windows
        today = date.today()
        rolling_7d = self._compute_rolling_rate(all_runs, today, days=7)
        rolling_30d = self._compute_rolling_rate(all_runs, today, days=30)

        # Determine signal (use overall rate, supplemented by rolling)
        active_rate = rolling_7d if rolling_7d is not None else rate
        signal, reason = self._assess_signal(active_rate, total)

        if signal != NoTradeRateSignal.NORMAL:
            _log.warning(
                "no_trade_rate_signal",
                signal=signal.value,
                rate=round(active_rate, 4),
                reason=reason,
                total_runs=total,
            )

        return NoTradeRateMetrics(
            runs_total=total,
            runs_with_no_trade=no_trade_count,
            no_trade_rate=round(rate, 4),
            rolling_7d_rate=round(rolling_7d, 4) if rolling_7d is not None else None,
            rolling_30d_rate=round(rolling_30d, 4) if rolling_30d is not None else None,
            signal=signal,
            signal_reason=reason,
        )

    # --- Private ---

    @staticmethod
    def _compute_rolling_rate(
        runs: list[_RunRecord],
        today: date,
        *,
        days: int,
    ) -> float | None:
        """Compute no-trade rate over a rolling window of days."""
        from datetime import timedelta

        cutoff = today - timedelta(days=days)
        window = [r for r in runs if r.record_date >= cutoff]

        if not window:
            return None

        no_trade = sum(1 for r in window if r.had_no_trade)
        return no_trade / len(window)

    def _assess_signal(
        self,
        rate: float,
        total_runs: int,
    ) -> tuple[NoTradeRateSignal, str]:
        """Assess signal from no-trade rate."""
        # Need minimum runs for meaningful signal
        if total_runs < 10:
            return NoTradeRateSignal.NORMAL, "insufficient_data"

        if rate < self._low_threshold:
            return (
                NoTradeRateSignal.LOW_RATE_WARNING,
                f"No-trade rate {rate:.1%} below {self._low_threshold:.0%} — "
                "potential quality erosion, system may be accepting weak trades",
            )

        if rate > self._high_threshold:
            return (
                NoTradeRateSignal.HIGH_RATE_WARNING,
                f"No-trade rate {rate:.1%} above {self._high_threshold:.0%} — "
                "potential over-filtering, system may be missing valid opportunities",
            )

        return NoTradeRateSignal.NORMAL, ""
