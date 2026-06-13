"""Candidate seed proposals — written for human review, never auto-applied.

Discovery writes suggestions to ``data/proposed-seeds.yaml``. A human reviews
them and promotes the good ones with ``radar seed add``. The radar never adds a
source to its own config automatically: what it tracks stays a deliberate
choice.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

from radar.models import Category


class SeedProposal(BaseModel):
    """A discovered repository proposed as a possible new source."""

    model_config = ConfigDict(extra="forbid")

    project: str
    category: Category
    url: str
    stars: int
    description: str = ""
    suggested_id: str
    suggested_tags: list[str] = []


def write_proposals(path: Path, proposals: list[SeedProposal]) -> None:
    """Write proposals to YAML (atomic). Overwrites any prior proposals file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"proposals": [p.model_dump(mode="json") for p in proposals]}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    tmp.replace(path)


def load_proposals(path: Path) -> list[SeedProposal]:
    """Load proposals; a missing file is an empty list."""
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [SeedProposal.model_validate(item) for item in raw.get("proposals") or []]
