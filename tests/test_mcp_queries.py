"""Tests for the transport-agnostic radar query service behind the MCP server."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from radar.models import Category, DecisionCard, Ring
from radar.pipeline.delta import CardDelta, ChangeType
from radar.mcp_server.queries import RadarQueryService
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
        observed_at=datetime(2026, 6, 10, tzinfo=timezone.utc),
    )


def test_recommendations_returns_all_cards(tmp_path: Path):
    _seed(tmp_path)
    svc = RadarQueryService(tmp_path)

    recs = svc.recommendations()

    projects = {r["project"] for r in recs}
    assert projects == {"vLLM", "Ollama", "SomethingElse"}
    vllm = next(r for r in recs if r["project"] == "vLLM")
    assert vllm["ring"] == "adopt"
    assert vllm["why_it_matters"] == "it matters"


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
