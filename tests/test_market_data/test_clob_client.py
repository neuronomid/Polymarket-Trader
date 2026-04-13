"""Tests for the CLOB API client with mocked HTTP responses."""

import httpx
from pytest import approx

from config.settings import PolymarketApiConfig
from market_data.clob_client import ClobClient
from market_data.rate_limiter import AsyncRateLimiter


def _mock_transport_handler(routes: dict[str, dict | list]) -> httpx.MockTransport:
    """Create a mock transport that routes by URL path."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        for route_path, response_data in routes.items():
            if path == route_path:
                return httpx.Response(200, json=response_data)
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def _make_clob_client(routes: dict) -> ClobClient:
    transport = _mock_transport_handler(routes)
    client = httpx.AsyncClient(transport=transport, base_url="https://clob.polymarket.com")
    config = PolymarketApiConfig()
    limiter = AsyncRateLimiter(max_requests=100)
    return ClobClient(config=config, rate_limiter=limiter, http_client=client)


async def test_fetch_order_book():
    clob = _make_clob_client({
        "/book": {
            "bids": [
                {"price": "0.55", "size": "100"},
                {"price": "0.50", "size": "200"},
            ],
            "asks": [
                {"price": "0.60", "size": "150"},
                {"price": "0.65", "size": "50"},
            ],
        },
    })

    book = await clob.fetch_order_book("tok-1")

    assert book.token_id == "tok-1"
    assert book.best_bid == 0.55
    assert book.best_ask == 0.60
    assert book.spread == approx(0.05)
    assert book.mid_price == approx(0.575)
    assert len(book.bids) == 2
    assert len(book.asks) == 2


async def test_fetch_order_book_empty():
    clob = _make_clob_client({
        "/book": {"bids": [], "asks": []},
    })

    book = await clob.fetch_order_book("tok-1")

    assert book.best_bid is None
    assert book.best_ask is None
    assert book.spread is None
    assert book.mid_price is None


async def test_fetch_order_book_one_side_only():
    clob = _make_clob_client({
        "/book": {
            "bids": [{"price": "0.50", "size": "100"}],
            "asks": [],
        },
    })

    book = await clob.fetch_order_book("tok-1")

    assert book.best_bid == 0.50
    assert book.best_ask is None
    assert book.spread is None


async def test_fetch_price():
    clob = _make_clob_client({
        "/price": {"price": "0.55"},
    })

    price = await clob.fetch_price("tok-1")
    assert price == 0.55


async def test_fetch_price_missing():
    clob = _make_clob_client({
        "/price": {},
    })

    price = await clob.fetch_price("tok-1")
    assert price is None


async def test_fetch_last_trade():
    clob = _make_clob_client({
        "/last-trade-price": {
            "price": "0.58",
            "timestamp": "2026-04-13T12:00:00Z",
        },
    })

    price, time = await clob.fetch_last_trade("tok-1")
    assert price == 0.58
    assert time is not None


async def test_fetch_market_snapshot():
    clob = _make_clob_client({
        "/book": {
            "bids": [{"price": "0.55", "size": "100"}],
            "asks": [{"price": "0.60", "size": "150"}],
        },
        "/last-trade-price": {
            "price": "0.57",
            "timestamp": "2026-04-13T12:00:00Z",
        },
    })

    snapshot = await clob.fetch_market_snapshot("tok-1")

    assert snapshot.token_id == "tok-1"
    assert snapshot.best_bid == 0.55
    assert snapshot.best_ask == 0.60
    assert snapshot.spread == approx(0.05)
    assert snapshot.mid_price == approx(0.575)
    assert snapshot.last_trade_price == 0.57
    assert snapshot.depth_levels is not None
    assert "bids" in snapshot.depth_levels


async def test_fetch_batch_snapshots():
    """Batch fetch should return snapshots for all successful tokens."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/book":
            return httpx.Response(200, json={
                "bids": [{"price": "0.50", "size": "100"}],
                "asks": [{"price": "0.60", "size": "100"}],
            })
        if path == "/last-trade-price":
            return httpx.Response(200, json={"price": "0.55"})
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="https://clob.polymarket.com")
    config = PolymarketApiConfig()
    limiter = AsyncRateLimiter(max_requests=100)
    clob = ClobClient(config=config, rate_limiter=limiter, http_client=client)

    results = await clob.fetch_batch_snapshots(["tok-1", "tok-2", "tok-3"])

    assert len(results) == 3
    for tid in ["tok-1", "tok-2", "tok-3"]:
        assert tid in results
        assert results[tid].best_bid == 0.50
