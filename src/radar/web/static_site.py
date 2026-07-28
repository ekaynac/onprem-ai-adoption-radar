"""Static-site export for GitHub Pages.

The dashboard is a live FastAPI app; Pages needs plain files. This renders a
small, self-contained static site (index + compare + history) with embedded CSS
and relative cross-links, so a CI job can scan and publish a complete snapshot.
"""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from radar.discovery.model_candidate_detect import ModelCandidateEntry
from radar.discovery.technique_candidate_detect import TechniqueCandidateEntry
from radar.discovery.trending_detect import TRENDING_WINDOWS, build_trending
from radar.discovery.trending_entities import Lane, TrendingEntry, TrendingObservation
from radar.models import Category, DecisionCard, Ring
from radar.models_radar.entities import HardwareTier, ModelEntry
from radar.models_radar.history import ModelHistoryEvent
from radar.models_radar.memory import minimum_viable_quant
from radar.models_radar.reports import model_events_to_feed_atom, model_events_to_feed_json
from radar.reports.comparison import ComparisonError, build_comparison
from radar.reports.feeds import render_changes_atom, render_changes_json, render_changes_rss
from radar.research_radar.entities import TechniqueEntry
from radar.research_radar.history import TechniqueHistoryEvent
from radar.research_radar.pedigree import TechniquePedigree
from radar.research_radar.reports import (
    technique_events_to_feed_atom,
    technique_events_to_feed_json,
)
from radar.research_radar.timeline import build_technique_timeline
from radar.storage.digest_log import DigestLogEntry
from radar.storage.history_store import ProjectHistoryEvent
from radar.storage.metrics_store import ProjectMetrics
from radar.storage.model_metrics_store import ModelMetrics
from radar.web.backer_badge import backer_badge
from radar.web.badge import badge_markdown, fit_badge_svg, ring_badge_svg
from radar.web.hub_sections import HubRow
from radar.web.models_summary import summarize_models
from radar.web.picker_context import fit_by_tier, picker_context
from radar.web.research_summary import summarize_techniques
from radar.web.scan_health import summarize_meta
from radar.web.slugs import build_slug_map
from radar.web.source_health import SourceHealth
from radar.web.spark_series import downloads_sparkline, star_sparkline, trending_sparklines
from radar.web.tenure import TenureLine
from radar.web.trending_summary import summarize_trending


logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_STATIC_DIR = Path(__file__).parent / "static"
_TRY_RINGS = {Ring.ADOPT, Ring.PILOT}
_FEED_LIMIT = 50


