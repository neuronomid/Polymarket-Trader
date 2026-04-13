"""Tests for market data types."""

from datetime import UTC, datetime

from pytest import approx

from market_data.types import (
    CachedMarketData,
    CacheStats,
    DataSource,
    FreshnessStatus,
    MarketInfo,
    MarketSnapshot,
    OrderBookLevel,
    OrderBookSnapshot,
    _safe_float,
)


def test_order_book_level():
    level = OrderBookLevel(price=0.55, size=100.0)
    assert level.price == 0.55
    assert level.size == 100.0


def test_order_book_snapshot_from_raw_book():
    bids = [
        {"price": "0.50", "size": "200"},
        {"price": "0.55", "size": "100"},
        {"price": "0.45", "size": "300"},
    ]
    asks = [
        {"price": "0.60", "size": "150"},
        {"price": "0.65", "size": "50"},
    ]

    book = OrderBookSnapshot.from_raw_book("token-1", bids, asks, max_levels=3)

    assert book.token_id == "token-1"
    assert book.best_bid == 0.55
    assert book.best_ask == 0.60
    assert book.spread == approx(0.05)
    assert book.mid_price == approx(0.575)
    assert len(book.bids) == 3
    assert len(book.asks) == 2
    # Bids sorted descending
    assert book.bids[0].price == 0.55
    assert book.bids[1].price == 0.50
    # Asks sorted ascending
    assert book.asks[0].price == 0.60


def test_order_book_snapshot_empty():
    book = OrderBookSnapshot.from_raw_book("token-1", [], [])
    assert book.best_bid is None
    assert book.best_ask is None
    assert book.spread is None
    assert book.mid_price is None
    assert book.depth_levels == 0


def test_order_book_snapshot_max_levels():
    bids = [{"price": str(i), "size": "10"} for i in range(20)]
    book = OrderBookSnapshot.from_raw_book("t", bids, [], max_levels=5)
    assert len(book.bids) == 5


def test_market_info_from_gamma_response():
    data = {
        "id": "market-123",
        "condition_id": "cond-456",
        "question": "Will X happen?",
        "description": "Some description",
        "category": "politics",
        "tags": ["elections", "us"],
        "slug": "will-x-happen",
        "end_date_iso": "2026-06-01T00:00:00Z",
        "active": True,
        "volume_num_24hr": "12345.67",
        "liquidity_num": "5000.0",
        "tokens": [
            {"token_id": "tok-yes", "outcome": "Yes"},
            {"token_id": "tok-no", "outcome": "No"},
        ],
    }

    info = MarketInfo.from_gamma_response(data)

    assert info.market_id == "market-123"
    assert info.condition_id == "cond-456"
    assert info.title == "Will X happen?"
    assert info.category == "politics"
    assert info.slug == "will-x-happen"
    assert info.is_active is True
    assert info.volume_24h == 12345.67
    assert info.liquidity == 5000.0
    assert len(info.token_ids) == 2
    assert "tok-yes" in info.token_ids
    assert info.end_date is not None


def test_market_info_from_gamma_response_minimal():
    data = {"condition_id": "cond-1"}
    info = MarketInfo.from_gamma_response(data)
    assert info.market_id == "cond-1"
    assert info.token_ids == []
    assert info.volume_24h is None


def test_market_snapshot_defaults():
    snap = MarketSnapshot(token_id="tok-1")
    assert snap.price is None
    assert snap.polled_at is not None


def test_cached_market_data():
    snap = MarketSnapshot(token_id="tok-1", price=0.55)
    cached = CachedMarketData(
        snapshot=snap,
        source=DataSource.LIVE,
        freshness=FreshnessStatus.FRESH,
        cache_age_seconds=0.0,
    )
    assert cached.source == DataSource.LIVE
    assert cached.freshness == FreshnessStatus.FRESH


def test_cache_stats():
    stats = CacheStats()
    assert stats.market_count == 0
    assert stats.hit_rate == 0.0


def test_safe_float():
    assert _safe_float("123.45") == 123.45
    assert _safe_float(42) == 42.0
    assert _safe_float(None) is None
    assert _safe_float("not-a-number") is None
    assert _safe_float({}) is None


def test_data_source_values():
    assert DataSource.LIVE.value == "live"
    assert DataSource.CACHE.value == "cache"
    assert DataSource.SECONDARY.value == "secondary"


def test_freshness_status_values():
    assert FreshnessStatus.FRESH.value == "fresh"
    assert FreshnessStatus.STALE.value == "stale"
    assert FreshnessStatus.EXPIRED.value == "expired"
