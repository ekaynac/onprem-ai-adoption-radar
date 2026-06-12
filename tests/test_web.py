from pathlib import Path

from fastapi.testclient import TestClient

from radar.models import Category, DecisionCard, Ring
from radar.storage.database import RadarDatabase
from radar.web.app import create_app


def test_dashboard_lists_cards(tmp_path: Path):
    db_path = tmp_path / "data" / "radar.db"
    db = RadarDatabase(db_path)
    db.initialize()
    db.upsert_cards(
        [
            DecisionCard(
                project="Cline",
                category=Category.CODING_AGENTS,
                ring=Ring.PILOT,
                summary="Coding agent",
                workflow_fit={"personal_dev": "high"},
                risk_level="medium",
            )
        ]
    )

    client = TestClient(create_app(tmp_path))
    response = client.get("/")

    assert response.status_code == 200
    assert "Cline" in response.text
    assert "pilot" in response.text


def _init_project(tmp_path: Path) -> None:
    from radar.init_project import initialize_project

    initialize_project(tmp_path)


def test_sources_page_shows_add_form(tmp_path: Path):
    _init_project(tmp_path)

    client = TestClient(create_app(tmp_path))
    response = client.get("/sources")

    assert response.status_code == 200
    assert "<form" in response.text
    # existing seed sources are listed
    assert "github" in response.text.lower()


def test_post_source_adds_seed_and_persists(tmp_path: Path):
    _init_project(tmp_path)

    client = TestClient(create_app(tmp_path))
    response = client.post(
        "/sources",
        data={
            "id": "rss-web-feed",
            "type": "rss",
            "project": "Web Feed",
            "category": "model_serving",
            "url": "https://example.com/feed.xml",
            "tags": "vendor-blog, inference",
        },
        follow_redirects=False,
    )

    # redirect back to the sources page after a successful add
    assert response.status_code in (302, 303)

    from radar.storage.config import load_config
    config = load_config(tmp_path / "data" / "config.yaml")
    assert any(s.id == "rss-web-feed" for s in config.sources)


def test_post_source_rejects_duplicate_with_message(tmp_path: Path):
    _init_project(tmp_path)
    client = TestClient(create_app(tmp_path))
    form = {
        "id": "rss-web-dup", "type": "rss", "project": "Dup",
        "category": "model_serving", "url": "https://example.com/feed.xml",
        "tags": "",
    }
    client.post("/sources", data=form, follow_redirects=False)

    response = client.post("/sources", data=form, follow_redirects=False)

    assert response.status_code == 200
    assert "already exists" in response.text
