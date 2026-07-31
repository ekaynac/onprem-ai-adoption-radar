from pathlib import Path

import yaml

from test_intelligence_workflows import all_run_commands, load_yaml


def test_readme_matches_shipping_cadence_and_current_source_count() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    seed = yaml.safe_load(
        Path("config/seed-sources.yaml").read_text(encoding="utf-8")
    )
    source_count = len(seed["sources"])

    assert "every two hours" in readme.casefold()
    assert f"{source_count} curated sources" in readme
    assert "51 curated sources" not in readme
    assert "a daily github action scans" not in readme.casefold()


def test_readme_separates_shipping_restoration_and_planner_surfaces() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "### Radar — shipping" in readme
    assert "### Intelligence — restoration in progress" in readme
    assert "### Planner — CLI and MCP" in readme
    assert "web planner arrives in Phase 3" in readme


def test_persistence_artifacts_are_committed_by_publish_workflow() -> None:
    commands = all_run_commands(load_yaml(".github/workflows/publish.yml"))

    assert "git add -f data/intelligence.db" in commands
    assert "git add -f data/intelligence/events.jsonl" in commands
    assert "git add -f data/intelligence/snapshots" in commands


def test_persistence_documents_recovery_order_and_derived_snapshot() -> None:
    persistence = Path("docs/persistence.md").read_text(encoding="utf-8")

    assert "intelligence-migrate" in persistence
    assert "intelligence-replay-events" in persistence
    assert "events.jsonl" in persistence
    assert "snapshots/<sha256>.bin" in persistence
    assert "public-snapshot.v1.json" in persistence
    assert "derived" in persistence.casefold()
