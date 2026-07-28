"""Tests for the static-site export, focused on per-project pages."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from radar.models import (
    Backer,
    BackerType,
    Category,
    DecisionCard,
    OnPremAssessment,
    Ring,
    ScoreBreakdown,
)
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


def test_static_index_shows_card_staleness_note(tmp_path: Path):
    render_static_site(
        [_card("vLLM", Ring.ADOPT)],
        tmp_path / "_site",
        datetime(2026, 6, 13, tzinfo=UTC),
        latest_scan_meta={"updated_at": "2026-06-13T00:00:00+00:00"},
        card_staleness="1 of 2 cards predate the latest scan (oldest 2026-06-11, newest 2026-06-13)",
    )

    index = (tmp_path / "_site" / "index.html").read_text(encoding="utf-8")
    assert "predate the latest scan" in index


def test_static_index_omits_card_staleness_when_none(tmp_path: Path):
    render_static_site(
        [_card("vLLM", Ring.ADOPT)],
        tmp_path / "_site",
        datetime(2026, 6, 13, tzinfo=UTC),
        latest_scan_meta={"updated_at": "2026-06-13T00:00:00+00:00"},
    )

    index = (tmp_path / "_site" / "index.html").read_text(encoding="utf-8")
    assert "predate the latest scan" not in index


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
    assert 'class="positioning"' in index
    assert (
        "Trending tells you what&#39;s hot. The radar tells you what to adopt "
        "— and what it takes to run it."
    ) in index


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


def test_static_project_page_shows_star_sparkline(tmp_path: Path):
    cards = [_card("vLLM", Ring.ADOPT)]
    metrics_by_project = {
        "vLLM": [
            ProjectMetrics(project="vLLM", run_id=f"run-{d}",
                           observed_at=datetime(2026, 6, d, tzinfo=UTC), stars=100 * d)
            for d in (1, 2, 3)
        ]
    }

    render_static_site(
        cards, tmp_path / "_site", datetime(2026, 6, 13, tzinfo=UTC),
        metrics_by_project=metrics_by_project,
    )

    page = (tmp_path / "_site" / "project_vllm.html").read_text(encoding="utf-8")
    assert 'class="spark"' in page
    assert "stars, last 3 scans" in page


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


def test_static_index_renders_stale_source_health(tmp_path: Path):
    from radar.web.source_health import SourceHealth, StaleFeed

    health = SourceHealth(
        total_sources=3,
        stale=[StaleFeed(source_id="rss-ollama-blog", project="Ollama Blog")],
    )
    render_static_site(
        [_card("vLLM", Ring.ADOPT)],
        tmp_path / "_site",
        datetime(2026, 6, 13, tzinfo=UTC),
        source_health=health,
    )

    index = (tmp_path / "_site" / "index.html").read_text(encoding="utf-8")
    assert "rss-ollama-blog" in index
    assert "1 stale feed of 3" in index


def test_static_index_back_compat_without_source_health(tmp_path: Path):
    # Omitting source_health must still render (the partial is guarded).
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


def test_static_site_renders_models_section(tmp_path):
    from datetime import UTC, datetime

    from radar.models import Ring
    from radar.models_radar.entities import (
        HardwareTier,
        ModelEntry,
        Openness,
        Platform,
        QuantVariant,
    )
    from radar.web.static_site import render_static_site
    e = ModelEntry(id="qwen3-8b", name="Qwen3 8B", family="Qwen3", ring=Ring.ADOPT,
                   hardware_tier=HardwareTier.LAPTOP, openness=Openness.OPEN_PERMISSIVE,
                   quants=[QuantVariant(format="Q4_K_M", bits_per_weight=4.5,
                                        est_memory_gb_4k=8.0, platform=Platform.GENERIC, source="x")])
    render_static_site([], tmp_path / "_site", datetime(2026, 6, 22, tzinfo=UTC),
                       model_entries=[e])
    site = tmp_path / "_site"
    assert (site / "models.html").exists()
    assert "qwen3-8b" in (site / "models.html").read_text(encoding="utf-8")
    assert (site / "model_qwen3-8b.html").exists()


def test_static_site_models_backcompat_without_models(tmp_path):
    from datetime import UTC, datetime

    from radar.web.static_site import render_static_site
    render_static_site([], tmp_path / "_site", datetime(2026, 6, 22, tzinfo=UTC))
    assert (tmp_path / "_site" / "index.html").exists()  # no crash, no models


def test_model_page_has_runs_on_table(tmp_path):
    from datetime import UTC, datetime

    from radar.models import Ring
    from radar.models_radar.entities import (
        HardwareTier,
        ModelEntry,
        Openness,
        Platform,
        QuantVariant,
    )
    from radar.web.static_site import render_static_site

    m = ModelEntry(id="qwen3-8b", name="Qwen3 8B", family="Qwen3", params_total=8_000_000_000,
                   ring=Ring.ADOPT, hardware_tier=HardwareTier.LAPTOP, openness=Openness.OPEN_PERMISSIVE,
                   quants=[QuantVariant(format="Q4_K_M", bits_per_weight=4.5, est_memory_gb_4k=8.4,
                                        platform=Platform.GENERIC, source="x")])
    render_static_site([], tmp_path / "_site", datetime(2026, 6, 22, tzinfo=UTC), model_entries=[m])
    page = (tmp_path / "_site" / "model_qwen3-8b.html").read_text(encoding="utf-8")
    assert "Runs on" in page
    assert "RTX 4090 (24GB)" in page  # one of the COMMON_DEVICE_TIERS


def test_static_model_page_shows_download_sparkline(tmp_path):
    from datetime import UTC, datetime

    from radar.models import Ring
    from radar.models_radar.entities import HardwareTier, ModelEntry, Openness
    from radar.storage.model_metrics_store import ModelMetrics
    from radar.web.static_site import render_static_site

    m = ModelEntry(id="qwen3-8b", name="Qwen3 8B", family="Qwen3", ring=Ring.ADOPT,
                   hardware_tier=HardwareTier.LAPTOP, openness=Openness.OPEN_PERMISSIVE,
                   quants=[])
    model_metrics_by_id = {
        "qwen3-8b": [
            ModelMetrics(model_id="qwen3-8b", run_id=f"run-{d}",
                        observed_at=datetime(2026, 6, d, tzinfo=UTC), downloads=1000 * d)
            for d in (1, 2, 3)
        ]
    }
    render_static_site([], tmp_path / "_site", datetime(2026, 6, 22, tzinfo=UTC),
                       model_entries=[m], model_metrics_by_id=model_metrics_by_id)
    page = (tmp_path / "_site" / "model_qwen3-8b.html").read_text(encoding="utf-8")
    assert 'class="spark"' in page
    assert "downloads, last 3 scans" in page


def test_static_model_page_download_sparkline_backcompat(tmp_path):
    """Omitting model_metrics_by_id must not break the export (house pattern)."""
    from datetime import UTC, datetime

    from radar.models import Ring
    from radar.models_radar.entities import HardwareTier, ModelEntry, Openness
    from radar.web.static_site import render_static_site

    m = ModelEntry(id="qwen3-8b", name="Qwen3 8B", family="Qwen3", ring=Ring.ADOPT,
                   hardware_tier=HardwareTier.LAPTOP, openness=Openness.OPEN_PERMISSIVE,
                   quants=[])
    render_static_site([], tmp_path / "_site", datetime(2026, 6, 22, tzinfo=UTC),
                       model_entries=[m])  # no model_metrics_by_id
    page = (tmp_path / "_site" / "model_qwen3-8b.html").read_text(encoding="utf-8")
    assert 'class="spark"' not in page


def test_static_model_page_renders_architecture_benchmarks_and_unverified_marker(tmp_path):
    """Task 8 parity: the static export renders the same _model_detail.html
    partial as the live app, so architecture/benchmarks/unverified must show
    here too (see test_web.py's live-route sibling for the same contract)."""
    from datetime import UTC, datetime

    from radar.models import Ring
    from radar.models_radar.entities import (
        ArchitectureSpec,
        AttentionKind,
        BenchmarkScore,
        HardwareTier,
        ModelEntry,
        Openness,
    )
    from radar.web.static_site import render_static_site

    m = ModelEntry(
        id="deepseek-v3-arch", name="DeepSeek V3", family="DeepSeek",
        params_total=671_000_000_000,
        ring=Ring.ADOPT, hardware_tier=HardwareTier.DATACENTER, openness=Openness.OPEN_PERMISSIVE,
        architecture=ArchitectureSpec(
            attention_kind=AttentionKind.MLA, kv_lora_rank=512,
            num_experts=256, experts_per_token=8,
        ),
        benchmarks=[BenchmarkScore(name="MMLU-Pro", score=0.81,
                                   source_url="https://example.com/card")],
        provenance={},
    )
    render_static_site([], tmp_path / "_site", datetime(2026, 6, 22, tzinfo=UTC), model_entries=[m])
    page = (tmp_path / "_site" / "model_deepseek-v3-arch.html").read_text(encoding="utf-8")
    assert "mla" in page.lower()
    assert "256 experts, 8 active" in page
    assert "MMLU-Pro" in page
    assert "unverified" in page


def test_fit_by_tier_returns_verdicts():
    from radar.models_radar.entities import ModelEntry, Platform, QuantVariant
    from radar.web.picker_context import fit_by_tier

    m = ModelEntry(id="x", name="x", family="F", params_total=8_000_000_000,
                   quants=[QuantVariant(format="Q4_K_M", bits_per_weight=4.5, est_memory_gb_4k=8.4,
                                        platform=Platform.GENERIC, source="x")])
    rows = fit_by_tier(m)
    assert rows and {"device", "verdict", "best_quant"} <= set(rows[0])
    assert any(r["verdict"] == "fits" for r in rows)


def test_fit_by_tier_no_quants_returns_unknown():
    from radar.models_radar.devices import COMMON_DEVICE_TIERS
    from radar.models_radar.entities import ModelEntry
    from radar.web.picker_context import fit_by_tier

    m = ModelEntry(id="no-quants", name="no-quants", family="F")  # no quants, no params_total
    rows = fit_by_tier(m)
    assert len(rows) == len(COMMON_DEVICE_TIERS)
    assert all(r["verdict"] == "unknown" for r in rows)
    assert all(r["best_quant"] == "-" for r in rows)


def test_models_page_is_styled_and_filterable(tmp_path):
    from datetime import UTC, datetime

    from radar.models import Ring
    from radar.models_radar.entities import (
        HardwareTier,
        ModelEntry,
        Openness,
        Platform,
        QuantVariant,
    )
    from radar.web.static_site import render_static_site

    e = ModelEntry(
        id="qwen3-8b", name="Qwen3 8B", family="Qwen3", ring=Ring.ADOPT,
        params_total=8_000_000_000, context_length=40960,
        hardware_tier=HardwareTier.LAPTOP, openness=Openness.OPEN_PERMISSIVE,
        quants=[QuantVariant(format="Q4_K_M", bits_per_weight=4.5,
                              est_memory_gb_4k=8.0, platform=Platform.GENERIC, source="x")],
    )
    render_static_site([], tmp_path / "_site", datetime(2026, 6, 22, tzinfo=UTC), model_entries=[e])
    html = (tmp_path / "_site" / "models.html").read_text(encoding="utf-8")
    # Shell is included (not literal tag name)
    assert "_base_styles" not in html
    # Filter bar and table
    assert "mfilter-family" in html
    assert "models-table" in html
    # Ring pill present
    assert "ring-pill" in html
    # Richer metadata columns
    assert "Use case" in html
    assert "Context" in html
    # Sortable headers + numeric sort data + sort script
    assert 'data-key="params" data-type="num"' in html
    assert "onclick=\"modelsSort(this)\"" in html
    assert "function modelsSort" in html
    assert 'data-params="8000000000"' in html and 'data-context=' in html
    # "Models" nav link in the dashboard
    index_html = (tmp_path / "_site" / "index.html").read_text(encoding="utf-8")
    assert 'href="models.html"' in index_html


def _technique_entry():
    from radar.models import Category, Ring
    from radar.research_radar.entities import (
        OnPremImpact,
        PaperLink,
        TechniqueDomain,
        TechniqueEntry,
    )

    return TechniqueEntry(
        id="speculative-decoding", name="Speculative Decoding",
        category=Category.MODEL_SERVING, domain=TechniqueDomain.INFERENCE,
        onprem_impact=OnPremImpact.REDUCES_LATENCY, ring=Ring.ADOPT, score=4.3,
        citation_count=1697,
        papers=[PaperLink(arxiv_id="2211.17192", title="Fast Inference", published="2022-11")],
    )


def _technique_event():
    from datetime import UTC, datetime

    from radar.models import Ring
    from radar.research_radar.entities import TechniqueDomain
    from radar.research_radar.history import TechniqueHistoryEvent
    from radar.storage.history_store import ChangeType

    return TechniqueHistoryEvent(
        technique_id="speculative-decoding", domain=TechniqueDomain.INFERENCE,
        change_type=ChangeType.NEW, ring=Ring.ADOPT, run_id="run-1",
        observed_at=datetime(2026, 7, 3, 10, 0, tzinfo=UTC),
    )


def test_static_site_renders_research_section(tmp_path):
    render_static_site(
        [], tmp_path / "_site", datetime(2026, 7, 3, tzinfo=UTC),
        technique_entries=[_technique_entry()], technique_events=[_technique_event()],
    )
    site = tmp_path / "_site"

    techniques_html = (site / "techniques.html").read_text(encoding="utf-8")
    assert "Speculative Decoding" in techniques_html
    assert 'href="technique_speculative-decoding.html"' in techniques_html
    detail_html = (site / "technique_speculative-decoding.html").read_text(encoding="utf-8")
    assert "2211.17192" in detail_html
    assert "canonical paper" in detail_html  # timeline rendered
    assert 'href="techniques.html"' in detail_html  # static back-link
    assert (site / "changes-research.xml").exists()
    assert "urn:radar-technique:speculative-decoding" in (
        site / "changes-research.json").read_text(encoding="utf-8")
    index_html = (site / "index.html").read_text(encoding="utf-8")
    assert "Research: 1 techniques" in index_html
    assert 'href="techniques.html"' in index_html


def test_static_technique_page_shows_momentum_note(tmp_path):
    entry = _technique_entry().model_copy(update={
        "momentum_direction": "rising",
        "momentum_note": "Citations +12.3% since last comparable scan.",
    })

    render_static_site(
        [], tmp_path / "_site", datetime(2026, 7, 3, tzinfo=UTC),
        technique_entries=[entry],
    )

    detail_html = (tmp_path / "_site" / "technique_speculative-decoding.html").read_text(
        encoding="utf-8")
    assert "Momentum: rising" in detail_html
    assert "Citations +12.3%" in detail_html


def test_static_technique_page_without_momentum_still_renders(tmp_path):
    """Back-compat: an entry with no momentum fields (old technique_cards.json) still renders."""
    render_static_site(
        [], tmp_path / "_site", datetime(2026, 7, 3, tzinfo=UTC),
        technique_entries=[_technique_entry()],
    )

    detail_html = (tmp_path / "_site" / "technique_speculative-decoding.html").read_text(
        encoding="utf-8")
    assert "Momentum:" not in detail_html


def test_static_site_backcompat_without_techniques(tmp_path):
    render_static_site([], tmp_path / "_site", datetime(2026, 7, 3, tzinfo=UTC))
    site = tmp_path / "_site"

    assert not (site / "techniques.html").exists()
    assert not (site / "changes-research.xml").exists()
    assert (site / "index.html").exists()


def test_static_project_page_shows_pedigree_with_static_links(tmp_path):
    from radar.models import Ring
    from radar.research_radar.pedigree import TechniquePedigree

    card = _card("vLLM", Ring.ADOPT)
    pedigree_by_project = {"vLLM": [TechniquePedigree(
        technique_id="spec-dec", name="Speculative Decoding",
        ring=Ring.ADOPT, citation_count=1697,
    )]}

    render_static_site(
        [card], tmp_path / "_site", datetime(2026, 7, 5, tzinfo=UTC),
        pedigree_by_project=pedigree_by_project,
        technique_hrefs={"spec-dec": "technique_spec-dec.html"},
    )

    page = (tmp_path / "_site" / "project_vllm.html").read_text(encoding="utf-8")
    assert "Research techniques" in page
    assert 'href="technique_spec-dec.html"' in page
    assert "1697 citations" in page


def test_static_model_page_shows_pedigree(tmp_path):
    from radar.models import Ring
    from radar.models_radar.entities import ModelEntry
    from radar.research_radar.pedigree import TechniquePedigree

    entry = ModelEntry(id="qwen3-8b", name="Qwen3 8B", family="Qwen3")
    render_static_site(
        [], tmp_path / "_site", datetime(2026, 7, 5, tzinfo=UTC),
        model_entries=[entry],
        pedigree_by_model={entry.id: [TechniquePedigree(
            technique_id="spec-dec", name="Speculative Decoding",
            ring=Ring.ADOPT, citation_count=1697,
        )]},
        technique_hrefs={"spec-dec": "technique_spec-dec.html"},
    )

    page_name = next(p.name for p in (tmp_path / "_site").iterdir()
                     if p.name.startswith("model_"))
    page = (tmp_path / "_site" / page_name).read_text(encoding="utf-8")
    assert "Research techniques" in page
    assert 'href="technique_spec-dec.html"' in page


def test_static_technique_page_links_impls_only_when_targets_exist(tmp_path):
    from radar.research_radar.entities import ImplKind, ResolvedImplementation

    entry = _technique_entry()
    entry = entry.model_copy(update={"resolved_implementations": [
        ResolvedImplementation(kind=ImplKind.TOOL, ref="github-vllm", ring=None),
    ]})

    render_static_site(
        [], tmp_path / "_site", datetime(2026, 7, 5, tzinfo=UTC),
        technique_entries=[entry],
        impl_hrefs={"github-vllm": "project_vllm.html"},
    )

    page = (tmp_path / "_site" / "technique_speculative-decoding.html").read_text(
        encoding="utf-8")
    assert 'href="project_vllm.html"' in page


def _trending_obs():
    from datetime import UTC, datetime

    from radar.discovery.trending_entities import Lane, TrendingObservation

    return [
        TrendingObservation(
            repo="acme/rocket", lane=Lane.ONPREM, stars=stars,
            observed_at=datetime(2026, 7, day, 7, 0, tzinfo=UTC),
            repo_created_at=datetime(2026, 6, 1, tzinfo=UTC),
            description="fast serving", topics=["llm"], license="MIT")
        for day, stars in ((1, 100), (4, 400))
    ]


def test_static_site_renders_trending_page(tmp_path):
    render_static_site(
        [], tmp_path / "_site", datetime(2026, 7, 8, tzinfo=UTC),
        trending_observations=_trending_obs(),
    )
    site = tmp_path / "_site"

    page = (site / "trending.html").read_text(encoding="utf-8")
    assert "acme/rocket" in page
    assert 'href="https://github.com/acme/rocket"' in page
    assert "On-prem radar candidates" in page
    index = (site / "index.html").read_text(encoding="utf-8")
    assert 'href="trending.html"' in index
    assert "Trending:" in index


def test_static_trending_page_shows_sparklines(tmp_path):
    from radar.discovery.trending_entities import Lane, TrendingObservation

    # third observation so acme/rocket clears the 3-point floor
    obs = [*_trending_obs(), TrendingObservation(
        repo="acme/rocket", lane=Lane.ONPREM, stars=500,
        observed_at=datetime(2026, 7, 5, 7, 0, tzinfo=UTC),
        repo_created_at=datetime(2026, 6, 1, tzinfo=UTC),
        description="fast serving", topics=["llm"], license="MIT",
    )]
    render_static_site(
        [], tmp_path / "_site", datetime(2026, 7, 8, tzinfo=UTC),
        trending_observations=obs,
    )

    page = (tmp_path / "_site" / "trending.html").read_text(encoding="utf-8")
    assert 'class="spark"' in page


def test_static_trending_writes_three_window_variants(tmp_path):
    render_static_site(
        [], tmp_path / "_site", datetime(2026, 7, 28, tzinfo=UTC),
        trending_observations=_trending_obs(),
    )
    site = tmp_path / "_site"

    assert (site / "trending.html").exists()
    assert (site / "trending-30d.html").exists()
    assert (site / "trending-90d.html").exists()


def test_static_trending_variants_show_active_tab_and_cross_link(tmp_path):
    render_static_site(
        [], tmp_path / "_site", datetime(2026, 7, 28, tzinfo=UTC),
        trending_observations=_trending_obs(),
    )
    site = tmp_path / "_site"

    default_page = (site / "trending.html").read_text(encoding="utf-8")
    assert 'tab-active">7d' in default_page
    assert 'href="trending-30d.html"' in default_page
    assert 'href="trending-90d.html"' in default_page

    page_30d = (site / "trending-30d.html").read_text(encoding="utf-8")
    assert 'tab-active">30d' in page_30d
    assert 'href="trending.html"' in page_30d   # links back to the 7d (default-named) page

    page_90d = (site / "trending-90d.html").read_text(encoding="utf-8")
    assert 'tab-active">90d' in page_90d


def test_static_trending_window_changes_velocity_value(tmp_path):
    from radar.discovery.trending_entities import Lane, TrendingObservation

    obs = [
        TrendingObservation(
            repo="win/test", lane=Lane.ONPREM, stars=stars,
            observed_at=datetime(2026, 7, day, 7, 0, tzinfo=UTC),
            repo_created_at=datetime(2026, 1, 1, tzinfo=UTC),
            description="d", topics=["llm"], license="MIT")
        for day, stars in ((8, 100), (27, 400))  # +300 over 19 days = 15.8/day
    ]
    render_static_site(
        [], tmp_path / "_site", datetime(2026, 7, 28, tzinfo=UTC),
        trending_observations=obs,
    )
    site = tmp_path / "_site"

    page_7d = (site / "trending.html").read_text(encoding="utf-8")
    page_30d = (site / "trending-30d.html").read_text(encoding="utf-8")

    assert "15.8" not in page_7d   # only the day-27 row is within the default 7d window
    assert "15.8" in page_30d      # both rows qualify for 30d -> a real velocity


def test_static_site_backcompat_without_trending(tmp_path):
    render_static_site([], tmp_path / "_site", datetime(2026, 7, 8, tzinfo=UTC))

    assert not (tmp_path / "_site" / "trending.html").exists()
    assert (tmp_path / "_site" / "index.html").exists()


def test_export_survives_naive_datetime_observation(tmp_path):
    from radar.discovery.trending_entities import Lane, TrendingObservation

    naive = TrendingObservation(
        repo="acme/rocket", lane=Lane.ONPREM, stars=400,
        observed_at=datetime(2026, 7, 4, 7, 0),        # tz-naive → would crash build_trending
        repo_created_at=datetime(2026, 6, 1, 7, 0),
        description="d", topics=["llm"], license="MIT",
    )
    # must not raise; index still renders, trending page simply omitted
    render_static_site([], tmp_path / "_site", datetime(2026, 7, 8, tzinfo=UTC),
                       trending_observations=[naive])

    assert (tmp_path / "_site" / "index.html").exists()
    assert not (tmp_path / "_site" / "trending.html").exists()


def test_static_site_copies_digests_and_links_latest(tmp_path):
    from radar.storage.digest_log import DigestLogEntry

    digests = tmp_path / "digests"
    (digests / "cards").mkdir(parents=True)
    (digests / "digest_2026-W28.html").write_text("<h1>W28</h1>", encoding="utf-8")
    latest = DigestLogEntry(label="2026-W28", generated_at=datetime(2026, 7, 8, tzinfo=UTC),
                            url="digests/digest_2026-W28.html", summary="Week 28")

    render_static_site([], tmp_path / "_site", datetime(2026, 7, 8, tzinfo=UTC),
                       digest_dir=digests, latest_digest=latest)
    site = tmp_path / "_site"

    assert (site / "digests" / "digest_2026-W28.html").exists()
    assert 'href="digests/digest_2026-W28.html"' in (site / "index.html").read_text("utf-8")


def test_static_site_without_digests_is_backcompat(tmp_path):
    render_static_site([], tmp_path / "_site", datetime(2026, 7, 8, tzinfo=UTC))
    assert not (tmp_path / "_site" / "digests").exists()
    assert (tmp_path / "_site" / "index.html").exists()


def test_static_site_survives_bad_digest_dir(tmp_path):
    # digests exists but as a FILE, not a dir — copytree would raise
    bad = tmp_path / "digests_file"
    bad.write_text("not a dir", encoding="utf-8")

    render_static_site([], tmp_path / "_site", datetime(2026, 7, 8, tzinfo=UTC),
                       digest_dir=bad)   # must not raise; index still renders

    assert (tmp_path / "_site" / "index.html").exists()


def test_static_site_renders_hub_sections(tmp_path):
    from radar.web.hub_sections import HubRow

    model_hub = [HubRow(id="m1", name="M One", subtitle="Fam", metric=5000, growth=120.0,
                        momentum=None, direction="rising", ring="pilot", is_new=False,
                        kind="model")]
    technique_hub = [HubRow(id="t1", name="T One", subtitle="reasoning", metric=900,
                            growth=None, momentum=5, direction="rising", ring="adopt",
                            is_new=True, kind="technique")]

    render_static_site([], tmp_path / "_site", datetime(2026, 7, 8, tzinfo=UTC),
                       model_hub=model_hub, technique_hub=technique_hub,
                       top_model=model_hub[0], top_technique=technique_hub[0])
    trending = (tmp_path / "_site" / "trending.html").read_text(encoding="utf-8")

    assert "Trending Models" in trending and "M One" in trending
    assert "Trending Techniques" in trending and "T One" in trending
    index = (tmp_path / "_site" / "index.html").read_text(encoding="utf-8")
    assert "M One" in index or "T One" in index   # strip shows a top hub item


def test_static_site_hub_backcompat(tmp_path):
    render_static_site([], tmp_path / "_site", datetime(2026, 7, 8, tzinfo=UTC))
    assert (tmp_path / "_site" / "index.html").exists()   # no hub data → still renders


def test_static_site_renders_emerging(tmp_path):
    from radar.discovery.model_candidate_detect import ModelCandidateEntry

    cands = [ModelCandidateEntry(hf_repo="acme/emerging", name="emerging", family="acme",
                                 downloads=4000, downloads_per_day=1000.0, is_new=True,
                                 first_seen="2026-07-01", last_seen="2026-07-01", is_stale=False)]
    render_static_site([], tmp_path / "_site", datetime(2026, 7, 8, tzinfo=UTC),
                       model_candidates=cands)
    page = (tmp_path / "_site" / "trending.html").read_text(encoding="utf-8")

    assert "Emerging" in page and "acme/emerging" in page
    assert 'href="https://huggingface.co/acme/emerging"' in page


def test_static_site_emerging_backcompat(tmp_path):
    render_static_site([], tmp_path / "_site", datetime(2026, 7, 8, tzinfo=UTC))
    assert (tmp_path / "_site" / "index.html").exists()   # no candidates → still renders


def test_static_site_renders_emerging_papers(tmp_path):
    from radar.discovery.technique_candidate_detect import TechniqueCandidateEntry

    cands = [TechniqueCandidateEntry(arxiv_id="2501.9999", name="Hot Paper", upvotes=130,
                                     upvotes_per_day=40.0, citation_count=3, is_new=True,
                                     first_seen="2026-07-01", last_seen="2026-07-01", is_stale=False)]
    render_static_site([], tmp_path / "_site", datetime(2026, 7, 8, tzinfo=UTC),
                       technique_candidates=cands)
    page = (tmp_path / "_site" / "trending.html").read_text(encoding="utf-8")

    assert "Hot Paper" in page
    assert 'href="https://arxiv.org/abs/2501.9999"' in page


def test_static_site_emerging_papers_backcompat(tmp_path):
    render_static_site([], tmp_path / "_site", datetime(2026, 7, 8, tzinfo=UTC))
    assert (tmp_path / "_site" / "index.html").exists()   # no candidates → still renders


def test_static_site_marks_stale_and_shows_last_seen(tmp_path):
    from radar.discovery.model_candidate_detect import ModelCandidateEntry

    cands = [ModelCandidateEntry(hf_repo="acme/old", name="old", family="acme", downloads=2000,
                                 downloads_per_day=None, is_new=False, first_seen="2026-06-01",
                                 last_seen="2026-06-02", is_stale=True)]
    render_static_site([], tmp_path / "_site", datetime(2026, 7, 8, tzinfo=UTC),
                       model_candidates=cands)
    page = (tmp_path / "_site" / "trending.html").read_text(encoding="utf-8")
    assert "Last seen" in page and "2026-06-02" in page and "STALE" in page


def test_static_site_technique_stale_wins_over_new(tmp_path):
    from radar.discovery.technique_candidate_detect import TechniqueCandidateEntry

    cands = [TechniqueCandidateEntry(arxiv_id="2501.stale", name="Quiet Paper", upvotes=9,
                                     upvotes_per_day=None, citation_count=1, is_new=True,
                                     first_seen="2026-06-20", last_seen="2026-06-25",
                                     is_stale=True)]
    render_static_site([], tmp_path / "_site", datetime(2026, 7, 8, tzinfo=UTC),
                       technique_candidates=cands)
    page = (tmp_path / "_site" / "trending.html").read_text(encoding="utf-8")
    assert "STALE" in page and "2026-06-25" in page and "Quiet Paper" in page
    assert "NEW" not in page.split("Quiet Paper")[1].split("</tr>")[0]


def test_static_tables_are_scroll_wrapped(tmp_path):
    from radar.models_radar.entities import ModelEntry

    render_static_site([], tmp_path / "_site", datetime(2026, 7, 8, tzinfo=UTC),
                       model_entries=[ModelEntry(id="x", name="x", family="F")])
    for page in (tmp_path / "_site").glob("*.html"):
        text = page.read_text(encoding="utf-8")
        if "<table" in text:
            assert '<div class="table-wrap">' in text, page.name

    models_page = (tmp_path / "_site" / "models.html").read_text(encoding="utf-8")
    assert 'class="num"' in models_page
    assert "Min mem (GB)" in models_page


# ---------------------------------------------------------------------------
# Signal badges: ring pills, humanized fit verdicts, trend/risk, Status
# headers (Task 3) — static-export twins of the live-route assertions.
# ---------------------------------------------------------------------------


def test_static_techniques_catalog_renders_ring_pill(tmp_path):
    render_static_site(
        [], tmp_path / "_site", datetime(2026, 7, 3, tzinfo=UTC),
        technique_entries=[_technique_entry()],
    )
    page = (tmp_path / "_site" / "techniques.html").read_text(encoding="utf-8")
    assert 'class="ring-pill ring-' in page


def test_static_model_fit_verdict_humanized(tmp_path):
    from radar.models_radar.entities import (
        HardwareTier,
        ModelEntry,
        Openness,
        Platform,
        QuantVariant,
    )

    m = ModelEntry(
        id="qwen3-8b", name="Qwen3 8B", family="Qwen3", params_total=8_000_000_000,
        hardware_tier=HardwareTier.LAPTOP, openness=Openness.OPEN_PERMISSIVE,
        quants=[QuantVariant(format="Q4_K_M", bits_per_weight=4.5, est_memory_gb_4k=8.4,
                             platform=Platform.GENERIC, source="x")],
    )
    render_static_site([], tmp_path / "_site", datetime(2026, 6, 22, tzinfo=UTC), model_entries=[m])
    page = (tmp_path / "_site" / "model_qwen3-8b.html").read_text(encoding="utf-8")
    assert "wont_fit" not in page and "fits_tight" not in page
    assert "Won't fit" in page or "Fits" in page


def test_static_index_trend_and_risk_badges(tmp_path: Path):
    card = _card("vLLM", Ring.ADOPT).model_copy(update={"risk_level": "high", "trend": "rising"})
    render_static_site([card], tmp_path / "_site", datetime(2026, 6, 13, tzinfo=UTC))
    index = (tmp_path / "_site" / "index.html").read_text(encoding="utf-8")
    assert 'class="trend-' in index
    assert "risk-" in index


def test_static_index_legend_has_risk_column(tmp_path: Path):
    render_static_site([_card("vLLM", Ring.ADOPT)], tmp_path / "_site", datetime(2026, 6, 13, tzinfo=UTC))
    index = (tmp_path / "_site" / "index.html").read_text(encoding="utf-8")
    assert "<h4>Risk</h4>" in index
    assert 'class="ring-pill risk-low"' in index
    assert 'class="ring-pill risk-medium"' in index
    assert 'class="ring-pill risk-high"' in index


def test_static_trending_status_headers(tmp_path):
    from radar.discovery.trending_entities import Lane, TrendingObservation
    from radar.web.hub_sections import HubRow

    obs = [
        TrendingObservation(
            repo="acme/rocket", lane=Lane.ONPREM, stars=400,
            observed_at=datetime(2026, 7, 4, tzinfo=UTC),
            repo_created_at=datetime(2026, 6, 1, tzinfo=UTC),
            description="fast serving", topics=["llm"], license="MIT"),
        TrendingObservation(
            repo="big/model", lane=Lane.BROADER, stars=90000,
            observed_at=datetime(2026, 7, 4, tzinfo=UTC),
            repo_created_at=datetime(2024, 1, 1, tzinfo=UTC),
            description="a model", topics=["llm"], license="Apache-2.0"),
    ]
    model_hub = [HubRow(id="m1", name="M One", subtitle="Fam", metric=5000, growth=120.0,
                        momentum=None, direction="rising", ring="pilot", is_new=False, kind="model")]
    technique_hub = [HubRow(id="t1", name="T One", subtitle="reasoning", metric=900,
                            growth=None, momentum=5, direction="rising", ring="adopt",
                            is_new=True, kind="technique")]

    render_static_site(
        [], tmp_path / "_site", datetime(2026, 7, 8, tzinfo=UTC),
        trending_observations=obs, model_hub=model_hub, technique_hub=technique_hub,
    )
    page = (tmp_path / "_site" / "trending.html").read_text(encoding="utf-8")
    assert page.count("<th>Status</th>") >= 4
    assert "<th></th>" not in page


STATIC_NAV = [
    "Radar", "Models", "Research", "Trending", "Compare", "History", "Changes feed",
]


def test_static_nav_identical_across_pages(tmp_path: Path):
    """Every hero-bearing static page renders the same 7-item nav (finding #6)."""
    from radar.models_radar.entities import ModelEntry

    render_static_site(
        [_card("vLLM", Ring.ADOPT)], tmp_path / "_site", datetime(2026, 7, 8, tzinfo=UTC),
        model_entries=[ModelEntry(id="qwen3-8b", name="Qwen3 8B", family="Qwen3")],
        technique_entries=[_technique_entry()],
        trending_observations=_trending_obs(),
    )
    site = tmp_path / "_site"
    for name in ("models.html", "techniques.html", "trending.html", "history.html", "compare.html"):
        html = (site / name).read_text(encoding="utf-8")
        for label in STATIC_NAV:
            assert f">{label}</a>" in html, f"{label} missing from {name}"


def test_static_compare_uses_design_system(tmp_path: Path):
    """static_compare.html adopts the shared hero/table/footer system (finding #8b)."""
    cards = [
        _card("Cline", Ring.PILOT),
        _card("Aider", Ring.ADOPT),
    ]
    render_static_site(cards, tmp_path / "_site", datetime(2026, 7, 8, tzinfo=UTC))
    page = (tmp_path / "_site" / "compare.html").read_text(encoding="utf-8")

    assert 'class="hero"' in page            # shared hero present
    assert "--hero-bg" in page               # shared stylesheet inlined
    assert "#f9fafb" not in page             # bespoke light-only style gone
    assert '<div class="table-wrap">' in page
    assert "Cline" in page and "Aider" in page


def test_static_legend_on_catalog_pages(tmp_path: Path):
    """Static models/research catalogs explain rings/backers/risk (finding #8)."""
    from radar.models_radar.entities import ModelEntry

    render_static_site(
        [], tmp_path / "_site", datetime(2026, 7, 8, tzinfo=UTC),
        model_entries=[ModelEntry(id="qwen3-8b", name="Qwen3 8B", family="Qwen3")],
        technique_entries=[_technique_entry()],
    )
    site = tmp_path / "_site"
    assert "Rings" in (site / "models.html").read_text(encoding="utf-8")
    assert "Rings" in (site / "techniques.html").read_text(encoding="utf-8")


def test_export_emits_no_empty_table_wrap(tmp_path):
    """Guards the table-wrap/heading fix in trending, _project_detail,
    _model_detail, and _technique_detail: no `<div class="table-wrap">` may
    ever render empty, under BOTH the guard-true and guard-false path of
    each affected block.

    Must actually render the affected pages — a call with no cards/models/
    trending data would pass on the pre-fix buggy templates too, since none
    of them would even be written.

    A second render below (empty hub/candidate sections, trending_entries
    only) drives trending.html's "Trending Models/Techniques" and "Emerging
    — not yet tracked" blocks down their guard-false path specifically — the
    exact combination a prior version of this test skipped by always
    supplying non-empty hub/candidate data alongside the trending entries.
    """
    from radar.discovery.model_candidate_detect import ModelCandidateEntry
    from radar.discovery.technique_candidate_detect import TechniqueCandidateEntry
    from radar.models_radar.entities import ModelEntry, Platform, QuantVariant
    from radar.web.hub_sections import HubRow

    # (a) _project_detail's "Score breakdown" / "On-prem rubric" blocks:
    # one card with neither (guard-false — must emit no empty wrap) and one
    # with both (guard-true — must render real rows).
    plain_card = _card("vLLM", Ring.ADOPT)
    scored_card = _card("Ray", Ring.PILOT).model_copy(update={
        "score_breakdown": ScoreBreakdown(
            workflow_impact=4, laptop_runnability=3, open_source_maturity=5,
            on_prem_relevance=4, security_posture=3, demo_value=4, setup_friction=2,
        ),
        "on_prem_rubric": {"data_locality": OnPremAssessment(score=5, reason="fully local")},
    })

    # (b) _model_detail's "Runs on" (fit_by_tier) block: one model with real
    # quants (concrete fit verdicts) and one without (falls back to
    # "unknown" verdicts) — both exercise the fixed heading/div ordering.
    model_with_quants = ModelEntry(
        id="qwen3-8b", name="Qwen3 8B", family="Qwen3", params_total=8_000_000_000,
        quants=[QuantVariant(format="Q4_K_M", bits_per_weight=4.5, est_memory_gb_4k=8.4,
                             platform=Platform.GENERIC, source="x")],
    )
    model_no_quants = ModelEntry(id="no-quants", name="No Quants", family="F")

    # (c) trending.html's on-prem/broader block: _trending_obs() only supplies
    # ONPREM observations, so "broader" is genuinely empty (guard-false)
    # while "onprem" renders real rows (guard-true). The hub/candidate rows
    # below additionally exercise the guard-true path of the "Trending
    # Models/Techniques" and "Emerging — not yet tracked" blocks; the
    # guard-false path of those same blocks is covered by the second render
    # further down, which omits hub/candidate data entirely.
    model_hub = [HubRow(id="m1", name="M One", subtitle="Fam", metric=5000, growth=120.0,
                        momentum=None, direction="rising", ring="pilot", is_new=False,
                        kind="model")]
    technique_hub = [HubRow(id="t1", name="T One", subtitle="reasoning", metric=900,
                            growth=None, momentum=5, direction="rising", ring="adopt",
                            is_new=True, kind="technique")]
    model_candidates = [ModelCandidateEntry(hf_repo="acme/emerging", name="emerging",
                        family="acme", downloads=4000, downloads_per_day=1000.0, is_new=True,
                        first_seen="2026-07-01", last_seen="2026-07-01", is_stale=False)]
    technique_candidates = [TechniqueCandidateEntry(arxiv_id="2501.9999", name="Hot Paper",
                            upvotes=130, upvotes_per_day=40.0, citation_count=3, is_new=True,
                            first_seen="2026-07-01", last_seen="2026-07-01", is_stale=False)]

    # (e) _technique_detail's "Score breakdown" block: _technique_entry()
    # leaves score_breakdown unset (guard-false — must emit no empty wrap).
    render_static_site(
        [plain_card, scored_card],
        tmp_path / "_site",
        datetime(2026, 7, 8, tzinfo=UTC),
        model_entries=[model_with_quants, model_no_quants],
        technique_entries=[_technique_entry()],
        trending_observations=_trending_obs(),
        model_hub=model_hub,
        technique_hub=technique_hub,
        model_candidates=model_candidates,
        technique_candidates=technique_candidates,
    )

    site = tmp_path / "_site"
    for page in site.glob("*.html"):
        text = page.read_text(encoding="utf-8")
        assert not re.search(r'<div class="table-wrap">\s*</div>', text), page.name

    # The affected pages must actually have been written — otherwise the
    # scan above proves nothing (the original vacuous-test failure mode).
    assert (site / "trending.html").exists()
    assert list(site.glob("project_*.html"))
    assert list(site.glob("model_*.html"))
    assert list(site.glob("technique_*.html"))

    # (d) trending.html's "Trending Models"/"Trending Techniques" and their
    # "Emerging — not yet tracked" candidate blocks, guard-false path:
    # trending_entries alone is enough to satisfy static_site.py's write
    # guard (`if trending_entries or model_hub or ...`), so trending.html is
    # written even though model_hub/technique_hub/model_candidates/
    # technique_candidates are all left empty.
    empty_hubs_dir = tmp_path / "_site_empty_hubs"
    render_static_site(
        [plain_card],
        empty_hubs_dir,
        datetime(2026, 7, 8, tzinfo=UTC),
        trending_observations=_trending_obs(),
    )
    trending_page = (empty_hubs_dir / "trending.html").read_text(encoding="utf-8")
    assert not re.search(r'<div class="table-wrap">\s*</div>', trending_page)
    assert "No trending models this week." in trending_page
    assert "No trending techniques this week." in trending_page
    assert "No emerging models yet." in trending_page
    assert "No emerging papers yet." in trending_page


# ---------------------------------------------------------------------------
# Tenure credential (Task 1, differentiation pass)
# ---------------------------------------------------------------------------


def test_static_index_shows_tenure_and_backcompat(tmp_path: Path):
    from radar.web.tenure import TenureLine

    tenure = {"vLLM": TenureLine(days_on_radar=77, ring="adopt",
                                 ring_since="2026-05-12", change_count=2)}
    render_static_site([_card("vLLM", Ring.ADOPT)], tmp_path / "_site",
                       datetime(2026, 7, 28, tzinfo=UTC), tenure_by_project=tenure)
    index = (tmp_path / "_site" / "index.html").read_text(encoding="utf-8")
    assert "On radar 77 days · ADOPT since 2026-05-12 · 2 ring changes" in index

    # Back-compat: omitting the kwarg renders without tenure chrome.
    render_static_site([_card("vLLM", Ring.ADOPT)], tmp_path / "_site2",
                       datetime(2026, 7, 28, tzinfo=UTC))
    index2 = (tmp_path / "_site2" / "index.html").read_text(encoding="utf-8")
    assert 'class="tenure"' not in index2


def test_static_project_page_shows_tenure(tmp_path: Path):
    from radar.web.tenure import TenureLine

    tenure = {"vLLM": TenureLine(days_on_radar=77, ring="adopt",
                                 ring_since="2026-05-12", change_count=2)}
    render_static_site([_card("vLLM", Ring.ADOPT)], tmp_path / "_site",
                       datetime(2026, 7, 28, tzinfo=UTC), tenure_by_project=tenure)
    page = (tmp_path / "_site" / "project_vllm.html").read_text(encoding="utf-8")
    assert "On radar 77 days · ADOPT since 2026-05-12 · 2 ring changes" in page
    assert 'class="tenure"' in page


def test_static_project_page_tenure_backcompat(tmp_path: Path):
    render_static_site([_card("vLLM", Ring.ADOPT)], tmp_path / "_site",
                       datetime(2026, 7, 28, tzinfo=UTC))
    page = (tmp_path / "_site" / "project_vllm.html").read_text(encoding="utf-8")
    assert 'class="tenure"' not in page


def test_static_model_page_shows_tenure(tmp_path: Path):
    from radar.models_radar.entities import ModelEntry
    from radar.web.tenure import TenureLine

    model = ModelEntry(id="qwen3-8b", name="Qwen3 8B", family="Qwen3")
    model_tenure = {"qwen3-8b": TenureLine(days_on_radar=40, ring="pilot",
                                           ring_since="2026-06-18", change_count=1)}
    render_static_site([], tmp_path / "_site", datetime(2026, 7, 28, tzinfo=UTC),
                       model_entries=[model], model_tenure_by_id=model_tenure)
    page = (tmp_path / "_site" / "model_qwen3-8b.html").read_text(encoding="utf-8")
    assert "On radar 40 days · PILOT since 2026-06-18 · 1 ring change" in page
    assert 'class="tenure"' in page


def test_static_model_page_tenure_backcompat(tmp_path: Path):
    from radar.models_radar.entities import ModelEntry

    model = ModelEntry(id="qwen3-8b", name="Qwen3 8B", family="Qwen3")
    render_static_site([], tmp_path / "_site", datetime(2026, 7, 28, tzinfo=UTC),
                       model_entries=[model])
    page = (tmp_path / "_site" / "model_qwen3-8b.html").read_text(encoding="utf-8")
    assert 'class="tenure"' not in page


def test_static_export_writes_badges_and_snippet(tmp_path: Path):
    render_static_site([_card("vLLM", Ring.ADOPT)], tmp_path / "_site",
                       datetime(2026, 7, 28, tzinfo=UTC),
                       self_base_url="https://radar.example")
    badge = tmp_path / "_site" / "badges" / "vllm.svg"
    assert badge.exists() and "ADOPT" in badge.read_text(encoding="utf-8")
    page = (tmp_path / "_site" / "project_vllm.html").read_text(encoding="utf-8")
    assert "https://radar.example/badges/vllm.svg" in page  # snippet uses base url


def test_static_export_badge_snippet_relative_without_base_url(tmp_path: Path):
    render_static_site([_card("vLLM", Ring.ADOPT)], tmp_path / "_site",
                       datetime(2026, 7, 28, tzinfo=UTC))
    page = (tmp_path / "_site" / "project_vllm.html").read_text(encoding="utf-8")
    assert "badges/vllm.svg" in page
    assert "https://" not in page.split("badge-snippet")[1].split("</pre>")[0]


def test_static_export_writes_model_ring_and_fit_badges(tmp_path: Path):
    from radar.models_radar.entities import HardwareTier, ModelEntry, Platform, QuantVariant

    model = ModelEntry(
        id="qwen3-8b", name="Qwen3 8B", family="Qwen3", ring=Ring.ADOPT,
        hardware_tier=HardwareTier.LAPTOP,
        quants=[QuantVariant(format="Q5_K_M", bits_per_weight=5.5, est_memory_gb_4k=6.0,
                             platform=Platform.GENERIC, source="hf:x")],
    )
    render_static_site([], tmp_path / "_site", datetime(2026, 7, 28, tzinfo=UTC),
                       model_entries=[model], self_base_url="https://radar.example")

    ring_badge = tmp_path / "_site" / "badges" / "model-qwen3-8b.svg"
    fit_badge = tmp_path / "_site" / "badges" / "fit-qwen3-8b.svg"
    assert ring_badge.exists() and "ADOPT" in ring_badge.read_text(encoding="utf-8")
    assert fit_badge.exists()
    fit_text = fit_badge.read_text(encoding="utf-8")
    assert "laptop" in fit_text and "Q5_K_M" in fit_text

    page = (tmp_path / "_site" / "model_qwen3-8b.html").read_text(encoding="utf-8")
    assert "https://radar.example/badges/model-qwen3-8b.svg" in page
    assert "https://radar.example/badges/fit-qwen3-8b.svg" in page


def test_static_export_model_badges_backcompat_when_unringed_and_unknown_tier(tmp_path: Path):
    """A model with no ring and unknown hardware_tier gets no badge files/section."""
    from radar.models_radar.entities import ModelEntry

    model = ModelEntry(id="mystery", name="Mystery", family="F")
    render_static_site([], tmp_path / "_site", datetime(2026, 7, 28, tzinfo=UTC),
                       model_entries=[model])

    assert not (tmp_path / "_site" / "badges" / "model-mystery.svg").exists()
    assert not (tmp_path / "_site" / "badges" / "fit-mystery.svg").exists()
    page = (tmp_path / "_site" / "model_mystery.html").read_text(encoding="utf-8")
    assert "<h2>Badge</h2>" not in page


def test_static_export_badges_dir_empty_without_cards_or_models(tmp_path: Path):
    """Back-compat: an export with no cards/models still creates an empty badges/ dir."""
    render_static_site([], tmp_path / "_site", datetime(2026, 7, 28, tzinfo=UTC))
    badges_dir = tmp_path / "_site" / "badges"
    assert badges_dir.is_dir()
    assert list(badges_dir.iterdir()) == []


# ---------------------------------------------------------------------------
# Receipts-first cards + HN chip (Task 6, differentiation pass)
# ---------------------------------------------------------------------------


def test_static_index_caps_evidence_and_shows_hn_chip(tmp_path: Path):
    """Both the "Try This Week" table and the "All Tracked Projects" table
    cap evidence to the top two notes with a "+N more" link; the HN chip
    renders in the summary-bearing "Try This Week" cell only."""
    card = _card("vLLM", Ring.ADOPT).model_copy(
        update={"evidence_notes": ["note one", "note two", "note three"]}
    )
    render_static_site(
        [card], tmp_path / "_site", datetime(2026, 7, 28, tzinfo=UTC),
        hn_by_project={"vLLM": 12},
    )
    index = (tmp_path / "_site" / "index.html").read_text(encoding="utf-8")
    # Appears once in "Try This Week", once in "All Tracked Projects".
    assert index.count("note one") == 2
    assert index.count("note two") == 2
    assert "note three" not in index
    assert index.count("+1 more") == 2
    assert ">12 HN<" in index
    assert 'href="project_vllm.html">+1 more' in index


def test_static_index_hn_chip_backcompat(tmp_path: Path):
    """Back-compat: omitting hn_by_project renders no HN chip at all."""
    card = _card("vLLM", Ring.ADOPT).model_copy(
        update={"evidence_notes": ["note one", "note two", "note three"]}
    )
    render_static_site([card], tmp_path / "_site", datetime(2026, 7, 28, tzinfo=UTC))
    index = (tmp_path / "_site" / "index.html").read_text(encoding="utf-8")
    assert "chip-hn" not in index
    # Evidence cap still applies regardless of the HN chip.
    assert "note three" not in index
    assert index.count("+1 more") == 2
