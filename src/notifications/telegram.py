"""Async Telegram bot client.

Handles message delivery to pre-approved chat IDs with:
- Retry with exponential backoff on failure
- Deduplication within a configurable time window
- Delivery status tracking
- Security: only sends to pre-approved recipients
- Never exposes secrets in messages

Uses httpx for async HTTP requests to the Telegram Bot API
rather than requiring the full python-telegram-bot library,
keeping the dependency footprint small.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from typing import Any

import httpx
import structlog

from config.settings import TelegramConfig

_log = structlog.get_logger(component="telegram_client")

# Telegram Bot API base URL
TELEGRAM_API_BASE = "https://api.telegram.org"

# Telegram message length limit
TELEGRAM_MAX_LENGTH = 4096


class TelegramDeliveryResult:
    """Result of a Telegram message delivery attempt."""

    def __init__(
        self,
        *,
        success: bool,
        message_id: str | None = None,
        chat_id: str = "",
        attempts: int = 0,
        error: str | None = None,
        first_attempt_at: datetime | None = None,
        last_attempt_at: datetime | None = None,
        delivered_at: datetime | None = None,
    ) -> None:
        self.success = success
        self.message_id = message_id
        self.chat_id = chat_id
        self.attempts = attempts
        self.error = error
        self.first_attempt_at = first_attempt_at
        self.last_attempt_at = last_attempt_at
        self.delivered_at = delivered_at


class TelegramClient:
    """Async Telegram bot client for notification delivery.

    Args:
        config: Telegram configuration with bot token and chat IDs.
        http_client: Optional injected httpx client for testing.
        max_retries: Maximum delivery attempts per message.
        retry_base_delay: Base delay between retries (seconds).
        dedup_window_seconds: Time window for deduplication (seconds).
    """

    def __init__(
        self,
        config: TelegramConfig,
        *,
        http_client: httpx.AsyncClient | None = None,
        max_retries: int = 3,
        retry_base_delay: float = 1.0,
        dedup_window_seconds: int = 300,
    ) -> None:
        self._config = config
        self._http_client = http_client
        self._owns_client = http_client is None
        self._max_retries = max_retries
        self._retry_base_delay = retry_base_delay
        self._dedup_window = dedup_window_seconds

        # Dedup tracking: key -> last send timestamp
        self._dedup_log: dict[str, float] = {}

        # Approved chat IDs (parsed from comma-separated config)
        self._approved_chat_ids: set[str] = set()
        if config.chat_id:
            self._approved_chat_ids = {
                cid.strip() for cid in config.chat_id.split(",") if cid.strip()
            }

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=30.0)
        return self._http_client

    async def close(self) -> None:
        """Close the HTTP client if we own it."""
        if self._owns_client and self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    @property
    def enabled(self) -> bool:
        """Whether Telegram delivery is enabled."""
        return self._config.enabled and bool(self._config.bot_token)

    def _is_approved_chat(self, chat_id: str) -> bool:
        """Check if a chat ID is pre-approved for delivery."""
        return chat_id in self._approved_chat_ids

    def _is_duplicate(self, dedup_key: str | None) -> bool:
        """Check if a message is a duplicate within the dedup window."""
        if not dedup_key:
            return False

        now = time.monotonic()
        last_sent = self._dedup_log.get(dedup_key)
        if last_sent is not None and (now - last_sent) < self._dedup_window:
            return True

        # Clean old entries
        cutoff = now - self._dedup_window
        self._dedup_log = {
            k: v for k, v in self._dedup_log.items() if v > cutoff
        }
        return False

    def _record_dedup(self, dedup_key: str | None) -> None:
        """Record a successful send for deduplication tracking."""
        if dedup_key:
            self._dedup_log[dedup_key] = time.monotonic()

    def _truncate_message(self, text: str) -> str:
        """Truncate message to Telegram's max length."""
        if len(text) <= TELEGRAM_MAX_LENGTH:
            return text
        return text[: TELEGRAM_MAX_LENGTH - 20] + "\n... (truncated)"

    async def send_message(
        self,
        text: str,
        *,
        chat_id: str | None = None,
        dedup_key: str | None = None,
        parse_mode: str = "Markdown",
    ) -> TelegramDeliveryResult:
        """Send a message via Telegram Bot API.

        Args:
            text: Message text.
            chat_id: Target chat ID (must be pre-approved). Uses default if None.
            dedup_key: Optional deduplication key.
            parse_mode: Telegram parse mode (Markdown or HTML).

        Returns:
            TelegramDeliveryResult with delivery status.
        """
        if not self.enabled:
            _log.debug("telegram_disabled")
            return TelegramDeliveryResult(
                success=False,
                error="Telegram not enabled",
            )

        target_chat = chat_id or (
            next(iter(self._approved_chat_ids)) if self._approved_chat_ids else ""
        )

        if not target_chat:
            _log.warning("telegram_no_chat_id")
            return TelegramDeliveryResult(
                success=False,
                error="No chat ID configured",
            )

        # Security: reject unknown recipients
        if not self._is_approved_chat(target_chat):
            _log.warning(
                "telegram_unapproved_chat",
                chat_id=target_chat,
            )
            return TelegramDeliveryResult(
                success=False,
                chat_id=target_chat,
                error=f"Chat ID not approved: {target_chat}",
            )

        # Deduplication check
        if self._is_duplicate(dedup_key):
            _log.debug(
                "telegram_dedup_suppressed",
                dedup_key=dedup_key,
            )
            return TelegramDeliveryResult(
                success=True,
                chat_id=target_chat,
                error="Deduplicated — suppressed",
            )

        text = self._truncate_message(text)

        # Retry loop with exponential backoff
        first_attempt: datetime | None = None
        last_attempt: datetime | None = None
        last_error: str | None = None

        for attempt in range(1, self._max_retries + 1):
            now = datetime.now(tz=UTC)
            if first_attempt is None:
                first_attempt = now
            last_attempt = now

            try:
                client = await self._get_client()
                url = f"{TELEGRAM_API_BASE}/bot{self._config.bot_token}/sendMessage"

                response = await client.post(
                    url,
                    json={
                        "chat_id": target_chat,
                        "text": text,
                        "parse_mode": parse_mode,
                    },
                )

                if response.status_code == 200:
                    data = response.json()
                    telegram_msg_id = str(data.get("result", {}).get("message_id", ""))

                    self._record_dedup(dedup_key)

                    _log.info(
                        "telegram_sent",
                        chat_id=target_chat,
                        message_id=telegram_msg_id,
                        attempt=attempt,
                    )

                    return TelegramDeliveryResult(
                        success=True,
                        message_id=telegram_msg_id,
                        chat_id=target_chat,
                        attempts=attempt,
                        first_attempt_at=first_attempt,
                        last_attempt_at=last_attempt,
                        delivered_at=now,
                    )

                # Non-200: log and retry
                last_error = f"HTTP {response.status_code}: {response.text[:200]}"
                _log.warning(
                    "telegram_send_failed",
                    attempt=attempt,
                    status_code=response.status_code,
                    error=last_error,
                )

                # Telegram rate limit: respect Retry-After header
                if response.status_code == 429:
                    retry_after = response.json().get("parameters", {}).get(
                        "retry_after", self._retry_base_delay * attempt
                    )
                    await asyncio.sleep(retry_after)
                    continue

            except Exception as exc:
                last_error = str(exc)
                _log.error(
                    "telegram_send_error",
                    attempt=attempt,
                    error=last_error,
                )

            # Exponential backoff
            if attempt < self._max_retries:
                delay = self._retry_base_delay * (2 ** (attempt - 1))
                await asyncio.sleep(delay)

        # All retries exhausted
        _log.error(
            "telegram_all_retries_exhausted",
            chat_id=target_chat,
            attempts=self._max_retries,
            error=last_error,
        )

        return TelegramDeliveryResult(
            success=False,
            chat_id=target_chat,
            attempts=self._max_retries,
            error=last_error,
            first_attempt_at=first_attempt,
            last_attempt_at=last_attempt,
        )

    async def send_to_all_approved(
        self,
        text: str,
        *,
        dedup_key: str | None = None,
        parse_mode: str = "Markdown",
    ) -> list[TelegramDeliveryResult]:
        """Send a message to all pre-approved chat IDs.

        Used for critical alerts that should reach every approved recipient.

        Returns:
            List of delivery results, one per chat ID.
        """
        results = []
        for chat_id in self._approved_chat_ids:
            result = await self.send_message(
                text,
                chat_id=chat_id,
                dedup_key=f"{dedup_key}:{chat_id}" if dedup_key else None,
                parse_mode=parse_mode,
            )
            results.append(result)
        return results
