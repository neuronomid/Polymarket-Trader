"""Tests for the Gamma API client with mocked HTTP responses."""

import json

import httpx
import pytest

from config.settings import PolymarketApiConfig
from market_data.gamma_client import GammaClient
from market_data.rate_limiter import AsyncRateLimiter


def _mock_transport(responses: list[httpx.Response]) -> httpx.MockTransport:
    """Create a mock transport that returns responses in order."""
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        if call_count < len(responses):
            resp = responses[call_count]
            call_count += 1
            return resp
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def _gamma_market_data(market_id: str = "m-1", **overrides) -> dict:
    base = {
        "id": market_id,
        "condition_id": f"cond-{market_id}",
        "question": f"Will {market_id} happen?",
        "description": "Test market",
        "category": "politics",
        "tags": ["test"],
        "slug": f"will-{market_id}-happen",
        "end_date_iso": "2026-12-01T00:00:00Z",
        "active": True,
        "volume_num_24hr": "1000.0",
        "liquidity_num": "500.0",
        "tokens": [
            {"token_id": f"tok-{market_id}-yes", "outcome": "Yes"},
            {"token_id": f"tok-{market_id}-no", "outcome": "No"},
        ],
    }
    base.update(overrides)
    return base


async def test_fetch_markets():
    data = [_gamma_market_data("m-1"), _gamma_market_data("m-2")]
    transport = _mock_transport([
        httpx.Response(200, json=data),
    ])
    client = httpx.AsyncClient(transport=transport, base_url="https://gamma-api.polymarket.com")
    config = PolymarketApiConfig()
    limiter = AsyncRateLimiter(max_requests=100)

    gamma = GammaClient(config=config, rate_limiter=limiter, http_client=client)
    markets = await gamma.fetch_markets()

    assert len(markets) == 2
    assert markets[0].market_id == "m-1"
    assert markets[0].condition_id == "cond-m-1"
    assert markets[0].title == "Will m-1 happen?"
    assert len(markets[0].token_ids) == 2


async def test_fetch_markets_empty_response():
    transport = _mock_transport([httpx.Response(200, json=[])])
    client = httpx.AsyncClient(transport=transport, base_url="https://gamma-api.polymarket.com")
    config = PolymarketApiConfig()
    limiter = AsyncRateLimiter(max_requests=100)

    gamma = GammaClient(config=config, rate_limiter=limiter, http_client=client)
    markets = await gamma.fetch_markets()

    assert markets == []


async def test_fetch_market_by_id():
    data = [_gamma_market_data("m-1")]
    transport = _mock_transport([httpx.Response(200, json=data)])
    client = httpx.AsyncClient(transport=transport, base_url="https://gamma-api.polymarket.com")
    config = PolymarketApiConfig()
    limiter = AsyncRateLimiter(max_requests=100)

    gamma = GammaClient(config=config, rate_limiter=limiter, http_client=client)
    market = await gamma.fetch_market_by_id("m-1")

    assert market is not None
    assert market.market_id == "m-1"


async def test_fetch_market_by_id_not_found():
    transport = _mock_transport([httpx.Response(200, json=[])])
    client = httpx.AsyncClient(transport=transport, base_url="https://gamma-api.polymarket.com")
    config = PolymarketApiConfig()
    limiter = AsyncRateLimiter(max_requests=100)

    gamma = GammaClient(config=config, rate_limiter=limiter, http_client=client)
    market = await gamma.fetch_market_by_id("nonexistent")

    assert market is None


async def test_fetch_all_active_markets_pagination():
    """Test that pagination stops when a page returns fewer items than page_size."""
    page1 = [_gamma_market_data(f"m-{i}") for i in range(3)]
    page2 = [_gamma_market_data(f"m-{i}") for i in range(3, 5)]  # less than page_size=3

    transport = _mock_transport([
        httpx.Response(200, json=page1),
        httpx.Response(200, json=page2),
    ])
    client = httpx.AsyncClient(transport=transport, base_url="https://gamma-api.polymarket.com")
    config = PolymarketApiConfig(market_list_page_size=3)
    limiter = AsyncRateLimiter(max_requests=100)

    gamma = GammaClient(config=config, rate_limiter=limiter, http_client=client)
    markets = await gamma.fetch_all_active_markets()

    assert len(markets) == 5


async def test_fetch_markets_unexpected_response_type():
    """Non-list response should return empty list."""
    transport = _mock_transport([httpx.Response(200, json={"error": "unexpected"})])
    client = httpx.AsyncClient(transport=transport, base_url="https://gamma-api.polymarket.com")
    config = PolymarketApiConfig()
    limiter = AsyncRateLimiter(max_requests=100)

    gamma = GammaClient(config=config, rate_limiter=limiter, http_client=client)
    markets = await gamma.fetch_markets()

    assert markets == []
