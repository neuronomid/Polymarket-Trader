"""Secondary price source via Polymarket subgraph on The Graph.

Used as a fallback when the CLOB API is unavailable.
Provides basic price monitoring only — no order book depth.
"""

from __future__ import annotations

import httpx

from config.settings import PolymarketApiConfig
from logging_.logger import get_logger


class SubgraphClient:
    """Async client for the Polymarket subgraph (secondary price source).

    Used ONLY for:
    - Basic price monitoring
    - Detecting large adverse moves on held positions
    - Triggering Level D risk interventions

    NOT used for depth analysis or full trigger detection.
    """

    PRICE_QUERY = """
    query MarketPrice($conditionId: String!) {
      fixedProductMarketMakers(where: { conditionIds_contains: [$conditionId] }) {
        id
        outcomeTokenAmounts
        outcomeTokenPrices
        lastActiveDay
      }
    }
    """

    HEALTH_QUERY = """
    query Health {
      _meta {
        block { number }
        hasIndexingErrors
      }
    }
    """

    def __init__(
        self,
        config: PolymarketApiConfig,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._config = config
        self._owns_client = http_client is None
        self._client = http_client or httpx.AsyncClient(
            timeout=httpx.Timeout(config.request_timeout, connect=config.connect_timeout),
        )
        self._log = get_logger(component="subgraph_client")

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _graphql(self, query: str, variables: dict | None = None) -> dict:
        """Execute a GraphQL query against the subgraph."""
        payload: dict = {"query": query}
        if variables:
            payload["variables"] = variables

        response = await self._client.post(self._config.subgraph_url, json=payload)
        response.raise_for_status()
        result = response.json()

        if "errors" in result:
            self._log.warning("subgraph_graphql_errors", errors=result["errors"])

        return result.get("data", {})

    async def fetch_price(self, condition_id: str) -> float | None:
        """Fetch the latest price for a market by condition ID.

        Returns the first outcome token price, or None on failure.
        """
        try:
            data = await self._graphql(
                self.PRICE_QUERY, {"conditionId": condition_id}
            )
            makers = data.get("fixedProductMarketMakers") or []
            if not makers:
                return None

            prices = makers[0].get("outcomeTokenPrices") or []
            if not prices:
                return None

            return float(prices[0])
        except Exception:
            self._log.warning("subgraph_price_failed", condition_id=condition_id)
            return None

    async def fetch_prices_batch(
        self, condition_ids: list[str]
    ) -> dict[str, float | None]:
        """Fetch prices for multiple markets.

        Returns a dict of condition_id → price (or None).
        """
        results: dict[str, float | None] = {}
        for cid in condition_ids:
            results[cid] = await self.fetch_price(cid)
        return results

    async def is_available(self) -> bool:
        """Check if the subgraph is reachable and healthy."""
        try:
            data = await self._graphql(self.HEALTH_QUERY)
            meta = data.get("_meta", {})
            return not meta.get("hasIndexingErrors", True)
        except Exception:
            return False
