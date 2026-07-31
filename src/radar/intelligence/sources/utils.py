"""Small deterministic helpers shared by source adapters."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            from email.utils import parsedate_to_datetime

            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
    return parsed.replace(tzinfo=parsed.tzinfo or UTC)


def canonical_url(value: str) -> str:
    parts = urlsplit(value)
    query = urlencode(sorted(parse_qsl(parts.query, keep_blank_values=True)))
    return urlunsplit(
        (
            parts.scheme.casefold(),
            parts.netloc.casefold(),
            parts.path or "/",
            query,
            "",
        )
    )


def url_is_official(url: str, official_domains: list[str]) -> bool:
    hostname = (urlsplit(url).hostname or "").casefold().rstrip(".")
    return any(
        hostname == domain.casefold().rstrip(".")
        or hostname.endswith(f".{domain.casefold().rstrip('.')}")
        for domain in official_domains
    )
