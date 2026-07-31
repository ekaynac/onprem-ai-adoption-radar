"""Append-only JSONL log of untracked model-candidate observations.

The daily candidate sweep records untracked HF-trending models here so download
velocity becomes durable across CI runs (the publish workflow commits the file,
like the history/metrics logs). Detection and the promote gate read it.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, field_validator


logger = logging.getLogger(__name__)


class ModelCandidateObservation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    hf_repo: str
    name: str
    family: str
    downloads: int
    likes: int = 0
    pipeline_tag: str | None = None
    created_at: str | None = None
    last_modified: str | None = None
    observed_at: datetime

    @field_validator("observed_at")
    @classmethod
    def _ensure_aware(cls, v: datetime) -> datetime:
        # A hand-edited/merge-mangled line can drop the UTC offset. Normalize
        # here at the model boundary so every consumer's sorted()/comparison
        # sees tz-aware datetimes — never a naive-vs-aware TypeError downstream
        # (build_model_candidates, has_sustained_download_momentum, etc.).
        return v.replace(tzinfo=UTC) if v.tzinfo is None else v


def append_model_candidates(path: Path, rows: list[ModelCandidateObservation]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(r.model_dump(mode="json"), ensure_ascii=False) for r in rows]
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def load_model_candidates(path: Path) -> list[ModelCandidateObservation]:
    if not path.exists():
        return []
    rows: list[ModelCandidateObservation] = []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line_no, raw in enumerate(handle, start=1):
                line = raw.strip()
                if not line:
                    continue
                try:
                    rows.append(ModelCandidateObservation.model_validate_json(line))
                except ValueError as exc:
                    logger.warning("Skipping corrupt model-candidate line %d in %s: %s",
                                   line_no, path, exc)
    except OSError as exc:
        logger.warning("Could not read model-candidate store %s: %s", path, exc)
    return rows
