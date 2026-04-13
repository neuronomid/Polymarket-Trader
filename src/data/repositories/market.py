"""Market and position repositories."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Sequence

from sqlalchemy import select

from data.models import Market, Order, Position, Trade
from data.repositories import BaseRepository


class MarketRepository(BaseRepository[Market]):
    """Repository for Market entities."""

    model = Market

    async def get_by_market_id(self, market_id: str) -> Market | None:
        """Fetch by external Polymarket market ID."""
        stmt = select(Market).where(Market.market_id == market_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_active_markets(self, *, limit: int = 500) -> Sequence[Market]:
        """Fetch all active markets."""
        stmt = select(Market).where(Market.is_active.is_(True)).limit(limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_by_category(self, category: str) -> Sequence[Market]:
        """Fetch markets by category."""
        stmt = select(Market).where(Market.category == category)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_eligible(self, outcome: str = "trigger_eligible") -> Sequence[Market]:
        """Fetch markets matching an eligibility outcome."""
        stmt = select(Market).where(Market.eligibility_outcome == outcome)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_by_cluster(self, cluster_id: uuid.UUID) -> Sequence[Market]:
        """Fetch markets in a given event cluster."""
        stmt = select(Market).where(Market.event_cluster_id == cluster_id)
        result = await self.session.execute(stmt)
        return result.scalars().all()


class PositionRepository(BaseRepository[Position]):
    """Repository for Position entities."""

    model = Position

    async def get_open_positions(self) -> Sequence[Position]:
        """Fetch all currently open positions."""
        stmt = select(Position).where(Position.status == "open")
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_by_market(self, market_id: uuid.UUID) -> Sequence[Position]:
        """Fetch positions for a market."""
        stmt = select(Position).where(Position.market_id == market_id)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_positions_for_review(
        self, before: datetime
    ) -> Sequence[Position]:
        """Fetch open positions due for review."""
        stmt = (
            select(Position)
            .where(Position.status == "open")
            .where(Position.next_review_at <= before)
            .order_by(Position.next_review_at)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_by_review_tier(self, tier: str) -> Sequence[Position]:
        """Fetch open positions by review tier."""
        stmt = (
            select(Position)
            .where(Position.status == "open")
            .where(Position.review_tier == tier)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_by_correlation_group(
        self, group_id: uuid.UUID
    ) -> Sequence[Position]:
        """Fetch positions in a correlation group."""
        stmt = select(Position).where(Position.correlation_group_id == group_id)
        result = await self.session.execute(stmt)
        return result.scalars().all()


class OrderRepository(BaseRepository[Order]):
    """Repository for Order entities."""

    model = Order

    async def get_by_position(self, position_id: uuid.UUID) -> Sequence[Order]:
        """Fetch orders for a position."""
        stmt = (
            select(Order)
            .where(Order.position_id == position_id)
            .order_by(Order.created_at)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_pending_orders(self) -> Sequence[Order]:
        """Fetch all pending orders."""
        stmt = select(Order).where(Order.status == "pending")
        result = await self.session.execute(stmt)
        return result.scalars().all()


class TradeRepository(BaseRepository[Trade]):
    """Repository for Trade entities."""

    model = Trade

    async def get_by_position(self, position_id: uuid.UUID) -> Sequence[Trade]:
        """Fetch trades for a position."""
        stmt = (
            select(Trade)
            .where(Trade.position_id == position_id)
            .order_by(Trade.executed_at)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_recent_trades(
        self, *, limit: int = 20
    ) -> Sequence[Trade]:
        """Fetch most recent trades."""
        stmt = select(Trade).order_by(Trade.executed_at.desc()).limit(limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()
