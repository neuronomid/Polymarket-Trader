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

    @classmethod
    def from_gamma_response(cls, data: dict) -> MarketInfo:
        """Parse a single market object from Gamma API response."""
        token_ids: list[str] = []
        tokens = data.get("tokens") or []
        for t in tokens:
            if isinstance(t, dict) and "token_id" in t:
                token_ids.append(str(t["token_id"]))

        end_date = None
        end_date_raw = data.get("end_date_iso")
        if end_date_raw:
            try:
                end_date = datetime.fromisoformat(end_date_raw.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass

        return cls(
            market_id=str(data.get("id", data.get("condition_id", ""))),
            condition_id=data.get("condition_id"),
            token_ids=token_ids,
            title=data.get("question", data.get("title", "")),
            description=data.get("description"),
            category=data.get("category"),
            tags=data.get("tags") or [],
            slug=data.get("slug"),
            end_date=end_date,
            is_active=data.get("active", True),
            volume_24h=_safe_float(data.get("volume_num_24hr")),
            liquidity=_safe_float(data.get("liquidity_num")),
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
