"""Export the read-only React command center and canonical public data."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from radar.intelligence.bootstrap import build_intelligence_repository
from radar.intelligence.services.container import build_services_for_root
from radar.reports.auxiliary_feeds import write_auxiliary_feeds
from radar.reports.unified_feeds import write_unified_feeds
from radar.storage.history_log import load_events
from radar.storage.history_store import HistoryStore
from radar.web.intelligence_snapshot import (
    build_public_snapshot,
    write_model_index,
    write_public_snapshot,
)


def _write_restoration_downloads(
    root: Path,
    out_dir: Path,
    *,
    base_url: str,
    project_events: list,
) -> None:
    """Guarantee every download advertised by the restoration bridge."""

    from radar.models_radar.history import load_model_events
    from radar.research_radar.history import load_technique_events
    from radar.storage.digest_log import load_digests

    history_names = (
        "history.jsonl",
        "model-history.jsonl",
        "technique-history.jsonl",
        "trending-observations.jsonl",
    )
    for name in history_names:
        source = root / "data" / name
        destination = out_dir / name
        if source.is_file():
            shutil.copy2(source, destination)
        elif name == "history.jsonl" and project_events:
            destination.write_text(
                "".join(
                    json.dumps(event.model_dump(mode="json"), sort_keys=True) + "\n"
                    for event in project_events
                ),
                encoding="utf-8",
            )
        elif not destination.exists():
            destination.write_text("", encoding="utf-8")

    site_title = "On-Prem AI Adoption Radar"
    model_events = load_model_events(root / "data" / "model-history.jsonl")
    technique_events = load_technique_events(
        root / "data" / "technique-history.jsonl"
    )

    source_digests = root / "digests"
    destination_digests = out_dir / "digests"
    if source_digests.is_dir():
        shutil.copytree(
            source_digests,
            destination_digests,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("digest.xml", "digest-rss.xml"),
        )
    digests = load_digests(root / "data" / "digest-log.jsonl")
    write_auxiliary_feeds(
        out_dir,
        model_events=model_events,
        technique_events=technique_events,
        digests=digests,
        site_title=site_title,
        base_url=base_url,
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
    canonical_releases = repository.list_all_releases()
    services = build_services_for_root(root, repository)
    snapshot = build_public_snapshot(
        services,
        now,
        root=root,
        canonical_releases=canonical_releases,
    )
    write_public_snapshot(snapshot, out_dir)
    write_model_index(
        canonical_releases,
        out_dir,
        now,
        repository=repository,
        legacy_rings=services.deployments.recommendations.legacy_rings,
    )
    events = repository.list_events(limit=500, public_only=True)
    history = HistoryStore(root / "data" / "radar.db")
    history.initialize()
    project_events = history.all_events()
    if not project_events:
        project_events = load_events(root / "data" / "history.jsonl")
    write_unified_feeds(
        out_dir,
        project_events=project_events,
        intelligence_events=events,
        site_title="On-Prem AI Adoption Radar",
        base_url=base_url,
    )
    _write_restoration_downloads(
        root,
        out_dir,
        base_url=base_url,
        project_events=project_events,
    )
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
