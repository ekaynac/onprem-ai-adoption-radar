from __future__ import annotations

import subprocess
from pathlib import Path


def _publish_workflow() -> str:
    return Path(".github/workflows/publish.yml").read_text(encoding="utf-8")


def test_publish_restores_canonical_state_before_migration():
    text = _publish_workflow()

    restore_idx = text.index("radar intelligence-state-restore")
    migrate_idx = text.index("radar intelligence-migrate")

    assert "gh release download radar-state" in text
    assert "intelligence-state.tar.gz" in text
    assert restore_idx < migrate_idx


def test_publish_bootstraps_only_for_confirmed_missing_state():
    text = _publish_workflow()

    assert 'case "$release_status" in' in text
    assert "200)" in text
    assert "404)" in text
    assert "Unexpected GitHub API status" in text
    assert "if gh release download" not in text


def test_publish_checkpoints_discovery_and_verified_state_before_export():
    text = _publish_workflow()

    discovery_idx = text.index("radar intelligence-run discovery")
    discovery_checkpoint_idx = text.index("Checkpoint discovered intelligence")
    verify_new_idx = text.index("radar intelligence-run verify-new")
    verified_checkpoint_idx = text.index("Checkpoint verified intelligence")
    export_idx = text.index("radar export")

    assert discovery_idx < discovery_checkpoint_idx < verify_new_idx
    assert verify_new_idx < verified_checkpoint_idx < export_idx
    assert text.count("gh release upload radar-state") >= 2
    assert text.count("--clobber") >= 2


def test_publish_does_not_commit_raw_canonical_state():
    lines = [line.strip() for line in _publish_workflow().splitlines()]

    assert "git add -f data/intelligence.db" not in lines
    assert "git add -f data/intelligence/events.jsonl || true" not in lines
    assert "git add -f data/intelligence/snapshots || true" not in lines
    assert "git add -f data/intelligence/public-snapshot.v1.json || true" in lines


def test_raw_canonical_state_is_not_tracked_by_git():
    tracked = subprocess.check_output(
        [
            "git",
            "ls-files",
            "data/intelligence.db",
            "data/intelligence/events.jsonl",
            "data/intelligence/snapshots/**",
        ],
        text=True,
    ).splitlines()

    assert tracked == []


def test_publish_has_bounded_runtime_and_optional_hugging_face_auth():
    text = _publish_workflow()

    assert "timeout-minutes: 180" in text
    assert "HF_TOKEN: ${{ secrets.HF_TOKEN }}" in text


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


def test_publish_commits_model_metrics_log():
    text = Path(".github/workflows/publish.yml").read_text(encoding="utf-8")
    assert "data/model-metrics.jsonl" in text


def test_publish_runs_candidate_scan_and_commits_store():
    text = Path(".github/workflows/publish.yml").read_text(encoding="utf-8")
    models_idx = text.index("radar models scan")
    cand_idx = text.index("radar models candidates scan")
    export_idx = text.index("radar export")
    assert models_idx < cand_idx < export_idx
    assert "data/model-candidate-observations.jsonl" in text


def test_publish_runs_paper_candidate_scan_and_commits_store():
    text = Path(".github/workflows/publish.yml").read_text(encoding="utf-8")
    research_idx = text.index("radar research scan")
    cand_idx = text.index("radar research candidates scan")
    export_idx = text.index("radar export")
    assert research_idx < cand_idx < export_idx
    assert "data/technique-candidate-observations.jsonl" in text


def test_publish_scan_health_gate_before_scoring_quality_gate():
    text = Path(".github/workflows/publish.yml").read_text(encoding="utf-8")

    scan_health_idx = text.index("Scan health gate")
    scoring_idx = text.index("Scoring quality gate")

    assert scan_health_idx < scoring_idx
    assert "radar scan-health --root . --check" in text


def test_publish_scan_step_uses_publish_history_flag():
    text = Path(".github/workflows/publish.yml").read_text(encoding="utf-8")

    # Pinned: without --publish-history the scan would write to the
    # gitignored local lane (D5) and the committed timeline would never
    # advance, even though the persist step below force-adds it every run.
    assert "radar scan --root . --days 7 --publish-history" in text


def test_publish_persist_step_force_adds_source_health_log():
    text = Path(".github/workflows/publish.yml").read_text(encoding="utf-8")

    assert "git add -f data/source-health.jsonl" in text


def test_spec_verify_workflow_runs_check():
    text = Path(".github/workflows/spec-verify.yml").read_text(encoding="utf-8")
    assert "radar models verify --root . --check" in text
    assert "schedule:" in text


def test_publish_deploy_retries_on_transient_pages_failure():
    text = Path(".github/workflows/publish.yml").read_text(encoding="utf-8")

    # The Pages deploy is retried (>=2 attempts), with continue-on-error guarding
    # the earlier ones, so a transient "try again later" self-heals without a
    # manual re-run. The final attempt is unguarded (a persistent failure still
    # fails the job).
    assert text.count("uses: actions/deploy-pages@v5") >= 2
    assert "continue-on-error: true" in text
