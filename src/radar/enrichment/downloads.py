"""Weekly download counts for package-mapped projects (PyPI / npm)."""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any, Protocol

from radar.models import PackageRef


logger = logging.getLogger(__name__)

PYPISTATS_URL = "https://pypistats.org/api/packages/{name}/recent"
NPM_DOWNLOADS_URL = "https://api.npmjs.org/downloads/point/last-week/{name}"

# pypistats rate-limits a burst of per-package calls with HTTP 429. Retry a few
# times honoring Retry-After (with backoff + jitter) before giving up; the caller
# already degrades a None to a logged warning.
DOWNLOADS_MAX_RETRIES = 3
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
RETRY_BASE_SECONDS = 0.5
RETRY_MAX_SLEEP_SECONDS = 5.0


class _AsyncClient(Protocol):
    async def get(self, url: str, **kwargs: Any) -> Any: ...


async def fetch_weekly_downloads(
    package: PackageRef,
    client: _AsyncClient,
) -> int | None:
    """Last-week download count, or None for unsupported ecosystems."""
    ecosystem = package.ecosystem.lower()
    if ecosystem == "pypi":
        response = await _get_with_retry(client, PYPISTATS_URL.format(name=package.name))
        data = response.json().get("data") or {}
        value = data.get("last_week")
        return int(value) if value is not None else None
    if ecosystem == "npm":
        response = await _get_with_retry(
            client, NPM_DOWNLOADS_URL.format(name=package.name)
        )
        value = response.json().get("downloads")
        return int(value) if value is not None else None
    return None


async def _get_with_retry(client: _AsyncClient, url: str) -> Any:
    """GET ``url``, retrying transient/rate-limit statuses before raising.

    A response without a ``status_code`` attribute is treated as success, so
    lightweight fakes keep working. On the final attempt the response's own
    ``raise_for_status`` decides success vs. failure (the caller degrades any
    raised error to a logged warning).
    """
    for attempt in range(DOWNLOADS_MAX_RETRIES + 1):
        response = await client.get(url)
        status = getattr(response, "status_code", 200)
        if status not in RETRYABLE_STATUS or attempt == DOWNLOADS_MAX_RETRIES:
            response.raise_for_status()
            return response
        delay = _retry_delay(response, attempt)
        logger.warning(
            "downloads %s returned HTTP %s; retry %d/%d in %.1fs",
            url,
            status,
            attempt + 1,
            DOWNLOADS_MAX_RETRIES,
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
