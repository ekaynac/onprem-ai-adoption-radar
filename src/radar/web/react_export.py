"""Export the read-only React command center and canonical public data."""

from __future__ import annotations

import argparse
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from radar.intelligence.bootstrap import build_intelligence_repository
from radar.intelligence.services.container import build_services
from radar.reports.intelligence_feeds import (
    render_intelligence_atom,
    render_intelligence_json_feed,
    render_intelligence_rss,
)
from radar.web.intelligence_snapshot import (
    build_public_snapshot,
    write_public_snapshot,
)


def build_react_frontend(root: Path, *, static: bool = False) -> Path:
    """Regenerate the API contract and build the locked frontend toolchain."""

    from radar.api.export_openapi import export_openapi

    frontend = root / "frontend"
    if not (frontend / "package.json").exists():
        raise FileNotFoundError(f"Frontend source missing: {frontend}")
    export_openapi(root, root / "build" / "openapi.json")
    if not (frontend / "node_modules").exists():
        subprocess.run(["npm", "ci"], cwd=frontend, check=True)
    subprocess.run(["npm", "run", "generate:api"], cwd=frontend, check=True)
    command = ["npm", "run", "build"]
    if static:
        command.extend(["--", "--mode", "static"])
    subprocess.run(command, cwd=frontend, check=True)
    return root / "build" / "frontend"


def export_react_site(
    root: Path,
    out_dir: Path,
    *,
    frontend_dir: Path | None = None,
    base_url: str = "",
    generated_at: datetime | None = None,
) -> Path:
    frontend = frontend_dir or root / "build" / "frontend"
    index = frontend / "index.html"
    if not index.exists():
        raise FileNotFoundError(
            f"React build missing: {index}. Run the frontend build first."
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(frontend, out_dir, dirs_exist_ok=True)
    shutil.copy2(index, out_dir / "404.html")

    _database, repository = build_intelligence_repository(root)
    now = generated_at or datetime.now(UTC)
    snapshot = build_public_snapshot(build_services(repository), now)
    write_public_snapshot(snapshot, out_dir)
    events = repository.list_events(limit=500, public_only=True)
    feed_base = base_url.rstrip("/")
    (out_dir / "changes.atom").write_text(
        render_intelligence_atom(events, feed_base),
        encoding="utf-8",
    )
    (out_dir / "changes.rss").write_text(
        render_intelligence_rss(events, feed_base),
        encoding="utf-8",
    )
    (out_dir / "changes.json").write_text(
        render_intelligence_json_feed(events, feed_base),
        encoding="utf-8",
    )
    for name in (
        "history.jsonl",
        "model-history.jsonl",
        "technique-history.jsonl",
    ):
        source = root / "data" / name
        if source.exists():
            shutil.copy2(source, out_dir / name)
    return out_dir


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--frontend", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=Path("_site"))
    parser.add_argument("--base-url", default="")
    args = parser.parse_args()
    export_react_site(
        args.root,
        args.out,
        frontend_dir=args.frontend,
        base_url=args.base_url,
    )


if __name__ == "__main__":
    main()
