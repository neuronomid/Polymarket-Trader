"""Internal event bus for notification delivery.

Decoupled pub/sub system: workflows emit typed events, the notification
service subscribes to event types it cares about. Trading logic never
touches Telegram or any delivery channel directly.

Design:
    - In-process asyncio-based event bus (no external broker needed)
    - Type-safe subscriptions via NotificationType enum
    - Async handler callbacks
    - Logging of every event emission and handler invocation
    - Designed for channel expansion without rewriting business logic
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any, Awaitable, Callable

import structlog

from core.enums import NotificationType
from notifications.types import NotificationEnvelope

_log = structlog.get_logger(component="event_bus")

# Handler signature: async (envelope) -> None
EventHandler = Callable[[NotificationEnvelope], Awaitable[None]]


class NotificationEventBus:
    """In-process async event bus for notification events.

    Workflows publish events; the notification service subscribes to
    specific event types and receives them asynchronously.

    Usage::

        bus = NotificationEventBus()

        async def on_trade_entry(envelope: NotificationEnvelope):
            await send_telegram(envelope)

        bus.subscribe(NotificationType.TRADE_ENTRY, on_trade_entry)
        await bus.publish(envelope)  # handler invoked asynchronously
    """

    def __init__(self) -> None:
        self._handlers: dict[NotificationType, list[EventHandler]] = defaultdict(list)
        self._global_handlers: list[EventHandler] = []
        self._event_count: int = 0

    def subscribe(
        self,
        event_type: NotificationType,
        handler: EventHandler,
    ) -> None:
        """Subscribe a handler to a specific event type."""
        self._handlers[event_type].append(handler)
        _log.info(
            "event_bus_subscribe",
            event_type=event_type.value,
            handler=handler.__qualname__,
        )

    def subscribe_all(self, handler: EventHandler) -> None:
        """Subscribe a handler to all event types (e.g., for logging)."""
        self._global_handlers.append(handler)
        _log.info(
            "event_bus_subscribe_all",
            handler=handler.__qualname__,
        )

    def unsubscribe(
        self,
        event_type: NotificationType,
        handler: EventHandler,
    ) -> None:
        """Remove a handler subscription."""
        handlers = self._handlers.get(event_type, [])
        if handler in handlers:
            handlers.remove(handler)

    async def publish(self, envelope: NotificationEnvelope) -> None:
        """Publish an event to all subscribed handlers.

        Handlers are invoked concurrently via asyncio.gather.
        Failures in individual handlers are logged but do not
        prevent other handlers from executing.
        """
        self._event_count += 1

        _log.info(
            "event_bus_publish",
            event_id=envelope.event_id,
            event_type=envelope.event_type.value,
            severity=envelope.severity.value,
            market_id=envelope.market_id,
            event_number=self._event_count,
        )

        # Collect all relevant handlers
        handlers: list[EventHandler] = []
        handlers.extend(self._handlers.get(envelope.event_type, []))
        handlers.extend(self._global_handlers)

        if not handlers:
            _log.debug(
                "event_bus_no_handlers",
                event_type=envelope.event_type.value,
                event_id=envelope.event_id,
            )
            return

        # Execute all handlers concurrently
        tasks = [self._safe_invoke(handler, envelope) for handler in handlers]
        await asyncio.gather(*tasks)

    async def _safe_invoke(
        self,
        handler: EventHandler,
        envelope: NotificationEnvelope,
    ) -> None:
        """Invoke a handler with error isolation."""
        try:
            await handler(envelope)
        except Exception as exc:
            _log.error(
                "event_bus_handler_error",
                handler=handler.__qualname__,
                event_id=envelope.event_id,
                event_type=envelope.event_type.value,
                error=str(exc),
            )

    @property
    def event_count(self) -> int:
        """Total events published since bus creation."""
        return self._event_count

    @property
    def subscription_count(self) -> int:
        """Total number of active subscriptions."""
        total = sum(len(h) for h in self._handlers.values())
        total += len(self._global_handlers)
        return total
