"""Notification service — the orchestration layer.

Subscribes to the event bus, formats messages, delivers via Telegram,
and persists event + delivery records to the database.

This is the central service that ties together:
    - Event bus (events.py) — receives typed events from workflows
    - Formatter (formatter.py) — deterministic message formatting
    - Telegram client (telegram.py) — async delivery with retry/dedup
    - Repository (repository.py) — persistence of events and delivery audit trail

The service:
    - Persists every received event as a NotificationEvent record
    - Formats the message using deterministic templates
    - Delivers via configured channels (Telegram first, extensible)
    - Persists delivery attempts as NotificationDeliveryRecord entries
    - Routes by severity: CRITICAL → send to all approved chat IDs
    - Logs every action for audit trail
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from core.enums import NotificationSeverity, NotificationType
from data.models.notification import NotificationDeliveryRecord, NotificationEvent
from notifications.events import NotificationEventBus
from notifications.formatter import format_notification
from notifications.repository import (
    NotificationDeliveryRepository,
    NotificationEventRepository,
)
from notifications.telegram import TelegramClient, TelegramDeliveryResult
from notifications.types import NotificationEnvelope

_log = structlog.get_logger(component="notification_service")


class NotificationService:
    """Orchestrates notification event processing: persist → format → deliver → audit.

    Args:
        event_bus: The notification event bus to subscribe to.
        telegram_client: Async Telegram client for delivery.
        session_factory: Async session factory for database persistence.
            Expected to be a callable returning AsyncSession context manager.
    """

    def __init__(
        self,
        *,
        event_bus: NotificationEventBus,
        telegram_client: TelegramClient,
        session_factory: Any = None,
    ) -> None:
        self._event_bus = event_bus
        self._telegram = telegram_client
        self._session_factory = session_factory
        self._started = False

    def start(self) -> None:
        """Subscribe to all event types on the bus.

        Call once during application startup.
        """
        if self._started:
            return

        # Subscribe to every event type
        for event_type in NotificationType:
            self._event_bus.subscribe(event_type, self._handle_event)

        self._started = True
        _log.info("notification_service_started")

    async def _handle_event(self, envelope: NotificationEnvelope) -> None:
        """Process a single notification event.

        Steps:
            1. Persist the event
            2. Format the message
            3. Deliver via Telegram
            4. Persist delivery result
        """
        _log.info(
            "notification_processing",
            event_id=envelope.event_id,
            event_type=envelope.event_type.value,
            severity=envelope.severity.value,
        )

        # Step 1: Persist the event
        event_db_id = await self._persist_event(envelope)

        # Step 2: Format the message
        message = format_notification(envelope)

        # Step 3: Deliver via Telegram
        delivery_results = await self._deliver_telegram(envelope, message)

        # Step 4: Persist delivery records
        await self._persist_delivery_records(event_db_id, delivery_results)

        _log.info(
            "notification_processed",
            event_id=envelope.event_id,
            event_type=envelope.event_type.value,
            deliveries=len(delivery_results),
            all_successful=all(r.success for r in delivery_results),
        )

    async def _persist_event(
        self,
        envelope: NotificationEnvelope,
    ) -> uuid.UUID | None:
        """Persist the notification event to the database."""
        if self._session_factory is None:
            return None

        try:
            async with self._session_factory() as session:
                repo = NotificationEventRepository(session)
                event = NotificationEvent(
                    event_type=envelope.event_type.value,
                    severity=envelope.severity.value,
                    market_id=(
                        uuid.UUID(envelope.market_id)
                        if envelope.market_id
                        else None
                    ),
                    position_id=(
                        uuid.UUID(envelope.position_id)
                        if envelope.position_id
                        else None
                    ),
                    workflow_run_id=(
                        uuid.UUID(envelope.workflow_run_id)
                        if envelope.workflow_run_id
                        else None
                    ),
                    title=f"{envelope.event_type.value} - {envelope.severity.value}",
                    body=format_notification(envelope),
                    payload=envelope.payload,
                    dedup_key=envelope.dedup_key,
                    emitted_at=envelope.timestamp,
                )
                await repo.create(event)
                await session.commit()

                _log.debug(
                    "notification_event_persisted",
                    event_id=envelope.event_id,
                    db_id=str(event.id),
                )
                return event.id

        except Exception as exc:
            _log.error(
                "notification_event_persist_failed",
                event_id=envelope.event_id,
                error=str(exc),
            )
            return None

    async def _deliver_telegram(
        self,
        envelope: NotificationEnvelope,
        message: str,
    ) -> list[TelegramDeliveryResult]:
        """Deliver message via Telegram.

        CRITICAL severity → send to all approved chat IDs.
        Other severities → send to default chat ID.
        """
        if not self._telegram.enabled:
            _log.debug("telegram_delivery_skipped_disabled")
            return []

        if envelope.severity == NotificationSeverity.CRITICAL:
            # Critical: deliver to ALL approved channels
            results = await self._telegram.send_to_all_approved(
                message,
                dedup_key=envelope.dedup_key,
            )
        else:
            # Non-critical: deliver to default chat
            result = await self._telegram.send_message(
                message,
                dedup_key=envelope.dedup_key,
            )
            results = [result]

        return results

    async def _persist_delivery_records(
        self,
        event_db_id: uuid.UUID | None,
        delivery_results: list[TelegramDeliveryResult],
    ) -> None:
        """Persist delivery attempt records to the database."""
        if self._session_factory is None or event_db_id is None:
            return
        if not delivery_results:
            return

        try:
            async with self._session_factory() as session:
                repo = NotificationDeliveryRepository(session)

                for result in delivery_results:
                    status = "sent" if result.success else "failed"
                    if result.error and "Deduplicated" in result.error:
                        status = "deduplicated"

                    record = NotificationDeliveryRecord(
                        notification_event_id=event_db_id,
                        channel="telegram",
                        status=status,
                        attempts=result.attempts,
                        channel_message_id=result.message_id,
                        error_message=result.error,
                        first_attempt_at=result.first_attempt_at,
                        last_attempt_at=result.last_attempt_at,
                        delivered_at=result.delivered_at,
                    )
                    await repo.create(record)

                await session.commit()

                _log.debug(
                    "delivery_records_persisted",
                    event_db_id=str(event_db_id),
                    record_count=len(delivery_results),
                )

        except Exception as exc:
            _log.error(
                "delivery_record_persist_failed",
                event_db_id=str(event_db_id) if event_db_id else None,
                error=str(exc),
            )

    async def shutdown(self) -> None:
        """Graceful shutdown: close the Telegram client."""
        await self._telegram.close()
        _log.info("notification_service_shutdown")

    # --- Direct convenience methods for workflows ---

    async def notify(self, envelope: NotificationEnvelope) -> None:
        """Directly handle a notification without going through the bus.

        Useful for workflows that want to emit+deliver in a single call.
        The event bus is still the preferred path for decoupled systems.
        """
        await self._handle_event(envelope)

    async def publish(self, envelope: NotificationEnvelope) -> None:
        """Publish an event through the event bus.

        Preferred for decoupled notification delivery.
        """
        await self._event_bus.publish(envelope)
