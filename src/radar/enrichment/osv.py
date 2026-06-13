"""OSV.dev security-advisory lookup for package-mapped projects.

A package-level OSV query returns the package's FULL vulnerability history,
so results are windowed to recently-modified advisories — "this project has
current security activity worth reviewing", not "every CVE ever filed".
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Protocol

from radar.models import Advisory, PackageRef


OSV_QUERY_URL = "https://api.osv.dev/v1/query"
MAX_ADVISORIES = 5


class _AsyncClient(Protocol):
    async def post(self, url: str, **kwargs: Any) -> Any: ...


async def fetch_recent_advisories(
    package: PackageRef,
    client: _AsyncClient,
    now: datetime,
    window_days: int,
) -> list[Advisory]:
    """Recently-modified, non-withdrawn advisories for a package (newest first)."""
    response = await client.post(
        OSV_QUERY_URL,
        json={"package": {"ecosystem": package.ecosystem, "name": package.name}},
    )
    response.raise_for_status()
    payload = response.json()

    cutoff = now - timedelta(days=window_days)
    recent: list[tuple[datetime, Advisory]] = []
    for vuln in payload.get("vulns") or []:
        if vuln.get("withdrawn"):
            continue
        modified = _parse_datetime(vuln.get("modified"))
        if modified is None or modified < cutoff:
            continue
        recent.append(
            (
                modified,
                Advisory(
                    id=str(vuln.get("id") or "unknown"),
                    severity=_severity(vuln),
                    summary=str(vuln.get("summary") or "")[:200],
                ),
            )
        )
    recent.sort(key=lambda item: item[0], reverse=True)
    return [advisory for _, advisory in recent[:MAX_ADVISORIES]]


def _severity(vuln: dict[str, Any]) -> str:
    database_specific = vuln.get("database_specific") or {}
    severity = database_specific.get("severity")
    if isinstance(severity, str) and severity:
        return severity.upper()
    return "UNKNOWN"


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
