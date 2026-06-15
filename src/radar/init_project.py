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
    config_refreshed: bool = False
    backup_path: Path | None = None


def initialize_project(root: Path, force: bool = False) -> InitResult:
    """Create local config and data directories.

    By default the active ``config.yaml`` is never overwritten, so re-running
    ``init`` is safe. With ``force=True`` the config is (re)written from the
    bundled seed; any existing config is preserved first as ``config.yaml.bak``
    so a refresh is recoverable.
    """
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

    config_refreshed = False
    backup_path: Path | None = None
    if config_path.exists():
        if force:
            backup_path = config_path.with_suffix(".yaml.bak")
            shutil.copy2(config_path, backup_path)
            shutil.copy2(seed_config, config_path)
            config_refreshed = True
    else:
        shutil.copy2(seed_config, config_path)
        config_refreshed = True

    if not env_example_path.exists():
        shutil.copy2(env_example, env_example_path)

    return InitResult(
        config_path=config_path,
        env_example_path=env_example_path,
        runs_path=runs_dir,
        config_refreshed=config_refreshed,
        backup_path=backup_path,
    )
