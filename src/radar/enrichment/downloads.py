"""Weekly download counts for package-mapped projects (PyPI / npm)."""

from __future__ import annotations

from typing import Any, Protocol

from radar.enrichment.retry import get_with_retry
from radar.models import PackageRef


PYPISTATS_URL = "https://pypistats.org/api/packages/{name}/recent"
NPM_DOWNLOADS_URL = "https://api.npmjs.org/downloads/point/last-week/{name}"


class _AsyncClient(Protocol):
    async def get(self, url: str, **kwargs: Any) -> Any: ...


async def fetch_weekly_downloads(
    package: PackageRef,
    client: _AsyncClient,
) -> int | None:
    """Last-week download count, or None for unsupported ecosystems.

    pypistats rate-limits a burst of per-package calls with HTTP 429; the shared
    retry helper honors Retry-After before giving up, and the caller degrades a
    raised error to a logged warning.
    """
    ecosystem = package.ecosystem.lower()
    if ecosystem == "pypi":
        response = await get_with_retry(
            client, PYPISTATS_URL.format(name=package.name), label="downloads pypi"
        )
        data = response.json().get("data") or {}
        value = data.get("last_week")
        return int(value) if value is not None else None
    if ecosystem == "npm":
        response = await get_with_retry(
            client, NPM_DOWNLOADS_URL.format(name=package.name), label="downloads npm"
        )
        value = response.json().get("downloads")
        return int(value) if value is not None else None
    return None
