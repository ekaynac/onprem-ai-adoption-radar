"""Append-only JSONL stores for the newsroom: raw items + classifications.

Unlike the time-series stores (stars, downloads, benchmarks), news
articles are static documents — re-observing one adds nothing. Both
stores therefore dedupe at write time by stable id: an item or a
classification is written once and never again, which also keeps the
LLM classification budget from re-billing the same article every run.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator


logger = logging.getLogger(__name__)

OPERATIONAL_IMPACTS = ("breaking", "improvement", "informational")

# Closed taxonomy the classifier must pick from; unknown values fail
# schema validation and the item stays unclassified (never on the site).
NEWS_EVENT_TYPES = (
    "release",
    "breaking-change",
    "security-advisory",
    "performance",
    "deprecation",
    "integration",
    "research",
    "community",
    "hardware-launch",
    "other",
)


def news_id_for(url: str) -> str:
    """Stable id derived from the canonical article URL."""
    digest = hashlib.sha256(url.strip().encode("utf-8")).hexdigest()
    return f"news:{digest[:16]}"


class NewsItem(BaseModel):
    """One article as observed from a feed — raw, unclassified."""

    model_config = ConfigDict(frozen=True)

    id: str
    source_id: str
    title: str
    url: str
    summary: str | None = None
    published_at: datetime | None = None
    observed_at: datetime

    @field_validator("published_at", "observed_at")
    @classmethod
    def _ensure_aware(cls, v: datetime | None) -> datetime | None:
        if v is None:
            return None
        return v.replace(tzinfo=UTC) if v.tzinfo is None else v


class NewsClassification(BaseModel):
    """The LLM's structured read of one item, schema-validated.

    ``relevant=False`` marks an item the classifier judged noise for
    on-prem operators — stored so the budget never re-bills it, but
    excluded from every product surface except the raw firehose.
    """

    model_config = ConfigDict(frozen=True)

    news_id: str
    relevant: bool
    event_type: Literal[
        "release",
        "breaking-change",
        "security-advisory",
        "performance",
        "deprecation",
        "integration",
        "research",
        "community",
        "hardware-launch",
        "other",
    ]
    components: list[str]
    operational_impact: Literal["breaking", "improvement", "informational"]
    summary: str
    citation: str
    model: str
    classified_at: datetime

    @field_validator("classified_at")
    @classmethod
    def _ensure_aware(cls, v: datetime) -> datetime:
        return v.replace(tzinfo=UTC) if v.tzinfo is None else v


def _append_jsonl(path: Path, rows: list[str]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(rows) + "\n")


def append_news_items(path: Path, items: list[NewsItem]) -> int:
    """Append only items whose id is not already stored; return count."""
    existing = {item.id for item in load_news_items(path)}
    fresh: list[NewsItem] = []
    seen: set[str] = set()
    for item in items:
        if item.id in existing or item.id in seen:
            continue
        seen.add(item.id)
        fresh.append(item)
    _append_jsonl(
        path,
        [
            json.dumps(item.model_dump(mode="json"), ensure_ascii=False)
            for item in fresh
        ],
    )
    return len(fresh)


def load_news_items(path: Path) -> list[NewsItem]:
    if not path.exists():
        return []
    items: list[NewsItem] = []
    for line_no, raw in enumerate(
        path.read_text(encoding="utf-8", errors="replace").splitlines(),
        start=1,
    ):
        line = raw.strip()
        if not line:
            continue
        try:
            items.append(NewsItem.model_validate_json(line))
        except ValueError as exc:
            logger.warning(
                "Skipping corrupt news item at %s:%d: %s", path, line_no, exc
            )
    return items


def append_news_classifications(
    path: Path, rows: list[NewsClassification]
) -> int:
    """Append only classifications for ids not already classified."""
    existing = {row.news_id for row in load_news_classifications(path)}
    fresh: list[NewsClassification] = []
    seen: set[str] = set()
    for row in rows:
        if row.news_id in existing or row.news_id in seen:
            continue
        seen.add(row.news_id)
        fresh.append(row)
    _append_jsonl(
        path,
        [
            json.dumps(row.model_dump(mode="json"), ensure_ascii=False)
            for row in fresh
        ],
    )
    return len(fresh)


def load_news_classifications(path: Path) -> list[NewsClassification]:
    if not path.exists():
        return []
    rows: list[NewsClassification] = []
    for line_no, raw in enumerate(
        path.read_text(encoding="utf-8", errors="replace").splitlines(),
        start=1,
    ):
        line = raw.strip()
        if not line:
            continue
        try:
            rows.append(NewsClassification.model_validate_json(line))
        except ValueError as exc:
            logger.warning(
                "Skipping corrupt news classification at %s:%d: %s",
                path,
                line_no,
                exc,
            )
    return rows
