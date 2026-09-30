"""Pulse's own collectors: newest lab uploads and Hugging Face daily papers.

The model lane cannot lean on the candidate sweep: that sweep drops a model the
moment the catalog autopilot seeds it (Kimi-K3 stopped appearing on
2026-07-31), and it samples by trending score, not by recency. Asking each lab
org for its newest uploads is ~30 cheap requests and cannot miss a release.

Mappers are pure; fetchers only do HTTP and report failures instead of hiding
them, so a dead source shows up as a dead source.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from pydantic import ValidationError

from radar.enrichment.retry import get_with_retry
from radar.pulse.items import Lane, PulseItem
from radar.pulse.lineage import classify_model_origin


logger = logging.getLogger(__name__)

HF_MODELS_URL = "https://huggingface.co/api/models"
HF_DAILY_PAPERS_URL = "https://huggingface.co/api/daily_papers"


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


def model_item(raw: dict[str, Any], lab_orgs: frozenset[str], now: datetime) -> PulseItem | None:
    """Map one ``/api/models`` row; private or malformed rows are dropped."""
    repo_id = raw.get("id") or raw.get("modelId")
    if not isinstance(repo_id, str) or "/" not in repo_id or raw.get("private"):
        return None
    tags = tuple(t for t in raw.get("tags") or () if isinstance(t, str))
    verdict = classify_model_origin(repo_id, tags, lab_orgs)
    pipeline = raw.get("pipeline_tag")
    try:
        return PulseItem(
            lane=Lane.MODEL,
            key=repo_id,
            title=repo_id.split("/", 1)[1],
            url=f"https://huggingface.co/{repo_id}",
            source="huggingface",
            published_at=raw.get("createdAt"),
            first_seen=now,
            last_seen=now,
            kind=verdict.origin.value,
            parent=verdict.parent,
            signals=_numbers(raw, ("downloads", "likes")),
            tags=(pipeline,) if isinstance(pipeline, str) else (),
        )
    except ValidationError as exc:
        logger.warning("Dropping malformed HF model row %s: %s", repo_id, exc)
        return None


def paper_item(raw: dict[str, Any], now: datetime) -> PulseItem | None:
    """Map one ``/api/daily_papers`` row, keyed by arXiv id."""
    nested = raw.get("paper")
    paper: dict[str, Any] = nested if isinstance(nested, dict) else {}
    arxiv_id = paper.get("id")
    title = paper.get("title") or raw.get("title")
    if not isinstance(arxiv_id, str) or not isinstance(title, str):
        return None
    github = paper.get("githubRepo")
    signals = _numbers(paper, ("upvotes",))
    signals["has_code"] = 1.0 if isinstance(github, str) and github else 0.0
    try:
        return PulseItem(
            lane=Lane.PAPER,
            key=arxiv_id,
            title=" ".join(title.split()),
            url=f"https://arxiv.org/abs/{arxiv_id}",
            source="hf-daily-papers",
            published_at=paper.get("publishedAt") or raw.get("publishedAt"),
            first_seen=now,
            last_seen=now,
            summary=_first_sentences(paper.get("summary") or raw.get("summary")),
            kind="paper",
            signals=signals,
            tags=(github,) if isinstance(github, str) and github else (),
        )
    except ValidationError as exc:
        logger.warning("Dropping malformed daily-paper row %s: %s", arxiv_id, exc)
        return None


async def fetch_lab_models(
    client: Any,
    lab_orgs: Iterable[str],
    per_org_limit: int,
    lab_org_set: frozenset[str],
    now: datetime,
    headers: dict[str, str] | None = None,
) -> SourceRun:
    items: list[PulseItem] = []
    errors: list[str] = []
    orgs = list(lab_orgs)
    for org in orgs:
        try:
            response = await get_with_retry(
                client, HF_MODELS_URL, label=f"hf-models:{org}",
                params={"author": org, "sort": "createdAt", "direction": -1,
                        "limit": per_org_limit},
                headers=headers or {},
            )
            payload = response.json()
        except Exception as exc:
            errors.append(f"{org}: {type(exc).__name__}: {exc}")
            continue
        if not isinstance(payload, list):
            errors.append(f"{org}: unexpected payload {type(payload).__name__}")
            continue
        items.extend(
            item for row in payload
            if isinstance(row, dict) and (item := model_item(row, lab_org_set, now)) is not None
        )
    return SourceRun("huggingface:lab-models", tuple(items), len(orgs), tuple(errors))


async def fetch_daily_papers(client: Any, limit: int, now: datetime) -> SourceRun:
    try:
        response = await get_with_retry(
            client, HF_DAILY_PAPERS_URL, label="hf-daily-papers", params={"limit": limit},
        )
        payload = response.json()
    except Exception as exc:
        return SourceRun("huggingface:daily-papers", (), 1, (f"{type(exc).__name__}: {exc}",))
    if not isinstance(payload, list):
        return SourceRun("huggingface:daily-papers", (), 1,
                         (f"unexpected payload {type(payload).__name__}",))
    items = tuple(
        item for row in payload
        if isinstance(row, dict) and (item := paper_item(row, now)) is not None
    )
    return SourceRun("huggingface:daily-papers", items, 1)


def _numbers(raw: dict[str, Any], keys: tuple[str, ...]) -> dict[str, float]:
    return {
        key: float(value) for key in keys
        if isinstance(value := raw.get(key), int | float) and not isinstance(value, bool)
    }


def _first_sentences(text: Any, limit: int = 400) -> str | None:
    if not isinstance(text, str) or not text.strip():
        return None
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"
