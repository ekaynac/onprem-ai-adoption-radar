"""Tests for offline replay/re-score from persisted raw signals."""

from __future__ import annotations

from pathlib import Path

from radar.init_project import initialize_project
from radar.orchestrator import RadarOrchestrator


MANUAL_CONFIG = """
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
"""


def _scanned_root(tmp_path: Path) -> tuple[RadarOrchestrator, str]:
    initialize_project(tmp_path)
    (tmp_path / "data" / "config.yaml").write_text(MANUAL_CONFIG, encoding="utf-8")
    orchestrator = RadarOrchestrator(root=tmp_path)
    result = orchestrator.scan(days=2)
    return orchestrator, result.run_id


def test_replay_rescores_persisted_signals_offline(tmp_path: Path):
    orchestrator, original_run = _scanned_root(tmp_path)

    replay = orchestrator.replay(original_run)

    assert replay.run_id != original_run
    assert replay.cards[0].project == "Model Context Protocol"
    assert replay.report_path.exists()
    # The new run is marked as a replay of the original.
    import json

    meta = json.loads(
        (tmp_path / "data" / "runs" / replay.run_id / "meta.json").read_text()
    )
    assert meta["replay_of"] == original_run


def test_replay_does_not_touch_history_or_db_cards(tmp_path: Path):
    orchestrator, original_run = _scanned_root(tmp_path)
    history_before = (tmp_path / "data" / "history.jsonl").read_text(encoding="utf-8")
    cards_before = [c.model_dump_json() for c in orchestrator.latest_cards()]

    orchestrator.replay(original_run)

    assert (tmp_path / "data" / "history.jsonl").read_text(encoding="utf-8") == history_before
    assert [c.model_dump_json() for c in orchestrator.latest_cards()] == cards_before


def test_replay_reflects_current_config(tmp_path: Path):
    """The whole point: change scoring config, replay, see different output."""
    _orchestrator, original_run = _scanned_root(tmp_path)
    # Make 'mcp' a security-penalty tag — the replayed card must now carry risk.
    (tmp_path / "data" / "config.yaml").write_text(
        MANUAL_CONFIG.replace(
            "scoring:\n  default_ring: watch",
            "scoring:\n  default_ring: watch\n  security_penalty_tags: [mcp]",
        ),
        encoding="utf-8",
    )
    fresh = RadarOrchestrator(root=tmp_path)

    replay = fresh.replay(original_run)

    card = replay.cards[0]
    assert card.risk_level == "high"


def test_replay_unknown_run_raises(tmp_path: Path):
    orchestrator, _ = _scanned_root(tmp_path)

    import pytest

    with pytest.raises(FileNotFoundError):
        orchestrator.replay("run-19990101T000000Z-deadbeef")


def test_rescore_is_side_effect_free(tmp_path: Path):
    orchestrator, original_run = _scanned_root(tmp_path)
    runs_before = sorted(p.name for p in (tmp_path / "data" / "runs").iterdir())
    history_before = (tmp_path / "data" / "history.jsonl").read_text(encoding="utf-8")
    cards_before = [c.model_dump_json() for c in orchestrator.latest_cards()]

    from radar.models import Signal
    from radar.storage.config import load_config

    config = load_config(tmp_path / "data" / "config.yaml")
    raw = [
        Signal.model_validate(item)
        for item in orchestrator.run_store.load_stage(original_run, "raw_signals")
    ]
    cards = orchestrator._rescore(raw, config, source_run_id=original_run)

    assert cards  # produced cards
    runs_after = sorted(p.name for p in (tmp_path / "data" / "runs").iterdir())
    assert runs_after == runs_before  # no new run dir
    assert (tmp_path / "data" / "history.jsonl").read_text(encoding="utf-8") == history_before
    assert [c.model_dump_json() for c in orchestrator.latest_cards()] == cards_before


def test_rescore_applies_weights(tmp_path: Path):
    orchestrator, original_run = _scanned_root(tmp_path)
    from radar.models import Signal
    from radar.storage.config import load_config

    config = load_config(tmp_path / "data" / "config.yaml")
    raw = [
        Signal.model_validate(item)
        for item in orchestrator.run_store.load_stage(original_run, "raw_signals")
    ]

    baseline = orchestrator._rescore(raw, config, source_run_id=original_run)
    # Weight a dimension that differs from the mean so the score must move.
    weighted = orchestrator._rescore(
        raw, config, source_run_id=original_run,
        weights={"open_source_maturity": 5.0},
    )

    # Same projects, but the weighting changes representative scores.
    base_scores = {c.project: c.score for c in baseline}
    weighted_scores = {c.project: c.score for c in weighted}
    assert base_scores != weighted_scores
