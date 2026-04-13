"""Workflow, trigger, and eligibility repositories."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Sequence

from sqlalchemy import select

from data.models.workflow import EligibilityDecision, TriggerEvent, WorkflowRun
from data.repositories import BaseRepository


class WorkflowRunRepository(BaseRepository[WorkflowRun]):
    """Repository for WorkflowRun entities."""

    model = WorkflowRun

    async def get_by_workflow_run_id(self, workflow_run_id: str) -> WorkflowRun | None:
        """Fetch by the string workflow_run_id."""
        stmt = select(WorkflowRun).where(WorkflowRun.workflow_run_id == workflow_run_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_type_and_status(
        self, run_type: str, status: str
    ) -> Sequence[WorkflowRun]:
        """Fetch workflow runs by type and status."""
        stmt = (
            select(WorkflowRun)
            .where(WorkflowRun.run_type == run_type)
            .where(WorkflowRun.status == status)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_recent(self, *, limit: int = 50) -> Sequence[WorkflowRun]:
        """Fetch most recent workflow runs."""
        stmt = (
            select(WorkflowRun)
            .order_by(WorkflowRun.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_by_market(self, market_id: uuid.UUID) -> Sequence[WorkflowRun]:
        """Fetch workflow runs for a market."""
        stmt = (
            select(WorkflowRun)
            .where(WorkflowRun.market_id == market_id)
            .order_by(WorkflowRun.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()


class TriggerEventRepository(BaseRepository[TriggerEvent]):
    """Repository for TriggerEvent entities."""

    model = TriggerEvent

    async def get_by_market(
        self, market_id: uuid.UUID, *, limit: int = 50
    ) -> Sequence[TriggerEvent]:
        """Fetch trigger events for a market."""
        stmt = (
            select(TriggerEvent)
            .where(TriggerEvent.market_id == market_id)
            .order_by(TriggerEvent.triggered_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_by_class_and_level(
        self, trigger_class: str, trigger_level: str
    ) -> Sequence[TriggerEvent]:
        """Fetch triggers by class and level."""
        stmt = (
            select(TriggerEvent)
            .where(TriggerEvent.trigger_class == trigger_class)
            .where(TriggerEvent.trigger_level == trigger_level)
            .order_by(TriggerEvent.triggered_at.desc())
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_recent_triggers(
        self, since: datetime, *, limit: int = 100
    ) -> Sequence[TriggerEvent]:
        """Fetch recent triggers since a timestamp."""
        stmt = (
            select(TriggerEvent)
            .where(TriggerEvent.triggered_at >= since)
            .order_by(TriggerEvent.triggered_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()


class EligibilityDecisionRepository(BaseRepository[EligibilityDecision]):
    """Repository for EligibilityDecision entities."""

    model = EligibilityDecision

    async def get_by_market(
        self, market_id: uuid.UUID
    ) -> Sequence[EligibilityDecision]:
        """Fetch eligibility decisions for a market."""
        stmt = (
            select(EligibilityDecision)
            .where(EligibilityDecision.market_id == market_id)
            .order_by(EligibilityDecision.decided_at.desc())
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_latest_for_market(
        self, market_id: uuid.UUID
    ) -> EligibilityDecision | None:
        """Fetch the most recent eligibility decision for a market."""
        stmt = (
            select(EligibilityDecision)
            .where(EligibilityDecision.market_id == market_id)
            .order_by(EligibilityDecision.decided_at.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
