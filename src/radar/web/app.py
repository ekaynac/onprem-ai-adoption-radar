"""FastAPI dashboard app."""

from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Form, Request, Response
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    PlainTextResponse,
    RedirectResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from radar.discovery.trending_detect import TRENDING_WINDOWS, build_trending
from radar.discovery.trending_entities import Lane, TrendingEntry, TrendingObservation
from radar.mcp_server.model_queries import _latest_model_cards
from radar.mcp_server.technique_queries import load_technique_entries
from radar.mcp_server.trending_queries import load_trending_entries
from radar.models import Category, SourceType
from radar.models_radar.entities import HardwareTier, ModelEntry
from radar.models_radar.history import ModelHistoryEvent, load_model_events
from radar.models_radar.memory import minimum_viable_quant
from radar.models_radar.scoring import ModelProfileError, rescore_entries
from radar.reports.comparison import ComparisonError, build_comparison
from radar.research_radar.entities import ImplKind, TechniqueEntry
from radar.research_radar.history import load_technique_events
from radar.research_radar.pedigree import (
    TechniquePedigree,
    build_pedigree_index,
    pedigree_for_refs,
)
from radar.research_radar.timeline import build_technique_timeline
from radar.storage.config import ConfigError, load_config
from radar.storage.database import RadarDatabase
from radar.storage.history_store import HistoryStore
from radar.storage.metrics_store import MetricsStore
from radar.storage.model_metrics_store import ModelMetricsStore
from radar.storage.run_store import RunStore
from radar.storage.seed_store import SeedError, add_seed
from radar.storage.source_health_store import SourceHealthStore
from radar.storage.trending_observations_log import load_observations
from radar.web.backer_badge import backer_badge
from radar.web.badge import badge_markdown, fit_badge_svg, ring_badge_svg
from radar.web.hub_sections import load_hub_sections
from radar.web.models_summary import summarize_models
from radar.web.picker_context import datacenter_fit_rows, fit_by_tier, picker_context
from radar.web.research_summary import summarize_techniques
from radar.web.scan_health import latest_tool_scan_meta, summarize_meta
from radar.web.slugs import build_slug_map
from radar.web.source_health import SourceHealth, summarize_source_health
from radar.web.spark_series import downloads_sparkline, star_sparkline, trending_sparklines
from radar.web.tenure import model_tenure, project_tenure
from radar.web.trending_summary import summarize_trending


logger = logging.getLogger(__name__)

_WEB_DIR = Path(__file__).parent
STATIC_DIR = _WEB_DIR / "static"

TEMPLATES = Jinja2Templates(directory=str(_WEB_DIR / "templates"))
# Shared presentation helper so live + static render backers identically.
TEMPLATES.env.globals["backer_badge"] = backer_badge
# Live dashboard serves brand assets under an absolute /static path (pages live
# at varying depths like /project/X, so a relative path would break).
TEMPLATES.env.globals["asset_base"] = "/"


