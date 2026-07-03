"""Load the technique seed (config/technique-seed.yaml). Fails loud before network."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from radar.research_radar.entities import TechniqueSeed


class TechniqueSeedError(ValueError):
    """Raised when the technique seed cannot be loaded."""


def load_technique_seed(path: Path) -> list[TechniqueSeed]:
    try:
        contents = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise TechniqueSeedError(f"Technique seed not found: {path}") from exc
    try:
        raw = yaml.safe_load(contents) or {}
    except yaml.YAMLError as exc:
        raise TechniqueSeedError(f"Invalid YAML in {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise TechniqueSeedError(
            f"Technique seed {path} must be a mapping with a 'techniques' list"
        )
    try:
        seeds = [TechniqueSeed.model_validate(item) for item in raw.get("techniques") or []]
    except ValidationError as exc:
        raise TechniqueSeedError(f"Technique seed validation failed for {path}: {exc}") from exc
    _check_ids(seeds, path)
    return seeds


def _check_ids(seeds: list[TechniqueSeed], path: Path) -> None:
    """Unique ids; every superseded_by must reference a seeded id."""
    ids = [s.id for s in seeds]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise TechniqueSeedError(f"Duplicate technique ids in {path}: {', '.join(duplicates)}")
    known = set(ids)
    for seed in seeds:
        if seed.superseded_by is None:
            continue
        if seed.superseded_by == seed.id:
            raise TechniqueSeedError(
                f"{path}: {seed.id} has superseded_by set to its own id"
                " (self-supersession is not allowed)"
            )
        if seed.superseded_by not in known:
            raise TechniqueSeedError(
                f"{path}: {seed.id} has superseded_by={seed.superseded_by!r},"
                " which is not a seeded technique id"
            )
