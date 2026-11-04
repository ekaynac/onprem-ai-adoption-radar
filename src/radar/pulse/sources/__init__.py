"""Pulse sources. Each fetcher returns a ``SourceRun``; mappers are pure.

A dead source shows up as a dead source: errors are reported per request,
never hidden, and land in ``data/pulse/health.json`` and on the site.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from radar.pulse.items import PulseItem


@dataclass(frozen=True)
class SourceRun:
    """What one source produced this run; ``errors`` is empty when healthy."""

    source: str
    items: tuple[PulseItem, ...]
    requests: int
    errors: tuple[str, ...] = field(default_factory=tuple)

    @property
    def status(self) -> str:
        if not self.errors:
            return "ok"
        return "error" if len(self.errors) >= self.requests else "partial"


def error_text(exc: BaseException) -> str:
    """One short line for health.json; httpx errors span several lines."""
    message = str(exc).splitlines()[0][:160] if str(exc) else ""
    return f"{type(exc).__name__}: {message}".rstrip(": ")
