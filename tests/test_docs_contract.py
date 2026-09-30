import re
from pathlib import Path

import yaml

from test_intelligence_workflows import all_run_commands, load_yaml


def test_readme_matches_shipping_cadence_without_a_frozen_source_count() -> None:
    # The source autopilot commits new seeds weekly with [skip ci]; a count
    # baked into the README silently went stale and kept main red for weeks.
    readme = Path("README.md").read_text(encoding="utf-8")
    seed = yaml.safe_load(
        Path("config/seed-sources.yaml").read_text(encoding="utf-8")
    )

    assert seed["sources"], "seed-sources.yaml must ship at least one source"
    assert "every two hours" in readme.casefold()
    assert re.search(r"\b\d+ curated sources\b", readme) is None
    assert "a daily github action scans" not in readme.casefold()


def test_readme_leads_with_pulse_and_links_its_docs() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")

    assert readme.index("## Radar Pulse") < readme.index("## Also in this repository")
    for link in ("docs/pulse.md", "docs/jev.md",
                 "docs/reports/2026-09-29-radar-rescue-research-and-plan.md"):
        assert link in readme and Path(link).exists(), link
    # Frozen features are named as frozen, not sold as shipping.
    assert "Frozen since 2026-09-30" in readme
    assert "### Planner — CLI and MCP" not in readme
    assert "restoration in progress" not in readme.casefold()


def test_jev_doc_matches_the_shipped_configuration() -> None:
    import yaml as _yaml

    from radar.pulse.telegram import DIGEST_PER_LANE

    doc = Path("docs/jev.md").read_text(encoding="utf-8")
    pulse = _yaml.safe_load(Path("config/pulse.yaml").read_text(encoding="utf-8"))
    questions = _yaml.safe_load(Path("config/pulse-questions.yaml").read_text(encoding="utf-8"))

    budget = pulse["triage"]["token_budget_per_run"]
    assert f"{budget:,}" in doc  # "300,000"
    assert "config/pulse-questions.yaml" in doc
    for lane, keys in questions["lanes"].items():
        for key in keys:
            assert f"`{key}`" in doc, f"{lane}.{key} undocumented"
    pulse_doc = Path("docs/pulse.md").read_text(encoding="utf-8")
    counts = DIGEST_PER_LANE
    assert (f"top {counts['model']} models, {counts['paper']} papers, "
            f"{counts['repo']} repos and {counts['news']} news items") in pulse_doc


def test_readme_describes_current_verification_behavior_without_refetch_claims() -> None:
    readme = Path("README.md").read_text(encoding="utf-8").casefold()

    assert "re-evaluates persisted trusted claims weekly" in readme
    assert "re-verifies them against upstream" not in readme
    assert "re-fetch and re-evaluate every trusted claim" not in readme


def test_persistence_artifacts_are_checkpointed_outside_git() -> None:
    commands = all_run_commands(load_yaml(".github/workflows/publish.yml"))

    assert "radar intelligence-state-pack" in commands
    assert "gh release upload radar-state" in commands
    assert "git add -f data/intelligence.db" not in commands
    assert "git add -f data/intelligence/events.jsonl" not in commands
    assert "git add -f data/intelligence/snapshots" not in commands


def test_persistence_documents_recovery_order_and_derived_snapshot() -> None:
    persistence = Path("docs/persistence.md").read_text(encoding="utf-8")

    assert "intelligence-migrate" in persistence
    assert "intelligence-replay-events" in persistence
    assert "events.jsonl" in persistence
    assert "snapshots/<sha256>.bin" in persistence
    assert "public-snapshot.v1.json" in persistence
    assert "derived" in persistence.casefold()
