"""The publish workflow's contract: Pulse only, never blocked by a source outage."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def _workflow() -> dict[str, Any]:
    return yaml.safe_load(Path(".github/workflows/publish.yml").read_text(encoding="utf-8"))


def _steps() -> list[dict[str, Any]]:
    return _workflow()["jobs"]["build"]["steps"]


def _commands() -> str:
    return "\n".join(step.get("run", "") for step in _steps())


def test_publish_runs_collect_triage_build_export_in_order() -> None:
    commands = _commands()
    order = [
        commands.index("npm run build --prefix frontend"),
        commands.index("radar pulse collect"),
        commands.index("radar pulse triage"),
        commands.index("radar pulse export"),
    ]
    assert order == sorted(order)


def test_source_or_triage_outages_never_block_the_publish() -> None:
    flat = " ".join(_commands().replace("\\\n", " ").split())
    assert 'radar pulse collect --root . || echo "::warning' in flat
    assert 'radar pulse triage --root . || echo "::warning' in flat


def test_only_the_pulse_store_is_persisted_and_never_blocks_deploy() -> None:
    persist = next(s for s in _steps() if s.get("name") == "Persist Pulse item store")
    assert persist["continue-on-error"] is True
    assert persist["run"].split()[1:] == ["data/pulse/items.jsonl", "data/pulse/labels.jsonl"]
    names = [s.get("name") for s in _steps()]
    assert names.index("Upload Pages artifact") < names.index("Persist Pulse item store")


def test_secrets_reach_only_the_step_that_needs_them() -> None:
    with_secrets = [s["name"] for s in _steps() if "secrets." in str(s.get("env", {}))]
    assert with_secrets == ["Collect and triage"]


def test_the_retired_intelligence_pipeline_is_gone() -> None:
    commands = _commands()
    for retired in ("intelligence-", "radar scan", "radar export ", "radar-state", "calibrate"):
        assert retired not in commands, retired


def test_watchdogs_still_find_the_workflow_by_name_and_file() -> None:
    # publish-watchdog.yml matches the name; the homelab watchdog the file name.
    assert _workflow()["name"] == "Publish radar to Pages"
    watchdog = Path(".github/workflows/publish-watchdog.yml").read_text(encoding="utf-8")
    assert '"Publish radar to Pages"' in watchdog
    config = yaml.safe_load(Path("config/pulse.yaml").read_text(encoding="utf-8"))
    assert config["watchdog"]["publish_workflow"] == "publish.yml"
