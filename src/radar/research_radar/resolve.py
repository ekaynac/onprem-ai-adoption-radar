"""Resolve technique implementation links against the radar's own catalogs.

The closed loop: tool refs map source id → project (config.yaml) → the
project's latest DecisionCard ring; model refs map model id → the last ring
event in model-history.jsonl. Everything is offline. Missing stores degrade
to empty maps + a warning so a research scan works before any tool scan.
"""

from __future__ import annotations

import logging
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from radar.models import Ring
from radar.models_radar.history import load_model_events
from radar.models_radar.seed import ModelSeedError, load_model_seed
from radar.research_radar.entities import (
    ImplementationLink,
    ImplKind,
    ResolvedImplementation,
)
from radar.storage.config import load_config
from radar.storage.database import RadarDatabase


logger = logging.getLogger(__name__)


class ResolutionContext(BaseModel):
    """Current rings per known tool source id and model id (None = unringed)."""

    model_config = ConfigDict(frozen=True)

    tool_rings: dict[str, Ring | None] = Field(default_factory=dict)
    model_rings: dict[str, Ring | None] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


def build_resolution_context(
    config_path: Path,
    db_path: Path,
    model_seed_path: Path,
    model_history_path: Path,
) -> ResolutionContext:
    warnings: list[str] = []
    tool_rings = _tool_rings(config_path, db_path, warnings)
    model_rings = _model_rings(model_seed_path, model_history_path, warnings)
    return ResolutionContext(tool_rings=tool_rings, model_rings=model_rings, warnings=warnings)


def resolve_implementations(
    links: list[ImplementationLink],
    context: ResolutionContext,
) -> tuple[list[ResolvedImplementation], list[str]]:
    """(resolved links with current rings, warnings for dangling refs)."""
    resolved: list[ResolvedImplementation] = []
    warnings: list[str] = []
    for link in links:
        known = context.tool_rings if link.kind == ImplKind.TOOL else context.model_rings
        if link.ref not in known:
            warnings.append(f"implementation ref not found ({link.kind.value}): {link.ref}")
            continue
        resolved.append(ResolvedImplementation(
            kind=link.kind, ref=link.ref, ring=known[link.ref], note=link.note,
        ))
    return resolved, warnings


def _tool_rings(config_path: Path, db_path: Path, warnings: list[str]) -> dict[str, Ring | None]:
    try:
        config = load_config(config_path)
    except Exception as exc:
        warnings.append(f"tool catalog unavailable ({config_path}): {exc}")
        return {}
    ring_by_project: dict[str, Ring] = {}
    try:
        database = RadarDatabase(db_path)
        database.initialize()
        ring_by_project = {card.project: card.ring for card in database.list_cards()}
    except Exception as exc:  # cards are optional: sources still resolve as unringed
        logger.warning("Decision cards unavailable (%s): %s", db_path, exc)
    return {source.id: ring_by_project.get(source.project) for source in config.sources}


def _model_rings(
    model_seed_path: Path, model_history_path: Path, warnings: list[str],
) -> dict[str, Ring | None]:
    try:
        seeds = load_model_seed(model_seed_path)
    except ModelSeedError as exc:
        warnings.append(f"model catalog unavailable ({model_seed_path}): {exc}")
        return {}
    latest: dict[str, Ring] = {}
    for event in load_model_events(model_history_path):  # oldest-first → last wins
        latest[event.model_id] = event.ring
    return {seed.id: latest.get(seed.id) for seed in seeds}
