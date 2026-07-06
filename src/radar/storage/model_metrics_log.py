"""Append-only JSONL log of model metrics (mirror of the history/metrics logs).

CI does not persist ``radar.db`` between runs, so download velocity would
always read "first scan" on the published site. ``models scan`` appends each
run's metric rows here; the publish workflow commits the file, which makes
model download-growth durable — the same pattern technique-metrics.jsonl uses
for citation velocity.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from radar.storage.model_metrics_store import ModelMetrics


logger = logging.getLogger(__name__)


def append_model_metrics(path: Path, rows: list[ModelMetrics]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(r.model_dump(mode="json"), ensure_ascii=False) for r in rows]
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def load_model_metrics(path: Path) -> list[ModelMetrics]:
    if not path.exists():
        return []
    rows: list[ModelMetrics] = []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line_no, raw in enumerate(handle, start=1):
                line = raw.strip()
                if not line:
                    continue
                try:
                    rows.append(ModelMetrics.model_validate_json(line))
                except ValueError as exc:
                    logger.warning("Skipping corrupt model-metrics line %d in %s: %s",
                                   line_no, path, exc)
    except OSError as exc:
        logger.warning("Could not read model-metrics store %s: %s", path, exc)
    return rows
