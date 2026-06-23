"""Static-site export for GitHub Pages.

The dashboard is a live FastAPI app; Pages needs plain files. This renders a
small, self-contained static site (index + compare + history) with embedded CSS
and relative cross-links, so a CI job can scan and publish a complete snapshot.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from radar.models import Category, DecisionCard, Ring
from radar.models_radar.entities import ModelEntry
from radar.models_radar.history import ModelHistoryEvent
from radar.models_radar.reports import model_events_to_feed_atom, model_events_to_feed_json
from radar.reports.comparison import ComparisonError, build_comparison
from radar.reports.feeds import render_changes_atom, render_changes_json
from radar.storage.history_store import ProjectHistoryEvent
from radar.storage.metrics_store import ProjectMetrics
from radar.web.backer_badge import backer_badge
from radar.web.models_summary import summarize_models
from radar.web.picker_context import fit_by_tier, picker_context
from radar.web.scan_health import summarize_meta
from radar.web.slugs import build_slug_map
from radar.web.source_health import SourceHealth


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
) -> Path:
    """Render index.html, compare.html, history.html, per-project pages + feeds.

    ``timelines`` is an optional list of ``{"summary", "events"}`` (as the live
    dashboard builds) for the history page; when omitted, history renders empty.
    The same events drive ``changes.xml`` (Atom) and ``changes.json`` so the
    published site is subscribable. ``metrics_by_project`` (optional) supplies
    each project page's metrics history; omitting it renders empty metric tables.
    When ``model_entries`` is provided, writes ``models.html``, per-model pages,
    and ``changes-models.xml``/``.json`` feeds (the latter only when
    ``model_events`` is also provided).
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

    downloads = {
        "History (JSONL)": "history.jsonl" if history_available else None,
        "Changes (JSON)": "changes.json",
        "Changes (Atom)": "changes.xml",
        "Model History (JSONL)": "model-history.jsonl" if model_history_available else None,
    }

    # Summarize models for the index page banner (None when no models yet).
    models_summary = summarize_models(model_entries) if model_entries else None

    index = out_dir / "index.html"
    index.write_text(
        env.get_template("static_index.html").render(
            cards=cards,
            try_this_week=[c for c in cards if c.ring in _TRY_RINGS],
            generated_at=stamp,
            slug_by_project=slug_by_project,
            scan_health=summarize_meta(latest_scan_meta or {}),
            source_health=source_health,
            downloads=downloads,
            models_summary=models_summary,
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
        env, out_dir, cards, slug_by_project, timelines or [], metrics_by_project or {}
    )
    _write_feeds(out_dir, timelines or [], site_title, self_base_url)

    if model_entries:
        _write_model_pages(
            env, out_dir, model_entries, model_events or [], site_title, self_base_url, stamp
        )

    return index


def _write_project_pages(
    env: Environment,
    out_dir: Path,
    cards: list[DecisionCard],
    slug_by_project: dict[str, str],
    timelines: list[dict[str, Any]],
    metrics_by_project: dict[str, list[ProjectMetrics]],
) -> None:
    """Render one self-contained project_<slug>.html per card."""
    events_by_project: dict[str, list[ProjectHistoryEvent]] = {
        t["summary"].project: t.get("events") or [] for t in timelines
    }
    template = env.get_template("static_project.html")
    # Static pages are flat files in the same dir — all nav links are relative.
    links = {"home": "index.html", "compare": "compare.html", "history": "history.html"}
    for card in cards:
        metrics = list(reversed(metrics_by_project.get(card.project, [])))  # newest-first
        (out_dir / f"project_{slug_by_project[card.project]}.html").write_text(
            template.render(
                card=card,
                events=events_by_project.get(card.project, []),
                metrics=metrics,
                links=links,
            ),
            encoding="utf-8",
        )


def _write_feeds(
    out_dir: Path,
    timelines: list[dict[str, Any]],
    site_title: str,
    self_base_url: str,
) -> None:
    """Write changes.xml (Atom) and changes.json from the timeline events."""
    events: list[ProjectHistoryEvent] = []
    for timeline in timelines:
        events.extend(timeline.get("events") or [])
    events.sort(key=lambda e: e.observed_at, reverse=True)
    recent = events[:_FEED_LIMIT]

    self_url = f"{self_base_url.rstrip('/')}/changes.xml" if self_base_url else "changes.xml"
    (out_dir / "changes.xml").write_text(
        render_changes_atom(recent, site_title=site_title, self_url=self_url),
        encoding="utf-8",
    )
    (out_dir / "changes.json").write_text(
        json.dumps(render_changes_json(recent, site_title=site_title), indent=2),
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
) -> None:
    """Render models.html, per-model pages, and model feed files."""
    slug_by_model = build_slug_map([m.id for m in model_entries])

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
        (out_dir / f"model_{slug_by_model[entry.id]}.html").write_text(
            model_template.render(
                model=entry, fit_by_tier=fit_by_tier(entry), generated_at=generated_at
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
