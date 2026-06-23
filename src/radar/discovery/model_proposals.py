"""Candidate MODEL proposals — discovered, written to a review file, optionally promoted.

Model discovery writes suggestions to ``data/proposed-model-seeds.yaml``. Those become
catalog entries one of two ways:

- **Manual:** a human reviews the file and edits the good ones into ``config/model-seed.yaml``.
- **Autopilot:** ``radar models promote`` (run weekly by ``catalog-autopilot.yml``) filters the
  proposals, enriches survivors into full seeds, and appends them — validating the catalog before
  it writes. See ``radar.discovery.model_promotion`` for the filtering/enrichment gate that stands
  in for human review on that path.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict


class ModelProposal(BaseModel):
    """A discovered model proposed as a possible new seed entry."""

    model_config = ConfigDict(extra="forbid", frozen=True, protected_namespaces=())

    model_id: str
    name: str
    family: str
    hf_repo: str
    downloads: int
    likes: int
    modality: str
    reason: str = ""
    suggested_id: str


def write_model_proposals(path: Path, proposals: list[ModelProposal]) -> None:
    """Write model proposals to YAML (atomic). Overwrites any prior file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"proposals": [p.model_dump(mode="json") for p in proposals]}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    tmp.replace(path)


def load_model_proposals(path: Path) -> list[ModelProposal]:
    """Load model proposals; a missing file is an empty list."""
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [ModelProposal.model_validate(item) for item in raw.get("proposals") or []]
