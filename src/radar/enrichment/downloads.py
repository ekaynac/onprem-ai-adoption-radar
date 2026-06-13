"""Weekly download counts for package-mapped projects (PyPI / npm)."""

from __future__ import annotations

from typing import Any, Protocol

from radar.models import PackageRef


PYPISTATS_URL = "https://pypistats.org/api/packages/{name}/recent"
NPM_DOWNLOADS_URL = "https://api.npmjs.org/downloads/point/last-week/{name}"


class _AsyncClient(Protocol):
    async def get(self, url: str, **kwargs: Any) -> Any: ...


async def fetch_weekly_downloads(
    package: PackageRef,
    client: _AsyncClient,
) -> int | None:
    """Last-week download count, or None for unsupported ecosystems."""
    ecosystem = package.ecosystem.lower()
    if ecosystem == "pypi":
        response = await client.get(PYPISTATS_URL.format(name=package.name))
        response.raise_for_status()
        data = response.json().get("data") or {}
        value = data.get("last_week")
        return int(value) if value is not None else None
    if ecosystem == "npm":
        response = await client.get(NPM_DOWNLOADS_URL.format(name=package.name))
        response.raise_for_status()
        value = response.json().get("downloads")
        return int(value) if value is not None else None
    return None
