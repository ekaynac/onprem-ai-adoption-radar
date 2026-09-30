"""The one item shape every Pulse lane shares: models, papers, repos, news."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class Lane(StrEnum):
    MODEL = "model"
    PAPER = "paper"
    REPO = "repo"
    NEWS = "news"


class PulseItem(BaseModel):
    """A single thing that happened, normalized across sources.

    ``key`` is the source-native identity (``Qwen/Qwen3.8-27B``, an arXiv id,
    ``owner/repo``, a news id); ``id`` is ``<lane>:<key>`` and is stable across
    runs so re-observations merge instead of duplicating.
    """

    model_config = ConfigDict(frozen=True)

    lane: Lane
    key: str = Field(min_length=1)
    title: str = Field(min_length=1)
    url: HttpUrl
    source: str = Field(min_length=1)
    published_at: datetime | None = None
    first_seen: datetime
    last_seen: datetime
    summary: str | None = None
    kind: str | None = None  # lane-specific: model origin, repo lane, news source...
    parent: str | None = None  # model variants/derivatives point at their release
    signals: dict[str, float] = Field(default_factory=dict)
    tags: tuple[str, ...] = ()

    @property
    def id(self) -> str:
        return f"{self.lane.value}:{self.key}"
