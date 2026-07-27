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


def test_publish_deploy_retries_on_transient_pages_failure():
    text = Path(".github/workflows/publish.yml").read_text(encoding="utf-8")

    # The Pages deploy is retried (>=2 attempts), with continue-on-error guarding
    # the earlier ones, so a transient "try again later" self-heals without a
    # manual re-run. The final attempt is unguarded (a persistent failure still
    # fails the job).
    assert text.count("uses: actions/deploy-pages@v5") >= 2
    assert "continue-on-error: true" in text
