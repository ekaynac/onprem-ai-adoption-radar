"""One Pulse collection pass: fetch every source, merge, enrich, persist, report."""

from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from radar.pulse.config import PulseConfig
from radar.pulse.health import HEALTH_PATH, record_runs
from radar.pulse.items import Lane, PulseItem
from radar.pulse.sources import SourceRun
from radar.pulse.sources.cards import fetch_card_summary
from radar.pulse.sources.github import fetch_new_repos
from radar.pulse.sources.huggingface import fetch_daily_papers, fetch_lab_models
from radar.pulse.sources.news import fetch_news
from radar.pulse.store import load_items, merge_items, save_items


ITEMS_PATH = Path("data") / "pulse" / "items.jsonl"
CARD_CONCURRENCY = 6


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
        return dict(Counter(i.kind or "?" for i in self.items if i.lane is Lane.MODEL))

    @property
    def all_sources_failed(self) -> bool:
        return bool(self.runs) and all(run.status == "error" for run in self.runs)


async def collect(
    root: Path,
    config: PulseConfig,
    client: Any,
    now: datetime,
    hf_headers: dict[str, str] | None = None,
    github_headers: dict[str, str] | None = None,
) -> CollectReport:
    runs = (
        await fetch_lab_models(client, config.models.lab_orgs, config.models.per_org_limit,
                               config.lab_org_set, now, headers=hf_headers),
        await fetch_daily_papers(client, config.papers.daily_papers_limit, now),
        await fetch_new_repos(client, config.repos.topics, config.repos.min_stars,
                              config.window_days, now, headers=github_headers),
        await fetch_news(client, list(config.news.sources), now),
    )
    store_path = root / ITEMS_PATH
    incoming = [item for run in runs for item in run.items]
    merged = merge_items(load_items(store_path), incoming, now, config.window_days)
    merged, cards_added = await add_card_summaries(
        merged, client, config.models.card_limit, hf_headers,
    )
    save_items(store_path, merged)
    record_runs(root / HEALTH_PATH, runs, now)
    return CollectReport(runs=runs, items=tuple(merged), cards_added=cards_added)


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
