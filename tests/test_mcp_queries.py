"""Tests for the transport-agnostic radar query service behind the MCP server."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from radar.mcp_server.queries import RadarQueryService
from radar.models import Backer, BackerType, Category, DecisionCard, Ring
from radar.pipeline.delta import CardDelta, ChangeType
from radar.storage.database import RadarDatabase
from radar.storage.history_store import HistoryStore


def _card(project: str, ring: Ring) -> DecisionCard:
    return DecisionCard(
        project=project,
        category=Category.MODEL_SERVING,
        ring=ring,
        summary=f"{project} summary",
        workflow_fit={"personal_dev": "high"},
        risk_level="medium",
        why_it_matters="it matters",
        try_next=["pull the image"],
        evidence=["https://example.com/evidence"],
    )


def _seed(tmp_path: Path) -> None:
    db = RadarDatabase(tmp_path / "data" / "radar.db")
    db.initialize()
    db.upsert_cards(
        [
            _card("vLLM", Ring.ADOPT),
            _card("Ollama", Ring.PILOT),
            _card("SomethingElse", Ring.WATCH),
        ]
    )
    history = HistoryStore(tmp_path / "data" / "radar.db")
    history.initialize()
    history.record_deltas(
        [
            CardDelta(
                project="vLLM",
                category=Category.MODEL_SERVING,
                change_type=ChangeType.NEW,
                current_ring=Ring.ADOPT,
                previous_ring=None,
                reasons=["New on the radar."],
                card=_card("vLLM", Ring.ADOPT),
            )
        ],
        run_id="run-1",
        observed_at=datetime(2026, 6, 10, tzinfo=UTC),
    )


def test_recommendations_returns_all_cards(tmp_path: Path):
    _seed(tmp_path)
    svc = RadarQueryService(tmp_path)

    recs = svc.recommendations()

    projects = {r["project"] for r in recs}
    assert projects == {"vLLM", "Ollama", "SomethingElse"}
    vllm = next(r for r in recs if r["project"] == "vLLM")
    assert vllm["ring"] == "adopt"
    # full detail still exposes the prose fields
    full = next(r for r in svc.recommendations(detail="full") if r["project"] == "vLLM")
    assert full["why_it_matters"] == "it matters"


def test_recommendations_compact_is_lean_by_default(tmp_path: Path):
    _seed(tmp_path)
    svc = RadarQueryService(tmp_path)

    card = svc.recommendations()[0]

    # high-signal browse fields present
    for key in ("project", "ring", "score", "risk_level", "trend", "summary", "backer"):
        assert key in card
    assert "headline" in card  # one evidence line
    # heavy drill-down fields are NOT in the compact projection
    for key in ("evidence", "try_next", "risks", "why_it_matters", "tags"):
        assert key not in card


def test_recommendations_limit_and_score_order(tmp_path: Path):
    db = RadarDatabase(tmp_path / "data" / "radar.db")
    db.initialize()
    db.upsert_cards(
        [
            _card("Low", Ring.PILOT).model_copy(update={"score": 1.0}),
            _card("High", Ring.PILOT).model_copy(update={"score": 5.0}),
            _card("Mid", Ring.PILOT).model_copy(update={"score": 3.0}),
        ]
    )
    svc = RadarQueryService(tmp_path)

    ranked = [c["project"] for c in svc.recommendations()]
    assert ranked == ["High", "Mid", "Low"]  # highest score first
    assert [c["project"] for c in svc.recommendations(limit=2)] == ["High", "Mid"]


def test_recommendations_filters_by_ring(tmp_path: Path):
    _seed(tmp_path)
    svc = RadarQueryService(tmp_path)

    picks = svc.recommendations(rings=["adopt", "pilot"])

    assert {r["project"] for r in picks} == {"vLLM", "Ollama"}


def test_recommendations_unknown_ring_is_ignored_safely(tmp_path: Path):
    _seed(tmp_path)
    svc = RadarQueryService(tmp_path)

    assert svc.recommendations(rings=["nonsense"]) == []


def test_get_project_includes_card_and_history(tmp_path: Path):
    _seed(tmp_path)
    svc = RadarQueryService(tmp_path)

    detail = svc.get_project("vLLM")

    assert detail is not None
    assert detail["project"] == "vLLM"
    assert detail["ring"] == "adopt"
    assert len(detail["history"]) == 1
    assert detail["history"][0]["change_type"] == "new"


def test_get_project_unknown_returns_none(tmp_path: Path):
    _seed(tmp_path)
    svc = RadarQueryService(tmp_path)

    assert svc.get_project("DoesNotExist") is None


def test_list_tracked_projects(tmp_path: Path):
    _seed(tmp_path)
    svc = RadarQueryService(tmp_path)

    names = {p["project"] for p in svc.list_projects()}
    assert names == {"vLLM", "Ollama", "SomethingElse"}


def test_compare_returns_matrix_dict(tmp_path: Path):
    _seed(tmp_path)
    svc = RadarQueryService(tmp_path)

    matrix = svc.compare(projects=["vLLM", "Ollama"])

    assert matrix["projects"] == ["vLLM", "Ollama"]
    labels = [row["label"] for row in matrix["rows"]]
    assert "Ring" in labels and "Risk" in labels


def test_compare_unknown_project_returns_error(tmp_path: Path):
    _seed(tmp_path)
    svc = RadarQueryService(tmp_path)

    result = svc.compare(projects=["vLLM", "Ghost"])

    assert "error" in result
    assert "Ghost" in result["error"]


def _rich_card() -> DecisionCard:
    return DecisionCard(
        project="vLLM",
        category=Category.MODEL_SERVING,
        backer=Backer(name="vLLM (PyTorch Foundation)", type=BackerType.COMMUNITY),
        ring=Ring.AVOID,
        score=2.71,
        summary="fast inference",
        workflow_fit={},
        risk_level="high",
        evidence_notes=[
            "Stars +1,240 (+3.1%) since last scan.",
            "Recent CRITICAL security advisory GHSA-xxxx: RCE.",
        ],
        upgrade_risk="high",
        upgrade_risk_notes=["BREAKING CHANGE: engine API moved."],
        trend="rising",
        pinned=True,
        pinned_reason="failed internal review",
        computed_ring=Ring.WATCH,
    )


def test_card_dict_surfaces_evidence_and_decision_context(tmp_path: Path):
    db = RadarDatabase(tmp_path / "data" / "radar.db")
    db.initialize()
    db.upsert_cards([_rich_card()])
    svc = RadarQueryService(tmp_path)

    card = svc.recommendations(detail="full")[0]

    assert card["score"] == 2.71
    assert card["trend"] == "rising"
    assert card["upgrade_risk"] == "high"
    assert "BREAKING CHANGE: engine API moved." in card["upgrade_risk_notes"]
    assert any("GHSA-xxxx" in note for note in card["evidence_notes"])
    assert card["pinned"] is True
    assert card["pinned_reason"] == "failed internal review"
    assert card["computed_ring"] == "watch"
    assert card["backer"] == {
        "name": "vLLM (PyTorch Foundation)",
        "type": "community",
    }


def test_card_dict_defaults_are_clean_for_plain_cards(tmp_path: Path):
    _seed(tmp_path)
    svc = RadarQueryService(tmp_path)

    card = next(
        c for c in svc.recommendations(detail="full") if c["project"] == "vLLM"
    )

    assert card["trend"] == "steady"
    assert card["upgrade_risk"] == "none"
    assert card["evidence_notes"] == []
    assert card["pinned"] is False
    assert card["computed_ring"] is None
