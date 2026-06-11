"""FastAPI dashboard app."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from radar.storage.database import RadarDatabase


TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def create_app(root: Path) -> FastAPI:
    """Create a read-only local dashboard app."""
    app = FastAPI(title="Agent/Tooling Adoption Radar")
    db = RadarDatabase(root / "data" / "radar.db")

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        db.initialize()
        cards = db.list_cards()
        return TEMPLATES.TemplateResponse(
            request,
            "index.html",
            {"cards": cards},
        )

    return app
