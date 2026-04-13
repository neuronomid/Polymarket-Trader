"""CLOB API client for order book and price data.

Fetches from https://clob.polymarket.com.
Public read endpoints (no authentication required for Phase 3).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import httpx

from config.settings import PolymarketApiConfig
from logging_.logger import get_logger
from market_data.rate_limiter import AsyncRateLimiter, RetryPolicy
from market_data.types import MarketSnapshot, OrderBookSnapshot


class ClobClient:
    """Async client for the Polymarket CLOB API (order book and prices)."""

    def __init__(
        self,
        config: PolymarketApiConfig,
        rate_limiter: AsyncRateLimiter,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._config = config
        self._rate_limiter = rate_limiter
        self._retry = RetryPolicy(
            max_retries=config.max_retries,
            backoff_base=config.backoff_base_seconds,
            backoff_max=config.backoff_max_seconds,
        )
        self._owns_client = http_client is None
        self._client = http_client or httpx.AsyncClient(
            base_url=config.clob_base_url,
            timeout=httpx.Timeout(config.request_timeout, connect=config.connect_timeout),
        )
        self._log = get_logger(component="clob_client")

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _request(self, path: str, params: dict | None = None) -> dict:
        """Make a rate-limited, retried GET request."""
        await self._rate_limiter.acquire()

        async def _do_request() -> dict:
            response = await self._client.get(path, params=params)
            response.raise_for_status()
            return response.json()

        return await self._retry.execute(_do_request)

    async def fetch_order_book(self, token_id: str) -> OrderBookSnapshot:
        """Fetch order book for a token.

        Parses bids/asks, computes best_bid, best_ask, spread, mid_price.
        """
        data = await self._request("/book", params={"token_id": token_id})

        return OrderBookSnapshot.from_raw_book(
            token_id=token_id,
            bids=data.get("bids") or [],
            asks=data.get("asks") or [],
            max_levels=self._config.orderbook_depth_levels,
        )

    async def fetch_price(self, token_id: str) -> float | None:
        """Fetch midpoint price for a token."""
        try:
            data = await self._request("/price", params={"token_id": token_id})
            price = data.get("price")
            return float(price) if price is not None else None
        except Exception:
            self._log.warning("price_fetch_failed", token_id=token_id)
            return None

    async def fetch_last_trade(
        self, token_id: str
    ) -> tuple[float | None, datetime | None]:
        """Fetch last trade price and timestamp for a token."""
        try:
            data = await self._request(
                "/last-trade-price", params={"token_id": token_id}
            )
            price = data.get("price")
            timestamp_raw = data.get("timestamp")

            trade_price = float(price) if price is not None else None
            trade_time = None
            if timestamp_raw:
                try:
                    trade_time = datetime.fromisoformat(
                        str(timestamp_raw).replace("Z", "+00:00")
                    )
                except (ValueError, AttributeError):
                    pass

            return trade_price, trade_time
        except Exception:
            self._log.warning("last_trade_fetch_failed", token_id=token_id)
            return None, None

    async def fetch_market_snapshot(self, token_id: str) -> MarketSnapshot:
        """Fetch a complete market snapshot: order book + last trade.

        Combines order book data with last trade info into a single snapshot.
        """
        book = await self.fetch_order_book(token_id)
        last_trade_price, last_trade_time = await self.fetch_last_trade(token_id)

        depth_levels_data: dict | None = None
        if book.bids or book.asks:
            depth_levels_data = {
                "bids": [{"price": l.price, "size": l.size} for l in book.bids],
                "asks": [{"price": l.price, "size": l.size} for l in book.asks],
            }

        return MarketSnapshot(
            token_id=token_id,
            price=book.mid_price,
            best_bid=book.best_bid,
            best_ask=book.best_ask,
            spread=book.spread,
            mid_price=book.mid_price,
            last_trade_price=last_trade_price,
            last_trade_time=last_trade_time,
            depth_levels=depth_levels_data,
            polled_at=datetime.now(tz=UTC),
        )

    async def fetch_batch_snapshots(
        self,
        token_ids: list[str],
        *,
        max_concurrency: int = 10,
    ) -> dict[str, MarketSnapshot]:
        """Fetch market snapshots for multiple tokens concurrently.

        Uses a semaphore to limit concurrent requests.
        Returns a dict keyed by token_id. Failed fetches are omitted.
        """
        semaphore = asyncio.Semaphore(max_concurrency)
        results: dict[str, MarketSnapshot] = {}

        async def _fetch_one(tid: str) -> None:
            async with semaphore:
                try:
                    snapshot = await self.fetch_market_snapshot(tid)
                    results[tid] = snapshot
                except Exception:
                    self._log.warning("batch_snapshot_failed", token_id=tid)

        await asyncio.gather(*[_fetch_one(tid) for tid in token_ids])

        self._log.info(
            "batch_snapshots_complete",
            requested=len(token_ids),
            succeeded=len(results),
        )
        return results
