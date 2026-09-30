"""Radar Pulse: the ranked what's-new view (same JSON the static site ships)."""

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Request

from radar.pulse.view import build_pulse_view


router = APIRouter(tags=["pulse"])


@router.get("/pulse")
def pulse_view(request: Request) -> dict[str, Any]:
    return build_pulse_view(request.app.state.root, datetime.now(UTC))
