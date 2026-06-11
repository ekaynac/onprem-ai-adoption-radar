"""Base collector interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from radar.models import Signal


class BaseCollector(ABC):
    """Fetch signals published after a point in time."""

    @abstractmethod
    async def fetch(self, since: datetime) -> list[Signal]:
        """Return normalized signals."""
