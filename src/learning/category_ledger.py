"""Category Performance Ledger builder.

Builds the weekly per-category performance ledger with all required
fields per spec Section 15.8.

Fully deterministic (Tier D).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import structlog

from learning.types import CategoryLedgerEntry, CategoryLedgerReport

_log = structlog.get_logger(component="category_ledger")

# Default categories to track
DEFAULT_CATEGORIES = [
    "politics",
    "geopolitics",
    "technology",
    "science_health",
    "macro_policy",
    "sports",
]


class CategoryLedgerBuilder:
    """Builds the weekly Category Performance Ledger.

    Collects metrics from multiple sources and assembles a complete
    ledger with all required fields.

    Usage:
        builder = CategoryLedgerBuilder()
        builder.set_period(period_start, period_end)
        builder.add_trade_metrics("politics", trades=5, wins=3, ...)
        builder.add_cost_metrics("politics", inference_cost=1.50, ...)
        builder.add_brier_metrics("politics", brier=0.15, ...)
        report = builder.build()
    """

    def __init__(self) -> None:
        self._entries: dict[str, CategoryLedgerEntry] = {}
        self._period_start: datetime | None = None
        self._period_end: datetime | None = None

    def set_period(
        self,
        period_start: datetime,
        period_end: datetime | None = None,
    ) -> None:
        """Set the reporting period."""
        self._period_start = period_start
        self._period_end = period_end or datetime.now(tz=UTC)

        # Initialize entries for all categories
        for cat in DEFAULT_CATEGORIES:
            if cat not in self._entries:
                self._entries[cat] = CategoryLedgerEntry(
                    category=cat,
                    period_start=self._period_start,
                    period_end=self._period_end,
                )

    def add_trade_metrics(
        self,
        category: str,
        *,
        trades_count: int = 0,
        wins: int = 0,
        gross_pnl: float = 0.0,
        net_pnl: float = 0.0,
        average_edge: float | None = None,
        average_holding_hours: float | None = None,
    ) -> None:
        """Add trade performance metrics for a category."""
        entry = self._get_entry(category)
        entry.trades_count = trades_count
        entry.win_rate = wins / trades_count if trades_count > 0 else None
        entry.gross_pnl = gross_pnl
        entry.net_pnl = net_pnl
        entry.average_edge = average_edge
        entry.average_holding_hours = average_holding_hours

    def add_cost_metrics(
        self,
        category: str,
        *,
        inference_cost_usd: float = 0.0,
        cost_of_selectivity: float | None = None,
        slippage_ratio: float | None = None,
        entry_impact_pct: float | None = None,
    ) -> None:
        """Add cost and friction metrics for a category."""
        entry = self._get_entry(category)
        entry.inference_cost_usd = inference_cost_usd
        entry.cost_of_selectivity = cost_of_selectivity
        entry.slippage_ratio = slippage_ratio
        entry.entry_impact_pct = entry_impact_pct

    def add_quality_metrics(
        self,
        category: str,
        *,
        rejection_rate: float | None = None,
        no_trade_rate: float | None = None,
        brier_score: float | None = None,
        system_vs_market_brier: float | None = None,
    ) -> None:
        """Add quality and calibration metrics for a category."""
        entry = self._get_entry(category)
        entry.rejection_rate = rejection_rate
        entry.no_trade_rate = no_trade_rate
        entry.brier_score = brier_score
        entry.system_vs_market_brier = system_vs_market_brier

    def add_exit_distribution(
        self,
        category: str,
        distribution: dict[str, int],
    ) -> None:
        """Add exit classification distribution for a category."""
        entry = self._get_entry(category)
        entry.exit_distribution = distribution

    def build(self) -> CategoryLedgerReport:
        """Build the complete category performance ledger report."""
        if self._period_start is None:
            now = datetime.now(tz=UTC)
            self._period_start = now - timedelta(days=7)
            self._period_end = now

        report = CategoryLedgerReport(
            entries=list(self._entries.values()),
            period_start=self._period_start,
            period_end=self._period_end,
        )

        _log.info(
            "category_ledger_built",
            categories=len(report.entries),
            total_trades=report.total_trades,
            total_pnl=round(report.total_pnl, 4),
            total_cost=round(report.total_cost, 4),
        )

        return report

    # --- Private ---

    def _get_entry(self, category: str) -> CategoryLedgerEntry:
        """Get or create a ledger entry for a category."""
        if category not in self._entries:
            self._entries[category] = CategoryLedgerEntry(
                category=category,
                period_start=self._period_start or datetime.now(tz=UTC),
                period_end=self._period_end or datetime.now(tz=UTC),
            )
        return self._entries[category]
