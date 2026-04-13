"""Thesis card repository."""

from __future__ import annotations

import uuid
from typing import Sequence

from sqlalchemy import select

from data.models.thesis import NetEdgeEstimate, ThesisCard
from data.repositories import BaseRepository


class ThesisCardRepository(BaseRepository[ThesisCard]):
    """Repository for ThesisCard entities."""

    model = ThesisCard

    async def get_by_market(self, market_id: uuid.UUID) -> Sequence[ThesisCard]:
        """Fetch thesis cards for a market."""
        stmt = (
            select(ThesisCard)
            .where(ThesisCard.market_id == market_id)
            .order_by(ThesisCard.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_by_workflow_run(
        self, workflow_run_id: uuid.UUID
    ) -> Sequence[ThesisCard]:
        """Fetch thesis cards produced by a workflow run."""
        stmt = select(ThesisCard).where(
            ThesisCard.workflow_run_id == workflow_run_id
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_by_category(
        self, category: str, *, limit: int = 50
    ) -> Sequence[ThesisCard]:
        """Fetch thesis cards by category."""
        stmt = (
            select(ThesisCard)
            .where(ThesisCard.category == category)
            .order_by(ThesisCard.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_with_positive_edge(self) -> Sequence[ThesisCard]:
        """Fetch thesis cards with positive net edge after cost."""
        stmt = (
            select(ThesisCard)
            .where(ThesisCard.net_edge_after_cost > 0)
            .order_by(ThesisCard.net_edge_after_cost.desc())
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()


class NetEdgeEstimateRepository(BaseRepository[NetEdgeEstimate]):
    """Repository for NetEdgeEstimate entities."""

    model = NetEdgeEstimate

    async def get_by_thesis_card(
        self, thesis_card_id: uuid.UUID
    ) -> Sequence[NetEdgeEstimate]:
        """Fetch edge estimates for a thesis card."""
        stmt = (
            select(NetEdgeEstimate)
            .where(NetEdgeEstimate.thesis_card_id == thesis_card_id)
            .order_by(NetEdgeEstimate.estimated_at)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()
