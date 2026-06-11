from pathlib import Path

from radar.models import Category, DecisionCard, Ring
from radar.storage.database import RadarDatabase


def test_database_persists_decision_cards(tmp_path: Path):
    db = RadarDatabase(tmp_path / "radar.db")
    db.initialize()
    card = DecisionCard(
        project="Cline",
        category=Category.CODING_AGENTS,
        ring=Ring.PILOT,
        summary="Coding agent",
        workflow_fit={"personal_dev": "high"},
        risk_level="medium",
        evidence=["https://example.com"],
    )

    db.upsert_cards([card])

    cards = db.list_cards()
    assert len(cards) == 1
    assert cards[0].project == "Cline"
    assert cards[0].ring == Ring.PILOT
