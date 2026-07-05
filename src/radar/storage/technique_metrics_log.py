"""Append-only JSONL log of technique metrics (mirror of the history logs).

CI does not persist ``radar.db`` between runs, so citation velocity would
always read "first scan" on the published site. The scan appends each run's
metric rows here; the pipeline rehydrates an empty store from this log before
scoring. The file is committed back by the publish workflow like the history
logs, which makes velocity durable.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from radar.storage.technique_metrics_store import TechniqueMetrics


logger = logging.getLogger(__name__)


def append_metrics(path: Path, rows: list[TechniqueMetrics]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(r.model_dump(mode="json"), ensure_ascii=False) for r in rows]
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def load_metrics(path: Path) -> list[TechniqueMetrics]:
    if not path.exists():
        return []
    rows: list[TechniqueMetrics] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, raw in enumerate(handle, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                rows.append(TechniqueMetrics.model_validate_json(line))
            except ValueError as exc:
                logger.warning("Skipping corrupt technique-metrics line %d in %s: %s",
                               line_no, path, exc)
    return rows
