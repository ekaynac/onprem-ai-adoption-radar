"""Presentation helper: render a project's backer as a compact badge.

Pure and dependency-free so both the live dashboard (FastAPI) and the static
export share one source of truth for how a provider/backer is shown. Templates
call ``backer_badge(card.backer)`` and get a small dict they can render.
"""

from __future__ import annotations

from dataclasses import dataclass

from radar.models import Backer, BackerType


# Emoji + human label per backer type. Kept here (not in templates) so the live
# and static sites can never drift on how a provider is presented.
_DISPLAY: dict[BackerType, tuple[str, str]] = {
    BackerType.BIG_TECH: ("🏢", "Big Tech"),
    BackerType.STARTUP: ("🚀", "Startup"),
    BackerType.COMMUNITY: ("🌐", "Community"),
    BackerType.INDIVIDUAL: ("👤", "Individual"),
    BackerType.ACADEMIC: ("🎓", "Academic"),
}


@dataclass(frozen=True)
class BackerBadge:
    """A renderable backer badge."""

    name: str
    type: str  # the BackerType value, for CSS classes / data attributes
    emoji: str
    label: str  # human-readable type label, e.g. "Big Tech"

    @property
    def title(self) -> str:
        """Tooltip text, e.g. "NVIDIA — Big Tech"."""
        return f"{self.name} — {self.label}"


def backer_badge(backer: Backer | None) -> BackerBadge | None:
    """Build a badge for a backer, or ``None`` when unknown.

    Unknown/uncurated backers return ``None`` so templates render nothing rather
    than a misleading placeholder.
    """
    if backer is None:
        return None
    emoji, label = _DISPLAY.get(backer.type, ("•", backer.type.value))
    return BackerBadge(
        name=backer.name,
        type=backer.type.value,
        emoji=emoji,
        label=label,
    )
