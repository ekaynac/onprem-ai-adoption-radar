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
