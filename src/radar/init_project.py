"""Project initialization helpers."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class InitResult:
    """Paths created or reused by init."""

    config_path: Path
    env_example_path: Path
    runs_path: Path


def initialize_project(root: Path) -> InitResult:
    """Create local config and data directories without overwriting config."""
    root = root.resolve()
    data_dir = root / "data"
    runs_dir = data_dir / "runs"
    config_path = data_dir / "config.yaml"
    env_example_path = root / ".env.example"

    data_dir.mkdir(parents=True, exist_ok=True)
    runs_dir.mkdir(parents=True, exist_ok=True)

    package_root = Path(__file__).resolve().parents[2]
    seed_config = package_root / "config" / "seed-sources.yaml"
    env_example = package_root / ".env.example"

    if not config_path.exists():
        shutil.copy2(seed_config, config_path)
    if not env_example_path.exists():
        shutil.copy2(env_example, env_example_path)

    return InitResult(
        config_path=config_path,
        env_example_path=env_example_path,
        runs_path=runs_dir,
    )
