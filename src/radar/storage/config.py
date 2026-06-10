"""Configuration loading and environment expansion."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from radar.models import Config


_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class ConfigError(ValueError):
    """Raised when configuration cannot be loaded."""


def expand_env_vars(value: Any) -> Any:
    """Recursively expand ${VAR} references in strings."""
    if isinstance(value, str):
        return _ENV_PATTERN.sub(
            lambda match: os.environ.get(match.group(1), match.group(0)), value
        )
    if isinstance(value, dict):
        return {key: expand_env_vars(item) for key, item in value.items()}
    if isinstance(value, list):
        return [expand_env_vars(item) for item in value]
    return value


def load_config(path: Path) -> Config:
    """Load and validate a YAML config file."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {path}: {exc}") from exc
    except FileNotFoundError as exc:
        raise ConfigError(f"Configuration file not found: {path}") from exc

    if raw is None:
        raw = {}

    expanded = expand_env_vars(raw)

    try:
        return Config.model_validate(expanded)
    except ValidationError as exc:
        raise ConfigError(f"Configuration validation failed for {path}: {exc}") from exc
