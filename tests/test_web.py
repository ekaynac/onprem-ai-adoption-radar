from datetime import UTC
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


def test_compare_page_renders_matrix(tmp_path: Path):
    from radar.models import Category, Ring
    from radar.storage.database import RadarDatabase

    db_path = tmp_path / "data" / "radar.db"
    db = RadarDatabase(db_path)
    db.initialize()
    db.upsert_cards(
        [
            DecisionCard(
                project="Cline", category=Category.CODING_AGENTS, ring=Ring.PILOT,
                summary="x", workflow_fit={}, risk_level="medium",
            ),
            DecisionCard(
                project="Aider", category=Category.CODING_AGENTS, ring=Ring.ADOPT,
                summary="x", workflow_fit={}, risk_level="low",
            ),
        ]
    )

    client = TestClient(create_app(tmp_path))
    response = client.get("/compare", params={"category": "coding_agents"})

    assert response.status_code == 200
    assert "Cline" in response.text
    assert "Aider" in response.text
    assert "adopt" in response.text


def test_history_page_renders_recorded_events(tmp_path: Path):
    from datetime import datetime

    from radar.models import Category, Ring
    from radar.pipeline.delta import CardDelta, ChangeType
    from radar.storage.history_store import HistoryStore

    _init_project(tmp_path)
    history = HistoryStore(tmp_path / "data" / "radar.db")
    history.initialize()
    card = DecisionCard(
        project="Ollama",
        category=Category.MODEL_SERVING,
        ring=Ring.PILOT,
        summary="x",
        workflow_fit={},
        risk_level="medium",
    )
    history.record_deltas(
        [
            CardDelta(
                project="Ollama",
                category=Category.MODEL_SERVING,
                change_type=ChangeType.NEW,
                current_ring=Ring.PILOT,
                previous_ring=None,
                reasons=["New on the radar."],
                card=card,
            )
        ],
        run_id="run-1",
        observed_at=datetime(2026, 6, 10, tzinfo=UTC),
    )

    client = TestClient(create_app(tmp_path))
    response = client.get("/history")

    assert response.status_code == 200
    assert "Ollama" in response.text
    assert "2026-06-10" in response.text


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
