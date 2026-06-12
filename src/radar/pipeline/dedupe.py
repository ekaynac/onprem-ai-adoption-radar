"""Signal deduplication."""

from __future__ import annotations

from urllib.parse import urlparse

from radar.models import Signal


def dedupe_signals(signals: list[Signal]) -> list[Signal]:
    """Deduplicate signals by (normalized URL, project), keeping the richest summary.

    The project is part of the key because firehose re-attribution can assign
    entries that share a URL to different projects; URL-only dedupe would drop
    one project's signal entirely.
    """
    groups: dict[tuple[str, str], Signal] = {}
    for signal in signals:
        key = (_normalize_url(str(signal.url)), signal.project)
        current = groups.get(key)
        if current is None or len(signal.raw_summary) > len(current.raw_summary):
            groups[key] = signal
    return list(groups.values())


def _normalize_url(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if host.startswith("www."):
        host = host[4:]
    path = parsed.path.rstrip("/")
    return f"{host}{path}"
