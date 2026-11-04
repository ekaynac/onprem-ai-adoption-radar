"""``data/pulse/health.json``: the latest outcome of every Pulse source.

The site, the RSS-side view and the homelab watchdog read it, so a failing
source is visible within one run instead of hiding behind an empty lane.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

from radar.pulse.sources import SourceRun


HEALTH_PATH = Path("data") / "pulse" / "health.json"
MAX_ERRORS_KEPT = 5


def record_runs(path: Path, runs: Iterable[SourceRun], now: datetime) -> dict[str, dict[str, Any]]:
    """Replace each run's entry; other entries (a source removed from config) stay until edited."""
    health = load_health(path)
    for run in runs:
        health[run.source] = {
            "status": run.status,
            "count": len(run.items),
            "requests": run.requests,
            "errors": list(run.errors[:MAX_ERRORS_KEPT]),
            "observed_at": now.isoformat(),
        }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(health, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)
    return health


def load_health(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: malformed Pulse health file")
    return {str(k): v for k, v in data.items() if isinstance(v, dict)}
