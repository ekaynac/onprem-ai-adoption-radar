"""Append-only JSONL log of untracked paper-candidate observations.

The daily candidate sweep records untracked hot papers here so upvote velocity
becomes durable across CI runs (the publish workflow commits the file, like the
history/metrics logs). Detection reads it; there is no promotion gate.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, field_validator


logger = logging.getLogger(__name__)


class TechniqueCandidateObservation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    arxiv_id: str
    name: str
    upvotes: int = 0
    citation_count: int | None = None
    published: str | None = None
    suggested_domain: str
    suggested_category: str
    observed_at: datetime

    @field_validator("observed_at")
    @classmethod
    def _ensure_aware(cls, v: datetime) -> datetime:
        return v.replace(tzinfo=UTC) if v.tzinfo is None else v


def append_technique_candidates(path: Path, rows: list[TechniqueCandidateObservation]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(r.model_dump(mode="json"), ensure_ascii=False) for r in rows]
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def load_technique_candidates(path: Path) -> list[TechniqueCandidateObservation]:
    if not path.exists():
        return []
    rows: list[TechniqueCandidateObservation] = []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line_no, raw in enumerate(handle, start=1):
                line = raw.strip()
                if not line:
                    continue
                try:
                    rows.append(TechniqueCandidateObservation.model_validate_json(line))
                except ValueError as exc:
                    logger.warning("Skipping corrupt technique-candidate line %d in %s: %s",
                                   line_no, path, exc)
    except OSError as exc:
        logger.warning("Could not read technique-candidate store %s: %s", path, exc)
    return rows
