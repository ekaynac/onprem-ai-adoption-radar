"""The source-autopilot workflow promotes and commits under the right gates."""

from __future__ import annotations

from pathlib import Path

import yaml


def _workflow() -> dict:
    text = Path(".github/workflows/source-autopilot.yml").read_text(encoding="utf-8")
    return yaml.safe_load(text)


def test_workflow_runs_weekly_with_dispatch_and_write_perms():
    wf = _workflow()
    # PyYAML parses the bare `on:` key as boolean True — accept either.
    triggers = wf.get("on") or wf.get(True)
    assert "schedule" in triggers and "workflow_dispatch" in triggers
    assert triggers["schedule"][0]["cron"] == "30 7 * * 1"
    assert wf["permissions"]["contents"] == "write"
    assert wf["permissions"]["actions"] == "write"


def test_workflow_promotes_gates_commits_and_dispatches():
    text = Path(".github/workflows/source-autopilot.yml").read_text(encoding="utf-8")

    assert "radar trending promote" in text
    assert "config/seed-sources.yaml" in text
    assert "data/autopilot-log.jsonl" in text
    # commit is gated on the seed changing, then publish is dispatched
    assert "git diff --quiet -- config/seed-sources.yaml" in text
    assert "gh workflow run publish.yml" in text
