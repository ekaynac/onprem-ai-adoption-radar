"""Candidate technique proposals — written for human review, never auto-applied.

Discovery writes suggestions to ``data/proposed-technique-seeds.yaml``. A human
reviews them and promotes the good ones by editing ``config/technique-seed.yaml``
(curating papers/implementations by hand). The radar never adds a technique to
its own seed automatically: techniques need judgment, not a download floor.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

from radar.models import Category
from radar.research_radar.entities import TechniqueDomain


class TechniqueProposal(BaseModel):
    """A discovered paper proposed as a possible new technique seed."""

    model_config = ConfigDict(extra="forbid")

    suggested_id: str
    name: str
    arxiv_id: str
    published: str | None = None
    upvotes: int = 0
    suggested_domain: TechniqueDomain
    suggested_category: Category
    matched_keyword: str
    discovered_via: str = "hf-daily-papers"
    citation_count: int | None = None
    citations_per_day: float | None = None


def write_technique_proposals(path: Path, proposals: list[TechniqueProposal]) -> None:
    """Write proposals to YAML (atomic). Overwrites any prior proposals file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"proposals": [p.model_dump(mode="json") for p in proposals]}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    tmp.replace(path)


def load_technique_proposals(path: Path) -> list[TechniqueProposal]:
    """Load proposals; a missing file is an empty list."""
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [TechniqueProposal.model_validate(item) for item in raw.get("proposals") or []]
