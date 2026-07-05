"""CLI: radar research scan / list / show against a temp project root."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from radar.cli import app


@pytest.fixture(autouse=True)
def _no_live_citations(monkeypatch):
    """Keep `research scan` offline: the pipeline imports fetch_citations into its
    own namespace, so it must be patched there (not on radar.research_radar.citations)
    to avoid live POSTs to api.semanticscholar.org during tests."""

    async def _no_citations(arxiv_ids, client, contact_email=None):
        return {}

    monkeypatch.setattr("radar.research_radar.pipeline.fetch_citations", _no_citations)


SEED = """
techniques:
  - id: qlora
    name: QLoRA
    category: ai_infrastructure
    domain: fine_tuning
    papers:
      - arxiv_id: "0000.00000"
        title: "QLoRA"
    open_code: true
    onprem_impact: reduces_memory
"""
# arxiv_id 0000.00000 does not exist: with OR without network the citation
# lookup finds nothing, so the "citations unknown" path is deterministic.


def _project(tmp_path: Path) -> Path:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "technique-seed.yaml").write_text(SEED, encoding="utf-8")
    (tmp_path / "data").mkdir()
    return tmp_path


def test_research_scan_offline_writes_run_and_history(tmp_path):
    runner = CliRunner()

    result = runner.invoke(app, ["research", "scan", "--root", str(_project(tmp_path))])

    assert result.exit_code == 0
    assert "1 technique" in result.stdout
    assert (tmp_path / "data" / "technique-history.jsonl").exists()
    runs = list((tmp_path / "data" / "runs").iterdir())
    assert len(runs) == 1
    assert (runs[0] / "technique_cards.json").exists()


def test_crashed_research_scan_run_still_carries_kind(tmp_path, monkeypatch):
    """A scan that dies mid-way must not leave a kind-less run that masks scan health."""
    import radar.research_radar.pipeline as pipeline_mod

    async def _boom(**kwargs):
        raise RuntimeError("simulated mid-scan crash")

    monkeypatch.setattr(pipeline_mod, "run_research_scan", _boom)
    runner = CliRunner()
    root = _project(tmp_path)

    result = runner.invoke(app, ["research", "scan", "--root", str(root)])

    assert result.exit_code != 0
    from radar.storage.run_store import RunStore

    store = RunStore(root / "data" / "runs")
    run_ids = store.list_runs()
    assert len(run_ids) == 1
    assert store.read_meta(run_ids[0]).get("kind") == "research"


def test_research_list_shows_ring_and_domain(tmp_path):
    runner = CliRunner()
    root = _project(tmp_path)
    runner.invoke(app, ["research", "scan", "--root", str(root)])

    result = runner.invoke(app, ["research", "list", "--root", str(root)])

    assert result.exit_code == 0
    assert "qlora" in result.stdout
    assert "watch" in result.stdout
    assert "fine_tuning" in result.stdout


def test_research_list_filters_by_ring(tmp_path):
    runner = CliRunner()
    root = _project(tmp_path)
    runner.invoke(app, ["research", "scan", "--root", str(root)])

    result = runner.invoke(app, ["research", "list", "--root", str(root),
                                 "--ring", "adopt"])

    assert result.exit_code == 0
    assert "qlora" not in result.stdout


def test_research_list_without_scan_prompts_for_scan(tmp_path):
    runner = CliRunner()

    result = runner.invoke(app, ["research", "list", "--root", str(_project(tmp_path))])

    assert result.exit_code == 0
    assert "radar research scan" in result.stdout


def test_research_show_prints_breakdown_and_warnings(tmp_path):
    runner = CliRunner()
    root = _project(tmp_path)
    runner.invoke(app, ["research", "scan", "--root", str(root)])

    result = runner.invoke(app, ["research", "show", "qlora", "--root", str(root)])

    assert result.exit_code == 0
    assert "QLoRA" in result.stdout
    assert "watch" in result.stdout
    assert "0000.00000" in result.stdout
    assert "citations unknown" in result.stdout


def test_research_show_unknown_id_fails(tmp_path):
    runner = CliRunner()
    root = _project(tmp_path)
    runner.invoke(app, ["research", "scan", "--root", str(root)])

    result = runner.invoke(app, ["research", "show", "nope", "--root", str(root)])

    assert result.exit_code == 1


BAD_SEED_DUPLICATE_IDS = """
techniques:
  - id: qlora
    name: QLoRA
    category: ai_infrastructure
    domain: fine_tuning
    open_code: true
    onprem_impact: reduces_memory
  - id: qlora
    name: QLoRA Duplicate
    category: ai_infrastructure
    domain: fine_tuning
    open_code: true
    onprem_impact: reduces_memory
