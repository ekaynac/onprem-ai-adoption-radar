"""Append-only JSONL log of trending observations (mirror of the history logs).

GitHub search reports stars-now, not growth. The daily sweep appends each
repo's current stars here; detection derives velocity by comparing rows across
days. The publish workflow commits this file back like the history logs, which
makes trend detection durable across CI runs.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from radar.discovery.trending_entities import TrendingObservation


logger = logging.getLogger(__name__)


def append_observations(path: Path, rows: list[TrendingObservation]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(r.model_dump(mode="json"), ensure_ascii=False) for r in rows]
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def load_observations(path: Path) -> list[TrendingObservation]:
    if not path.exists():
        return []
    rows: list[TrendingObservation] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, raw in enumerate(handle, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                rows.append(TrendingObservation.model_validate_json(line))
            except ValueError as exc:
                logger.warning("Skipping corrupt trending-observations line %d in %s: %s",
                               line_no, path, exc)
    return rows
