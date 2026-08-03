"""Bridge durable legacy radar data into the public intelligence snapshot.

The React cutover must not discard the project, enriched-model, discovery, or
source-health projections that are still produced by the proven scan pipeline.
This module is the single read-only adapter for those durable views.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field

from radar.models import DecisionCard
from radar.storage.history_store import ProjectHistoryEvent
from radar.storage.metrics_store import ProjectMetrics


_CATEGORY_BY_PIPELINE = {
    "text-generation": "text_reasoning",
    "image-text-to-text": "multimodal",
    "feature-extraction": "embedding_reranking",
    "sentence-similarity": "embedding_reranking",
    "automatic-speech-recognition": "speech_audio",
    "text-to-speech": "speech_audio",
    "text-to-image": "image_video",
    "text-to-video": "image_video",
    "image-to-text": "vision_document",
}


logger = logging.getLogger(__name__)


class _PublicProjectSource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    type: str
    url: str


class _PublicProjectRecord(DecisionCard):
    """Strict allowlist for every project field crossing the public boundary."""

    model_config = ConfigDict(extra="forbid")
    repository_url: str | None = None
    sources: list[_PublicProjectSource] = Field(default_factory=list)
    history: list[ProjectHistoryEvent] = Field(default_factory=list)
    latest_metrics: ProjectMetrics | None = None


@dataclass(frozen=True)
class PublicProjectBundle:
    projects: list[dict[str, Any]]
    mode: Literal["live_projection", "last_published_baseline", "unavailable"]
    generated_at: datetime | None


def _parse_snapshot_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _normalize_public_project(
    item: dict[str, Any],
    *,
    index: int,
    path: Path,
) -> dict[str, Any] | None:
    allowed = {
        key: item[key]
        for key in _PublicProjectRecord.model_fields
        if key in item
    }
    try:
        return _PublicProjectRecord.model_validate(allowed).model_dump(mode="json")
    except ValueError as exc:
        logger.warning(
            "Skipping invalid public project row %d in %s: %s",
            index,
            path,
            exc,
        )
        return None


def _load_snapshot_project_bundle(root: Path) -> PublicProjectBundle:
    """Load the last published project baseline from the tracked snapshot."""

    path = root / "data" / "intelligence" / "public-snapshot.v1.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        if path.exists():
            logger.warning("Skipping unreadable public project snapshot %s: %s", path, exc)
        return PublicProjectBundle([], "unavailable", None)
    if not isinstance(payload, dict):
        logger.warning("Skipping non-object public project snapshot: %s", path)
        return PublicProjectBundle([], "unavailable", None)
    projects = payload.get("projects")
    if not isinstance(projects, list):
        logger.warning("Skipping public project snapshot without a projects list: %s", path)
        return PublicProjectBundle([], "unavailable", None)

    previous_state = payload.get("project_data")
    previous_generated_at = (
        previous_state.get("generated_at")
        if isinstance(previous_state, dict)
        else None
    )
    generated_at = _parse_snapshot_time(previous_generated_at) or _parse_snapshot_time(
        payload.get("generated_at")
    )

    rows: list[dict[str, Any]] = []
    for index, item in enumerate(projects):
        if not isinstance(item, dict):
            logger.warning("Skipping invalid public project row %d in %s", index, path)
            continue
        normalized = _normalize_public_project(item, index=index, path=path)
        if normalized is not None:
            rows.append(normalized)
    return PublicProjectBundle(rows, "last_published_baseline", generated_at)


def load_latest_digest(root: Path) -> dict[str, str] | None:
    """Return the newest valid digest and only advertise an existing card."""

    from radar.storage.digest_log import load_digests

    entries = load_digests(root / "data" / "digest-log.jsonl")
    if not entries:
        return None
    latest = max(entries, key=lambda item: item.generated_at)
    parsed = urlsplit(latest.url)
    marker = "/digests/"
    if marker in parsed.path:
        html_url = f"digests/{parsed.path.split(marker, 1)[1]}"
    elif parsed.scheme:
        html_url = latest.url
    else:
        html_url = latest.url.lstrip("/")

    result = {
        "generated_at": latest.generated_at.isoformat().replace("+00:00", "Z"),
        "html_url": html_url,
    }
    for filename in ("trending_og.png", "trending_og.svg"):
        card = root / "digests" / "cards" / filename
        if card.is_file():
            result["card_url"] = f"digests/cards/{filename}"
            break
    return result


def load_public_project_bundle(root: Path) -> PublicProjectBundle:
    """Return project cards plus truthful live-or-baseline provenance."""

    database_path = root / "data" / "radar.db"
    if not database_path.exists():
        return _load_snapshot_project_bundle(root)

    from radar.storage.config import ConfigError, load_config
    from radar.storage.database import RadarDatabase
    from radar.storage.history_store import HistoryStore
    from radar.storage.metrics_store import MetricsStore

    database = RadarDatabase(database_path)
    database.initialize()
    cards = database.list_cards()
    if not cards:
        return _load_snapshot_project_bundle(root)

    source_rows: dict[str, list[dict[str, str]]] = {}
    try:
        config = load_config(root / "data" / "config.yaml")
    except ConfigError:
        config = None
    if config is not None:
        for source in config.sources:
            source_rows.setdefault(source.project, []).append(
                {
                    "id": source.id,
                    "type": source.type.value,
                    "url": str(source.url),
                }
            )

    history = HistoryStore(database_path)
    history.initialize()
    metrics = MetricsStore(database_path)
    metrics.initialize()

    rows: list[dict[str, Any]] = []
    for card in cards:
        sources = source_rows.get(card.project, [])
        repository_url = next(
            (
                source["url"]
                for source in sources
                if source["type"] == "github_repo"
            ),
            next(
                (
                    evidence
                    for evidence in card.evidence
                    if "github.com/" in evidence.casefold()
                ),
                None,
            ),
        )
        metric_rows = metrics.history_for(card.project)
        rows.append(
            {
                **card.model_dump(mode="json"),
                "repository_url": repository_url,
                "sources": sources,
                "history": [
                    item.model_dump(mode="json")
                    for item in history.history_for(card.project)[-24:]
                ],
                "latest_metrics": (
                    metric_rows[-1].model_dump(mode="json")
                    if metric_rows
                    else None
                ),
            }
        )
    normalized_rows = [
        normalized
        for index, row in enumerate(rows)
        if (
            normalized := _normalize_public_project(
                row,
                index=index,
                path=database_path,
            )
        )
        is not None
    ]
    generated_at = max((card.last_reviewed_at for card in cards), default=None)
    return PublicProjectBundle(
        sorted(
            normalized_rows,
            key=lambda item: (-float(item["score"]), item["project"]),
        ),
        "live_projection",
        generated_at,
    )


def load_public_projects(root: Path) -> list[dict[str, Any]]:
    """Return current public project records with private fields stripped."""

    return load_public_project_bundle(root).projects


def load_public_model_profiles(root: Path) -> dict[str, dict[str, Any]]:
    """Return latest enriched model cards keyed by stable legacy model id."""

    from radar.mcp_server.model_queries import _latest_model_cards
    from radar.models_radar.assemble import build_model_entry
    from radar.models_radar.seed import ModelSeedError, load_model_seed

    cards = _latest_model_cards(root)
    if not cards:
        seed_path = root / "config" / "model-seed.yaml"
        try:
            cards = []
            for seed in load_model_seed(seed_path):
                if not seed.enabled:
                    continue
                entry = build_model_entry(seed, None, [])
                warnings = list(
                    dict.fromkeys(
                        [
                            *entry.warnings,
                            "Curated seed baseline; scan enrichment is pending",
                        ]
                    )
                )
                cards.append(
                    entry.model_copy(update={"warnings": warnings}).model_dump(
                        mode="json"
                    )
                )
        except ModelSeedError:
            cards = []

    return {
        str(item["id"]): item
        for item in cards
        if item.get("id")
    }


def load_public_research_entries(root: Path) -> list[Any]:
    """Return scanned techniques, falling back to the curated seed baseline."""

    from radar.mcp_server.technique_queries import load_technique_entries
    from radar.research_radar.entities import ResolvedImplementation, TechniqueEntry
    from radar.research_radar.seed import TechniqueSeedError, load_technique_seed

    entries = load_technique_entries(root)
    if entries:
        return entries
    seed_path = root / "config" / "technique-seed.yaml"
    try:
        seeds = load_technique_seed(seed_path)
    except TechniqueSeedError:
        return []
    return [
        TechniqueEntry(
            id=seed.id,
            name=seed.name,
            category=seed.category,
            domain=seed.domain,
            aliases=seed.aliases,
            papers=seed.papers,
            resolved_implementations=[
                ResolvedImplementation(
                    kind=item.kind,
                    ref=item.ref,
                    note=item.note,
                )
                for item in seed.implementations
            ],
            open_code=seed.open_code,
            onprem_impact=seed.onprem_impact,
            superseded_by=seed.superseded_by,
            notes=seed.notes,
            warnings=["Curated seed baseline; scan enrichment is pending"],
        )
        for seed in seeds
        if seed.enabled
    ]


def load_public_model_candidates(
    root: Path,
    now: datetime,
    *,
    limit: int = 250,
) -> list[dict[str, Any]]:
    """Return current untracked HF observations with explicit trust metadata."""

    from radar.discovery.model_candidate_detect import build_model_candidates
    from radar.models_radar.seed import load_model_seed
    from radar.storage.model_candidate_log import load_model_candidates

    seed_path = root / "config" / "model-seed.yaml"
    seeded = {
        (seed.hf_repo or "").casefold()
        for seed in (load_model_seed(seed_path) if seed_path.exists() else [])
        if seed.hf_repo
    }
    entries = [
        item
        for item in build_model_candidates(
            load_model_candidates(
                root / "data" / "model-candidate-observations.jsonl"
            ),
            now,
        )
        if item.hf_repo.casefold() not in seeded and not item.is_stale
    ]
    # Keep a dedicated recency lane so a just-released, low-download artifact
    # cannot be displaced by long-established popular repositories.
    recent = sorted(
        entries,
        key=lambda item: (
            item.last_modified or item.created_at
            or item.last_observed_at or "",
            item.downloads,
        ),
        reverse=True,
    )[:150]
    momentum = sorted(
        entries,
        key=lambda item: (
            item.downloads_per_day is not None,
            item.downloads_per_day or 0,
            item.downloads,
            item.likes,
        ),
        reverse=True,
    )[:100]
    selected: dict[str, Any] = {}
    for item in [*recent, *momentum]:
        selected.setdefault(item.hf_repo.casefold(), item)

    return [
        {
            **item.model_dump(mode="json"),
            "category": _CATEGORY_BY_PIPELINE.get(
                item.pipeline_tag or "",
                "text_reasoning",
            ),
            "source_url": f"https://huggingface.co/{item.hf_repo}",
            "source_strength": "trusted_registry",
        }
        for item in list(selected.values())[:limit]
    ]


def normalize_public_platforms(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return a stable matrix shape for seeded and dynamically found platforms."""

    normalized = []
    for row in rows:
        repo_url = str(row.get("repo_url") or "")
        sources = row.get("sources")
        normalized.append(
            {
                **row,
                "hardware": row.get("hardware") or {},
                "features": row.get("features") or {},
                "sources": (
                    list(sources)
                    if isinstance(sources, list)
                    else ([repo_url] if repo_url else [])
                ),
                "notes": row.get("notes") or "",
            }
        )
    return normalized


