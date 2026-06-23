"""Shared HTTP GET-with-retry for enrichers that hit rate-limited APIs.

Retries transient / rate-limit statuses (429 + 5xx) honoring ``Retry-After``,
with exponential backoff + jitter; on the final attempt the response's own
``raise_for_status`` decides success vs. failure. A response without a
``status_code`` attribute is treated as success so lightweight test fakes keep
working. Callers degrade a raised error to a logged warning (the enrichment
``_safe`` wrapper), so this never has to swallow exceptions itself.
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any, Protocol


logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
RETRY_BASE_SECONDS = 0.5
RETRY_MAX_SLEEP_SECONDS = 5.0


class _AsyncClient(Protocol):
    async def get(self, url: str, **kwargs: Any) -> Any: ...


async def get_with_retry(
    client: _AsyncClient,
    url: str,
    *,
    label: str = "request",
    **kwargs: Any,
) -> Any:
    """GET ``url`` (passing ``kwargs`` through), retrying 429/5xx before raising.

    ``label`` only colors the retry log line. Extra kwargs (``params``,
    ``follow_redirects``, ...) are forwarded verbatim to ``client.get``.
    """
    for attempt in range(MAX_RETRIES + 1):
        response = await client.get(url, **kwargs)
        status = getattr(response, "status_code", 200)
        if status not in RETRYABLE_STATUS or attempt == MAX_RETRIES:
            response.raise_for_status()
            return response
        delay = _retry_delay(response, attempt)
        logger.warning(
            "%s returned HTTP %s; retry %d/%d in %.1fs",
            label,
            status,
            attempt + 1,
            MAX_RETRIES,
            delay,
        )
        await asyncio.sleep(delay)
    # Unreachable: the loop always returns or raises on the last attempt.
    raise RuntimeError("retry loop exited without a response")


def _retry_delay(response: Any, attempt: int) -> float:
    """Seconds to wait: honor Retry-After if present, else backoff + jitter."""
    headers = getattr(response, "headers", None) or {}
    retry_after = headers.get("Retry-After")
    if retry_after is not None:
        try:
            return min(float(retry_after), RETRY_MAX_SLEEP_SECONDS)
        except (TypeError, ValueError):
            pass
    backoff = RETRY_BASE_SECONDS * (2**attempt)
    jitter = random.uniform(0, RETRY_BASE_SECONDS)
    return min(backoff + jitter, RETRY_MAX_SLEEP_SECONDS)
