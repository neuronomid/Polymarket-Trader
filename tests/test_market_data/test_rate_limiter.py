"""Tests for async rate limiter and retry policy."""

import asyncio
import time

import httpx
import pytest

from market_data.rate_limiter import AsyncRateLimiter, RetryPolicy


async def test_rate_limiter_allows_within_limit():
    limiter = AsyncRateLimiter(max_requests=5, window_seconds=1.0)

    start = time.monotonic()
    for _ in range(5):
        await limiter.acquire()
    elapsed = time.monotonic() - start

    # 5 requests within limit should be near-instant
    assert elapsed < 0.1


async def test_rate_limiter_blocks_when_full():
    limiter = AsyncRateLimiter(max_requests=3, window_seconds=0.5)

    # Fill the window
    for _ in range(3):
        await limiter.acquire()

    # 4th request should block until window slides
    start = time.monotonic()
    await limiter.acquire()
    elapsed = time.monotonic() - start

    # Should have waited roughly 0.5 seconds for window to slide
    assert elapsed >= 0.3


async def test_rate_limiter_current_usage():
    limiter = AsyncRateLimiter(max_requests=10, window_seconds=1.0)

    assert limiter.current_usage == 0
    await limiter.acquire()
    assert limiter.current_usage == 1
    await limiter.acquire()
    assert limiter.current_usage == 2


async def test_retry_policy_success_first_try():
    call_count = 0

    async def success_func():
        nonlocal call_count
        call_count += 1
        return "ok"

    policy = RetryPolicy(max_retries=3, backoff_base=0.01)
    result = await policy.execute(success_func)

    assert result == "ok"
    assert call_count == 1


async def test_retry_policy_retries_on_429():
    call_count = 0

    async def fail_then_succeed():
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            response = httpx.Response(429, request=httpx.Request("GET", "http://test"))
            raise httpx.HTTPStatusError("rate limited", request=response.request, response=response)
        return "ok"

    policy = RetryPolicy(max_retries=3, backoff_base=0.01)
    result = await policy.execute(fail_then_succeed)

    assert result == "ok"
    assert call_count == 3


async def test_retry_policy_retries_on_500():
    call_count = 0

    async def fail_then_succeed():
        nonlocal call_count
        call_count += 1
        if call_count <= 1:
            response = httpx.Response(500, request=httpx.Request("GET", "http://test"))
            raise httpx.HTTPStatusError("server error", request=response.request, response=response)
        return "ok"

    policy = RetryPolicy(max_retries=3, backoff_base=0.01)
    result = await policy.execute(fail_then_succeed)

    assert result == "ok"
    assert call_count == 2


async def test_retry_policy_raises_on_4xx():
    """Non-429 4xx errors should not be retried."""

    async def bad_request():
        response = httpx.Response(400, request=httpx.Request("GET", "http://test"))
        raise httpx.HTTPStatusError("bad request", request=response.request, response=response)

    policy = RetryPolicy(max_retries=3, backoff_base=0.01)
    with pytest.raises(httpx.HTTPStatusError):
        await policy.execute(bad_request)


async def test_retry_policy_exhausted():
    """Should raise after max retries exhausted."""

    async def always_fail():
        response = httpx.Response(429, request=httpx.Request("GET", "http://test"))
        raise httpx.HTTPStatusError("rate limited", request=response.request, response=response)

    policy = RetryPolicy(max_retries=2, backoff_base=0.01)
    with pytest.raises(httpx.HTTPStatusError):
        await policy.execute(always_fail)


async def test_retry_policy_connection_error():
    call_count = 0

    async def fail_then_succeed():
        nonlocal call_count
        call_count += 1
        if call_count <= 1:
            raise httpx.ConnectError("connection refused")
        return "ok"

    policy = RetryPolicy(max_retries=2, backoff_base=0.01)
    result = await policy.execute(fail_then_succeed)

    assert result == "ok"
    assert call_count == 2
