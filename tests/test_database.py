import sqlite3
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


def test_get_card_returns_card(tmp_path: Path):
    db = RadarDatabase(tmp_path / "radar.db")
    db.initialize()
    db.upsert_cards(
        [
            DecisionCard(
                project="vLLM", category=Category.MODEL_SERVING, ring=Ring.ADOPT,
                summary="s", workflow_fit={}, risk_level="low",
            )
        ]
    )

    card = db.get_card("vLLM")

    assert card is not None
    assert card.project == "vLLM"
    assert card.ring == Ring.ADOPT


def test_get_card_missing_returns_none(tmp_path: Path):
    db = RadarDatabase(tmp_path / "radar.db")
    db.initialize()

    assert db.get_card("Nope") is None


def _card(project: str) -> DecisionCard:
    return DecisionCard(
        project=project, category=Category.MODEL_SERVING, ring=Ring.ADOPT,
        summary="s", workflow_fit={}, risk_level="low",
    )


def test_card_staleness_note_none_when_no_cards(tmp_path: Path):
    db = RadarDatabase(tmp_path / "radar.db")
    db.initialize()

    assert db.card_staleness_note() is None


def test_card_staleness_note_flags_mixed_ages(tmp_path: Path):
    db = RadarDatabase(tmp_path / "radar.db")
    db.initialize()
    db.upsert_cards([_card("Fresh")])
    # Backdate one card directly — upsert always stamps now.
    db.upsert_cards([_card("Stale")])
    with sqlite3.connect(tmp_path / "radar.db") as conn:
        conn.execute(
            "UPDATE decision_cards SET updated_at = '2026-07-25T06:00:00+00:00' "
            "WHERE project = 'Stale'"
        )

    note = db.card_staleness_note()

    assert note is not None
    assert "1 of 2" in note
    assert "2026-07-25" in note

    with sqlite3.connect(tmp_path / "radar.db") as conn:
        conn.execute("UPDATE decision_cards SET updated_at = '2026-07-27T06:00:00+00:00'")

    assert db.card_staleness_note() is None
