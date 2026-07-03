"""CLI: radar research scan / list / show against a temp project root."""

from pathlib import Path

from typer.testing import CliRunner

from radar.cli import app


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
