"""Seed (source) management — the shared core behind the CLI and the web UI.

All mutations are immutable: functions return a new ``Config`` rather than
editing the original in place. ``add_seed`` is the boundary API that validates
external input, appends the source, and persists the result atomically.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from radar.models import Config, SourceConfig
from radar.storage.config import ConfigError, load_config


class SeedError(ValueError):
    """Raised when a seed/source cannot be added."""


def add_source(config: Config, source: SourceConfig) -> Config:
    """Return a new ``Config`` with ``source`` appended.

    The input ``config`` is never mutated. Raises ``SeedError`` if a source
    with the same id already exists.
    """
    if any(existing.id == source.id for existing in config.sources):
        raise SeedError(f"Source id already exists: {source.id}")
    return config.model_copy(update={"sources": [*config.sources, source]})


def save_config(config: Config, path: Path) -> None:
    """Persist ``config`` to ``path`` as YAML.

    Writes via a temporary file and atomic replace so a failed write never
    leaves a partially written config behind.
    """
    data = config.model_dump(mode="json")
    text = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    try:
        tmp_path.write_text(text, encoding="utf-8")
        tmp_path.replace(path)
    except OSError as exc:  # pragma: no cover - filesystem failure
        raise SeedError(f"Could not write config: {path}") from exc


def add_seed(path: Path, raw: dict[str, Any]) -> SourceConfig:
    """Load config at ``path``, add a source from ``raw``, and persist.

    ``raw`` is untrusted external input (CLI flags or an HTTP form), validated
    at this boundary. On any failure the on-disk config is left unchanged.
    Returns the validated source that was added.
    """
    try:
        config = load_config(path)
    except ConfigError as exc:
        raise SeedError(str(exc)) from exc

    try:
        source = SourceConfig.model_validate(raw)
    except ValidationError as exc:
        raise SeedError(f"Invalid source: {exc}") from exc

    updated = add_source(config, source)
    save_config(updated, path)
    return source
