"""Tests for evidence assembly: signals -> metrics -> ProjectEvidence -> notes."""

from __future__ import annotations

from datetime import UTC, datetime

from radar.models import Advisory, Category, ProjectEvidence, Signal
from radar.pipeline.evidence import (
    build_evidence,
    collect_project_metrics,
    evidence_notes,
)
from radar.storage.metrics_store import ProjectMetrics


NOW = datetime(2026, 6, 13, tzinfo=UTC)


def _snapshot_signal(project: str, stars: int, license_id: str = "MIT") -> Signal:
    return Signal(
        id=f"github:{project}:repo_snapshot",
        source_id=f"github-{project.lower()}",
        project=project,
        category=Category.MODEL_SERVING,
        title=f"{project} repository snapshot",
        url="https://github.com/org/repo",
        published_at=NOW,
        signal_type="github_repo_snapshot",
        metadata={
            "stars": stars,
            "forks": 10,
            "open_issues": 5,
            "license": license_id,
            "pushed_at": "2026-06-12T00:00:00Z",
        },
    )


def _release_signal(project: str, tag: str) -> Signal:
    return Signal(
        id=f"github:{project}:release:{tag}",
        source_id=f"github-{project.lower()}",
        project=project,
        category=Category.MODEL_SERVING,
        title=f"{project} released {tag}",
        url=f"https://github.com/org/repo/releases/{tag}",
        published_at=NOW,
        signal_type="github_release",
        metadata={"tag": tag},
    )


def test_collect_project_metrics_from_snapshot_and_releases():
    signals = [
        _snapshot_signal("vLLM", stars=1200),
        _release_signal("vLLM", "v1.0"),
        _release_signal("vLLM", "v1.1"),
        _release_signal("Ollama", "v0.5"),
    ]

    metrics = collect_project_metrics(signals, run_id="run-1", observed_at=NOW)

    vllm = metrics["vLLM"]
    assert vllm.stars == 1200
    assert vllm.license == "MIT"
    assert vllm.releases_in_window == 2
    assert vllm.pushed_at == "2026-06-12T00:00:00Z"
    # Ollama has releases but no snapshot: still gets a row.
    assert metrics["Ollama"].releases_in_window == 1
    assert metrics["Ollama"].stars is None


def test_build_evidence_computes_star_growth_and_license_change():
    current = ProjectMetrics(
        project="vLLM", run_id="run-2", observed_at=NOW,
        stars=1100, license="BUSL-1.1", releases_in_window=3,
        pushed_at="2026-06-12T00:00:00Z",
    )
    previous = ProjectMetrics(
        project="vLLM", run_id="run-1",
        observed_at=datetime(2026, 6, 6, tzinfo=UTC),
        stars=1000, license="Apache-2.0",
    )

    evidence = build_evidence(current, previous, now=NOW)

    assert evidence.star_growth == 100
    assert evidence.star_growth_pct == 10.0
    assert evidence.license_changed_from == "Apache-2.0"
    assert evidence.releases_in_window == 3
    assert evidence.days_since_push == 1


def test_build_evidence_without_previous_has_no_growth():
    current = ProjectMetrics(
        project="vLLM", run_id="run-1", observed_at=NOW, stars=1000,
    )

    evidence = build_evidence(current, None, now=NOW)

    assert evidence.star_growth is None
    assert evidence.license_changed_from is None


def test_build_evidence_same_license_is_not_a_change():
    current = ProjectMetrics(
        project="x", run_id="r2", observed_at=NOW, license="MIT",
    )
    previous = ProjectMetrics(
        project="x", run_id="r1", observed_at=NOW, license="MIT",
    )

    assert build_evidence(current, previous, now=NOW).license_changed_from is None


def test_evidence_notes_render_human_readable_lines():
    evidence = ProjectEvidence(
        star_growth=1240,
        star_growth_pct=3.1,
        releases_in_window=4,
        advisories=[Advisory(id="GHSA-xxxx", severity="HIGH", summary="RCE")],
        license_changed_from="Apache-2.0",
        license="BUSL-1.1",
        hn_mentions=12,
        downloads_weekly=2_400_000,
    )

    notes = evidence_notes(evidence)

    joined = "\n".join(notes)
    assert "+1,240" in joined and "3.1%" in joined
    assert "4 releases" in joined
    assert "HIGH" in joined and "GHSA-xxxx" in joined
    assert "Apache-2.0" in joined and "BUSL-1.1" in joined
    assert "12 Hacker News mentions" in joined
    assert "2,400,000 weekly downloads" in joined


def test_evidence_notes_empty_for_empty_evidence():
    assert evidence_notes(ProjectEvidence()) == []
