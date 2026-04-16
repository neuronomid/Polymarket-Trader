"""Market data types used across the market data layer.

These are runtime Pydantic models for in-process use — not ORM models.
The ORM persistence target is CLOBCacheEntry in data/models/scanner.py.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, Field


class DataSource(str, Enum):
    """Origin of a market data snapshot."""

    LIVE = "live"
    CACHE = "cache"
    SECONDARY = "secondary"


class FreshnessStatus(str, Enum):
    """Freshness classification of cached data."""

    FRESH = "fresh"
    STALE = "stale"
    EXPIRED = "expired"


class OrderBookLevel(BaseModel):
    """A single price level in the order book."""

    price: float
    size: float


class OrderBookSnapshot(BaseModel):
    """Point-in-time order book state for a single token."""

    token_id: str
    bids: list[OrderBookLevel] = Field(default_factory=list)
    asks: list[OrderBookLevel] = Field(default_factory=list)
    best_bid: float | None = None
    best_ask: float | None = None
    spread: float | None = None
    mid_price: float | None = None
    depth_levels: int = 0
    timestamp: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))

    @classmethod
    def from_raw_book(
        cls,
        token_id: str,
        bids: list[dict],
        asks: list[dict],
        *,
        max_levels: int = 5,
    ) -> OrderBookSnapshot:
        """Parse raw CLOB API book response into a typed snapshot.

        Raw format: [{"price": "0.55", "size": "100"}, ...]
        """
        parsed_bids = sorted(
            [OrderBookLevel(price=float(b["price"]), size=float(b["size"])) for b in bids],
            key=lambda x: x.price,
            reverse=True,
        )[:max_levels]

        parsed_asks = sorted(
            [OrderBookLevel(price=float(a["price"]), size=float(a["size"])) for a in asks],
            key=lambda x: x.price,
        )[:max_levels]

        best_bid = parsed_bids[0].price if parsed_bids else None
        best_ask = parsed_asks[0].price if parsed_asks else None

        spread: float | None = None
        mid_price: float | None = None
        if best_bid is not None and best_ask is not None:
            spread = best_ask - best_bid
            mid_price = (best_bid + best_ask) / 2

        return cls(
            token_id=token_id,
            bids=parsed_bids,
            asks=parsed_asks,
            best_bid=best_bid,
            best_ask=best_ask,
            spread=spread,
            mid_price=mid_price,
            depth_levels=max(len(parsed_bids), len(parsed_asks)),
        )


class MarketInfo(BaseModel):
    """Market metadata from the Gamma API."""

    market_id: str
    condition_id: str | None = None
    token_ids: list[str] = Field(default_factory=list)
    title: str = ""
    description: str | None = None
    category: str | None = None
    tags: list[str] = Field(default_factory=list)
    slug: str | None = None
    end_date: datetime | None = None
    is_active: bool = True
    volume_24h: float | None = None
    liquidity: float | None = None
    spread: float | None = None
    resolution_source: str | None = None
    # Price fields — populated from Gamma API when available (bestBid/bestAsk/lastTradePrice).
    # Avoids AttributeError if anything accesses market.price on a MarketInfo object.
    price: float | None = None
    mid_price: float | None = None

    @classmethod
    def from_gamma_response(cls, data: dict) -> MarketInfo:
        """Parse a single market object from Gamma API response."""
        import json as _json

        def _first_present(*keys: str) -> object | None:
            for key in keys:
                if key in data and data.get(key) is not None:
                    return data.get(key)
            return None

        # Token IDs: clobTokenIds is a JSON-encoded string e.g. '["id1","id2"]'
        token_ids: list[str] = []
        raw_clob = _first_present("clobTokenIds", "clob_token_ids")
        if isinstance(raw_clob, str):
            try:
                parsed = _json.loads(raw_clob)
                if isinstance(parsed, list):
                    token_ids = [str(t) for t in parsed]
            except (ValueError, TypeError):
                pass
        elif isinstance(raw_clob, list):
            token_ids = [str(t) for t in raw_clob]
        elif isinstance(data.get("tokens"), list):
            token_ids = [
                str(token.get("token_id") or token.get("tokenId"))
                for token in data["tokens"]
                if isinstance(token, dict) and (token.get("token_id") or token.get("tokenId"))
            ]

        end_date = None
        end_date_raw = _first_present("endDateIso", "end_date_iso")
        if end_date_raw:
            try:
                from datetime import timezone
                end_date = datetime.fromisoformat(end_date_raw.replace("Z", "+00:00"))
                if end_date.tzinfo is None:
                    end_date = end_date.replace(tzinfo=timezone.utc)
            except (ValueError, AttributeError):
                pass

        return cls(
            market_id=str(_first_present("id", "market_id", "conditionId", "condition_id") or ""),
            condition_id=(
                str(_first_present("conditionId", "condition_id"))
                if _first_present("conditionId", "condition_id") is not None
                else None
            ),
            token_ids=token_ids,
            title=data.get("question", data.get("title", "")),
            description=data.get("description"),
            category=data.get("category"),
            tags=data.get("tags") or [],
            slug=data.get("slug"),
            end_date=end_date,
            is_active=data.get("active", True),
            volume_24h=_safe_float(_first_present("volume24hr", "volume_24hr", "volume_num_24hr")),
            liquidity=_safe_float(_first_present("liquidityNum", "liquidity_num")),
            spread=_safe_float(data.get("spread")),
            resolution_source=_first_present("resolutionSource", "resolution_source") or None,
            price=_safe_float(_first_present("lastTradePrice", "last_trade_price", "price")),
            mid_price=_safe_float(_first_present("midPrice", "mid_price")),
        )


class MarketSnapshot(BaseModel):
    """Complete point-in-time market data state for a single token."""

    token_id: str
    market_id: str = ""
    price: float | None = None
    best_bid: float | None = None
    best_ask: float | None = None
    spread: float | None = None
    mid_price: float | None = None
    last_trade_price: float | None = None
    last_trade_time: datetime | None = None
    volume_24h: float | None = None
    depth_levels: dict | None = None
    market_status: str | None = None
    polled_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))


class CachedMarketData(BaseModel):
    """MarketSnapshot wrapped with cache metadata."""

    snapshot: MarketSnapshot
    source: DataSource
    freshness: FreshnessStatus
    cache_age_seconds: float
    cached_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))


class CacheStats(BaseModel):
    """Cache health statistics."""

    market_count: int = 0
    total_entries: int = 0
    hit_rate: float = 0.0
    miss_rate: float = 0.0
    oldest_entry_age_seconds: float | None = None
    newest_entry_age_seconds: float | None = None
    avg_entries_per_market: float = 0.0


def _safe_float(value: object) -> float | None:
    """Convert a value to float, returning None on failure."""
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None