def load_public_source_health(
    root: Path,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Project the durable source-health log into the operations contract."""

    from radar.storage.source_health_log import load_source_health

    records = load_source_health(root / "data" / "source-health.jsonl")
    if not records:
        return []
    rows: list[dict[str, Any]] = []
    source_ids = sorted(
        {
            source_id
            for record in records
            for source_id in record.sources
        }
    )
    for source_id in source_ids:
        latest_record = next(
            record for record in reversed(records) if source_id in record.sources
        )
        outcome = latest_record.sources[source_id]
        consecutive_failures = 0
        last_success_at = None
        for record in reversed(records):
            candidate = record.sources.get(source_id)
            if candidate is None:
                continue
            if candidate.status in {"ok", "empty"}:
                last_success_at = record.observed_at.isoformat()
                break
            if candidate.status == "error":
                consecutive_failures += 1
        status = outcome.status
        if (
            now is not None
            and now - latest_record.observed_at
            > timedelta(hours=6)
        ):
            status = "stale"
            consecutive_failures = max(1, consecutive_failures)
        rows.append(
            {
                "source_id": source_id,
                "last_success_at": last_success_at,
                "consecutive_failures": consecutive_failures,
                "latency_ms": None,
                "items_count": outcome.count,
                "circuit_open_until": None,
                "status": status,
                "observed_at": latest_record.observed_at.isoformat(),
            }
        )
    return rows


def profile_claims(
    profile: dict[str, Any],
    source_url: str | None,
) -> list[dict[str, Any]]:
    """Convert useful enriched-model fields into claim-shaped detail rows."""

    fields = (
        ("params_total", None),
        ("params_active", None),
        ("context_length", "tokens"),
        ("license", None),
        ("modality", None),
        ("hardware_tier", None),
        ("architecture", None),
    )
    provenance = profile.get("provenance") or {}
    claims = []
    for predicate, unit in fields:
        value = profile.get(predicate)
        if value is None:
            continue
        proof = provenance.get(predicate) or {}
        citation_url = proof.get("url") or source_url
        claims.append(
            {
                "predicate": predicate,
                "state": "verified" if proof.get("verified") else "candidate",
                "value": value,
                "unit": unit,
                "reason": (
                    "Human-verified source value"
                    if proof.get("verified")
                    else "Observed value; verification is pending"
                ),
                "observed_at": proof.get("retrieved_at"),
                "effective_range": None,
                "citations": (
                    [
                        {
                            "evidence_id": f"legacy-profile:{profile.get('id')}:{predicate}",
                            "url": citation_url,
                            "label": "Model source",
                            "strength": (
                                "official_artifact"
                                if proof.get("verified")
                                else "trusted_registry"
                            ),
                        }
                    ]
                    if citation_url
                    else []
                ),
            }
        )
    return claims
