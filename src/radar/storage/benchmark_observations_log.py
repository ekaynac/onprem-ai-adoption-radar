"""Append-only store for scraped benchmark observations.

Scraped channel only: curated model-card values live in
``config/model-seed.yaml`` and are merged at read time. Follows the
trending-observations log conventions: unconditional append, read-time
reduction elsewhere, corrupt lines skipped with a warning so one broken
line never makes the whole log unloadable.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, field_validator


logger = logging.getLogger(__name__)


class BenchmarkObservation(BaseModel):
    """One benchmark score for one model from one source at one time."""

    model_config = ConfigDict(frozen=True)

    model_id: str
    hf_repo: str | None = None
    benchmark: str
    score: float
    source_id: str
    source_url: str
    observed_at: datetime
    self_reported: bool = False

    @field_validator("observed_at")
    @classmethod
    def _ensure_aware(cls, v: datetime) -> datetime:
        # Hand-edited or merge-mangled lines can drop the UTC offset;
        # normalize at the model boundary so downstream comparisons never
        # hit naive-vs-aware TypeErrors.
        return v.replace(tzinfo=UTC) if v.tzinfo is None else v


def append_benchmark_observations(
    path: Path,
    observations: list[BenchmarkObservation],
) -> None:
    if not observations:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "\n".join(
        json.dumps(item.model_dump(mode="json"), ensure_ascii=False)
        for item in observations
    )
    with path.open("a", encoding="utf-8") as handle:
        handle.write(payload + "\n")


def load_benchmark_observations(path: Path) -> list[BenchmarkObservation]:
    if not path.exists():
        return []
    observations: list[BenchmarkObservation] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8", errors="replace").splitlines(),
        start=1,
    ):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            observations.append(
                BenchmarkObservation.model_validate(json.loads(stripped))
            )
        except Exception as exc:
            logger.warning(
                "Skipping corrupt benchmark observation at %s:%d: %s",
                path,
                line_number,
                exc,
            )
    return observations
