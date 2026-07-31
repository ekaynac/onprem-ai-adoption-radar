"""Export the read-only React command center and canonical public data."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from radar.intelligence.bootstrap import build_intelligence_repository
from radar.intelligence.services.container import build_services
from radar.reports.unified_feeds import write_unified_feeds
from radar.storage.history_store import HistoryStore
from radar.web.intelligence_snapshot import (
    build_public_snapshot,
    write_public_snapshot,
)


def _public_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path}" if base_url else path


def _write_restoration_downloads(
    root: Path,
    out_dir: Path,
    *,
    base_url: str,
    project_events: list,
) -> None:
    """Guarantee every download advertised by the restoration bridge."""

    from radar.models_radar.history import load_model_events
    from radar.models_radar.reports import (
        model_events_to_feed_atom,
        model_events_to_feed_json,
    )
    from radar.reports.digest_feeds import render_digest_atom, render_digest_rss
    from radar.research_radar.history import load_technique_events
    from radar.research_radar.reports import (
        technique_events_to_feed_atom,
        technique_events_to_feed_json,
    )
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
    (out_dir / "changes-models.xml").write_text(
        model_events_to_feed_atom(
            model_events,
            site_title,
            _public_url(base_url, "changes-models.xml"),
        ),
        encoding="utf-8",
    )
    (out_dir / "changes-models.json").write_text(
        json.dumps(model_events_to_feed_json(model_events, site_title), indent=2),
        encoding="utf-8",
    )

    technique_events = load_technique_events(
        root / "data" / "technique-history.jsonl"
    )
    (out_dir / "changes-research.xml").write_text(
        technique_events_to_feed_atom(
            technique_events,
            site_title,
            _public_url(base_url, "changes-research.xml"),
        ),
        encoding="utf-8",
    )
    (out_dir / "changes-research.json").write_text(
        json.dumps(
            technique_events_to_feed_json(technique_events, site_title),
            indent=2,
        ),
        encoding="utf-8",
    )

    source_digests = root / "digests"
    destination_digests = out_dir / "digests"
    if source_digests.is_dir():
        shutil.copytree(source_digests, destination_digests, dirs_exist_ok=True)
    destination_digests.mkdir(parents=True, exist_ok=True)
    digests = load_digests(root / "data" / "digest-log.jsonl")
    digest_title = f"{site_title} — Weekly Digest"
    (destination_digests / "digest.xml").write_text(
        render_digest_atom(
            digests,
            digest_title,
            _public_url(base_url, "digests/digest.xml"),
        ),
        encoding="utf-8",
    )
    (destination_digests / "digest-rss.xml").write_text(
        render_digest_rss(
            digests,
            digest_title,
            _public_url(base_url, "digests/digest-rss.xml"),
        ),
        encoding="utf-8",
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
    snapshot = build_public_snapshot(
        build_services(repository),
        now,
        root=root,
    )
    write_public_snapshot(snapshot, out_dir)
    events = repository.list_events(limit=500, public_only=True)
    history = HistoryStore(root / "data" / "radar.db")
    history.initialize()
    project_events = history.all_events()
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
