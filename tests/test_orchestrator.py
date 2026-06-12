from pathlib import Path

from radar.init_project import initialize_project
from radar.orchestrator import RadarOrchestrator


def test_orchestrator_scan_with_manual_source_creates_artifacts(tmp_path: Path):
    initialize_project(tmp_path)
    config_path = tmp_path / "data" / "config.yaml"
    config_path.write_text(
        """
version: "1.0"
sources:
  - id: mcp-docs
    type: manual
    enabled: true
    project: Model Context Protocol
    category: mcp_tooling
    url: https://modelcontextprotocol.io/docs/getting-started/intro
    tags: [mcp, protocol]
quotas:
  mcp_tooling: 4
scoring:
  default_ring: watch
""",
        encoding="utf-8",
    )

    orchestrator = RadarOrchestrator(root=tmp_path)
    result = orchestrator.scan(days=2)

    assert result.run_id.startswith("run-")
    assert (tmp_path / "data" / "runs" / result.run_id / "raw_signals.json").exists()
    assert (
        tmp_path / "data" / "runs" / result.run_id / "decision_cards.json"
    ).exists()
    assert (tmp_path / "data" / "runs" / result.run_id / "report.md").exists()
    assert result.cards[0].project == "Model Context Protocol"


def _write_manual_config(tmp_path: Path) -> None:
    config_path = tmp_path / "data" / "config.yaml"
    config_path.write_text(
        """
version: "1.0"
sources:
  - id: mcp-docs
    type: manual
    enabled: true
    project: Model Context Protocol
    category: mcp_tooling
    url: https://modelcontextprotocol.io/docs/getting-started/intro
    tags: [mcp, protocol]
quotas:
  mcp_tooling: 4
scoring:
  default_ring: watch
""",
        encoding="utf-8",
    )


def test_first_scan_writes_try_this_week_with_new_project(tmp_path: Path):
    initialize_project(tmp_path)
    _write_manual_config(tmp_path)

    result = RadarOrchestrator(root=tmp_path).scan(days=2)

    delta_path = tmp_path / "data" / "runs" / result.run_id / "try-this-week.md"
    assert delta_path.exists()
    assert result.delta_report_path == delta_path
    content = delta_path.read_text(encoding="utf-8")
    assert "New on the radar" in content
    assert "Model Context Protocol" in content
    assert len(result.deltas) == 1


def test_second_unchanged_scan_reports_no_changes(tmp_path: Path):
    initialize_project(tmp_path)
    _write_manual_config(tmp_path)

    orchestrator = RadarOrchestrator(root=tmp_path)
    orchestrator.scan(days=2)
    second = orchestrator.scan(days=2)

    content = (
        tmp_path / "data" / "runs" / second.run_id / "try-this-week.md"
    ).read_text(encoding="utf-8")
    assert "No changes since the last scan." in content
    assert second.deltas == []
