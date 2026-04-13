"""Tests for the in-memory market data cache."""

from datetime import UTC, datetime, timedelta

from market_data.cache import MarketDataCache
from market_data.types import FreshnessStatus, MarketSnapshot


def _make_snapshot(
    token_id: str = "tok-1",
    price: float = 0.55,
    polled_at: datetime | None = None,
) -> MarketSnapshot:
    return MarketSnapshot(
        token_id=token_id,
        price=price,
        polled_at=polled_at or datetime.now(tz=UTC),
    )


async def test_put_and_get():
    cache = MarketDataCache(cache_depth_hours=4, freshness_threshold_seconds=180)
    snap = _make_snapshot()

    await cache.put("tok-1", snap)
    result = await cache.get("tok-1")

    assert result is not None
    assert result.snapshot.price == 0.55
    assert result.freshness == FreshnessStatus.FRESH


async def test_get_missing_returns_none():
    cache = MarketDataCache()
    result = await cache.get("nonexistent")
    assert result is None


async def test_freshness_stale():
    cache = MarketDataCache(freshness_threshold_seconds=60)

    old_time = datetime.now(tz=UTC) - timedelta(seconds=120)
    snap = _make_snapshot(polled_at=old_time)

    await cache.put("tok-1", snap)
    result = await cache.get("tok-1")

    assert result is not None
    assert result.freshness == FreshnessStatus.STALE


async def test_freshness_fresh():
    cache = MarketDataCache(freshness_threshold_seconds=300)
    snap = _make_snapshot()

    await cache.put("tok-1", snap)
    result = await cache.get("tok-1")

    assert result is not None
    assert result.freshness == FreshnessStatus.FRESH


async def test_evict_expired():
    cache = MarketDataCache(cache_depth_hours=1, freshness_threshold_seconds=60)

    # Insert old snapshot directly into the store to bypass put's auto-eviction
    old_snap = _make_snapshot(token_id="tok-old", polled_at=datetime.now(tz=UTC) - timedelta(hours=2))
    from collections import deque
    cache._store["tok-old"] = deque([old_snap])

    # Recent snapshot via normal put
    new_snap = _make_snapshot(token_id="tok-new")
    await cache.put("tok-new", new_snap)

    evicted = await cache.evict_expired()
    assert evicted == 1

    old_result = await cache.get("tok-old")
    new_result = await cache.get("tok-new")
    assert old_result is None
    assert new_result is not None


async def test_get_returns_latest():
    cache = MarketDataCache()

    snap1 = _make_snapshot(price=0.40, polled_at=datetime.now(tz=UTC) - timedelta(seconds=60))
    snap2 = _make_snapshot(price=0.55)

    await cache.put("tok-1", snap1)
    await cache.put("tok-1", snap2)

    result = await cache.get("tok-1")
    assert result is not None
    assert result.snapshot.price == 0.55


async def test_get_all_latest():
    cache = MarketDataCache()

    await cache.put("tok-1", _make_snapshot(token_id="tok-1", price=0.50))
    await cache.put("tok-2", _make_snapshot(token_id="tok-2", price=0.70))

    all_latest = await cache.get_all_latest()
    assert len(all_latest) == 2
    assert all_latest["tok-1"].snapshot.price == 0.50
    assert all_latest["tok-2"].snapshot.price == 0.70


async def test_invalidate():
    cache = MarketDataCache()
    await cache.put("tok-1", _make_snapshot())
    await cache.invalidate("tok-1")

    result = await cache.get("tok-1")
    assert result is None


async def test_get_history():
    cache = MarketDataCache()

    for i in range(5):
        snap = _make_snapshot(
            price=0.50 + i * 0.01,
            polled_at=datetime.now(tz=UTC) - timedelta(seconds=300 - i * 60),
        )
        await cache.put("tok-1", snap)

    history = await cache.get_history("tok-1")
    assert len(history) == 5

    # Filter by hours
    history_1h = await cache.get_history("tok-1", hours=0.05)  # ~3 minutes
    assert len(history_1h) <= 5


async def test_stats():
    cache = MarketDataCache()

    await cache.put("tok-1", _make_snapshot(token_id="tok-1"))
    await cache.put("tok-2", _make_snapshot(token_id="tok-2"))

    # Generate some hits and misses
    await cache.get("tok-1")  # hit
    await cache.get("tok-2")  # hit
    await cache.get("tok-3")  # miss

    stats = await cache.stats()
    assert stats.market_count == 2
    assert stats.total_entries == 2
    assert stats.hit_rate > 0
    assert stats.miss_rate > 0
    assert stats.avg_entries_per_market == 1.0


async def test_hit_miss_tracking():
    cache = MarketDataCache()

    # Misses
    await cache.get("missing-1")
    await cache.get("missing-2")

    stats = await cache.stats()
    assert stats.hit_rate == 0.0
    assert stats.miss_rate == 1.0

    # Add data and hit
    await cache.put("tok-1", _make_snapshot())
    await cache.get("tok-1")

    stats = await cache.stats()
    # 1 hit out of 3 total requests
    assert stats.hit_rate == 1 / 3
