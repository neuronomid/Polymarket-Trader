"""Trigger scanner — async polling loop with degraded-mode handling.

The scanner is the event-driven core of the system. It:
1. Polls CLOB API at configured intervals
2. Stores results in the market data cache
3. Runs deterministic trigger detection on every poll
4. Manages degraded-mode escalation when the API is unavailable
5. Emits trigger events and health events

ALL logic is Tier D (deterministic). No LLM calls in the hot path.

Spec: Phase 5 Steps 1-6.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

from config.settings import AppConfig
from logging_.logger import get_logger
from market_data.service import MarketDataService
from market_data.types import CachedMarketData, DataSource, FreshnessStatus
from scanner.degraded_mode import DegradedModeManager
from scanner.health_monitor import ScannerHealthMonitor
from scanner.trigger_detector import TriggerDetector
from scanner.types import (
    DegradedModeLevel,
    MarketWatchEntry,
    TriggerBatch,
    TriggerEvent,
    TriggerThresholds,
)


class TriggerScanner:
    """Async trigger scanner loop.

    Watches eligible and held-position markets, detects triggers
    deterministically, and manages degraded-mode escalation.

    Usage:
        scanner = TriggerScanner(config, market_data_service)
        await scanner.start()
        # ...
        await scanner.stop()
    """

    def __init__(
        self,
        config: AppConfig,
        market_data_service: MarketDataService,
    ) -> None:
        self._config = config
        self._scanner_config = config.scanner
        self._market_data = market_data_service

        # Sub-components
        self._degraded_mode = DegradedModeManager(config.scanner)
        self._health_monitor = ScannerHealthMonitor(self._degraded_mode)
        self._trigger_detector = TriggerDetector(TriggerThresholds())

        # Watch list — markets being actively monitored
        self._watch_list: dict[str, MarketWatchEntry] = {}

        # State
        self._running = False
        self._scan_task: asyncio.Task | None = None
        self._eviction_task: asyncio.Task | None = None

        # Callback for trigger events (set by workflow layer)
        self._trigger_callback: callable | None = None

        self._log = get_logger(component="trigger_scanner")

    # --- Lifecycle ---

    async def start(self) -> None:
        """Start the scanner polling loop."""
        if self._running:
            self._log.warning("scanner_already_running")
            return

        self._running = True
        self._log.info(
            "scanner_starting",
            poll_interval=self._scanner_config.poll_interval_seconds,
            watch_list_size=len(self._watch_list),
        )

        self._scan_task = asyncio.create_task(self._scan_loop())
        self._eviction_task = asyncio.create_task(self._eviction_loop())

    async def stop(self) -> None:
        """Stop the scanner gracefully."""
        self._running = False
        self._log.info("scanner_stopping")

        for task in (self._scan_task, self._eviction_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        self._scan_task = None
        self._eviction_task = None

        health = self._health_monitor.get_health_status()
        self._log.info(
            "scanner_stopped",
            total_polls=health.total_polls,
            total_triggers=health.total_triggers_detected,
            final_degraded_level=health.degraded_mode_level.value,
        )

    # --- Watch List Management ---

    def add_to_watch_list(self, entry: MarketWatchEntry) -> None:
        """Add a market to the scanner watch list."""
        self._watch_list[entry.token_id] = entry
        self._log.info(
            "watch_list_add",
            market_id=entry.market_id,
            token_id=entry.token_id,
            is_held_position=entry.is_held_position,
        )

    def remove_from_watch_list(self, token_id: str) -> None:
        """Remove a market from the scanner watch list."""
        if token_id in self._watch_list:
            entry = self._watch_list.pop(token_id)
            self._log.info(
                "watch_list_remove",
                market_id=entry.market_id,
                token_id=token_id,
            )

    def update_watch_entry(self, token_id: str, **kwargs) -> None:
        """Update fields on an existing watch entry."""
        if token_id in self._watch_list:
            entry = self._watch_list[token_id]
            for key, value in kwargs.items():
                if hasattr(entry, key):
                    setattr(entry, key, value)

    def set_watch_list(self, entries: list[MarketWatchEntry]) -> None:
        """Replace the entire watch list."""
        self._watch_list = {e.token_id: e for e in entries}
        self._log.info("watch_list_set", count=len(self._watch_list))

    def get_watch_list(self) -> list[MarketWatchEntry]:
        """Get a copy of the current watch list."""
        return list(self._watch_list.values())

    def get_watch_entry(self, token_id: str) -> MarketWatchEntry | None:
        """Fetch a single watch entry by token ID."""
        return self._watch_list.get(token_id)

    def get_watch_entry_by_market(self, market_id: str) -> MarketWatchEntry | None:
        """Fetch the first watch entry matching a market ID."""
        for entry in self._watch_list.values():
            if entry.market_id == market_id:
                return entry
        return None

    # --- Callback ---

    def set_trigger_callback(self, callback: callable) -> None:
        """Set a callback function for trigger events.

        The callback receives a TriggerBatch with all triggers from a scan cycle.
        """
        self._trigger_callback = callback

    # --- Health ---

    @property
    def health_monitor(self) -> ScannerHealthMonitor:
        return self._health_monitor

    @property
    def degraded_mode(self) -> DegradedModeManager:
        return self._degraded_mode

    @property
    def is_running(self) -> bool:
        return self._running

    # --- Core Scan Logic ---

    async def scan_once(self) -> TriggerBatch:
        """Execute a single scan cycle across all watched markets.

        This is the core method that can also be called directly for testing
        or manual triggers (outside the polling loop).
        """
        batch_id = str(uuid.uuid4())[:8]
        token_ids = list(self._watch_list.keys())

        if not token_ids:
            return TriggerBatch(batch_id=batch_id, markets_scanned=0)

        self._log.debug(
            "scan_cycle_start",
            batch_id=batch_id,
            markets=len(token_ids),
        )

        # Poll all watched markets
        try:
            poll_results = await self._market_data.poll_batch(token_ids)
        except Exception as exc:
            self._log.error(
                "scan_cycle_poll_failed",
                batch_id=batch_id,
                error=str(exc),
            )
            self._health_monitor.record_poll_failure(str(exc))
            return TriggerBatch(
                batch_id=batch_id,
                markets_scanned=0,
                data_source="failed",
                degraded_mode_level=self._degraded_mode.current_level,
            )

        # Determine poll quality — only LIVE+FRESH data counts as true success
        has_live_fresh = any(
            r.source == DataSource.LIVE and r.freshness == FreshnessStatus.FRESH
            for r in poll_results.values()
        )
        if has_live_fresh:
            self._health_monitor.record_poll_success(
                triggers_detected=0  # Updated after detection
            )
        elif poll_results:
            # Data returned but from cache/secondary — not a full recovery
            self._health_monitor._total_polls += 1
        else:
            self._health_monitor.record_poll_failure("No poll results returned")

        # Run trigger detection on each market
        all_triggers: list[TriggerEvent] = []
        for token_id, cached_data in poll_results.items():
            watch_entry = self._watch_list.get(token_id)
            if watch_entry is None:
                continue

            # Skip discovery triggers during degraded mode
            if (
                self._degraded_mode.is_degraded
                and cached_data.freshness != FreshnessStatus.FRESH
            ):
                # Still allow position-specific triggers, but flag stale data
                if not watch_entry.is_held_position:
                    continue

            triggers = self._trigger_detector.detect_triggers(watch_entry, cached_data)

            # Filter out discovery triggers during degraded mode
            if not self._degraded_mode.discovery_triggers_allowed:
                triggers = [
                    t for t in triggers
                    if t.trigger_class != "discovery"
                    or watch_entry.is_held_position
                ]

            # Tag triggers with stale data flag if degraded
            if self._degraded_mode.stale_data_flag:
                for t in triggers:
                    t.escalation_status = (
                        f"stale_data_{t.escalation_status}"
                        if t.escalation_status
                        else "stale_data"
                    )

            all_triggers.extend(triggers)

            # Update watch entry with latest data
            self._update_watch_entry_from_data(token_id, cached_data)

        # Determine primary data source
        sources = {r.source for r in poll_results.values()}
        if DataSource.LIVE in sources:
            primary_source = "live"
        elif DataSource.SECONDARY in sources:
            primary_source = "secondary"
        elif DataSource.CACHE in sources:
            primary_source = "cache"
        else:
            primary_source = "unknown"

        batch = TriggerBatch(
            batch_id=batch_id,
            triggers=all_triggers,
            markets_scanned=len(poll_results),
            data_source=primary_source,
            degraded_mode_level=self._degraded_mode.current_level,
        )

        # Log trigger activity
        if all_triggers:
            self._log.info(
                "triggers_detected",
                batch_id=batch_id,
                total_triggers=len(all_triggers),
                actionable=len(batch.actionable_triggers),
                summary=batch.trigger_summary(),
            )
        else:
            self._log.debug(
                "no_triggers",
                batch_id=batch_id,
                markets_scanned=len(poll_results),
            )

        # Evict dead tokens that have exceeded the failure threshold
        failure_threshold = self._market_data.get_failure_threshold()
        dead_tokens = [
            tid for tid in list(self._watch_list.keys())
            if self._market_data.get_failure_count(tid) >= failure_threshold
        ]
        for tid in dead_tokens:
            self.remove_from_watch_list(tid)
            self._log.info("watch_list_evict_dead_token", token_id=tid, consecutive_failures=failure_threshold)

        # Invoke callback if set
        if self._trigger_callback and all_triggers:
            try:
                await self._trigger_callback(batch)
            except Exception as exc:
                self._log.error(
                    "trigger_callback_error",
                    batch_id=batch_id,
                    error=str(exc),
                )

        return batch

    def _update_watch_entry_from_data(
        self, token_id: str, data: CachedMarketData
    ) -> None:
        """Update a watch entry with the latest polled data."""
        entry = self._watch_list.get(token_id)
        if entry is None:
            return

        snapshot = data.snapshot
        entry.last_price = snapshot.mid_price or snapshot.price
        entry.last_spread = snapshot.spread
        entry.last_scanned_at = datetime.now(tz=UTC)

        # Update top-3 depth if available
        if snapshot.depth_levels:
            entry.last_depth_top3 = TriggerDetector._compute_top3_depth(
                snapshot.depth_levels
            )

    # --- Internal Loops ---

    async def _scan_loop(self) -> None:
        """Main scan loop — polls at configured interval."""
        self._log.info("scan_loop_started")

        while self._running:
            try:
                await self.scan_once()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self._log.error("scan_loop_error", error=str(exc))

            # Wait for next cycle
            try:
                await asyncio.sleep(self._scanner_config.poll_interval_seconds)
            except asyncio.CancelledError:
                break

        self._log.info("scan_loop_stopped")

    async def _eviction_loop(self) -> None:
        """Periodic cache eviction loop — runs every 5 minutes."""
        eviction_interval = 300  # 5 minutes

        while self._running:
            try:
                await asyncio.sleep(eviction_interval)
                evicted = await self._market_data.run_eviction()
                if evicted > 0:
                    self._log.debug("cache_eviction", entries_evicted=evicted)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self._log.warning("eviction_loop_error", error=str(exc))
