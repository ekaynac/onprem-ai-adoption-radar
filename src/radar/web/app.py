"""FastAPI dashboard app."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    PlainTextResponse,
    RedirectResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from radar.models import Category, SourceType
from radar.reports.comparison import ComparisonError, build_comparison
from radar.storage.config import ConfigError, load_config
from radar.storage.database import RadarDatabase
from radar.storage.history_store import HistoryStore
from radar.storage.metrics_store import MetricsStore
from radar.storage.run_store import RunStore
from radar.storage.seed_store import SeedError, add_seed
from radar.storage.source_health_store import SourceHealthStore
from radar.web.backer_badge import backer_badge
from radar.web.scan_health import summarize_meta
from radar.web.source_health import SourceHealth, summarize_source_health


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

    # Nav targets for the project-detail partial (live = server routes).
    live_links = {"home": "/", "compare": "/compare", "history": "/history"}

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        db.initialize()
        cards = db.list_cards()
        run_ids = run_store.list_runs()
        meta = run_store.read_meta(run_ids[-1]) if run_ids else {}
        return TEMPLATES.TemplateResponse(
            request,
            "index.html",
            {
                "cards": cards,
                "scan_health": summarize_meta(meta),
                "source_health": _source_health(),
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

    @app.get("/project/{name}", response_class=HTMLResponse)
    def project_detail(request: Request, name: str):
        db.initialize()
        # Exact match first; fall back to case-insensitive so the URL is forgiving.
        card = db.get_card(name)
        if card is None:
            card = next(
                (c for c in db.list_cards() if c.project.lower() == name.lower()),
                None,
            )
        if card is None:
            return TEMPLATES.TemplateResponse(
                request,
                "project.html",
                {"card": None, "missing": name, "links": live_links},
                status_code=404,
            )
        history.initialize()
        metrics.initialize()
        events = history.history_for(card.project)
        metric_rows = list(reversed(metrics.history_for(card.project)))  # newest-first
        return TEMPLATES.TemplateResponse(
            request,
            "project.html",
            {
                "card": card,
                "events": events,
                "metrics": metric_rows,
                "links": live_links,
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
        summaries = history.summaries()
        timelines = [
            {"summary": s, "events": history.history_for(s.project)}
            for s in sorted(summaries, key=lambda s: s.last_change_at, reverse=True)
        ]
        return TEMPLATES.TemplateResponse(
            request,
            "history.html",
            {"timelines": timelines},
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
