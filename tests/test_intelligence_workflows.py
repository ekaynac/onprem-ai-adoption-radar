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


def load_all_workflows() -> dict[Path, dict[str, Any]]:
    return {
        path: load_yaml(str(path))
        for path in sorted(Path(".github/workflows").glob("*.yml"))
    }


def test_only_publish_workflow_checkpoints_intelligence_and_deploys_pages() -> None:
    workflows = load_all_workflows()
    state_owners = [
        path
        for path, workflow in workflows.items()
        if "radar intelligence-state-pack" in all_run_commands(workflow)
    ]
    page_deployers = [
        path
        for path in workflows
        if "actions/deploy-pages" in path.read_text(encoding="utf-8")
    ]

    publish = Path(".github/workflows/publish.yml")
    assert state_owners == [publish]
    assert page_deployers == [publish]

    commands = all_run_commands(workflows[publish])
    assert "radar intelligence-run discovery" in commands
    assert "radar intelligence-run verify-new" in commands
    assert "radar intelligence-state-restore" in commands
    assert "gh release upload radar-state" in commands
    assert "git add -f data/intelligence.db" not in commands
    assert "git add -f data/intelligence/snapshots" not in commands


def test_two_hour_publish_and_weekly_verification_are_split() -> None:
    workflow = load_yaml(".github/workflows/publish.yml")
    triggers = workflow.get("on") or workflow.get(True)
    commands = all_run_commands(workflow)

    assert {"cron": "17 */2 * * *"} in triggers["schedule"]
    assert {"cron": "43 5 * * 0"} in triggers["schedule"]
    assert "radar intelligence-run enrichment" in commands
    assert "radar intelligence-run qualification" in commands
    assert "radar intelligence-run recommendations" in commands
    assert "radar models platforms-verify" in commands
    assert "radar intelligence-run verification" in commands
    assert commands.count("radar intelligence-state-pack") == 2
    assert commands.count("gh release upload radar-state") == 2


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
    assert "radar export --root . --out _site" in commands
    assert commands.index("radar export --root . --out _site") < commands.index(
        "playwright test"
    )
    assert "playwright test" in commands
    assert "git diff --exit-code -- frontend/src/api/generated" in commands
    assert "TEST_POSTGRES_URL" in serialized
    assert "postgres:" in serialized
