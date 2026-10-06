"""One Pulse collection pass: fetch, adapt, merge, persist, report."""

from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from radar.pulse.adapters import news_items, repo_items
from radar.pulse.cards import fetch_card_summary
from radar.pulse.config import PulseConfig
from radar.pulse.items import Lane, PulseItem
from radar.pulse.sources import SourceRun, fetch_daily_papers, fetch_lab_models
from radar.pulse.store import load_items, merge_items, save_items


ITEMS_PATH = Path("data") / "pulse" / "items.jsonl"
TRENDING_PATH = Path("data") / "trending-observations.jsonl"
NEWS_PATH = Path("data") / "news-observations.jsonl"


@dataclass(frozen=True)
class CollectReport:
    runs: tuple[SourceRun, ...]
    items: tuple[PulseItem, ...]
    cards_added: int = 0

    @property
    def lane_counts(self) -> dict[str, int]:
        return dict(Counter(i.lane.value for i in self.items))

    @property
    def model_origin_counts(self) -> dict[str, int]:
        return dict(Counter(i.kind or "?" for i in self.items if i.lane.value == "model"))

    @property
    def all_network_sources_failed(self) -> bool:
        return bool(self.runs) and all(run.status == "error" for run in self.runs)


async def collect(
    root: Path,
    config: PulseConfig,
    client: Any,
    now: datetime,
    hf_headers: dict[str, str] | None = None,
) -> CollectReport:
    models = await fetch_lab_models(
        client, config.models.lab_orgs, config.models.per_org_limit,
        config.lab_org_set, now, headers=hf_headers,
    )
    papers = await fetch_daily_papers(client, config.papers.daily_papers_limit, now)
    incoming = [
        *models.items,
        *papers.items,
        *repo_items(root / TRENDING_PATH, now, config.window_days),
        *news_items(root / NEWS_PATH, now, config.window_days),
    ]
    store_path = root / ITEMS_PATH
    merged = merge_items(load_items(store_path), incoming, now, config.window_days)
    merged, cards_added = await add_card_summaries(
        merged, client, config.models.card_limit, hf_headers,
    )
    save_items(store_path, merged)
    return CollectReport(runs=(models, papers), items=tuple(merged), cards_added=cards_added)


CARD_CONCURRENCY = 6


async def add_card_summaries(
    items: list[PulseItem],
    client: Any,
    limit: int,
    hf_headers: dict[str, str] | None = None,
) -> tuple[list[PulseItem], int]:
    """Fill missing summaries of release-like models from their Hub cards.

    Variants and derivatives are skipped (their card repeats the parent's);
    newest first, at most ``limit`` cards per run; a failed fetch leaves the
    item as it was and is retried next run.
    """
    wanted = sorted(
        (i for i in items
         if i.lane is Lane.MODEL and i.kind in ("original", "unknown") and not i.summary),
        key=lambda i: i.published_at or i.first_seen, reverse=True,
    )[:limit]
    if not wanted:
        return items, 0
    semaphore = asyncio.Semaphore(CARD_CONCURRENCY)

    async def one(item: PulseItem) -> tuple[str, str | None]:
        async with semaphore:
            return item.id, await fetch_card_summary(client, item.key, hf_headers)

    found = {key: text for key, text in await asyncio.gather(*(one(i) for i in wanted)) if text}
    updated = [i.model_copy(update={"summary": found[i.id]}) if i.id in found else i for i in items]
    return updated, len(found)
