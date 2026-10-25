from __future__ import annotations

"""
Transient-failure retry with exponential backoff + jitter.

Ported from the ollama-local-coding-agent (TypeScript) retry.ts.
"""

import asyncio
import math
import random
from typing import Callable, Awaitable, TypeVar

T = TypeVar("T")

# Retryable HTTP status codes
_RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}

# Retryable network error strings
_RETRYABLE_MSGS = re.compile(
    r"(connection|refused|reset|timed?\s*out|network|fetch\s+failed)",
    re.IGNORECASE,
)

import re


def should_retry(exc: Exception) -> bool:
    """Return True only for transient failures — never for user cancellation."""
    name = type(exc).__name__
    if name in ("KeyboardInterrupt", "SystemExit"):
        return False
    msg = str(exc).lower()
    # Connection/network errors
    if any(k in msg for k in ("connection refused", "connection reset", "timed out",
                               "network", "fetch failed", "econnrefused", "etimedout")):
        return True
    # HTTP status on the exception
    status = getattr(exc, "status", None)
    if isinstance(status, int) and status in _RETRYABLE_STATUS:
        return True
    return False


def backoff_delay(attempt: int, initial: float = 0.5, factor: float = 2.0,
                  max_delay: float = 4.0, jitter: float = 0.25) -> float:
    base = min(max_delay, initial * math.pow(factor, attempt))
    j = base * jitter * (random.random() * 2 - 1)
    return max(0.0, base + j)


async def retry_with_backoff(
    fn: Callable[[], Awaitable[T]],
    max_retries: int = 3,
    initial_delay: float = 0.5,
) -> T:
    """
    Call async fn(), retrying on transient failures with exponential backoff.
    Raises on the last attempt or on a non-retryable error.
    """
    last_exc: Exception = RuntimeError("no attempts made")
    for attempt in range(max_retries + 1):
        try:
            return await fn()
        except Exception as exc:
            last_exc = exc
            if attempt == max_retries or not should_retry(exc):
                raise
            delay = backoff_delay(attempt, initial=initial_delay)
            await asyncio.sleep(delay)
    raise last_exc
