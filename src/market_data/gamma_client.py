"""Gamma API client for market discovery.

Fetches market listings from https://gamma-api.polymarket.com.
All endpoints are public (no authentication required).
"""

from __future__ import annotations

import httpx

from config.settings import PolymarketApiConfig
from logging_.logger import get_logger
from market_data.rate_limiter import AsyncRateLimiter, RetryPolicy
from market_data.types import MarketInfo


class GammaClient:
    """Async client for the Polymarket Gamma API (market discovery)."""

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
            base_url=config.gamma_base_url,
            timeout=httpx.Timeout(config.request_timeout, connect=config.connect_timeout),
        )
        self._log = get_logger(component="gamma_client")

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _request(self, path: str, params: dict | None = None) -> list | dict:
        """Make a rate-limited, retried GET request."""
        await self._rate_limiter.acquire()

        async def _do_request() -> list | dict:
            url = f"{self._config.gamma_base_url}{path}"
            response = await self._client.get(url, params=params)
            response.raise_for_status()
            return response.json()

        return await self._retry.execute(_do_request)

    async def fetch_markets(
        self,
        *,
        limit: int | None = None,
        offset: int = 0,
        active: bool = True,
    ) -> list[MarketInfo]:
        """Fetch a page of markets from the Gamma API.

        Returns parsed MarketInfo objects.
        """
        page_size = limit or self._config.market_list_page_size
        params: dict = {
            "limit": page_size,
            "offset": offset,
            "active": str(active).lower(),
        }

        data = await self._request("/markets", params=params)

        if not isinstance(data, list):
            self._log.warning("unexpected_gamma_response", response_type=type(data).__name__)
            return []

        markets = []
        for item in data:
            try:
                markets.append(MarketInfo.from_gamma_response(item))
            except Exception:
                self._log.warning("market_parse_error", raw_id=item.get("id"))
        return markets

    async def fetch_market_by_id(self, market_id: str) -> MarketInfo | None:
        """Fetch a single market by its ID."""
        params = {"id": market_id}
        data = await self._request("/markets", params=params)

        if isinstance(data, list) and data:
            try:
                return MarketInfo.from_gamma_response(data[0])
            except Exception:
                self._log.warning("market_parse_error", market_id=market_id)
        return None

    async def fetch_all_active_markets(self) -> list[MarketInfo]:
        """Paginate through all active markets.

        Returns the full list of active MarketInfo objects.
        """
        all_markets: list[MarketInfo] = []
        offset = 0
        page_size = self._config.market_list_page_size

        while True:
            page = await self.fetch_markets(limit=page_size, offset=offset)
            if not page:
                break
            all_markets.extend(page)
            if len(page) < page_size:
                break
            offset += page_size

        self._log.info("fetched_all_markets", total=len(all_markets))
        return all_markets
