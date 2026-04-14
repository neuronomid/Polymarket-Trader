"""Notification repository — persistence for events and delivery records.

Extends the base repository pattern for notification-specific queries.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Sequence

from sqlalchemy import select, func

from data.models.notification import NotificationDeliveryRecord, NotificationEvent
from data.repositories import BaseRepository


class NotificationEventRepository(BaseRepository[NotificationEvent]):
    """Repository for NotificationEvent persistence and queries."""

    model = NotificationEvent

    async def get_by_event_type(
        self,
        event_type: str,
        *,
        limit: int = 50,
    ) -> Sequence[NotificationEvent]:
        """Fetch recent events by type."""
        stmt = (
            select(NotificationEvent)
            .where(NotificationEvent.event_type == event_type)
            .order_by(NotificationEvent.emitted_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_by_severity(
        self,
        severity: str,
        *,
        limit: int = 50,
    ) -> Sequence[NotificationEvent]:
        """Fetch recent events by severity."""
        stmt = (
            select(NotificationEvent)
            .where(NotificationEvent.severity == severity)
            .order_by(NotificationEvent.emitted_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_recent(
        self,
        *,
        limit: int = 100,
    ) -> Sequence[NotificationEvent]:
        """Fetch recent events across all types."""
        stmt = (
            select(NotificationEvent)
            .order_by(NotificationEvent.emitted_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_by_market(
        self,
        market_id: uuid.UUID,
        *,
        limit: int = 50,
    ) -> Sequence[NotificationEvent]:
        """Fetch events related to a specific market."""
        stmt = (
            select(NotificationEvent)
            .where(NotificationEvent.market_id == market_id)
            .order_by(NotificationEvent.emitted_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_by_dedup_key(
        self,
        dedup_key: str,
    ) -> NotificationEvent | None:
        """Find an existing event with the same dedup key."""
        stmt = (
            select(NotificationEvent)
            .where(NotificationEvent.dedup_key == dedup_key)
            .order_by(NotificationEvent.emitted_at.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def count_by_type_today(
        self,
        event_type: str,
        today_start: datetime,
    ) -> int:
        """Count events of a specific type emitted today."""
        stmt = (
            select(func.count())
            .select_from(NotificationEvent)
            .where(NotificationEvent.event_type == event_type)
            .where(NotificationEvent.emitted_at >= today_start)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()


class NotificationDeliveryRepository(BaseRepository[NotificationDeliveryRecord]):
    """Repository for NotificationDeliveryRecord persistence and queries."""

    model = NotificationDeliveryRecord

    async def get_by_event(
        self,
        notification_event_id: uuid.UUID,
    ) -> Sequence[NotificationDeliveryRecord]:
        """Get all delivery records for an event."""
        stmt = (
            select(NotificationDeliveryRecord)
            .where(
                NotificationDeliveryRecord.notification_event_id
                == notification_event_id
            )
            .order_by(NotificationDeliveryRecord.first_attempt_at.desc())
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_failed(
        self,
        *,
        limit: int = 50,
    ) -> Sequence[NotificationDeliveryRecord]:
        """Get recent failed delivery records for retry inspection."""
        stmt = (
            select(NotificationDeliveryRecord)
            .where(NotificationDeliveryRecord.status == "failed")
            .order_by(NotificationDeliveryRecord.last_attempt_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_pending(
        self,
        *,
        limit: int = 50,
    ) -> Sequence[NotificationDeliveryRecord]:
        """Get pending delivery records."""
        stmt = (
            select(NotificationDeliveryRecord)
            .where(NotificationDeliveryRecord.status.in_(["pending", "retrying"]))
            .order_by(NotificationDeliveryRecord.created_at.asc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def count_by_status(self) -> dict[str, int]:
        """Count delivery records grouped by status."""
        stmt = (
            select(
                NotificationDeliveryRecord.status,
                func.count(),
            )
            .group_by(NotificationDeliveryRecord.status)
        )
        result = await self.session.execute(stmt)
        return {row[0]: row[1] for row in result.all()}