def render_static_site(
    cards: list[DecisionCard],
    out_dir: Path,
    generated_at: datetime,
    timelines: list[dict[str, Any]] | None = None,
    site_title: str = "On-Prem AI Adoption Radar",
    self_base_url: str = "",
    metrics_by_project: dict[str, list[ProjectMetrics]] | None = None,
    latest_scan_meta: dict[str, Any] | None = None,
    history_jsonl: Path | None = None,
    source_health: SourceHealth | None = None,
    model_entries: list[ModelEntry] | None = None,
    model_events: list[ModelHistoryEvent] | None = None,
    technique_entries: list[TechniqueEntry] | None = None,
    technique_events: list[TechniqueHistoryEvent] | None = None,
    trending_observations: list[TrendingObservation] | None = None,
    pedigree_by_project: dict[str, list[TechniquePedigree]] | None = None,
    pedigree_by_model: dict[str, list[TechniquePedigree]] | None = None,
    technique_hrefs: dict[str, str] | None = None,
    impl_hrefs: dict[str, str] | None = None,
    digest_dir: Path | None = None,
    latest_digest: DigestLogEntry | None = None,
    model_hub: list[HubRow] | None = None,
    technique_hub: list[HubRow] | None = None,
    top_model: HubRow | None = None,
    top_technique: HubRow | None = None,
    model_candidates: list[ModelCandidateEntry] | None = None,
    technique_candidates: list[TechniqueCandidateEntry] | None = None,
    card_staleness: str | None = None,
    tenure_by_project: dict[str, TenureLine] | None = None,
    model_tenure_by_id: dict[str, TenureLine] | None = None,
    model_metrics_by_id: dict[str, list[ModelMetrics]] | None = None,
    hn_by_project: dict[str, int] | None = None,
) -> Path:
    """Render index.html, compare.html, history.html, per-project pages + feeds.

    ``timelines`` is an optional list of ``{"summary", "events"}`` (as the live
    dashboard builds) for the history page; when omitted, history renders empty.
    The same events drive ``changes.xml`` (Atom), ``changes.json``, and
    ``changes.rss`` (RSS 2.0) so the published site is subscribable. ``metrics_by_project`` (optional) supplies
    each project page's metrics history; omitting it renders empty metric tables.
    When ``model_entries`` is provided, writes ``models.html``, per-model pages,
    and ``changes-models.xml``/``.json`` feeds (the latter only when
    ``model_events`` is also provided). When ``technique_entries`` is provided,
    writes ``techniques.html``, per-technique pages, and
    ``changes-research.xml``/``.json`` feeds (the latter only when
    ``technique_events`` is also provided). ``pedigree_by_project`` and
    ``pedigree_by_model`` (optional) supply the project/model pages' "Research
    techniques" section; ``technique_hrefs`` maps technique id to its href and
    must cover every id referenced by either. ``impl_hrefs`` (optional) maps a
    technique's resolved-implementation ref to its project/model page href,
    driving the technique pages' "Implementations" links. When
    ``trending_observations`` is provided, derives trending entries and writes
    three velocity-window variants — ``trending.html`` (7d, the back-compat
    default filename), ``trending-30d.html``, ``trending-90d.html`` — each with
    a tab nav cross-linking the others (two lanes per page: on-prem candidates
    and broader AI heat; repo membership is identical across variants, only
    each entry's velocity_per_day differs by window).
    ``model_hub``/``technique_hub`` (optional) supply the "Trending Models"/
    "Trending Techniques" sections identically on all three pages — they are
    written whenever any of ``trending_observations``, ``model_hub``,
    ``technique_hub``, ``model_candidates``, or ``technique_candidates``
    yields data. ``top_model``/``top_technique`` (optional) drive the
    index-page trending strip's highlight lines. ``model_candidates``
    (optional) supplies the "Emerging — not yet tracked" sub-section under
    Trending Models, linking each untracked Hugging Face repo to its absolute
    ``https://huggingface.co/<repo>`` page. ``technique_candidates``
    (optional) supplies the same sub-section under Trending Techniques,
    linking each untracked paper to its absolute
    ``https://arxiv.org/abs/<arxiv_id>`` page.
    When ``digest_dir`` is given and exists, its tree (digest pages, cards,
    feeds) is copied into ``out_dir/digests``; ``latest_digest`` (optional)
    drives a "Latest digest" link on the index page. Both are a no-op when
    omitted — back-compat for exports without a digest log yet.
    ``card_staleness`` (optional, from ``RadarDatabase.card_staleness_note()``)
    renders a note in the scan-health panel when persisted cards span more
    than one scan day (a partial/degraded run mixing fresh and stale ages).
    ``tenure_by_project``/``model_tenure_by_id`` (optional) supply the tenure
    credential line ("On radar N days · RING since <date> · N ring changes")
    on the index page's project rows and each project/model detail page;
    omitting either renders that surface without the tenure chrome.
    ``model_metrics_by_id`` (optional) supplies each model page's download
    history, rendered as a sparkline beside the download stat; omitting it
    renders that page without the sparkline (differentiation pass, Task 3).
    ``hn_by_project`` (optional, differentiation pass Task 6) maps project ->
    latest Hacker News mention count; only positive counts should be passed,
    each rendering a "N HN" chip beside that project's summary on the index
    page's "Try This Week" table. Both index tables also cap evidence notes
    to the top two, with a "+N more" link to the project page when there are
    more.
    A ``badges/`` directory is always written (Task 5): one ring badge per
    project (``badges/<slug>.svg``), plus — per model entry — a ring badge
    when it has a ring (``badges/model-<id>.svg``) and a fit badge when its
    ``hardware_tier`` is known (``badges/fit-<id>.svg``, quant label from
    ``minimum_viable_quant``). Empty ``cards``/``model_entries`` just leave
    the directory empty. Each project/model page's "Badge" section threads
    ``badge_svg``/``badge_snippet`` (model pages also get
    ``fit_badge_svg``/``fit_badge_snippet``) built from these same URLs,
    qualified with ``self_base_url`` when given so the copied Markdown
    resolves from anywhere, or left site-relative otherwise.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    # Shared presentation helper so live + static render backers identically.
    env.globals["backer_badge"] = backer_badge
    # Static pages are flat files at the site root, so brand assets are
    # referenced relatively (the live app uses an absolute "/static" instead).
    env.globals["asset_base"] = ""

    # Copy bundled brand assets (logo, favicon) into the published site.
    if _STATIC_DIR.is_dir():
        shutil.copytree(_STATIC_DIR, out_dir / "static", dirs_exist_ok=True)
    stamp = generated_at.strftime("%Y-%m-%d %H:%M UTC")

    # One slug per project, shared by index links and per-project filenames so
    # they can never disagree.
    slug_by_project = build_slug_map([c.project for c in cards])

    # Publish the durable history log alongside the site so visitors can download
    # the full timeline. Only offered when the log exists.
    history_available = False
    if history_jsonl is not None and history_jsonl.exists():
        shutil.copy2(history_jsonl, out_dir / "history.jsonl")
        history_available = True

    # Model-history download: only when the log exists in the site root
    # (cli.py copies it there before calling us).
    model_history_available = (out_dir / "model-history.jsonl").exists()

    # Technique-history download: only when the log exists in the site root
    # (cli.py copies it there before calling us).
    technique_history_available = (out_dir / "technique-history.jsonl").exists()

    downloads = {
        "History (JSONL)": "history.jsonl" if history_available else None,
        "Changes (JSON)": "changes.json",
        "Changes (Atom)": "changes.xml",
        "Changes (RSS)": "changes.rss",
        "Model History (JSONL)": "model-history.jsonl" if model_history_available else None,
        "Technique History (JSONL)": (
            "technique-history.jsonl" if technique_history_available else None
        ),
    }

    # Summarize models for the index page banner (None when no models yet).
    models_summary = summarize_models(model_entries) if model_entries else None
    techniques_summary = summarize_techniques(technique_entries) if technique_entries else None
    # One set of entries per velocity window (7d/30d/90d) — window_days only
    # changes each entry's velocity_per_day, never repo membership, so the
    # write-guard/summary below can keep using the 7d set unchanged.
    try:
        trending_entries_by_window = (
            {
                key: build_trending(trending_observations, generated_at, window_days=days)
                for key, days in TRENDING_WINDOWS.items()
            }
            if trending_observations else {key: [] for key in TRENDING_WINDOWS}
        )
    except Exception as exc:
        logger.warning("Trending derivation failed during export: %s", exc)
        trending_entries_by_window = {key: [] for key in TRENDING_WINDOWS}
    trending_entries = trending_entries_by_window["7d"]
    trending_summary = summarize_trending(trending_entries) if trending_entries else None
    spark_by_repo = trending_sparklines(trending_observations or [])

    # One slug per model/technique, shared by the trending-hub detail links so
    # they can never disagree with the per-entity pages' own filenames.
    model_slugs = build_slug_map([e.id for e in (model_entries or [])])
    technique_slugs = build_slug_map([t.id for t in (technique_entries or [])])

    index = out_dir / "index.html"
    index.write_text(
        env.get_template("static_index.html").render(
            cards=cards,
            try_this_week=[c for c in cards if c.ring in _TRY_RINGS],
            generated_at=stamp,
            slug_by_project=slug_by_project,
            scan_health=summarize_meta(latest_scan_meta or {}),
            card_staleness=card_staleness,
            source_health=source_health,
            downloads=downloads,
            models_summary=models_summary,
            techniques_summary=techniques_summary,
            trending_summary=trending_summary,
            latest_digest=latest_digest,
            top_model=top_model,
            top_technique=top_technique,
            tenure_by_project=tenure_by_project,
            hn_by_project=hn_by_project,
        ),
        encoding="utf-8",
    )

    (out_dir / "compare.html").write_text(
        env.get_template("static_compare.html").render(
            comparisons=_comparisons_by_category(cards),
            generated_at=stamp,
        ),
        encoding="utf-8",
    )

    (out_dir / "history.html").write_text(
        env.get_template("static_history.html").render(
            timelines=timelines or [],
            generated_at=stamp,
            downloads=downloads,
        ),
        encoding="utf-8",
    )

    _write_project_pages(
        env, out_dir, cards, slug_by_project, timelines or [], metrics_by_project or {},
        pedigree_by_project=pedigree_by_project or {}, technique_hrefs=technique_hrefs or {},
        tenure_by_project=tenure_by_project or {}, self_base_url=self_base_url,
    )
    _write_feeds(out_dir, timelines or [], site_title, self_base_url)
    _write_badges(out_dir, cards, slug_by_project, model_entries or [])

    if model_entries:
        _write_model_pages(
            env, out_dir, model_entries, model_events or [], site_title, self_base_url, stamp,
            pedigree_by_model=pedigree_by_model or {}, technique_hrefs=technique_hrefs or {},
            model_tenure_by_id=model_tenure_by_id or {},
            model_metrics_by_id=model_metrics_by_id or {},
        )

    if technique_entries:
        _write_technique_pages(
            env, out_dir, technique_entries, technique_events or [],
            site_title, self_base_url, stamp,
            impl_hrefs=impl_hrefs,
        )

    if trending_entries or model_hub or technique_hub or model_candidates or technique_candidates:
        for window_key in TRENDING_WINDOWS:
            filename = "trending.html" if window_key == "7d" else f"trending-{window_key}.html"
            _write_trending_page(
                env, out_dir, trending_entries_by_window[window_key], stamp,
                model_hub=model_hub or [], technique_hub=technique_hub or [],
                model_slugs=model_slugs, technique_slugs=technique_slugs,
                model_candidates=model_candidates or [],
                technique_candidates=technique_candidates or [],
                spark_by_repo=spark_by_repo,
                filename=filename,
                active_window=window_key,
            )

    # Publish the generated weekly digests (page + cards + feeds) alongside
    # the site. Only offered when the directory exists — back-compat for
    # exports run before any digest has been generated.
    if digest_dir and digest_dir.exists():
        try:
            shutil.copytree(digest_dir, out_dir / "digests", dirs_exist_ok=True)
        except Exception as exc:
            logger.warning("Could not copy digests into site: %s", exc)

    return index


def _badge_url(base: str, path: str) -> str:
    """``{base}/{path}`` when a base URL is given, else the bare relative ``path``."""
    return f"{base}/{path}" if base else path


def _write_project_pages(
    env: Environment,
    out_dir: Path,
    cards: list[DecisionCard],
    slug_by_project: dict[str, str],
    timelines: list[dict[str, Any]],
    metrics_by_project: dict[str, list[ProjectMetrics]],
    pedigree_by_project: dict[str, list[TechniquePedigree]],
    technique_hrefs: dict[str, str],
    tenure_by_project: dict[str, TenureLine] | None = None,
    self_base_url: str = "",
) -> None:
    """Render one self-contained project_<slug>.html per card."""
    events_by_project: dict[str, list[ProjectHistoryEvent]] = {
        t["summary"].project: t.get("events") or [] for t in timelines
    }
    base = self_base_url.rstrip("/") if self_base_url else ""
    template = env.get_template("static_project.html")
    for card in cards:
        metrics_oldest_first = metrics_by_project.get(card.project, [])
        metrics = list(reversed(metrics_oldest_first))  # newest-first
        slug = slug_by_project[card.project]
        badge_snippet = badge_markdown(
            _badge_url(base, f"badges/{slug}.svg"),
            _badge_url(base, f"project_{slug}.html"),
            f"On-Prem Radar: {card.ring.value.upper()}",
        )
        (out_dir / f"project_{slug}.html").write_text(
            template.render(
                card=card,
                events=events_by_project.get(card.project, []),
                metrics=metrics,
                pedigree=(pedigree_by_project.get(card.project) or None),
                technique_hrefs=technique_hrefs,
                tenure=(tenure_by_project or {}).get(card.project),
                star_spark=star_sparkline(metrics_oldest_first),
                badge_svg=ring_badge_svg(card.ring.value),
                badge_snippet=badge_snippet,
            ),
            encoding="utf-8",
        )


def _write_feeds(
    out_dir: Path,
    timelines: list[dict[str, Any]],
    site_title: str,
    self_base_url: str,
) -> None:
    """Write changes.xml (Atom), changes.json, and changes.rss from the timeline events."""
    events: list[ProjectHistoryEvent] = []
    for timeline in timelines:
        events.extend(timeline.get("events") or [])
    events.sort(key=lambda e: e.observed_at, reverse=True)
    recent = events[:_FEED_LIMIT]

    base = self_base_url.rstrip("/") if self_base_url else ""
    self_url = f"{base}/changes.xml" if base else "changes.xml"
    (out_dir / "changes.xml").write_text(
        render_changes_atom(recent, site_title=site_title, self_url=self_url),
        encoding="utf-8",
    )
    (out_dir / "changes.json").write_text(
        json.dumps(render_changes_json(recent, site_title=site_title), indent=2),
        encoding="utf-8",
    )
    rss_url = f"{base}/changes.rss" if base else "changes.rss"
    (out_dir / "changes.rss").write_text(
        render_changes_rss(recent, site_title=site_title, self_url=rss_url),
        encoding="utf-8",
    )


def _write_badges(
    out_dir: Path,
    cards: list[DecisionCard],
    slug_by_project: dict[str, str],
    model_entries: list[ModelEntry],
) -> None:
    """Write badges/*.svg: one ring badge per project, plus ring/fit badges per model.

    Path-only URLs (``badges/<slug>.svg``, ``badges/model-<id>.svg``,
    ``badges/fit-<id>.svg``) so a future change to fit-badge *content* (e.g.
    sub-project D's GPU-count badges) never needs a URL change. Empty
    ``cards``/``model_entries`` just leave the directory empty.
    """
    badges_dir = out_dir / "badges"
    badges_dir.mkdir(parents=True, exist_ok=True)
    for card in cards:
        slug = slug_by_project[card.project]
        (badges_dir / f"{slug}.svg").write_text(
            ring_badge_svg(card.ring.value), encoding="utf-8"
        )
    for entry in model_entries:
        if entry.ring is not None:
            (badges_dir / f"model-{entry.id}.svg").write_text(
                ring_badge_svg(entry.ring.value), encoding="utf-8"
            )
        if entry.hardware_tier != HardwareTier.UNKNOWN:
            quant = minimum_viable_quant(entry.quants)
            (badges_dir / f"fit-{entry.id}.svg").write_text(
                fit_badge_svg(entry.hardware_tier.value, quant.format if quant else None),
                encoding="utf-8",
            )


def _write_model_pages(
    env: Environment,
    out_dir: Path,
    model_entries: list[ModelEntry],
    model_events: list[ModelHistoryEvent],
    site_title: str,
    self_base_url: str,
    generated_at: str = "",
    pedigree_by_model: dict[str, list[TechniquePedigree]] | None = None,
    technique_hrefs: dict[str, str] | None = None,
    model_tenure_by_id: dict[str, TenureLine] | None = None,
    model_metrics_by_id: dict[str, list[ModelMetrics]] | None = None,
) -> None:
    """Render models.html, per-model pages, and model feed files."""
    slug_by_model = build_slug_map([m.id for m in model_entries])
    base = self_base_url.rstrip("/") if self_base_url else ""

    (out_dir / "models.html").write_text(
        env.get_template("static_models.html").render(
            models=model_entries,
            slug_by_model=slug_by_model,
            device_picker=picker_context(),
            generated_at=generated_at,
        ),
        encoding="utf-8",
    )

    model_template = env.get_template("static_model.html")
    for entry in model_entries:
        slug = slug_by_model[entry.id]
        target_url = _badge_url(base, f"model_{slug}.html")
        badge_svg = ring_badge_svg(entry.ring.value) if entry.ring else None
        badge_snippet = (
            badge_markdown(
                _badge_url(base, f"badges/model-{entry.id}.svg"), target_url,
                f"On-Prem Radar: {entry.ring.value.upper()}",
            )
            if entry.ring else None
        )
        mv_quant = minimum_viable_quant(entry.quants)
        fit_svg = (
            fit_badge_svg(entry.hardware_tier.value, mv_quant.format if mv_quant else None)
            if entry.hardware_tier != HardwareTier.UNKNOWN else None
        )
        fit_snippet = (
            badge_markdown(
                _badge_url(base, f"badges/fit-{entry.id}.svg"), target_url,
                f"On-Prem Radar: runs on {entry.hardware_tier.value}",
            )
            if entry.hardware_tier != HardwareTier.UNKNOWN else None
        )
        (out_dir / f"model_{slug}.html").write_text(
            model_template.render(
                model=entry,
                fit_by_tier=fit_by_tier(entry),
                generated_at=generated_at,
                pedigree=(pedigree_by_model or {}).get(entry.id) or None,
                technique_hrefs=technique_hrefs or {},
                model_tenure_line=(model_tenure_by_id or {}).get(entry.id),
                download_spark=downloads_sparkline((model_metrics_by_id or {}).get(entry.id, [])),
                badge_svg=badge_svg,
                badge_snippet=badge_snippet,
                fit_badge_svg=fit_svg,
                fit_badge_snippet=fit_snippet,
            ),
            encoding="utf-8",
        )

    if model_events:
        self_url = (
            f"{self_base_url.rstrip('/')}/changes-models.xml"
            if self_base_url
            else "changes-models.xml"
        )
        (out_dir / "changes-models.xml").write_text(
            model_events_to_feed_atom(model_events, site_title=site_title, self_url=self_url),
            encoding="utf-8",
        )
        (out_dir / "changes-models.json").write_text(
            json.dumps(model_events_to_feed_json(model_events, site_title=site_title), indent=2),
            encoding="utf-8",
        )


def _write_technique_pages(
    env: Environment,
    out_dir: Path,
    technique_entries: list[TechniqueEntry],
    technique_events: list[TechniqueHistoryEvent],
    site_title: str,
    self_base_url: str,
    generated_at: str = "",
    impl_hrefs: dict[str, str] | None = None,
) -> None:
    """Render techniques.html, per-technique pages, and research feed files."""
    slug_by_technique = build_slug_map([t.id for t in technique_entries])

    (out_dir / "techniques.html").write_text(
        env.get_template("static_techniques.html").render(
            techniques=technique_entries,
            slug_by_technique=slug_by_technique,
            generated_at=generated_at,
        ),
        encoding="utf-8",
    )

    technique_template = env.get_template("static_technique.html")
    for entry in technique_entries:
        (out_dir / f"technique_{slug_by_technique[entry.id]}.html").write_text(
            technique_template.render(
                technique=entry,
                timeline=build_technique_timeline(entry, technique_events),
                generated_at=generated_at,
                impl_hrefs=impl_hrefs or {},
            ),
            encoding="utf-8",
        )

    if technique_events:
        self_url = (
            f"{self_base_url.rstrip('/')}/changes-research.xml"
            if self_base_url
            else "changes-research.xml"
        )
        (out_dir / "changes-research.xml").write_text(
            technique_events_to_feed_atom(technique_events, site_title=site_title,
                                          self_url=self_url),
            encoding="utf-8",
        )
        (out_dir / "changes-research.json").write_text(
            json.dumps(technique_events_to_feed_json(technique_events, site_title=site_title),
                       indent=2),
            encoding="utf-8",
        )


def _write_trending_page(
    env: Environment,
    out_dir: Path,
    trending_entries: list[TrendingEntry],
    generated_at: str = "",
    model_hub: list[HubRow] | None = None,
    technique_hub: list[HubRow] | None = None,
    model_slugs: dict[str, str] | None = None,
    technique_slugs: dict[str, str] | None = None,
    model_candidates: list[ModelCandidateEntry] | None = None,
    technique_candidates: list[TechniqueCandidateEntry] | None = None,
    spark_by_repo: dict[str, str] | None = None,
    filename: str = "trending.html",
    active_window: str = "7d",
) -> None:
    """Render one trending page variant (repo lanes + Models/Techniques hub
    sections). Called once per velocity window (Task 4) — ``filename``/
    ``active_window`` select which of trending.html (7d, back-compat name)/
    trending-30d.html/trending-90d.html gets written and which tab shows as
    active; the tab nav always links across all three filenames so the pages
    cross-link like the live route's ``?window=`` query param."""
    onprem = [e for e in trending_entries if e.lane == Lane.ONPREM]
    broader = [e for e in trending_entries if e.lane == Lane.BROADER]
    window_hrefs = {
        key: ("trending.html" if key == "7d" else f"trending-{key}.html")
        for key in TRENDING_WINDOWS
    }
    (out_dir / filename).write_text(
        env.get_template("static_trending.html").render(
            onprem=onprem, broader=broader, generated_at=generated_at,
            model_hub=model_hub or [], technique_hub=technique_hub or [],
            model_slugs=model_slugs or {}, technique_slugs=technique_slugs or {},
            model_candidates=model_candidates or [],
            technique_candidates=technique_candidates or [],
            spark_by_repo=spark_by_repo or {},
            active_window=active_window,
            windows=list(TRENDING_WINDOWS),
            window_hrefs=window_hrefs,
        ),
        encoding="utf-8",
    )


def _comparisons_by_category(cards: list[DecisionCard]) -> list[dict[str, Any]]:
    """Build one comparison matrix per category that has at least two projects."""
    out: list[dict[str, Any]] = []
    for category in Category:
        try:
            comparison = build_comparison(cards, category=category)
        except ComparisonError:
            continue  # fewer than two projects in this category — skip
        out.append({"category": category.value, "comparison": comparison})
    return out
