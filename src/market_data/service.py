"""MarketDataService — orchestrator for market data access.

Wires together CLOB client, Gamma client, secondary source, and cache.
Implements the fallback cascade: CLOB → secondary → cache.
Emits health events on consecutive API failures.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import httpx

from config.settings import AppConfig
from logging_.logger import get_logger
from market_data.cache import MarketDataCache
from market_data.clob_client import ClobClient
from market_data.gamma_client import GammaClient
from market_data.rate_limiter import AsyncRateLimiter
from market_data.secondary_client import SubgraphClient
from market_data.types import (
    CacheStats,
    CachedMarketData,
    DataSource,
    FreshnessStatus,
    MarketInfo,
    MarketSnapshot,
)


class MarketDataService:
    """Single entry point for all market data access.

    Downstream consumers (Scanner, Eligibility) use this service
    rather than interacting with individual clients directly.
    """

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        api_config = config.polymarket_api
        scanner_config = config.scanner

        # Shared HTTP client for connection pooling
        self._http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                api_config.request_timeout, connect=api_config.connect_timeout
            ),
        )

        # Rate limiters (separate per API)
        self._gamma_limiter = AsyncRateLimiter(
            max_requests=api_config.gamma_max_requests_per_10s,
            window_seconds=10.0,
        )
        self._clob_limiter = AsyncRateLimiter(
            max_requests=api_config.clob_max_requests_per_10s,
            window_seconds=10.0,
        )

        # Clients
        self._gamma = GammaClient(
            config=api_config,
            rate_limiter=self._gamma_limiter,
            http_client=self._http_client,
        )
        self._clob = ClobClient(
            config=api_config,
            rate_limiter=self._clob_limiter,
            http_client=self._http_client,
        )
        self._secondary = SubgraphClient(
            config=api_config,
            http_client=self._http_client,
        )

        # Cache
        self._cache = MarketDataCache(
            cache_depth_hours=scanner_config.cache_depth_hours,
            freshness_threshold_seconds=scanner_config.freshness_threshold_seconds,
        )

        # Per-market failure tracking
        self._consecutive_failures: dict[str, int] = {}
        self._failure_threshold = api_config.consecutive_failure_threshold

        # Token ID → condition ID mapping (populated by discover_markets)
        self._token_to_condition: dict[str, str] = {}

        self._log = get_logger(component="market_data_service")

    async def start(self) -> None:
        """Initialize the service. Call once at startup."""
        self._log.info("market_data_service_starting")

    async def stop(self) -> None:
        """Shut down the service and release resources."""
        stats = await self._cache.stats()
        self._log.info(
            "market_data_service_stopping",
            cache_markets=stats.market_count,
            cache_entries=stats.total_entries,
            cache_hit_rate=stats.hit_rate,
        )
        await self._http_client.aclose()

    # --- Market Discovery ---

    async def discover_markets(self) -> list[MarketInfo]:
        """Fetch all active markets from the Gamma API.

        Also builds the token_id → condition_id mapping needed for
        secondary source fallback.
        """
        markets = await self._gamma.fetch_all_active_markets()

        for m in markets:
            if m.condition_id:
                for tid in m.token_ids:
                    self._token_to_condition[tid] = m.condition_id

        self._log.info(
            "market_discovery_complete",
            markets_found=len(markets),
            token_mappings=len(self._token_to_condition),
        )
        return markets

    # --- Market Snapshot Polling ---

    async def poll_market(self, token_id: str) -> CachedMarketData | None:
        """Poll a single market with fallback cascade.

        1. Try CLOB API → success → cache + return LIVE
        2. On failure → try secondary source → return SECONDARY
        3. On failure → serve from cache → return CACHE
        4. If cache empty → return None
        """
        # Attempt 1: CLOB API (primary)
        try:
            snapshot = await self._clob.fetch_market_snapshot(token_id)
            self._reset_failures(token_id)
            await self._cache.put(token_id, snapshot)

            return CachedMarketData(
                snapshot=snapshot,
                source=DataSource.LIVE,
                freshness=FreshnessStatus.FRESH,
                cache_age_seconds=0.0,
                cached_at=datetime.now(tz=UTC),
            )
        except Exception as exc:
            self._record_failure(token_id, exc)

        # Attempt 2: Secondary source (subgraph)
        condition_id = self._token_to_condition.get(token_id)
        if condition_id:
            try:
                price = await self._secondary.fetch_price(condition_id)
                if price is not None:
                    snapshot = MarketSnapshot(
                        token_id=token_id,
                        price=price,
                        mid_price=price,
                        polled_at=datetime.now(tz=UTC),
                    )
                    await self._cache.put(token_id, snapshot)

                    return CachedMarketData(
                        snapshot=snapshot,
                        source=DataSource.SECONDARY,
                        freshness=FreshnessStatus.FRESH,
                        cache_age_seconds=0.0,
                        cached_at=datetime.now(tz=UTC),
                    )
            except Exception:
                self._log.warning(
                    "secondary_source_failed", token_id=token_id
                )

        # Attempt 3: Cache fallback
        cached = await self._cache.get(token_id)
        if cached is not None:
            self._log.info(
                "serving_from_cache",
                token_id=token_id,
                cache_age=cached.cache_age_seconds,
                freshness=cached.freshness.value,
            )
            return cached

        # No data available at all
        self._log.error(
            "no_data_available",
            token_id=token_id,
            consecutive_failures=self._consecutive_failures.get(token_id, 0),
        )
        return None

    async def poll_batch(
        self, token_ids: list[str], *, max_concurrency: int = 10
    ) -> dict[str, CachedMarketData]:
        """Poll multiple markets concurrently with fallback cascade.

        Returns results keyed by token_id. Markets with no data are omitted.
        """
        semaphore = asyncio.Semaphore(max_concurrency)
        results: dict[str, CachedMarketData] = {}

        async def _poll_one(tid: str) -> None:
            async with semaphore:
                result = await self.poll_market(tid)
                if result is not None:
                    results[tid] = result

        await asyncio.gather(*[_poll_one(tid) for tid in token_ids])

        self._log.info(
            "batch_poll_complete",
            requested=len(token_ids),
            succeeded=len(results),
        )
        return results

    # --- Cache Access ---

    async def get_cached(self, token_id: str) -> CachedMarketData | None:
        """Read from cache without making any API calls."""
        return await self._cache.get(token_id)

    async def get_cache_stats(self) -> CacheStats:
        """Return cache health statistics."""
        return await self._cache.stats()

    def get_cache_stats_snapshot(self) -> CacheStats:
        """Return an immediate cache snapshot for synchronous dashboard sync."""
        return self._cache.snapshot_stats()

    async def run_eviction(self) -> int:
        """Evict expired cache entries. Call periodically."""
        evicted = await self._cache.evict_expired()
        if evicted > 0:
            self._log.info("cache_eviction", entries_evicted=evicted)
        return evicted

    # --- Failure Tracking ---

    def _reset_failures(self, token_id: str) -> None:
        """Reset failure counter on successful poll."""
        if token_id in self._consecutive_failures:
            if self._consecutive_failures[token_id] >= self._failure_threshold:
                self._log.info("api_recovered", token_id=token_id)
            del self._consecutive_failures[token_id]

    def _record_failure(self, token_id: str, exc: Exception) -> None:
        """Increment failure counter and emit health events at thresholds."""
        count = self._consecutive_failures.get(token_id, 0) + 1
        self._consecutive_failures[token_id] = count

        self._log.warning(
            "clob_api_failure",
            token_id=token_id,
            consecutive_failures=count,
            error=str(exc),
        )

        # Emit health event at threshold and at powers of 2 thereafter
        if count == self._failure_threshold or (
            count > self._failure_threshold
            and count & (count - 1) == 0  # power of 2
        ):
            self._log.error(
                "health_event_api_failure",
                token_id=token_id,
                consecutive_failures=count,
                threshold=self._failure_threshold,
            )

    def get_failure_count(self, token_id: str) -> int:
        """Get the current consecutive failure count for a market."""
        return self._consecutive_failures.get(token_id, 0)

    def get_failure_threshold(self) -> int:
        """Get the consecutive failure threshold for eviction decisions."""
        return self._failure_threshold
