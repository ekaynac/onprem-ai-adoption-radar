"""The weekly digest workflow generates, rasterizes, commits, dispatches."""

from __future__ import annotations

from pathlib import Path

import yaml


def test_workflow_schedule_and_perms():
    wf = yaml.safe_load(Path(".github/workflows/digest.yml").read_text(encoding="utf-8"))
    triggers = wf.get("on") or wf.get(True)
    assert "schedule" in triggers and "workflow_dispatch" in triggers
    assert triggers["schedule"][0]["cron"] == "0 8 * * 1"
    assert wf["permissions"]["contents"] == "write"


def test_workflow_generates_rasterizes_commits_dispatches():
    text = Path(".github/workflows/digest.yml").read_text(encoding="utf-8")
    assert "radar digest generate" in text
    assert "librsvg2-bin" in text and "rsvg-convert" in text
    assert "digests/" in text and "data/digest-log.jsonl" in text
    assert "gh workflow run publish.yml" in text
