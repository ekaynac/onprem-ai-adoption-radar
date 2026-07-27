"""Degraded-run gate: collection outages must not reach scoring or history."""

from pathlib import Path

from radar.init_project import initialize_project
from radar.orchestrator import RadarOrchestrator


def _write_config(tmp_path: Path, n_dead_rss: int, with_manual: bool) -> None:
    sources = ""
    if with_manual:
        sources += """
  - id: mcp-docs
    type: manual
    enabled: true
    project: Model Context Protocol
    category: mcp_tooling
    url: https://modelcontextprotocol.io/docs/getting-started/intro
    tags: [mcp]
"""
    for i in range(n_dead_rss):
        sources += f"""
  - id: rss-dead-{i}
    type: rss
    enabled: true
    project: DeadFeed{i}
    category: model_serving
    url: http://127.0.0.1:1/feed-{i}.xml
    tags: []
"""
    (tmp_path / "data" / "config.yaml").write_text(
        f"""
version: "1.0"
sources:{sources}
quotas:
  mcp_tooling: 4
  model_serving: 12
scoring:
  default_ring: watch
""",
        encoding="utf-8",
    )


def test_outage_run_is_degraded_and_writes_no_history(tmp_path: Path):
    initialize_project(tmp_path)
    _write_config(tmp_path, n_dead_rss=3, with_manual=True)  # 3/4 sources error

    result = RadarOrchestrator(root=tmp_path).scan(days=2)

    assert result.degraded is True
    assert result.degraded_reason and "3/4" in result.degraded_reason
    assert result.cards == []
    assert result.deltas == []
    # Nothing durable was written.
    assert not (tmp_path / "data" / "history.jsonl").exists()
    run_dir = tmp_path / "data" / "runs" / result.run_id
    assert (run_dir / "raw_signals.json").exists()  # evidence is kept
    assert not (run_dir / "decision_cards.json").exists()

    import json

    meta = json.loads((run_dir / "meta.json").read_text())
    assert meta["degraded"] is True


def test_healthy_run_is_not_degraded(tmp_path: Path):
    initialize_project(tmp_path)
    _write_config(tmp_path, n_dead_rss=0, with_manual=True)

    result = RadarOrchestrator(root=tmp_path).scan(days=2)

    assert result.degraded is False
    assert len(result.cards) == 1
