"""File-based staged run artifact storage."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
STAGE_NAMES = {
    "raw_signals",
    "scored_signals",
    "filtered_signals",
    "decision_cards",
}


@dataclass
class RunStore:
    """Persist scan artifacts under data/runs/<run_id>."""

    root: Path

    def __post_init__(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def create_run(self, run_id: str | None = None) -> str:
        """Create a run directory and meta file."""
        resolved = run_id or self._make_run_id()
        run_dir = self._run_dir(resolved, must_exist=False)
        run_dir.mkdir(parents=True, exist_ok=True)
        meta_path = run_dir / "meta.json"
        if not meta_path.exists():
            meta_path.write_text(
                json.dumps(
                    {"run_id": resolved, "created_at": self._now()},
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        return resolved

    def save_stage(self, run_id: str, stage: str, payload: list[dict[str, Any]]) -> Path:
        """Save a JSON stage artifact."""
        if stage not in STAGE_NAMES:
            raise ValueError(f"Unsupported stage: {stage}")
        path = self._run_dir(run_id) / f"{stage}.json"
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        self.update_meta(run_id, {"last_stage": stage})
        return path

    def load_stage(self, run_id: str, stage: str) -> list[dict[str, Any]]:
        """Load a JSON stage artifact."""
        if stage not in STAGE_NAMES:
            raise ValueError(f"Unsupported stage: {stage}")
        path = self._run_dir(run_id) / f"{stage}.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def save_report(self, run_id: str, markdown: str) -> Path:
        """Save the full cumulative Markdown report artifact."""
        path = self._run_dir(run_id) / "report.md"
        path.write_text(markdown, encoding="utf-8")
        self.update_meta(run_id, {"report": "report.md"})
        return path

    def save_try_this_week(self, run_id: str, markdown: str) -> Path:
        """Save the separate Try This Week delta report artifact."""
        path = self._run_dir(run_id) / "try-this-week.md"
        path.write_text(markdown, encoding="utf-8")
        self.update_meta(run_id, {"try_this_week": "try-this-week.md"})
        return path

    def update_meta(self, run_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        """Merge values into meta.json."""
        path = self._run_dir(run_id) / "meta.json"
        meta = json.loads(path.read_text(encoding="utf-8"))
        meta.update(updates)
        meta["updated_at"] = self._now()
        path.write_text(
            json.dumps(meta, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return meta

    def _run_dir(self, run_id: str, must_exist: bool = True) -> Path:
        if not RUN_ID_RE.fullmatch(run_id) or ".." in run_id:
            raise ValueError("Invalid run_id")
        root = self.root.resolve()
        path = (self.root / run_id).resolve()
        if not path.is_relative_to(root):
            raise ValueError("Invalid run_id")
        if must_exist and not path.exists():
            raise FileNotFoundError(f"Run not found: {run_id}")
        return path

    @staticmethod
    def _make_run_id() -> str:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        return f"run-{stamp}-{uuid4().hex[:8]}"

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
