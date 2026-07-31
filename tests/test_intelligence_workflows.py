from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_yaml(path: str) -> dict[str, Any]:
    value = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def all_run_commands(workflow: dict[str, Any]) -> str:
    commands: list[str] = []
    for job in workflow.get("jobs", {}).values():
        for step in job.get("steps", []):
            command = step.get("run")
            if isinstance(command, str):
                commands.append(command)
    return "\n".join(commands)


def test_discovery_workflow_runs_every_two_hours() -> None:
    workflow = load_yaml(".github/workflows/intelligence-discovery.yml")
    triggers = workflow.get("on") or workflow.get(True)

    assert triggers["schedule"] == [{"cron": "17 */2 * * *"}]
    assert "workflow_dispatch" in triggers
    assert workflow["permissions"] == {
        "contents": "write",
        "pages": "write",
        "id-token": "write",
    }
    assert workflow["concurrency"]["group"] == "pages"

    commands = all_run_commands(workflow)
    assert "radar intelligence-migrate" in commands
    assert "radar intelligence-run discovery" in commands
    assert "radar intelligence-run verification" in commands
    assert "radar export" in commands
    assert "public-snapshot.v1.json" in commands
    assert "data/intelligence/events.jsonl" in commands
    assert "[skip ci]" in commands


def test_daily_publish_and_weekly_verification_are_split() -> None:
    workflow = load_yaml(".github/workflows/publish.yml")
    triggers = workflow.get("on") or workflow.get(True)
    commands = all_run_commands(workflow)

    assert {"cron": "0 6 * * *"} in triggers["schedule"]
    assert {"cron": "43 5 * * 0"} in triggers["schedule"]
    assert "radar intelligence-run enrichment" in commands
    assert "radar intelligence-run qualification" in commands
    assert "radar intelligence-run recommendations" in commands
    assert "radar intelligence-run verification" in commands


def test_ci_runs_backend_frontend_postgres_and_openapi_drift_checks() -> None:
    workflow = load_yaml(".github/workflows/ci.yml")
    commands = all_run_commands(workflow)
    serialized = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "pytest" in commands
    assert "npm ci" in commands
    assert "npm test" in commands
    assert "npm run typecheck" in commands
    assert "npm run lint" in commands
    assert "npm run build" in commands
    assert "playwright test" in commands
    assert "git diff --exit-code -- frontend/src/api/generated" in commands
    assert "TEST_POSTGRES_URL" in serialized
    assert "postgres:" in serialized
