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


def test_firehose_entries_are_reclassified_to_tracked_projects(tmp_path: Path, monkeypatch):
    """A firehose feed's entries must attach to tracked projects, not flood as one card."""
    import radar.orchestrator as orch
    from radar.models import Category, Signal
    from datetime import datetime, timezone

    initialize_project(tmp_path)
    (tmp_path / "data" / "config.yaml").write_text(
        """
version: "1.0"
sources:
  - id: github-vllm
    type: github_repo
    enabled: true
    project: vLLM
    category: model_serving
    url: https://github.com/vllm-project/vllm
    tags: [inference]
  - id: rss-hf
    type: rss
    enabled: true
    firehose: true
    project: HuggingFace Blog
    category: model_serving
    url: https://example.com/feed.xml
    tags: [firehose]
quotas:
  model_serving: 10
scoring:
  default_ring: watch
""",
        encoding="utf-8",
    )

    def fake_build_collectors(config, client):
        class _Stub:
            async def fetch(self, since):
                return [
                    Signal(
                        id="rss:rss-hf:a",
                        source_id="rss-hf",
                        project="HuggingFace Blog",
                        category=Category.MODEL_SERVING,
                        title="vLLM 0.7 released with faster attention",
                        url="https://example.com/a",
                        published_at=datetime.now(timezone.utc),
                        signal_type="rss_entry",
                        metadata={"feed": "rss-hf", "firehose": True},
                    ),
                    Signal(
                        id="rss:rss-hf:b",
                        source_id="rss-hf",
                        project="HuggingFace Blog",
                        category=Category.MODEL_SERVING,
                        title="A poem about the weather",
                        url="https://example.com/b",
                        published_at=datetime.now(timezone.utc),
                        signal_type="rss_entry",
                        metadata={"feed": "rss-hf", "firehose": True},
                    ),
                ]

        return [_Stub()]

    monkeypatch.setattr(orch, "build_collectors", fake_build_collectors)

    result = RadarOrchestrator(root=tmp_path).scan(days=2)

    projects = {c.project for c in result.cards}
    assert "vLLM" in projects  # matched entry attached to tracked project
    assert "HuggingFace Blog" not in projects  # firehose never becomes its own card


def test_scan_records_project_history_and_writes_report(tmp_path: Path):
    from radar.storage.history_store import HistoryStore

    initialize_project(tmp_path)
    _write_manual_config(tmp_path)

    result = RadarOrchestrator(root=tmp_path).scan(days=2)

    # History report artifact is written for the run.
    history_path = tmp_path / "data" / "runs" / result.run_id / "history.md"
    assert history_path.exists()
    assert "Model Context Protocol" in history_path.read_text(encoding="utf-8")

    # The durable history records the first observation.
    history = HistoryStore(tmp_path / "data" / "radar.db")
    events = history.history_for("Model Context Protocol")
    assert len(events) == 1
    assert events[0].change_type.value == "new"


def test_history_accumulates_across_scans(tmp_path: Path):
    from radar.storage.history_store import HistoryStore

    initialize_project(tmp_path)
    _write_manual_config(tmp_path)

    orchestrator = RadarOrchestrator(root=tmp_path)
    orchestrator.scan(days=2)
    orchestrator.scan(days=2)  # unchanged → no new event

    history = HistoryStore(tmp_path / "data" / "radar.db")
    events = history.history_for("Model Context Protocol")
    # Unchanged second scan must not append a duplicate event.
    assert len(events) == 1
    summaries = history.summaries()
    assert summaries[0].change_count == 1
