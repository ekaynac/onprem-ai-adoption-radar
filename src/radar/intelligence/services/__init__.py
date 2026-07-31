"""Transport-independent intelligence application contracts."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class Page[T](BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    items: list[T]
    next_cursor: str | None = None


__all__ = ["Page"]
