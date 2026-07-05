from __future__ import annotations

from pathlib import Path


def test_publish_runs_model_scan_before_export_and_commits_model_history():
    yml = Path(".github/workflows/publish.yml").read_text(encoding="utf-8")
    assert "radar models scan" in yml
    i_models = yml.index("radar models scan")
    i_export = yml.index("radar export")
    assert i_models < i_export, "model scan must run before export"
    assert "data/model-history.jsonl" in yml


def test_publish_runs_research_scan_before_export_and_commits_technique_history():
    text = Path(".github/workflows/publish.yml").read_text(encoding="utf-8")

    research_idx = text.index("radar research scan")
    export_idx = text.index("radar export")
    models_idx = text.index("radar models scan")

    assert models_idx < research_idx < export_idx
    assert "data/technique-history.jsonl" in text


def test_publish_commits_technique_metrics_log():
    text = Path(".github/workflows/publish.yml").read_text(encoding="utf-8")

    assert "data/technique-metrics.jsonl" in text


def test_publish_runs_trending_scan_and_commits_observations():
    text = Path(".github/workflows/publish.yml").read_text(encoding="utf-8")

    research_idx = text.index("radar research scan")
    trending_idx = text.index("radar trending scan")
    export_idx = text.index("radar export")

    assert research_idx < trending_idx < export_idx
    assert "data/trending-observations.jsonl" in text
