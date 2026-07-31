import json
from pathlib import Path

from fastapi.testclient import TestClient

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
