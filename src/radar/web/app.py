"""FastAPI dashboard app."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from radar.models import Category, SourceType
from radar.storage.config import ConfigError, load_config
from radar.storage.database import RadarDatabase
from radar.storage.seed_store import SeedError, add_seed


TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def create_app(root: Path) -> FastAPI:
    """Create a local dashboard app with read views and seed management."""
    app = FastAPI(title="Agent/Tooling Adoption Radar")
    db = RadarDatabase(root / "data" / "radar.db")
    config_path = root / "data" / "config.yaml"

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        db.initialize()
        cards = db.list_cards()
        return TEMPLATES.TemplateResponse(
            request,
            "index.html",
            {"cards": cards},
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
