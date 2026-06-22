from __future__ import annotations

from pathlib import Path


def test_publish_runs_model_scan_before_export_and_commits_model_history():
    yml = Path(".github/workflows/publish.yml").read_text(encoding="utf-8")
    assert "radar models scan" in yml
    i_models = yml.index("radar models scan")
    i_export = yml.index("radar export")
    assert i_models < i_export, "model scan must run before export"
    assert "data/model-history.jsonl" in yml
