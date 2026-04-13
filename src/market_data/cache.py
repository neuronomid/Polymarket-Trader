"""In-memory market data cache with freshness tracking and eviction.

Stores MarketSnapshot entries per market in time-ordered deques.
Serves stale data when the API is down, with age and freshness metadata.
"""

from __future__ import annotations

import asyncio
from collections import deque
from datetime import UTC, datetime

from market_data.types import (
    CacheStats,
    CachedMarketData,
    DataSource,
    FreshnessStatus,
    MarketSnapshot,
)


class MarketDataCache:
    """In-memory CLOB data cache.

    Each market's snapshots are stored in a deque, ordered by polled_at.
    Cache depth and freshness are configurable.
    """

    def __init__(
        self,
        cache_depth_hours: int = 4,
        freshness_threshold_seconds: int = 180,
    ) -> None:
        self._cache_depth_seconds = cache_depth_hours * 3600
        self._freshness_threshold_seconds = freshness_threshold_seconds
        self._store: dict[str, deque[MarketSnapshot]] = {}
        self._hits = 0
        self._misses = 0
        self._lock = asyncio.Lock()

    def _freshness(self, age_seconds: float) -> FreshnessStatus:
        """Classify freshness based on age."""
        if age_seconds < self._freshness_threshold_seconds:
            return FreshnessStatus.FRESH
        if age_seconds < self._cache_depth_seconds:
            return FreshnessStatus.STALE
        return FreshnessStatus.EXPIRED

    async def put(self, market_id: str, snapshot: MarketSnapshot) -> None:
        """Store a snapshot and evict expired entries for this market."""
        async with self._lock:
            if market_id not in self._store:
                self._store[market_id] = deque()
            self._store[market_id].append(snapshot)
            self._evict_market(market_id)

    async def get(self, market_id: str) -> CachedMarketData | None:
        """Get the most recent snapshot for a market with freshness metadata.

        Returns None only if no data exists at all for this market.
        """
        async with self._lock:
            snapshots = self._store.get(market_id)
            if not snapshots:
                self._misses += 1
                return None

            self._hits += 1
            latest = snapshots[-1]
            now = datetime.now(tz=UTC)
            age = (now - latest.polled_at).total_seconds()

            return CachedMarketData(
                snapshot=latest,
                source=DataSource.CACHE,
                freshness=self._freshness(age),
                cache_age_seconds=age,
                cached_at=now,
            )

    async def get_all_latest(self) -> dict[str, CachedMarketData]:
        """Get the latest snapshot for every cached market."""
        async with self._lock:
            result: dict[str, CachedMarketData] = {}
            now = datetime.now(tz=UTC)

            for market_id, snapshots in self._store.items():
                if not snapshots:
                    continue
                latest = snapshots[-1]
                age = (now - latest.polled_at).total_seconds()
                result[market_id] = CachedMarketData(
                    snapshot=latest,
                    source=DataSource.CACHE,
                    freshness=self._freshness(age),
                    cache_age_seconds=age,
                    cached_at=now,
                )

            return result

    async def evict_expired(self) -> int:
        """Remove all snapshots older than cache_depth across all markets.

        Returns the total number of entries evicted.
        """
        async with self._lock:
            total_evicted = 0
            empty_markets: list[str] = []

            for market_id in self._store:
                before = len(self._store[market_id])
                self._evict_market(market_id)
                after = len(self._store[market_id])
                total_evicted += before - after
                if after == 0:
                    empty_markets.append(market_id)

            for market_id in empty_markets:
                del self._store[market_id]

            return total_evicted

    def _evict_market(self, market_id: str) -> None:
        """Remove expired entries from a single market's deque (no lock)."""
        snapshots = self._store.get(market_id)
        if not snapshots:
            return
        cutoff = datetime.now(tz=UTC).timestamp() - self._cache_depth_seconds
        while snapshots and snapshots[0].polled_at.timestamp() < cutoff:
            snapshots.popleft()

    async def invalidate(self, market_id: str) -> None:
        """Remove all cached data for a market."""
        async with self._lock:
            self._store.pop(market_id, None)

    async def get_history(
        self, market_id: str, *, hours: float | None = None
    ) -> list[MarketSnapshot]:
        """Return time-ordered snapshot history for a market."""
        async with self._lock:
            snapshots = self._store.get(market_id)
            if not snapshots:
                return []

            if hours is None:
                return list(snapshots)

            cutoff = datetime.now(tz=UTC).timestamp() - (hours * 3600)
            return [s for s in snapshots if s.polled_at.timestamp() >= cutoff]

    async def stats(self) -> CacheStats:
        """Return cache health statistics."""
        async with self._lock:
            now = datetime.now(tz=UTC)
            total_entries = sum(len(d) for d in self._store.values())
            market_count = len(self._store)

            oldest_age: float | None = None
            newest_age: float | None = None

            for snapshots in self._store.values():
                if not snapshots:
                    continue
                oldest = (now - snapshots[0].polled_at).total_seconds()
                newest = (now - snapshots[-1].polled_at).total_seconds()
                if oldest_age is None or oldest > oldest_age:
                    oldest_age = oldest
                if newest_age is None or newest < newest_age:
                    newest_age = newest

            total_requests = self._hits + self._misses
            hit_rate = self._hits / total_requests if total_requests > 0 else 0.0
            miss_rate = self._misses / total_requests if total_requests > 0 else 0.0

            return CacheStats(
                market_count=market_count,
                total_entries=total_entries,
                hit_rate=hit_rate,
                miss_rate=miss_rate,
                oldest_entry_age_seconds=oldest_age,
                newest_entry_age_seconds=newest_age,
                avg_entries_per_market=(
                    total_entries / market_count if market_count > 0 else 0.0
                ),
            )
