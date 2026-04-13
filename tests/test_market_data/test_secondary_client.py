"""Tests for the subgraph secondary source client."""

import json

import httpx

from config.settings import PolymarketApiConfig
from market_data.secondary_client import SubgraphClient


def _mock_graphql_transport(response_data: dict) -> httpx.MockTransport:
    """Create a mock transport that returns GraphQL responses."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=response_data)

    return httpx.MockTransport(handler)


def _make_client(response_data: dict) -> SubgraphClient:
    transport = _mock_graphql_transport(response_data)
    http_client = httpx.AsyncClient(transport=transport)
    config = PolymarketApiConfig()
    return SubgraphClient(config=config, http_client=http_client)


async def test_fetch_price():
    client = _make_client({
        "data": {
            "fixedProductMarketMakers": [
                {
                    "id": "maker-1",
                    "outcomeTokenAmounts": ["1000000", "2000000"],
                    "outcomeTokenPrices": ["0.65", "0.35"],
                    "lastActiveDay": "2026-04-13",
                }
            ]
        }
    })

    price = await client.fetch_price("cond-1")
    assert price == 0.65


async def test_fetch_price_no_makers():
    client = _make_client({
        "data": {"fixedProductMarketMakers": []}
    })

    price = await client.fetch_price("cond-1")
    assert price is None


async def test_fetch_price_no_prices():
    client = _make_client({
        "data": {
            "fixedProductMarketMakers": [
                {"id": "maker-1", "outcomeTokenPrices": []}
            ]
        }
    })

    price = await client.fetch_price("cond-1")
    assert price is None


async def test_fetch_prices_batch():
    client = _make_client({
        "data": {
            "fixedProductMarketMakers": [
                {"id": "maker-1", "outcomeTokenPrices": ["0.55"]}
            ]
        }
    })

    prices = await client.fetch_prices_batch(["cond-1", "cond-2"])
    assert len(prices) == 2
    assert prices["cond-1"] == 0.55


async def test_is_available_healthy():
    client = _make_client({
        "data": {
            "_meta": {
                "block": {"number": 12345},
                "hasIndexingErrors": False,
            }
        }
    })

    assert await client.is_available() is True


async def test_is_available_unhealthy():
    client = _make_client({
        "data": {
            "_meta": {
                "block": {"number": 12345},
                "hasIndexingErrors": True,
            }
        }
    })

    assert await client.is_available() is False


async def test_is_available_connection_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=transport)
    config = PolymarketApiConfig()
    client = SubgraphClient(config=config, http_client=http_client)

    assert await client.is_available() is False


async def test_fetch_price_with_graphql_errors():
    """GraphQL errors in response should still return None gracefully."""
    client = _make_client({
        "errors": [{"message": "some error"}],
        "data": {"fixedProductMarketMakers": []}
    })

    price = await client.fetch_price("cond-1")
    assert price is None
