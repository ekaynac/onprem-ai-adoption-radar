"""Load the bundled model seed (config/model-seed.yaml)."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from radar.models_radar.entities import ModelSeed


class ModelSeedError(ValueError):
    """Raised when the model seed cannot be loaded."""


def load_model_seed(path: Path) -> list[ModelSeed]:
    try:
        contents = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ModelSeedError(f"Model seed not found: {path}") from exc
    try:
        raw = yaml.safe_load(contents) or {}
    except yaml.YAMLError as exc:
        raise ModelSeedError(f"Invalid YAML in {path}: {exc}") from exc
    try:
        return [ModelSeed.model_validate(item) for item in raw.get("models") or []]
    except ValidationError as exc:
        raise ModelSeedError(f"Model seed validation failed for {path}: {exc}") from exc