def create_app(root: Path) -> FastAPI:
    """Create a local dashboard app with read views and seed management."""
    app = FastAPI(title="Agent/Tooling Adoption Radar")
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    db = RadarDatabase(root / "data" / "radar.db")
    history = HistoryStore(root / "data" / "radar.db")
    metrics = MetricsStore(root / "data" / "radar.db")
    model_metrics = ModelMetricsStore(root / "data" / "radar.db")
    run_store = RunStore(root / "data" / "runs")
    source_health = SourceHealthStore(root / "data" / "radar.db")
    config_path = root / "data" / "config.yaml"

    def _source_health() -> SourceHealth | None:
        """Build the source-health view, tolerating a missing config/store."""
        try:
            config = load_config(config_path)
        except ConfigError:
            return None
        source_health.initialize()
        return summarize_source_health(
            source_health.stale_source_ids(),
            source_health.latest_counts(),
            config.sources,
        )

    def _model_entries() -> list[ModelEntry]:
        """Load model entries from the latest models run; empty list if none."""
        return [ModelEntry.model_validate(c) for c in _latest_model_cards(root)]

    def _model_events_for(model_id: str) -> list[ModelHistoryEvent]:
        """A single model's ring-change events, oldest-first; [] if none recorded."""
        all_events = load_model_events(root / "data" / "model-history.jsonl")
        return [e for e in all_events if e.model_id == model_id]

    def _technique_entries() -> list[TechniqueEntry]:
        """Load technique entries from the latest research run; empty list if none."""
        return load_technique_entries(root)

    def _trending_entries() -> list[TrendingEntry]:
        from datetime import UTC, datetime
        return load_trending_entries(root, datetime.now(UTC))

    def _trending_observations() -> list[TrendingObservation]:
        """Raw observations backing /trending's per-window rebuild and its
        window-independent spark map; [] when the store is absent or corrupt
        (guarded by ``load_observations`` itself)."""
        return load_observations(root / "data" / "trending-observations.jsonl")

    def _hub_sections():
        from datetime import UTC, datetime
        return load_hub_sections(root, datetime.now(UTC))

    def _model_candidates():
        """Emerging (untracked, unseeded) candidates for the route; guarded in the gateway."""
        from datetime import UTC, datetime

        from radar.discovery.model_candidate_detect import load_emerging_candidates
        return load_emerging_candidates(root, datetime.now(UTC))

    def _technique_candidates():
        """Emerging (untracked) paper candidates for the route; guarded in the gateway."""
        from datetime import UTC, datetime

        from radar.discovery.technique_candidate_detect import load_emerging_techniques
        return load_emerging_techniques(root, datetime.now(UTC))

    def _technique_hrefs() -> dict[str, str]:
        """Map technique id -> live href, shared by project/model pedigree sections."""
        return {t.id: f"/technique/{t.id}" for t in _technique_entries()}

    def _project_pedigree(project: str) -> list[TechniquePedigree]:
        """Techniques implemented by this project's sources; [] on any gap."""
        try:
            entries = _technique_entries()
            if not entries:
                return []
            config = load_config(root / "data" / "config.yaml")
            refs = [s.id for s in config.sources if s.project == project]
            return pedigree_for_refs(build_pedigree_index(entries).by_tool_ref, refs)
        except Exception:
            return []

    def _model_pedigree(model_id: str) -> list[TechniquePedigree]:
        """Techniques implemented by this model; [] on any gap."""
        try:
            entries = _technique_entries()
            if not entries:
                return []
            return pedigree_for_refs(build_pedigree_index(entries).by_model_ref, [model_id])
        except Exception:
            return []

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        from datetime import UTC, datetime

        db.initialize()
        cards = db.list_cards()
        meta = latest_tool_scan_meta(run_store)
        mh, th = _hub_sections()
        history.initialize()
        metrics.initialize()
        now = datetime.now(UTC)
        tenure_by_project = {
            c.project: project_tenure(history.history_for(c.project), now) for c in cards
        }
        # HN chip (Task 6, differentiation pass): only projects with a
        # positive latest hn_mentions get a chip.
        hn_by_project = {
            c.project: latest.hn_mentions
            for c in cards
            if (latest := metrics.latest(c.project)) and latest.hn_mentions
        }
        return TEMPLATES.TemplateResponse(
            request,
            "index.html",
            {
                "cards": cards,
                "scan_health": summarize_meta(meta),
                "card_staleness": db.card_staleness_note(),
                "source_health": _source_health(),
                "models_summary": summarize_models(_model_entries()),
                "models_href": "/models",
                "techniques_summary": summarize_techniques(_technique_entries()),
                "research_href": "/research",
                "trending_summary": summarize_trending(_trending_entries()),
                "trending_href": "/trending",
                "top_model": next((r for r in mh if not r.is_new), None),
                "top_technique": next((r for r in th if not r.is_new), None),
                "tenure_by_project": tenure_by_project,
                "hn_by_project": hn_by_project,
            },
        )

    @app.get("/history.jsonl")
    def history_download():
        """Serve the durable append-only history log for download."""
        log_path = root / "data" / "history.jsonl"
        if not log_path.exists():
            return PlainTextResponse(
                "No history log yet. Run a scan first.", status_code=404
            )
        return FileResponse(
            log_path,
            media_type="application/x-ndjson",
            filename="radar-history.jsonl",
        )

    # Model badge routes are registered before the generic project-slug route
    # below so their literal "model-"/"fit-" prefixes win the match — the
    # slug route's pattern would otherwise swallow them too.
    @app.get("/badge/model-{model_id}.svg")
    def model_ring_badge(model_id: str):
        """Serve a model's ring badge (shields-style SVG), or 404 if unknown/unringed."""
        entry = next((e for e in _model_entries() if e.id == model_id), None)
        if entry is None or entry.ring is None:
            return PlainTextResponse("Unknown model badge", status_code=404)
        return Response(content=ring_badge_svg(entry.ring.value), media_type="image/svg+xml")

    @app.get("/badge/fit-{model_id}.svg")
    def model_fit_badge(model_id: str):
        """Serve a model's fit badge (hardware tier + min-viable quant), or 404."""
        entry = next((e for e in _model_entries() if e.id == model_id), None)
        if entry is None or entry.hardware_tier == HardwareTier.UNKNOWN:
            return PlainTextResponse("Unknown model fit badge", status_code=404)
        quant = minimum_viable_quant(entry.quants)
        svg = fit_badge_svg(entry.hardware_tier.value, quant.format if quant else None)
        return Response(content=svg, media_type="image/svg+xml")

    @app.get("/badge/{slug}.svg")
    def project_badge(slug: str):
        """Serve a tracked project's ring badge (shields-style SVG), or 404 if unknown."""
        db.initialize()
        cards = db.list_cards()
        slug_map = build_slug_map([c.project for c in cards])
        card = next((c for c in cards if slug_map[c.project] == slug), None)
        if card is None:
            return PlainTextResponse("Unknown project badge", status_code=404)
        return Response(content=ring_badge_svg(card.ring.value), media_type="image/svg+xml")

    @app.get("/project/{name}", response_class=HTMLResponse)
    def project_detail(request: Request, name: str):
        from datetime import UTC, datetime

        db.initialize()
        all_cards = db.list_cards()
        slug_by_project = build_slug_map([c.project for c in all_cards])
        # Exact match first; fall back to case-insensitive so the URL is forgiving.
        card = db.get_card(name)
        if card is None:
            card = next(
                (c for c in all_cards if c.project.lower() == name.lower()),
                None,
            )
        if card is None:
            return TEMPLATES.TemplateResponse(
                request,
                "project.html",
                {"card": None, "missing": name},
                status_code=404,
            )
        history.initialize()
        metrics.initialize()
        events = history.history_for(card.project)
        metric_rows_oldest_first = metrics.history_for(card.project)
        metric_rows = list(reversed(metric_rows_oldest_first))  # newest-first
        slug = slug_by_project[card.project]
        badge_snippet = badge_markdown(
            f"/badge/{slug}.svg",
            f"/project/{quote(card.project, safe='')}",
            f"On-Prem Radar: {card.ring.value.upper()}",
        )
        return TEMPLATES.TemplateResponse(
            request,
            "project.html",
            {
                "card": card,
                "events": events,
                "metrics": metric_rows,
                "pedigree": _project_pedigree(card.project) or None,
                "technique_hrefs": _technique_hrefs(),
                "tenure": project_tenure(events, datetime.now(UTC)),
                "star_spark": star_sparkline(metric_rows_oldest_first),
                "badge_svg": ring_badge_svg(card.ring.value),
                "badge_snippet": badge_snippet,
            },
        )

    def _render_sources(request: Request, error: str | None, status_code: int):
        try:
            sources = load_config(config_path).sources
        except ConfigError:
            sources = []
        return TEMPLATES.TemplateResponse(
            request,
            "sources.html",
            {
                "sources": sources,
                "types": [t.value for t in SourceType],
                "categories": [c.value for c in Category],
                "error": error,
            },
            status_code=status_code,
        )

    @app.get("/sources", response_class=HTMLResponse)
    def sources(request: Request):
        return _render_sources(request, error=None, status_code=200)

    @app.get("/compare", response_class=HTMLResponse)
    def compare_page(
        request: Request, category: str = "", projects: str = ""
    ):
        db.initialize()
        cards = db.list_cards()
        all_categories = sorted({c.category.value for c in cards})
        comparison = None
        error = None
        project_list = [p.strip() for p in projects.split(",") if p.strip()] or None
        cat = None
        if category:
            try:
                cat = Category(category)
            except ValueError:
                error = f"Unknown category: {category}"
        if error is None and (cat is not None or project_list is not None):
            try:
                comparison = build_comparison(
                    cards, projects=project_list, category=cat
                )
            except ComparisonError as exc:
                error = str(exc)
        return TEMPLATES.TemplateResponse(
            request,
            "compare.html",
            {
                "comparison": comparison,
                "categories": all_categories,
                "selected_category": category,
                "error": error,
            },
        )

    @app.get("/history", response_class=HTMLResponse)
    def history_page(request: Request):
        history.initialize()
        # all_summaries(), not summaries(): a project entirely corrected away
        # must still show its raw timeline here.
        summaries = history.all_summaries()
        timelines = [
            {"summary": s, "events": history.history_for(s.project)}
            for s in sorted(summaries, key=lambda s: s.last_change_at, reverse=True)
        ]
        return TEMPLATES.TemplateResponse(
            request,
            "history.html",
            {"timelines": timelines},
        )

    @app.get("/models", response_class=HTMLResponse)
    def models_page(request: Request, profile: str = ""):
        entries = _model_entries()
        active_profile = ""
        if profile and profile != "default":
            try:
                entries = rescore_entries(entries, profile)
                active_profile = profile
            except ModelProfileError:
                pass  # unknown profile → default view, no note, no 500
        slug_by_model = build_slug_map([e.id for e in entries])
        return TEMPLATES.TemplateResponse(
            request,
            "models.html",
            {
                "models": entries,
                "slug_by_model": slug_by_model,
                "device_picker": picker_context(),
                "active_profile": active_profile,
            },
        )

    @app.get("/model/{model_id}", response_class=HTMLResponse)
    def model_detail(request: Request, model_id: str):
        from datetime import UTC, datetime

        entry = next((e for e in _model_entries() if e.id == model_id), None)
        if entry is None:
            return HTMLResponse("Model not found", status_code=404)
        model_metrics.initialize()
        badge_svg = ring_badge_svg(entry.ring.value) if entry.ring else None
        badge_snippet = (
            badge_markdown(
                f"/badge/model-{entry.id}.svg", f"/model/{entry.id}",
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
                f"/badge/fit-{entry.id}.svg", f"/model/{entry.id}",
                f"On-Prem Radar: runs on {entry.hardware_tier.value}",
            )
            if entry.hardware_tier != HardwareTier.UNKNOWN else None
        )
        return TEMPLATES.TemplateResponse(
            request,
            "model.html",
            {
                "model": entry,
                "fit_by_tier": fit_by_tier(entry),
                "datacenter_fit": datacenter_fit_rows(entry),
                "pedigree": _model_pedigree(model_id) or None,
                "technique_hrefs": _technique_hrefs(),
                "model_tenure_line": model_tenure(
                    _model_events_for(model_id), datetime.now(UTC)
                ),
                "download_spark": downloads_sparkline(model_metrics.history_for(model_id)),
                "badge_svg": badge_svg,
                "badge_snippet": badge_snippet,
                "fit_badge_svg": fit_svg,
                "fit_badge_snippet": fit_snippet,
            },
        )

    @app.get("/research", response_class=HTMLResponse)
    def research_page(request: Request):
        entries = _technique_entries()
        return TEMPLATES.TemplateResponse(
            request, "techniques.html", {"techniques": entries}
        )

    @app.get("/trending", response_class=HTMLResponse)
    def trending_page(request: Request, window: str = "7d"):
        from datetime import UTC, datetime

        days = TRENDING_WINDOWS.get(window)
        if days is None:
            window, days = "7d", TRENDING_WINDOWS["7d"]
        observations = _trending_observations()
        try:
            entries = build_trending(observations, datetime.now(UTC), window_days=days)
        except Exception as exc:
            logger.warning("Trending derivation failed for window=%s: %s", window, exc)
            entries = []
        onprem = [e for e in entries if e.lane == Lane.ONPREM]
        broader = [e for e in entries if e.lane == Lane.BROADER]
        model_hub, technique_hub = _hub_sections()
        return TEMPLATES.TemplateResponse(request, "trending.html", {
            "onprem": onprem, "broader": broader,
            "model_hub": model_hub, "technique_hub": technique_hub,
            "model_candidates": _model_candidates(),
            "technique_candidates": _technique_candidates(),
            "spark_by_repo": trending_sparklines(observations),
            "active_window": window,
            "windows": list(TRENDING_WINDOWS),
            "window_hrefs": {w: f"/trending?window={w}" for w in TRENDING_WINDOWS},
        })

    @app.get("/technique/{technique_id}", response_class=HTMLResponse)
    def technique_detail(request: Request, technique_id: str):
        entry = next((e for e in _technique_entries() if e.id == technique_id), None)
        if entry is None:
            return HTMLResponse("Technique not found", status_code=404)
        events = load_technique_events(root / "data" / "technique-history.jsonl")
        try:
            config = load_config(root / "data" / "config.yaml")
            project_by_id = {s.id: s.project for s in config.sources}
        except Exception:
            # No/invalid config → tool refs can't be resolved to a project name;
            # they stay plain text in the template.
            project_by_id = {}
        impl_hrefs: dict[str, str] = {}
        for impl in entry.resolved_implementations:
            if impl.kind == ImplKind.TOOL and impl.ref in project_by_id:
                impl_hrefs[impl.ref] = f"/project/{quote(project_by_id[impl.ref], safe='')}"
            elif impl.kind == ImplKind.MODEL:
                impl_hrefs[impl.ref] = f"/model/{impl.ref}"
        return TEMPLATES.TemplateResponse(
            request, "technique.html",
            {
                "technique": entry,
                "timeline": build_technique_timeline(entry, events),
                "impl_hrefs": impl_hrefs,
            },
        )

    @app.post("/sources")
    def add_source_route(
        request: Request,
        id: str = Form(...),
        type: str = Form(...),
        project: str = Form(...),
        category: str = Form(...),
        url: str = Form(...),
        tags: str = Form(""),
        enabled: bool = Form(True),
    ):
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        try:
            add_seed(
                config_path,
                {
                    "id": id.strip(),
                    "type": type,
                    "project": project.strip(),
                    "category": category,
                    "url": url.strip(),
                    "tags": tag_list,
                    "enabled": enabled,
                },
            )
        except SeedError as exc:
            return _render_sources(request, error=str(exc), status_code=200)
        return RedirectResponse(url="/sources", status_code=303)

    return app
