"""MCP technique query service over persisted research runs."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from radar.mcp_server.technique_queries import TechniqueQueryService, _latest_technique_cards
from radar.models import Category, Ring
from radar.research_radar.entities import OnPremImpact, TechniqueDomain, TechniqueEntry
from radar.research_radar.history import TechniqueHistoryEvent, append_technique_events
from radar.storage.history_store import ChangeType
from radar.storage.run_store import RunStore


def _entry(technique_id: str, ring: Ring, domain: TechniqueDomain,
           citations: int | None = 100) -> TechniqueEntry:
    return TechniqueEntry(
        id=technique_id, name=technique_id.title(), category=Category.MODEL_SERVING,
        domain=domain, onprem_impact=OnPremImpact.REDUCES_LATENCY, ring=ring,
        citation_count=citations, score=3.5,
    )


def _seed_research_run(root: Path, entries: list[TechniqueEntry]) -> None:
    (root / "data").mkdir(parents=True, exist_ok=True)
    store = RunStore(root / "data" / "runs")
    run_id = store.create_run()
    store.save_stage(run_id, "technique_cards", [e.model_dump(mode="json") for e in entries])
    store.update_meta(run_id, {"kind": "research", "technique_count": len(entries)})


def test_latest_cards_empty_without_research_run(tmp_path):
    (tmp_path / "data").mkdir()

    assert _latest_technique_cards(tmp_path) == []


def test_list_techniques_compact_and_filters(tmp_path):
    _seed_research_run(tmp_path, [
        _entry("speculative-decoding", Ring.ADOPT, TechniqueDomain.INFERENCE),
        _entry("qlora", Ring.WATCH, TechniqueDomain.FINE_TUNING),
    ])
    svc = TechniqueQueryService(tmp_path)

    rows = svc.list_techniques()
    assert {r["id"] for r in rows} == {"speculative-decoding", "qlora"}
    assert rows[0].keys() >= {"id", "name", "domain", "ring", "score",
                              "citation_count", "implementations"}

    assert [r["id"] for r in svc.list_techniques(ring="ADOPT")] == ["speculative-decoding"]
    assert [r["id"] for r in svc.list_techniques(domain="fine_tuning")] == ["qlora"]
    assert svc.list_techniques(category="coding_agents") == []


def test_list_techniques_full_detail_dumps_everything(tmp_path):
    _seed_research_run(tmp_path, [_entry("qlora", Ring.WATCH, TechniqueDomain.FINE_TUNING)])
    svc = TechniqueQueryService(tmp_path)

    rows = svc.list_techniques(detail="full")

    assert rows[0]["onprem_impact"] == "reduces_latency"
    assert "resolved_implementations" in rows[0]


def test_get_technique_includes_history_and_momentum(tmp_path):
    _seed_research_run(tmp_path, [_entry("qlora", Ring.WATCH, TechniqueDomain.FINE_TUNING)])
    append_technique_events(tmp_path / "data" / "technique-history.jsonl", [
        TechniqueHistoryEvent(
            technique_id="qlora", domain=TechniqueDomain.FINE_TUNING,
            change_type=ChangeType.NEW, ring=Ring.WATCH, run_id="run-1",
            observed_at=datetime(2026, 7, 3, 10, 0, tzinfo=UTC),
        ),
    ])
    svc = TechniqueQueryService(tmp_path)

    payload = svc.get_technique("qlora")

    assert payload["id"] == "qlora"
    assert payload["history"][0]["change_type"] == "new"
    assert payload["momentum"]["direction"] in {"rising", "falling", "steady"}
    assert svc.get_technique("nope") is None


def test_technique_movers_newest_first_capped_at_10(tmp_path):
    (tmp_path / "data").mkdir()
    _seed_research_run(tmp_path, [])
    events = [
        TechniqueHistoryEvent(
            technique_id=f"t-{i}", domain=TechniqueDomain.INFERENCE,
            change_type=ChangeType.NEW, ring=Ring.WATCH, run_id="run-1",
            observed_at=datetime(2026, 7, 1, 10, i, tzinfo=UTC),
        )
        for i in range(12)
    ]
    append_technique_events(tmp_path / "data" / "technique-history.jsonl", events)
    svc = TechniqueQueryService(tmp_path)

    movers = svc.technique_movers()

    assert len(movers) == 10
    assert movers[0]["technique_id"] == "t-11"  # newest first
    assert movers[0]["change"] == "new"


def test_cli_research_list_still_works_after_refactor(tmp_path):
    """cli._latest_technique_entries now delegates to _latest_technique_cards."""
    from typer.testing import CliRunner

    from radar.cli import app

    _seed_research_run(tmp_path, [_entry("qlora", Ring.WATCH, TechniqueDomain.FINE_TUNING)])
    runner = CliRunner()

    result = runner.invoke(app, ["research", "list", "--root", str(tmp_path)])

    assert result.exit_code == 0
    assert "qlora" in result.stdout
