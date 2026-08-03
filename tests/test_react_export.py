import json
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from radar.models import Category, Ring
from radar.pipeline.delta import ChangeType
from radar.storage.history_log import append_events
from radar.storage.history_store import HistoryStore, ProjectHistoryEvent
from radar.web.app import create_app
from radar.web.react_export import export_react_site


def _frontend_build(root: Path) -> Path:
    frontend = root / "build" / "frontend"
    (frontend / "assets").mkdir(parents=True)
    (frontend / "index.html").write_text(
        '<!doctype html><div id="root"></div>'
        '<script src="/assets/app-abc123.js"></script>',
        encoding="utf-8",
    )
    (frontend / "assets" / "app-abc123.js").write_text(
        "window.__RADAR__=true",
        encoding="utf-8",
    )
    return frontend


def test_live_root_serves_react_shell_and_api(tmp_path: Path) -> None:
    _frontend_build(tmp_path)
    client = TestClient(create_app(tmp_path))

    root = client.get("/")

    assert root.status_code == 200
    assert '<div id="root"></div>' in root.text
    assert root.headers["cache-control"] == "no-cache"
    assert client.get("/api/v1/releases").status_code == 200
    assert client.get("/overview").status_code == 200
    asset = client.get("/assets/app-abc123.js")
    assert asset.headers["cache-control"] == "public, max-age=31536000, immutable"


def test_static_export_contains_no_workspace_payload(tmp_path: Path) -> None:
    frontend = _frontend_build(tmp_path)
    history = HistoryStore(tmp_path / "data" / "radar.db")
    history.initialize()
    history.add_events(
        [
            ProjectHistoryEvent(
                project="vLLM",
                category=Category.MODEL_SERVING,
                change_type=ChangeType.PROMOTED,
                ring=Ring.ADOPT,
                previous_ring=Ring.PILOT,
                run_id="run-legacy",
                observed_at=datetime(2026, 7, 31, tzinfo=UTC),
                reasons=["evidence improved"],
            )
        ]
    )

    out = export_react_site(
        tmp_path,
        tmp_path / "_site",
        frontend_dir=frontend,
    )

    snapshot = json.loads(
        (out / "data" / "public-snapshot.v1.json").read_text()
    )
    encoded = json.dumps(snapshot).casefold()
    assert "workspace" not in encoded
    assert (out / "index.html").exists()
    assert (out / "404.html").exists()
    assert (out / "changes.rss").exists()
    manifest = json.loads((out / "data" / "model-index.v1.json").read_text())
    assert manifest["total"] == snapshot["model_index"]["total"]
    assert all((out / shard["path"]).is_file() for shard in manifest["shards"])
    assert "vLLM" in (out / "changes.rss").read_text()
    for promised_download in (
        "history.jsonl",
        "model-history.jsonl",
        "technique-history.jsonl",
        "trending-observations.jsonl",
        "changes-models.xml",
        "changes-research.xml",
        "digests/digest.xml",
        "digests/digest-rss.xml",
    ):
        assert (out / promised_download).is_file(), promised_download


def test_static_export_uses_durable_history_when_database_is_absent(
    tmp_path: Path,
) -> None:
    frontend = _frontend_build(tmp_path)
    append_events(
        tmp_path / "data" / "history.jsonl",
        [
            ProjectHistoryEvent(
                project="vLLM",
                category=Category.MODEL_SERVING,
                change_type=ChangeType.PROMOTED,
                ring=Ring.ADOPT,
                previous_ring=Ring.PILOT,
                run_id="run-clean-checkout",
                observed_at=datetime(2026, 7, 31, tzinfo=UTC),
                reasons=["evidence improved"],
            )
        ],
    )

    out = export_react_site(
        tmp_path,
        tmp_path / "_site",
        frontend_dir=frontend,
    )

    assert "vLLM" in (out / "changes.rss").read_text(encoding="utf-8")
    feed = json.loads((out / "changes.json").read_text(encoding="utf-8"))
    assert feed["items"][0]["title"].startswith("vLLM")
