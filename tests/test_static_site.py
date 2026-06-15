"""Tests for the static-site export, focused on per-project pages."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from radar.models import Backer, BackerType, Category, DecisionCard, Ring
from radar.storage.metrics_store import ProjectMetrics
from radar.web.static_site import render_static_site


def _card(project: str, ring: Ring) -> DecisionCard:
    return DecisionCard(
        project=project, category=Category.MODEL_SERVING, ring=ring,
        summary=f"{project} summary", workflow_fit={}, risk_level="low",
    )


def test_static_index_and_project_page_render_backer(tmp_path: Path):
    card = _card("vLLM", Ring.ADOPT).model_copy(
        update={"backer": Backer(name="NVIDIA", type=BackerType.BIG_TECH)}
    )
    render_static_site([card], tmp_path / "_site", datetime(2026, 6, 13, tzinfo=UTC))

    index = (tmp_path / "_site" / "index.html").read_text(encoding="utf-8")
    assert "Backed by" in index
    assert "NVIDIA" in index
    assert 'class="backer backer-big_tech"' in index
    assert 'id="filter-backer"' in index
    assert 'data-backer-type="big_tech"' in index

    page = (tmp_path / "_site" / "project_vllm.html").read_text(encoding="utf-8")
    assert "Backed by" in page
    assert "NVIDIA" in page


def test_export_copies_history_log_and_offers_download(tmp_path: Path):
    history = tmp_path / "history.jsonl"
    history.write_text('{"event": "demo"}\n', encoding="utf-8")

    render_static_site(
        [_card("vLLM", Ring.ADOPT)],
        tmp_path / "_site",
        datetime(2026, 6, 13, tzinfo=UTC),
        history_jsonl=history,
    )

    copied = tmp_path / "_site" / "history.jsonl"
    assert copied.exists()
    assert copied.read_text(encoding="utf-8") == '{"event": "demo"}\n'
    index = (tmp_path / "_site" / "index.html").read_text(encoding="utf-8")
    assert 'href="history.jsonl"' in index
    assert "Download data" in index


def test_export_without_history_log_omits_download(tmp_path: Path):
    render_static_site(
        [_card("vLLM", Ring.ADOPT)],
        tmp_path / "_site",
        datetime(2026, 6, 13, tzinfo=UTC),
        # no history_jsonl
    )
    assert not (tmp_path / "_site" / "history.jsonl").exists()
    index = (tmp_path / "_site" / "index.html").read_text(encoding="utf-8")
    assert 'href="history.jsonl"' not in index
    # Change feeds are always available, so the download section still renders.
    assert 'href="changes.json"' in index


def test_static_index_carries_mega_brand(tmp_path: Path):
    # The Mega corporate identity must survive: Process Blue, the logo lockup,
    # and the tagline. Guards against an accidental de-brand.
    render_static_site(
        [_card("vLLM", Ring.ADOPT)],
        tmp_path / "_site",
        datetime(2026, 6, 13, tzinfo=UTC),
    )
    index = (tmp_path / "_site" / "index.html").read_text(encoding="utf-8")
    assert "#009FDA" in index  # Process Blue brand color
    assert 'class="brand-logo"' in index  # real mega logo lockup
    assert "static/brand/mega-logo-white.svg" in index  # vector logo asset (relative)
    assert "Mega Bilgisayar Tic. Ltd. Şti." in index  # footer attribution
    # The logo, favicon, and bundled font are copied into the published site.
    assert (tmp_path / "_site" / "static" / "brand" / "mega-logo-white.svg").exists()
    assert (tmp_path / "_site" / "static" / "brand" / "favicon.png").exists()
    assert (
        tmp_path / "_site" / "static" / "brand" / "fonts" / "hanken-grotesk-400.woff2"
    ).exists()


def test_static_index_renders_hero_stats_and_legend(tmp_path: Path):
    render_static_site(
        [_card("vLLM", Ring.ADOPT), _card("Ray", Ring.PILOT)],
        tmp_path / "_site",
        datetime(2026, 6, 13, tzinfo=UTC),
    )
    index = (tmp_path / "_site" / "index.html").read_text(encoding="utf-8")
    assert 'class="hero"' in index  # brand header
    assert 'class="stats"' in index  # ring distribution chips
    assert 'class="legend"' in index  # rings/backer legend
    assert 'class="footer"' in index
    assert 'class="ring-pill ring-adopt"' in index  # ring rendered as a pill


def test_static_index_renders_em_dash_for_uncurated_backer(tmp_path: Path):
    # _card() leaves backer unset; the cell must degrade to a dash, not crash.
    render_static_site(
        [_card("vLLM", Ring.ADOPT)],
        tmp_path / "_site",
        datetime(2026, 6, 13, tzinfo=UTC),
    )
    index = (tmp_path / "_site" / "index.html").read_text(encoding="utf-8")
    assert 'class="backer-none"' in index


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


def test_static_index_renders_filter_controls(tmp_path: Path):
    render_static_site(
        [_card("vLLM", Ring.ADOPT), _card("Aider", Ring.PILOT)],
        tmp_path / "_site",
        datetime(2026, 6, 13, tzinfo=UTC),
    )

    index = (tmp_path / "_site" / "index.html").read_text(encoding="utf-8")
    assert 'id="filter-category"' in index
    assert 'id="filter-text"' in index
    assert "radarFilter" in index


def test_static_filter_targets_all_tracked_only(tmp_path: Path):
    # "Try This Week" rows (adopt/pilot) must NOT carry data-category;
    # only the "All Tracked Projects" table is filtered.
    render_static_site(
        [_card("vLLM", Ring.ADOPT)],
        tmp_path / "_site",
        datetime(2026, 6, 13, tzinfo=UTC),
    )

    index = (tmp_path / "_site" / "index.html").read_text(encoding="utf-8")
    # exactly one data-project (the all-tracked row), not two.
    assert index.count('data-project="vLLM"') == 1
    assert 'id="radar-table"' in index
