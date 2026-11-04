"""Small text helpers shared by sources and views."""

from __future__ import annotations

from typing import Any


def shorten(text: Any, limit: int = 400) -> str | None:
    """Whitespace-collapsed text cut at ``limit`` with an ellipsis; None if empty."""
    if not isinstance(text, str) or not text.strip():
        return None
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"
