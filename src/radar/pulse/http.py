"""HTTP calls with retries for transient and rate-limit responses.

429 and 5xx (including 529 "overloaded", which Jev and Anthropic use) are
retried with exponential backoff and jitter, honoring ``Retry-After``. On the
final attempt the response's own ``raise_for_status`` decides. Callers catch
and degrade; nothing here swallows an error.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from typing import Any


logger = logging.getLogger(__name__)

MAX_RETRIES = 4
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504, 529})
RETRY_BASE_SECONDS = 0.5
RETRY_MAX_SLEEP_SECONDS = 30.0


async def get_with_retry(client: Any, url: str, *, label: str = "request", **kwargs: Any) -> Any:
    return await _retry_loop(lambda: client.get(url, **kwargs), label)


async def post_with_retry(client: Any, url: str, *, label: str = "request", **kwargs: Any) -> Any:
    return await _retry_loop(lambda: client.post(url, **kwargs), label)


async def _retry_loop(send: Callable[[], Awaitable[Any]], label: str) -> Any:
    for attempt in range(MAX_RETRIES + 1):
        response = await send()
        status = getattr(response, "status_code", 200)
        if status not in RETRYABLE_STATUS or attempt == MAX_RETRIES:
            response.raise_for_status()
            return response
        delay = _retry_delay(response, attempt)
        logger.warning("%s returned HTTP %s; retry %d/%d in %.1fs",
                       label, status, attempt + 1, MAX_RETRIES, delay)
        await asyncio.sleep(delay)
    raise RuntimeError("retry loop exited without a response")  # unreachable


def _retry_delay(response: Any, attempt: int) -> float:
    headers = getattr(response, "headers", None) or {}
    retry_after = headers.get("Retry-After")
    if retry_after is not None:
        try:
            return min(float(retry_after), RETRY_MAX_SLEEP_SECONDS)
        except (TypeError, ValueError):
            pass
    backoff = RETRY_BASE_SECONDS * (2**attempt)
    return min(backoff + random.uniform(0, RETRY_BASE_SECONDS), RETRY_MAX_SLEEP_SECONDS)
