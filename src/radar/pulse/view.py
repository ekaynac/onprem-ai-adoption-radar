"""The published Pulse view: ranked lanes + health, one JSON for site, API, feeds."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from radar.pulse.items import Lane
from radar.pulse.pipeline import ITEMS_PATH
from radar.pulse.rank import Bucket, RankedItem, rank
from radar.pulse.store import load_items
from radar.pulse.triage import LABELS_PATH, load_labels
from radar.storage.source_health_log import load_source_health


SCHEMA_VERSION = "pulse-v1"
LANE_TITLES = {
    Lane.MODEL: "New models",
    Lane.PAPER: "Papers",
    Lane.REPO: "Repositories",
    Lane.NEWS: "News",
}
_PULSE_SOURCE_PREFIX = "huggingface:"
_RULES_SHARE_DEGRADED = 0.5  # more than half the shown items triaged by rules


def build_pulse_view(root: Path, now: datetime) -> dict[str, Any]:
    items = load_items(root / ITEMS_PATH)
    labels = load_labels(root / LABELS_PATH)
    ranked = rank(items, labels)
    lanes = [_lane(lane, [r for r in ranked if r.item.lane is lane]) for lane in Lane]
    shown = [row for lane in lanes for row in lane["items"]]
    engines = Counter(row["engine"] or "untriaged" for row in shown)
    rules_share = (engines["rules"] + engines["untriaged"]) / len(shown) if shown else 0.0
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now.isoformat(),
        "lanes": lanes,
        "health": {
            "sources": _latest_pulse_sources(root),
            "engines": dict(engines),
            "degraded": rules_share > _RULES_SHARE_DEGRADED,
        },
    }


def _lane(lane: Lane, ranked: list[RankedItem]) -> dict[str, Any]:
    """Everything in the window, nothing dropped: ranking orders, buckets group.

    The owner asked for "all, as much as possible" (2026-09-30), so filtered
    items ship too, each with the reason it was filtered.
    """
    by_bucket = {bucket: [_row(r) for r in ranked if r.bucket is bucket] for bucket in Bucket}
    return {
        "lane": lane.value,
        "title": LANE_TITLES[lane],
        "items": by_bucket[Bucket.TOP],
        "uncertain": by_bucket[Bucket.UNCERTAIN],
        "hidden": by_bucket[Bucket.HIDDEN],
        "hidden_count": len(by_bucket[Bucket.HIDDEN]),
        "total": len(ranked),
    }


def _row(entry: RankedItem) -> dict[str, Any]:
    item = entry.item
    return {
        "id": item.id,
        "lane": item.lane.value,
        "title": item.key if item.lane is Lane.MODEL else item.title,
        "url": str(item.url),
        "source": item.source,
        "published_at": item.published_at.isoformat() if item.published_at else None,
        "first_seen": item.first_seen.isoformat(),
        "summary": item.summary,
        "kind": item.kind,
        "parent": item.parent,
        "score": entry.score,
        "bucket": entry.bucket.value,
        "reasons": list(entry.reasons),
        "engine": entry.engine,
    }


def _latest_pulse_sources(root: Path) -> list[dict[str, Any]]:
    """Latest outcome of each Pulse network source, from the shared health log."""
    latest: dict[str, dict[str, Any]] = {}
    for record in load_source_health(root / "data" / "source-health.jsonl"):
        if not record.run_id.startswith("pulse-"):
            continue
        for name, outcome in record.sources.items():
            if name.startswith(_PULSE_SOURCE_PREFIX):
                latest[name] = {
                    "source": name,
                    "status": outcome.status,
                    "count": outcome.count,
                    "observed_at": record.observed_at.isoformat(),
                }
    return sorted(latest.values(), key=lambda s: s["source"])


def validate_view(payload: Any) -> dict[str, Any]:
    """Boundary check for a view fetched over HTTPS (the homelab worker reads
    the live site instead of pulling code); fail fast on anything unexpected."""
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("not a pulse-v1 view")
    datetime.fromisoformat(str(payload.get("generated_at")))
    lanes = payload.get("lanes")
    health = payload.get("health")
    if not isinstance(lanes, list) or not isinstance(health, dict):
        raise ValueError("pulse view lacks lanes/health")
    required = {"id", "lane", "title", "url", "source", "first_seen", "reasons"}
    for section in lanes:
        if not isinstance(section, dict) or not isinstance(section.get("items"), list):
            raise ValueError("pulse lane without an items list")
        if section.get("lane") not in {lane.value for lane in Lane}:
            raise ValueError(f"unknown pulse lane {section.get('lane')!r}")
        for row in section["items"]:
            if not isinstance(row, dict) or not required <= row.keys():
                raise ValueError("pulse item missing required fields")
            if not str(row["url"]).startswith(("https://", "http://")):
                raise ValueError("pulse item url is not http(s)")
    return payload
