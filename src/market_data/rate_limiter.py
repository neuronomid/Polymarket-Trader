"""Async rate limiter and retry policy for Polymarket API clients.

AsyncRateLimiter: sliding-window token bucket.
RetryPolicy: exponential backoff on 429 and 5xx responses.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import Any, Callable, TypeVar

import httpx

import structlog

T = TypeVar("T")


class AsyncRateLimiter:
    """Sliding-window rate limiter for async HTTP clients.

    Tracks request timestamps in a deque. When the window is full,
    waits until the oldest request slides out of the window.
    """

    def __init__(self, max_requests: int, window_seconds: float = 10.0) -> None:
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._timestamps: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Wait until a request slot is available, then record the request."""
        async with self._lock:
            now = time.monotonic()
            self._evict_expired(now)

            if len(self._timestamps) >= self._max_requests:
                oldest = self._timestamps[0]
                wait_time = self._window_seconds - (now - oldest)
                if wait_time > 0:
                    await asyncio.sleep(wait_time)
                    now = time.monotonic()
                    self._evict_expired(now)

            self._timestamps.append(now)

    def _evict_expired(self, now: float) -> None:
        """Remove timestamps older than the sliding window."""
        cutoff = now - self._window_seconds
        while self._timestamps and self._timestamps[0] < cutoff:
            self._timestamps.popleft()

    @property
    def current_usage(self) -> int:
        """Number of requests in the current window (approximate)."""
        self._evict_expired(time.monotonic())
        return len(self._timestamps)


class RetryPolicy:
    """Exponential backoff retry wrapper for async HTTP calls.

    Retries on 429 (rate limited) and 5xx (server error) responses.
    Raises the last exception after max_retries exhausted.
    """

    def __init__(
        self,
        max_retries: int = 3,
        backoff_base: float = 1.0,
        backoff_max: float = 30.0,
    ) -> None:
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._backoff_max = backoff_max

    async def execute(
        self,
        func: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Execute an async function with retry on transient failures.

        The function should raise httpx.HTTPStatusError on non-2xx responses.
        """
        last_exc: Exception | None = None

        for attempt in range(self._max_retries + 1):
            try:
                return await func(*args, **kwargs)
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if status == 429 or status >= 500:
                    last_exc = exc
                    if attempt < self._max_retries:
                        delay = min(
                            self._backoff_base * (2**attempt),
                            self._backoff_max,
                        )
                        structlog.get_logger(component="rate_limiter").warning(
                            "retry_backoff",
                            attempt=attempt + 1,
                            max_retries=self._max_retries,
                            status_code=status,
                            delay_seconds=delay,
                        )
                        await asyncio.sleep(delay)
                        continue
                # Non-retryable status code — raise immediately
                raise
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout) as exc:
                last_exc = exc
                if attempt < self._max_retries:
                    delay = min(
                        self._backoff_base * (2**attempt),
                        self._backoff_max,
                    )
                    structlog.get_logger(component="rate_limiter").warning(
                        "retry_backoff_connection",
                        attempt=attempt + 1,
                        max_retries=self._max_retries,
                        error=str(exc),
                        delay_seconds=delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                raise

        # Should not reach here, but just in case
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("RetryPolicy exhausted without result or exception")