"""


def test_research_scan_bad_seed_fails_clean_without_orphan_run_dir(tmp_path):
    """A broken seed must be rejected before create_run(): no unhandled traceback,
    and no orphaned data/runs/<id> directory left behind."""
    runner = CliRunner()
    root = tmp_path
    (root / "config").mkdir()
    (root / "config" / "technique-seed.yaml").write_text(
        BAD_SEED_DUPLICATE_IDS, encoding="utf-8"
    )
    (root / "data").mkdir()

    result = runner.invoke(app, ["research", "scan", "--root", str(root)])

    assert result.exit_code == 1
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "Duplicate technique ids" in result.output
    assert "Traceback" not in result.output
    runs_dir = root / "data" / "runs"
    assert not runs_dir.exists() or list(runs_dir.iterdir()) == []


def test_research_discover_writes_proposals(tmp_path, monkeypatch):
    from radar.discovery.technique_proposals import TechniqueProposal, load_technique_proposals
    from radar.models import Category as _Cat
    from radar.research_radar.entities import TechniqueDomain as _Dom

    async def _fake_discover(seeds, client, min_upvotes=10, limit=20):
        return [TechniqueProposal(
            suggested_id="test-time-scaling", name="Test-Time Scaling",
            arxiv_id="2502.12345", published="2025-02-18", upvotes=142,
            suggested_domain=_Dom.INFERENCE, suggested_category=_Cat.MODEL_SERVING,
            matched_keyword="inference",
        )]

    monkeypatch.setattr(
        "radar.discovery.hf_technique_candidates.discover_technique_candidates",
        _fake_discover,
    )
    runner = CliRunner()
    root = _project(tmp_path)

    result = runner.invoke(app, ["research", "discover", "--root", str(root)])

    assert result.exit_code == 0
    assert "1 technique candidate" in result.stdout
    proposals = load_technique_proposals(root / "data" / "proposed-technique-seeds.yaml")
    assert proposals[0].suggested_id == "test-time-scaling"


def test_research_discover_no_candidates_message(tmp_path, monkeypatch):
    async def _none(seeds, client, min_upvotes=10, limit=20):
        return []

    monkeypatch.setattr(
        "radar.discovery.hf_technique_candidates.discover_technique_candidates", _none,
    )
    runner = CliRunner()
    root = _project(tmp_path)

    result = runner.invoke(app, ["research", "discover", "--root", str(root)])

    assert result.exit_code == 0
    assert "No technique candidates" in result.stdout


def test_research_scan_writes_metrics_log(tmp_path):
    runner = CliRunner()
    root = _project(tmp_path)

    runner.invoke(app, ["research", "scan", "--root", str(root)])

    assert (root / "data" / "technique-metrics.jsonl").exists()


def test_research_discover_empty_run_clears_stale_proposals(tmp_path, monkeypatch):
    from radar.discovery.technique_proposals import load_technique_proposals

    async def _none(seeds, client, min_upvotes=10, limit=20):
        return []

    monkeypatch.setattr(
        "radar.discovery.hf_technique_candidates.discover_technique_candidates", _none,
    )
    runner = CliRunner()
    root = _project(tmp_path)
    stale = root / "data" / "proposed-technique-seeds.yaml"
    stale.write_text("proposals:\n  - suggested_id: old\n", encoding="utf-8")

    result = runner.invoke(app, ["research", "discover", "--root", str(root)])

    assert result.exit_code == 0
    assert load_technique_proposals(stale) == []


def test_research_discover_bad_seed_exits_clean(tmp_path):
    runner = CliRunner()
    root = _project(tmp_path)
    seed = root / "config" / "technique-seed.yaml"
    seed.write_text(
        """
techniques:
  - id: qlora
    name: QLoRA
    category: ai_infrastructure
    domain: fine_tuning
    onprem_impact: reduces_memory
  - id: qlora
    name: QLoRA Again
    category: ai_infrastructure
    domain: fine_tuning
    onprem_impact: reduces_memory
""",
        encoding="utf-8",
    )

    result = runner.invoke(app, ["research", "discover", "--root", str(root)])

    assert result.exit_code == 1
    assert "Traceback" not in result.output
