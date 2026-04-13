"""Tests for MarketDataService — integration tests with mocked clients.

Tests the fallback cascade: CLOB → secondary → cache.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from config.settings import AppConfig
from market_data.service import MarketDataService
from market_data.types import DataSource, FreshnessStatus, MarketSnapshot


@pytest.fixture
def config():
    """Minimal config for testing."""
    return AppConfig()


@pytest.fixture
def service(config):
    """MarketDataService with mocked HTTP transport."""
    svc = MarketDataService(config)
    return svc


async def test_poll_market_live_success(service):
    """Successful CLOB fetch returns LIVE source."""
    snapshot = MarketSnapshot(
        token_id="tok-1",
        price=0.55,
        best_bid=0.50,
        best_ask=0.60,
        spread=0.10,
        mid_price=0.55,
    )

    with patch.object(service._clob, "fetch_market_snapshot", new_callable=AsyncMock) as mock_clob:
        mock_clob.return_value = snapshot
        result = await service.poll_market("tok-1")

    assert result is not None
    assert result.source == DataSource.LIVE
    assert result.freshness == FreshnessStatus.FRESH
    assert result.snapshot.price == 0.55


async def test_poll_market_clob_fails_secondary_succeeds(service):
    """When CLOB fails, secondary source should be used."""
    # Set up token → condition mapping
    service._token_to_condition["tok-1"] = "cond-1"

    with (
        patch.object(
            service._clob, "fetch_market_snapshot", new_callable=AsyncMock,
            side_effect=httpx.ConnectError("fail"),
        ),
        patch.object(
            service._secondary, "fetch_price", new_callable=AsyncMock,
            return_value=0.55,
        ),
    ):
        result = await service.poll_market("tok-1")

    assert result is not None
    assert result.source == DataSource.SECONDARY
    assert result.snapshot.price == 0.55


async def test_poll_market_all_fail_serves_cache(service):
    """When both CLOB and secondary fail, cache should be served."""
    # Pre-populate cache
    cached_snap = MarketSnapshot(token_id="tok-1", price=0.50)
    await service._cache.put("tok-1", cached_snap)

    service._token_to_condition["tok-1"] = "cond-1"

    with (
        patch.object(
            service._clob, "fetch_market_snapshot", new_callable=AsyncMock,
            side_effect=httpx.ConnectError("fail"),
        ),
        patch.object(
            service._secondary, "fetch_price", new_callable=AsyncMock,
            side_effect=Exception("secondary down"),
        ),
    ):
        result = await service.poll_market("tok-1")

    assert result is not None
    assert result.source == DataSource.CACHE
    assert result.snapshot.price == 0.50


async def test_poll_market_all_fail_no_cache():
    """When everything fails and cache is empty, returns None."""
    config = AppConfig()
    service = MarketDataService(config)

    with patch.object(
        service._clob, "fetch_market_snapshot", new_callable=AsyncMock,
        side_effect=httpx.ConnectError("fail"),
    ):
        result = await service.poll_market("tok-1")

    assert result is None


async def test_failure_counter_increments(service):
    """Consecutive failures should be tracked per market."""
    with patch.object(
        service._clob, "fetch_market_snapshot", new_callable=AsyncMock,
        side_effect=httpx.ConnectError("fail"),
    ):
        await service.poll_market("tok-1")
        assert service.get_failure_count("tok-1") == 1

        await service.poll_market("tok-1")
        assert service.get_failure_count("tok-1") == 2


async def test_failure_counter_resets_on_success(service):
    """Success should reset the failure counter."""
    # Fail twice
    with patch.object(
        service._clob, "fetch_market_snapshot", new_callable=AsyncMock,
        side_effect=httpx.ConnectError("fail"),
    ):
        await service.poll_market("tok-1")
        await service.poll_market("tok-1")

    assert service.get_failure_count("tok-1") == 2

    # Succeed
    snapshot = MarketSnapshot(token_id="tok-1", price=0.55)
    with patch.object(
        service._clob, "fetch_market_snapshot", new_callable=AsyncMock,
        return_value=snapshot,
    ):
        await service.poll_market("tok-1")

    assert service.get_failure_count("tok-1") == 0


async def test_poll_batch(service):
    """Batch polling should return results for all successful tokens."""
    snapshot = MarketSnapshot(token_id="tok-1", price=0.55)

    with patch.object(
        service._clob, "fetch_market_snapshot", new_callable=AsyncMock,
        return_value=snapshot,
    ):
        results = await service.poll_batch(["tok-1", "tok-2", "tok-3"])

    assert len(results) == 3


async def test_get_cached(service):
    """get_cached should return data from cache without API calls."""
    snap = MarketSnapshot(token_id="tok-1", price=0.55)
    await service._cache.put("tok-1", snap)

    result = await service.get_cached("tok-1")
    assert result is not None
    assert result.snapshot.price == 0.55


async def test_get_cached_miss(service):
    result = await service.get_cached("nonexistent")
    assert result is None


async def test_discover_markets(service):
    """discover_markets should populate token-to-condition mapping."""
    from market_data.types import MarketInfo

    markets = [
        MarketInfo(
            market_id="m-1",
            condition_id="cond-1",
            token_ids=["tok-yes", "tok-no"],
            title="Test",
        ),
    ]

    with patch.object(
        service._gamma, "fetch_all_active_markets", new_callable=AsyncMock,
        return_value=markets,
    ):
        result = await service.discover_markets()

    assert len(result) == 1
    assert service._token_to_condition["tok-yes"] == "cond-1"
    assert service._token_to_condition["tok-no"] == "cond-1"


async def test_run_eviction(service):
    """Eviction should remove expired cache entries."""
    from collections import deque

    old_snap = MarketSnapshot(
        token_id="tok-old",
        price=0.50,
        polled_at=datetime.now(tz=UTC) - timedelta(hours=10),
    )
    # Insert directly to bypass put's auto-eviction
    service._cache._store["tok-old"] = deque([old_snap])

    evicted = await service.run_eviction()
    assert evicted == 1


async def test_get_cache_stats(service):
    stats = await service.get_cache_stats()
    assert stats.market_count == 0
