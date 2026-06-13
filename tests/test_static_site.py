"""Tests for the static-site export, focused on per-project pages."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from radar.models import Category, DecisionCard, Ring
from radar.storage.metrics_store import ProjectMetrics
from radar.web.static_site import render_static_site


def _card(project: str, ring: Ring) -> DecisionCard:
    return DecisionCard(
        project=project, category=Category.MODEL_SERVING, ring=ring,
        summary=f"{project} summary", workflow_fit={}, risk_level="low",
    )


def test_export_writes_per_project_pages_with_metrics(tmp_path: Path):
    cards = [_card("vLLM", Ring.ADOPT), _card("Model Context Protocol", Ring.PILOT)]
    metrics_by_project = {
        "vLLM": [
            ProjectMetrics(
                project="vLLM", run_id="run-1",
                observed_at=datetime(2026, 6, 10, tzinfo=UTC), stars=54321,
            )
        ]
    }

    render_static_site(
        cards,
        tmp_path / "_site",
        datetime(2026, 6, 13, tzinfo=UTC),
        metrics_by_project=metrics_by_project,
    )

    vllm_page = tmp_path / "_site" / "project_vllm.html"
    mcp_page = tmp_path / "_site" / "project_model-context-protocol.html"
    assert vllm_page.exists() and mcp_page.exists()
    text = vllm_page.read_text(encoding="utf-8")
    assert "vLLM" in text
    assert "54,321" in text or "54321" in text


def test_static_index_links_to_project_pages(tmp_path: Path):
    render_static_site(
        [_card("vLLM", Ring.ADOPT)],
        tmp_path / "_site",
        datetime(2026, 6, 13, tzinfo=UTC),
    )

    index = (tmp_path / "_site" / "index.html").read_text(encoding="utf-8")
    assert 'href="project_vllm.html"' in index
    assert (tmp_path / "_site" / "project_vllm.html").exists()


def test_render_without_metrics_still_writes_project_pages(tmp_path: Path):
    # Back-compat: omitting metrics_by_project must not break the export.
    render_static_site(
        [_card("Ollama", Ring.PILOT)],
        tmp_path / "_site",
        datetime(2026, 6, 13, tzinfo=UTC),
    )

    assert (tmp_path / "_site" / "index.html").exists()
    assert (tmp_path / "_site" / "project_ollama.html").exists()


def test_static_index_renders_scan_health(tmp_path: Path):
    render_static_site(
        [_card("vLLM", Ring.ADOPT)],
        tmp_path / "_site",
        datetime(2026, 6, 13, tzinfo=UTC),
        latest_scan_meta={
            "created_at": "2026-06-13T10:00:00+00:00",
            "firehose_dropped_count": 7,
        },
    )

    index = (tmp_path / "_site" / "index.html").read_text(encoding="utf-8")
    assert "scan-health" in index
    assert "7 firehose" in index


def test_static_index_back_compat_without_scan_meta(tmp_path: Path):
    render_static_site(
        [_card("vLLM", Ring.ADOPT)],
        tmp_path / "_site",
        datetime(2026, 6, 13, tzinfo=UTC),
    )

    assert (tmp_path / "_site" / "index.html").exists()
