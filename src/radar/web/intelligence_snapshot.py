"""Deterministic public intelligence snapshot."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from radar.intelligence.contracts import Release
from radar.intelligence.significance import (
    SIGNIFICANCE_RANK,
    Significance,
    compute_significance,
)


logger = logging.getLogger(__name__)

PUBLIC_RECENT_RELEASE_LIMIT = 250
MODEL_INDEX_SHARD_SIZE = 2_000
_OFFICIAL_FAMILIES = {
    "01-ai", "bigcode", "cohereforai", "deepseek-ai",
    "google", "ibm-granite", "meta-llama", "microsoft",
    "mistralai", "moonshotai", "nvidia", "openai",
    "openbmb", "qwen", "zai-org",
}
_EMPTY_LINEAGE = {
    "base_release": None,
    "relation": None,
    "root_release": None,
    "derivative_counts": None,
}
_INDEX_PREDICATES = {
    "context_length",
    "downloads",
    "hardware_tier",
    "hf_repo",
    "last_modified",
    "library_name",
    "license",
    "likes",
    "lineage_declared",
    "modality",
    "params_total",
    "pipeline_tag",
    "published_at",
    "pushed_at",
    "quantization_format",
    "release_date",
}


class SnapshotInvariantError(RuntimeError):
    """The published snapshot would violate a product guarantee."""


class PublicProjectDataState(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    mode: Literal["live_projection", "last_published_baseline", "unavailable"]
    generated_at: datetime | None = None


class ModelIndexReference(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    manifest_path: str = "data/model-index.v1.json"
    total: int


class ModelIndexShard(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    path: str
    count: int


class ModelIndexManifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["1.0"] = "1.0"
    generated_at: datetime
    total: int
    shard_size: int
    shards: list[ModelIndexShard]


class PublicSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["1.0"] = "1.0"
    generated_at: datetime
    releases: list[dict[str, Any]]
    models: list[dict[str, Any]]
    projects: list[dict[str, Any]]
    model_candidates: list[dict[str, Any]]
    platforms: list[dict[str, Any]]
    hardware: list[dict[str, Any]]
    research: list[dict[str, Any]]
    events: list[dict[str, Any]]
    source_health: dict[str, Any]
    project_data: PublicProjectDataState
    model_index: ModelIndexReference
    quality: dict[str, Any]
    source_coverage: list[dict[str, Any]]
    latest_digest: dict[str, str] | None = None
    briefing: dict[str, Any] | None = None
    planner: dict[str, Any] | None = None
    trending: dict[str, Any] | None = None
    advisor: dict[str, Any] | None = None
    desk: dict[str, Any] | None = None
    newsroom: dict[str, Any] | None = None
    stack_demo: dict[str, Any] | None = None


def _release_sort_key(
    release: Release,
    metadata: dict[str, dict[str, Any]] | None = None,
) -> tuple[float, str]:
    values = (metadata or {}).get(release.id, {})
    released_at = datetime.fromisoformat(
        _released_at(values, release.first_observed_at).replace("Z", "+00:00")
    )
    return (-released_at.timestamp(), release.id)


def _select_public_releases(
    releases: Sequence[Release],
    *,
    recent_limit: int = PUBLIC_RECENT_RELEASE_LIMIT,
    metadata: dict[str, dict[str, Any]] | None = None,
) -> list[Release]:
    legacy = [release for release in releases if release.id.startswith("release:legacy:")]
    recent = sorted(
        (
            release
            for release in releases
            if not release.id.startswith("release:legacy:")
        ),
        key=lambda release: _release_sort_key(release, metadata),
    )[:recent_limit]
    return sorted(
        [*legacy, *recent],
        key=lambda release: _release_sort_key(release, metadata),
    )


class _LineageContext:
    """Lineage edges reshaped for row building: parents, roots, and counts."""

    def __init__(self) -> None:
        self.parent_by_child: dict[str, dict[str, Any]] = {}
        self.children_count: dict[str, int] = {}
        self.derivative_counts: dict[str, dict[str, int]] = {}

    @classmethod
    def load(cls, repository: Any) -> _LineageContext:
        context = cls()
        lister = getattr(repository, "list_all_lineage_edges", None)
        if lister is None:
            return context
        by_child: dict[str, list[Any]] = {}
        for edge in lister():
            by_child.setdefault(edge.child_release_id, []).append(edge)
        from radar.intelligence.lineage import AUTO_ACCEPT_CONFIDENCE

        for child_id, edges in by_child.items():
            accepted = [
                edge
                for edge in edges
                if edge.confidence >= AUTO_ACCEPT_CONFIDENCE
            ]
            primary = max(
                accepted or edges,
                key=lambda edge: (
                    edge.confidence,
                    edge.parent_release_id or "",
                    edge.id,
                ),
            )
            context.parent_by_child[child_id] = {
                "base_release": primary.parent_release_id,
                "relation": primary.relation.value,
                "root_release": primary.root_release_id,
                # Tier-3 name fingerprints surface as suggestions, never
                # as confirmed ancestry.
                "inferred": primary.confidence < AUTO_ACCEPT_CONFIDENCE,
            }
            for edge in accepted:
                if edge.parent_release_id is not None:
                    context.children_count[edge.parent_release_id] = (
                        context.children_count.get(edge.parent_release_id, 0)
                        + 1
                    )
                group_id = edge.root_release_id or edge.parent_release_id
                if group_id is None:
                    continue
                counts = context.derivative_counts.setdefault(group_id, {})
                counts[edge.relation.value] = (
                    counts.get(edge.relation.value, 0) + 1
                )
        return context

    def fields(
        self,
        release_id: str,
        metadata: dict[str, Any],
    ) -> tuple[dict[str, Any], bool | None, bool]:
        """Return (lineage row payload, is_root, has_declared_parent)."""
        declared = metadata.get("lineage_declared")
        checked_base = declared == []
        primary = self.parent_by_child.get(release_id)
        children = self.children_count.get(release_id, 0)
        derivative_counts = self.derivative_counts.get(release_id)
        if primary is not None:
            lineage = {
                **primary,
                "derivative_counts": derivative_counts,
            }
            return lineage, False, True
        is_root = True if checked_base or children > 0 else None
        lineage = {
            "base_release": None,
            "relation": None,
            "root_release": release_id if is_root else None,
            "derivative_counts": derivative_counts,
        }
        return lineage, is_root, bool(declared)


def _int_or_none(value: Any) -> int | None:
    return value if isinstance(value, int) else None


def _parse_released_at(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _release_significance(
    release: Release,
    metadata: dict[str, Any],
    lineage_context: _LineageContext,
    now: datetime,
) -> tuple[dict[str, Any], Significance]:
    lineage, is_root, has_declared_parent = lineage_context.fields(
        release.id,
        metadata,
    )
    significance = compute_significance(
        official=not release.publisher_id.startswith("publisher:provisional:"),
        lifecycle=release.lifecycle.value,
        curated=release.id.startswith("release:legacy:"),
        is_root=is_root,
        has_declared_parent=has_declared_parent,
        released_at=_parse_released_at(
            _released_at(metadata, release.first_observed_at)
        ),
        now=now,
        downloads=_int_or_none(metadata.get("downloads")),
        likes=_int_or_none(metadata.get("likes")),
        children_count=lineage_context.children_count.get(release.id, 0),
        has_params=metadata.get("params_total") is not None,
        has_context=metadata.get("context_length") is not None,
        has_license=metadata.get("license") is not None,
    )
    return lineage, significance


_PLANNER_DEVICES = (
    "rtx-4090-24gb",
    "rtx-5090-32gb",
    "mac-64gb",
    "mac-128gb",
    "rtx-6000-ada-48gb",
    "a100-80gb",
    "h100-80gb",
    "h200-141gb",
    "b200-192gb",
    "8x-h100-80gb",
    "hgx-h200-8",
    "mi300x-192gb",
    # Vendor systems (H1): selectable platforms, not just bare chips.
    "dgx-spark",
    "dgx-station-gb300",
    "dell-xe9680-h200",
    "framework-desktop-395-128gb",
    "jetson-thor-t5000-128gb",
)
_PLANNER_CONTEXT_TOKENS = 4096


def _build_planner(root: Path) -> dict[str, Any] | None:
    """Precompute the curated-model × device fit grid for the static site.

    Every verdict comes from the same deterministic fit engine the CLI and
    MCP use — the static planner is a projection of it, never a re-implementation.
    """
    try:
        from radar.mcp_server.model_queries import ModelQueryService

        service = ModelQueryService(root)
        fits: list[dict[str, Any]] = []
        for device in _PLANNER_DEVICES:
            for fit in service.device_fit_report(
                device,
                _PLANNER_CONTEXT_TOKENS,
            ):
                fits.append({"device": device, **fit})
    except Exception as exc:  # planner data is additive, never fatal to publish
        logger.warning("Snapshot: planner section skipped: %s", exc)
        return None
    if not fits:
        return None
    return {
        "devices": list(_PLANNER_DEVICES),
        "context_tokens": _PLANNER_CONTEXT_TOKENS,
        "fits": fits,
    }


_TRENDING_ROWS_PER_WINDOW = 60
_TRENDING_SPARKLINE_DAYS = 14


def _build_trending_section(
    root: Path,
    generated_at: datetime,
) -> dict[str, Any] | None:
    """Trending repos across 7/30/90-day windows with 14-day star series.

    Derived from the append-only observation store via the same pure
    builders the MCP tools use; absent or corrupt data degrades to None.
    """
    try:
        from datetime import timedelta

        from radar.discovery.trending_detect import (
            TRENDING_WINDOWS,
            build_trending,
        )
        from radar.storage.trending_observations_log import load_observations

        observations = load_observations(
            root / "data" / "trending-observations.jsonl"
        )
        if not observations:
            return None
        windows: dict[str, list[dict[str, Any]]] = {}
        shown_repos: set[str] = set()
        for label, days in TRENDING_WINDOWS.items():
            entries = build_trending(
                observations,
                generated_at,
                window_days=days,
            )[:_TRENDING_ROWS_PER_WINDOW]
            windows[label] = [
                {
                    "repo": entry.repo,
                    "lane": entry.lane.value,
                    "stars": entry.stars,
                    "velocity_per_day": entry.velocity_per_day,
                    "is_new": entry.is_new,
                    "first_seen": entry.first_seen,
                    "description": entry.description,
                    "topics": entry.topics[:6],
                    "license": entry.license,
                    "url": f"https://github.com/{entry.repo}",
                }
                for entry in entries
            ]
            shown_repos.update(entry.repo for entry in entries)
        cutoff = generated_at - timedelta(days=_TRENDING_SPARKLINE_DAYS)
        series: dict[str, list[dict[str, Any]]] = {}
        for observation in sorted(
            observations,
            key=lambda item: item.observed_at,
        ):
            if (
                observation.repo not in shown_repos
                or observation.observed_at < cutoff
            ):
                continue
            series.setdefault(observation.repo, []).append(
                {
                    "observed_at": observation.observed_at.isoformat(),
                    "stars": observation.stars,
                }
            )
        return {
            "windows": windows,
            "series": series,
            "sparkline_days": _TRENDING_SPARKLINE_DAYS,
        }
    except Exception as exc:  # trending is additive, never fatal to publish
        logger.warning("Snapshot: trending section skipped: %s", exc)
        return None


def _build_desk(root: Path) -> dict[str, Any] | None:
    """Latest brief + folded calls ledger + the public track record."""
    try:
        from radar.storage.calls_ledger import (
            fold_calls,
            load_call_records,
            track_record,
        )

        briefs_dir = root / "data" / "briefs"
        brief: dict[str, Any] | None = None
        if briefs_dir.exists():
            latest = sorted(briefs_dir.glob("brief-*.json"))
            if latest:
                brief = json.loads(latest[-1].read_text(encoding="utf-8"))
        states = fold_calls(
            load_call_records(root / "data" / "calls-ledger.jsonl")
        )
        if brief is None and not states:
            return None
        return {
            "brief": brief,
            "calls": [state.model_dump(mode="json") for state in states[:25]],
            "track_record": track_record(states),
        }
    except Exception as exc:  # the desk is additive, never fatal to publish
        logger.warning("Snapshot: desk section skipped: %s", exc)
        return None


def _build_stack_demo(
    root: Path, generated_at: datetime
) -> dict[str, Any] | None:
    """The public demo profile + its computed alert feed.

    Static mode has no workspaces; this reference profile demonstrates
    the alert mechanism (events diffed against a stack) on real data.
    """
    try:
        from radar.intelligence.alerts import build_alerts, load_demo_profile
        from radar.notify.alert_delivery import annotate_delivery_state

        config_path = root / "config" / "stack-profile-demo.yaml"
        if not config_path.exists():
            config_path = (
                Path(__file__).resolve().parents[3]
                / "config"
                / "stack-profile-demo.yaml"
            )
        profile = load_demo_profile(config_path)
        return {
            "profile": {
                "name": profile.name,
                "devices": [
                    device.model_dump(mode="json")
                    for device in profile.devices
                ],
                "stack": profile.stack.model_dump(mode="json"),
            },
            "alerts": annotate_delivery_state(
                build_alerts(
                    root,
                    devices=profile.devices,
                    stack=profile.stack,
                    now=generated_at,
                ),
                root,
                profile.name,
            ),
        }
    except Exception as exc:  # the demo profile is additive, never fatal
        logger.warning("Snapshot: stack-demo section skipped: %s", exc)
        return None


_NEWSROOM_ITEM_LIMIT = 80


def _build_newsroom(root: Path) -> dict[str, Any] | None:
    """Classified change intelligence + the raw firehose, newest first.

    Only schema-validated classifications reach the section; items the
    classifier judged irrelevant (or hasn't reached yet) surface solely
    in the ``unclassified``/firehose sense via ``classification: null``.
    """
    try:
        from radar.storage.news_log import (
            NEWS_EVENT_TYPES,
            load_news_classifications,
            load_news_items,
        )

        items = load_news_items(root / "data" / "news-observations.jsonl")
        if not items:
            return None
        classifications = {
            row.news_id: row
            for row in load_news_classifications(
                root / "data" / "news-classified.jsonl"
            )
        }
        items.sort(
            key=lambda item: (item.published_at or item.observed_at),
            reverse=True,
        )
        rows: list[dict[str, Any]] = []
        impact_counts = {"breaking": 0, "improvement": 0, "informational": 0}
        classified = 0
        for item in items[:_NEWSROOM_ITEM_LIMIT]:
            classification = classifications.get(item.id)
            payload: dict[str, Any] | None = None
            if classification is not None and classification.relevant:
                classified += 1
                impact_counts[classification.operational_impact] += 1
                payload = {
                    "event_type": classification.event_type,
                    "components": classification.components,
                    "operational_impact": classification.operational_impact,
                    "summary": classification.summary,
                    "citation": classification.citation,
                    "model": classification.model,
                }
            rows.append(
                {
                    "id": item.id,
                    "source_id": item.source_id,
                    "title": item.title,
                    "url": item.url,
                    "summary": item.summary,
                    "published_at": (
                        item.published_at.isoformat()
                        if item.published_at
                        else None
                    ),
                    "classification": payload,
                }
            )
        return {
            "items": rows,
            "counts": {
                "total": len(rows),
                "classified": classified,
                "unclassified": len(rows) - classified,
                **impact_counts,
            },
            "event_types": list(NEWS_EVENT_TYPES),
        }
    except Exception as exc:  # the newsroom is additive, never fatal to publish
        logger.warning("Snapshot: newsroom section skipped: %s", exc)
        return None


def _build_advisor(profiles: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    """Precompute Answer Machine shortlists for every task × device preset.

    Policy filters (license allowlist, min context) apply client-side over
    these unpoliced answers — candidates carry license and context so the
    UI can gate them visibly. Live mode recomputes with arbitrary inputs
    via the API; both paths run the same ``build_answers``.
    """
    if not profiles:
        return None
    try:
        from radar.models_radar.advisor import TASKS, build_answers

        answers: dict[str, dict[str, Any]] = {}
        for task in TASKS:
            for device in _PLANNER_DEVICES:
                answers[f"{task}|{device}"] = build_answers(
                    profiles,
                    device,
                    task,
                )
        return {
            "tasks": {
                task: {"label": spec["label"]} for task, spec in TASKS.items()
            },
            "devices": list(_PLANNER_DEVICES),
            "answers": answers,
        }
    except Exception as exc:  # advisor is additive, never fatal to publish
        logger.warning("Snapshot: advisor section skipped: %s", exc)
        return None


_MOVER_WINDOW_DAYS = 14
_MOVER_LIMIT = 8
_TRY_THIS_WEEK_LIMIT = 6


def _build_briefing(
    projects: list[dict[str, Any]],
    model_rows: list[dict[str, Any]],
    generated_at: datetime,
    root: Path | None,
) -> dict[str, Any]:
    """The architect's morning brief: rings, picks, and recent moves."""
    project_rings: dict[str, int] = {}
    for row in projects:
        ring = row.get("ring")
        if isinstance(ring, str):
            project_rings[ring] = project_rings.get(ring, 0) + 1
    model_rings: dict[str, int] = {}
    curated_models = 0
    for row in model_rows:
        if not str(row.get("release_id", "")).startswith("release:legacy:"):
            continue
        curated_models += 1
        ring = row.get("public_ring")
        if isinstance(ring, str):
            model_rings[ring] = model_rings.get(ring, 0) + 1

    def _score(row: dict[str, Any]) -> float:
        value = row.get("score")
        return float(value) if isinstance(value, int | float) else 0.0

    try_this_week = [
        {
            "project": row.get("project"),
            "category": row.get("category"),
            "ring": row.get("ring"),
            "backer": row.get("backer"),
            "trend": row.get("trend"),
            "risk_level": row.get("risk_level"),
            "score": row.get("score"),
            "note": row.get("try_this_week"),
            "evidence_notes": list(row.get("evidence_notes") or [])[:2],
        }
        for row in sorted(projects, key=_score, reverse=True)
        if row.get("ring") in {"adopt", "pilot"}
    ][:_TRY_THIS_WEEK_LIMIT]

    cutoff = generated_at.timestamp() - _MOVER_WINDOW_DAYS * 86_400
    movers: list[dict[str, Any]] = []

    def _mover(
        subject: Any,
        kind: str,
        event: dict[str, Any],
    ) -> None:
        change_type = event.get("change_type")
        observed_at = _parse_released_at(event.get("observed_at"))
        if (
            change_type not in {"new", "promoted", "demoted"}
            or observed_at is None
            or observed_at.timestamp() < cutoff
        ):
            return
        ring = event.get("ring")
        previous = event.get("previous_ring")
        arrow = f"{previous} → {ring}" if previous else f"new → {ring}"
        movers.append(
            {
                "subject": subject,
                "kind": kind,
                "change_type": change_type,
                "ring": ring,
                "previous_ring": previous,
                "observed_at": event.get("observed_at"),
                "line": f"{subject}: {arrow} ({change_type})",
            }
        )

    for row in projects:
        for event in row.get("history") or []:
            if isinstance(event, dict):
                _mover(row.get("project"), "project", event)
    if root is not None:
        from radar.models_radar.history import load_model_events

        for model_event in load_model_events(
            root / "data" / "model-history.jsonl"
        ):
            _mover(
                model_event.model_id,
                "model",
                model_event.model_dump(mode="json"),
            )
    movers.sort(
        key=lambda item: (str(item.get("observed_at") or ""), str(item["subject"])),
        reverse=True,
    )

    return {
        "rings": {
            "projects": {
                "tracked": len(projects),
                **{key: project_rings[key] for key in sorted(project_rings)},
            },
            "models": {
                "tracked": curated_models,
                **{key: model_rings[key] for key in sorted(model_rings)},
            },
        },
        "try_this_week": try_this_week,
        "movers": movers[:_MOVER_LIMIT],
    }


def _model_row_order(row: dict[str, Any]) -> tuple[int, float, str, str]:
    """Significance class, then score, then recency, then stable id.

    Repository modification time is a freshness display value, not the
    definition of importance — a recently touched clone must not outrank
    the official upstream release.
    """
    significance = row.get("significance") or {}
    rank = significance.get("rank")
    score = significance.get("score")
    return (
        rank if isinstance(rank, int) else len(SIGNIFICANCE_RANK),
        -(score if isinstance(score, int | float) else 0.0),
        # Newest first within equal rank+score (ISO strings compare safely).
        _inverted_text(
            str(row.get("released_at") or row.get("first_observed_at") or "")
        ),
        str(row.get("release_id") or ""),
    )


def _inverted_text(value: str) -> str:
    """Map a string so ascending sort yields descending original order."""
    return "".join(chr(0x10FFFF - ord(character)) for character in value)


def _claim_metadata(repository: Any, releases: Sequence[Release]) -> dict[str, dict[str, Any]]:
    method = getattr(repository, "latest_claim_values", None)
    if method is None:
        return {}
    return method([release.id for release in releases], _INDEX_PREDICATES)


def _released_at(values: dict[str, Any], fallback: datetime | str) -> str:
    value = next(
        (
            values[predicate]
            for predicate in (
                "last_modified",
                "published_at",
                "pushed_at",
                "release_date",
            )
            if values.get(predicate)
        ),
        fallback,
    )
    if isinstance(value, datetime):
        return value.isoformat()
    text = str(value)
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return str(fallback)
    return text


def _confidence(values: dict[str, Any], *, official_publisher: bool) -> float:
    score = 0.35
    score += 0.15 if official_publisher else 0.0
    score += 0.10 if _released_at(values, "") else 0.0
    score += 0.10 if values.get("license") else 0.0
    score += 0.10 if values.get("pipeline_tag") or values.get("modality") else 0.0
    score += 0.10 if int(values.get("downloads") or 0) >= 100 else 0.0
    score += 0.05 if int(values.get("likes") or 0) >= 10 else 0.0
    score += 0.05 if values.get("params_total") or values.get("library_name") else 0.0
    return round(min(score, 0.99), 2)


def _quality_metrics(
    models: list[dict[str, Any]],
    hardware: list[dict[str, Any]],
    projects: list[dict[str, Any]],
    research: list[dict[str, Any]],
) -> dict[str, Any]:
    profiles = [item.get("profile") or {} for item in models]
    return {
        "models": {
            "total": len(models),
            "verified_or_better": sum(
                item.get("lifecycle") != "detected" for item in models
            ),
            "with_license": sum(bool(profile.get("license")) for profile in profiles),
            "with_parameters": sum(
                profile.get("params_total") is not None for profile in profiles
            ),
            "with_context": sum(
                profile.get("context_length") is not None for profile in profiles
            ),
            "with_hardware_tier": sum(
                bool(profile.get("hardware_tier")) for profile in profiles
            ),
            "with_ring": sum(
                bool(item.get("public_ring")) for item in models
            ),
            "with_benchmarks": sum(
                bool(
                    profile.get("benchmark_aggregates")
                    or profile.get("benchmarks")
                )
                for profile in profiles
            ),
            "with_independent_benchmarks": sum(
                any(
                    any(
                        not score.get("self_reported")
                        for score in aggregate.get("scores", [])
                    )
                    for aggregate in profile.get("benchmark_aggregates") or []
                )
                for profile in profiles
            ),
            "decision_complete": sum(
                bool(item.get("public_ring"))
                and profile.get("params_total") is not None
                and profile.get("context_length") is not None
                and bool(profile.get("license"))
                for item, profile in zip(models, profiles, strict=True)
            ),
        },
        "lineage": {
            "with_resolved_root": sum(
                bool((item.get("lineage") or {}).get("root_release"))
                for item in models
            ),
            "derivatives": sum(
                bool((item.get("lineage") or {}).get("relation"))
                for item in models
            ),
            "roots_with_derivatives": sum(
                bool((item.get("lineage") or {}).get("derivative_counts"))
                and not (item.get("lineage") or {}).get("relation")
                for item in models
            ),
        },
        "hardware": {
            "total": len(hardware),
            "with_spec_url": sum(bool(item.get("spec_url")) for item in hardware),
            "with_bandwidth": sum(
                item.get("memory_bandwidth_gbs") is not None for item in hardware
            ),
            "with_power": sum(item.get("tdp_watts") is not None for item in hardware),
            "with_interconnect": sum(bool(item.get("interconnect")) for item in hardware),
        },
        "projects": {
            "total": len(projects),
            "with_repository": sum(bool(item.get("repository_url")) for item in projects),
            "with_evidence": sum(bool(item.get("evidence")) for item in projects),
        },
        "research": {
            "total": len(research),
            "with_papers": sum(bool(item.get("papers")) for item in research),
            "with_implementations": sum(
                bool(item.get("resolved_implementations")) for item in research
            ),
        },
    }


def _source_coverage(root: Path | None) -> list[dict[str, Any]]:
    if root is None:
        return []
    path = root / "config" / "intelligence-sources.yaml"
    if not path.exists():
        return []
    import yaml

    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [
        {
            "id": str(source.get("id") or ""),
            "type": str(source.get("type") or ""),
            "enabled": bool(source.get("enabled")),
            "status": (
                "active"
                if source.get("enabled")
                else "disabled_pending_contract_verification"
            ),
        }
        for source in payload.get("sources") or []
        if isinstance(source, dict)
    ]


def build_public_snapshot(
    services,
    generated_at: datetime,
    *,
    root: Path | None = None,
    canonical_releases: Sequence[Release] | None = None,
) -> PublicSnapshot:
    repository = services.catalog.repository
    all_releases = list(
        canonical_releases
        if canonical_releases is not None
        else repository.list_all_releases()
    )
    all_release_metadata = _claim_metadata(repository, all_releases)
    lineage_context = _LineageContext.load(repository)
    public_releases = _select_public_releases(
        all_releases,
        metadata=all_release_metadata,
    )
    release_metadata = {
        release.id: all_release_metadata.get(release.id, {})
        for release in public_releases
    }
    releases = [
        services.releases.get(release.id, now=generated_at)
        for release in public_releases
    ]
    models = [
        services.catalog.get(release.id)
        for release in public_releases
    ]
    from radar.models_radar.devices import (
        CLUSTER_PRESETS,
        DEVICE_PRESETS,
        NODE_PRESETS,
    )

    hardware = [
        {
            "id": device_id,
            **profile.model_dump(mode="json"),
            "aggregate_memory_gb": profile.total_memory_gb * profile.gpu_count,
        }
        for device_id, profile in sorted(
            {
                **DEVICE_PRESETS,
                **NODE_PRESETS,
                **CLUSTER_PRESETS,
            }.items()
        )
    ]
    research: list[dict[str, Any]] = []
    projects: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    profiles: dict[str, dict[str, Any]] = {}
    legacy_source_health: list[dict[str, Any]] = []
    latest_digest: dict[str, str] | None = None
    project_data = PublicProjectDataState(mode="unavailable")
    if root is not None:
        from radar.web.public_context import (
            load_latest_digest,
            load_public_model_candidates,
            load_public_model_profiles,
            load_public_project_bundle,
            load_public_research_entries,
            load_public_source_health,
        )

        research = [
            item.model_dump(mode="json")
            for item in load_public_research_entries(root)
        ]
        project_bundle = load_public_project_bundle(root)
        projects = project_bundle.projects
        project_data = PublicProjectDataState(
            mode=project_bundle.mode,
            generated_at=project_bundle.generated_at,
        )
        profiles = load_public_model_profiles(root)
        candidates = load_public_model_candidates(root, generated_at)
        legacy_source_health = load_public_source_health(root, generated_at)
        latest_digest = load_latest_digest(root)
    operations = services.operations.snapshot()
    release_rows = [item.model_dump(mode="json") for item in releases]
    release_by_id = {release.id: release for release in public_releases}
    for row in release_rows:
        release_id = str(row.get("release_id") or "")
        release = release_by_id.get(release_id)
        if release is None:
            continue
        metadata = release_metadata.get(release_id, {})
        row["released_at"] = _released_at(metadata, release.first_observed_at)
        row["confidence"] = _confidence(
            metadata,
            official_publisher=not release.publisher_id.startswith(
                "publisher:provisional:"
            ),
        )
        lineage, significance = _release_significance(
            release,
            metadata,
            lineage_context,
            generated_at,
        )
        row["lineage"] = lineage
        row["is_official"] = not release.publisher_id.startswith(
            "publisher:provisional:"
        )
        row["significance"] = significance.as_dict()
    model_rows = []
    from radar.web.public_context import normalize_public_platforms, profile_claims

    for item in models:
        metadata = release_metadata.get(item.release_id, {})
        legacy_id = item.release_id.removeprefix("release:legacy:")
        profile = profiles.get(legacy_id)
        source_url = (
            f"https://huggingface.co/{profile['hf_repo']}"
            if profile and profile.get("hf_repo")
            else None
        )
        lineage, significance = _release_significance(
            release_by_id[item.release_id],
            metadata,
            lineage_context,
            generated_at,
        )
        model_rows.append(
            {
                "lineage": lineage,
                "is_official": not release_by_id[
                    item.release_id
                ].publisher_id.startswith("publisher:provisional:"),
                "significance": significance.as_dict(),
                "release_id": item.release_id,
                "name": item.name,
                "category": item.category.value,
                "lane": item.lane,
                "lifecycle": item.lifecycle.value,
                "first_observed_at": item.first_observed_at,
                "released_at": _released_at(metadata, item.first_observed_at),
                "confidence": _confidence(
                    metadata,
                    official_publisher=not release_by_id[
                        item.release_id
                    ].publisher_id.startswith("publisher:provisional:"),
                ),
                "public_ring": (
                    item.public_recommendation.ring.value
                    if item.public_recommendation.ring
                    else None
                ),
                "reasons": item.public_recommendation.reasons,
                "evidence_ids": item.public_recommendation.evidence_ids,
                "source_url": source_url,
                "source_strength": "trusted_registry",
                "profile": profile,
                "claims": profile_claims(profile, source_url) if profile else [],
            }
        )
    for candidate in candidates:
        release_id = f"release:hf:{candidate['hf_repo'].casefold()}"
        released_at = _released_at(
            candidate,
            candidate["first_observed_at"],
        )
        age_hours = max(
            0.0,
            (
                generated_at
                - datetime.fromisoformat(released_at)
            ).total_seconds()
            / 3600,
        )
        observation_age_hours = max(
            0.0,
            (
                generated_at
                - datetime.fromisoformat(candidate["last_observed_at"])
            ).total_seconds()
            / 3600,
        )
        citation = {
            "evidence_id": f"evidence:hf:{candidate['hf_repo'].casefold()}",
            "retrieved_at": candidate["last_observed_at"],
            "strength": "trusted_registry",
            "url": candidate["source_url"],
        }
        freshness = "fresh" if observation_age_hours <= 2 else "stale"
        official_family = (
            str(candidate.get("family") or "").casefold() in _OFFICIAL_FAMILIES
        )
        candidate_significance = compute_significance(
            official=official_family,
            lifecycle="detected",
            is_root=None,
            released_at=_parse_released_at(released_at),
            now=generated_at,
            downloads=_int_or_none(candidate.get("downloads")),
            likes=_int_or_none(candidate.get("likes")),
        )
        release_rows.append(
            {
                "release_id": release_id,
                "name": candidate["name"],
                "category": candidate["category"],
                "lane": "onprem_adjacent",
                "lifecycle": "detected",
                "first_observed_at": candidate["first_observed_at"],
                "released_at": released_at,
                "age_hours": age_hours,
                "freshness": freshness,
                "confidence": _confidence(
                    candidate,
                    official_publisher=official_family,
                ),
                "review_status": "clear",
                "citations": [citation],
                "lineage": dict(_EMPTY_LINEAGE),
                "is_official": official_family,
                "significance": candidate_significance.as_dict(),
            }
        )
        profile = {
            "id": release_id,
            "hf_repo": candidate["hf_repo"],
            "family": candidate["family"],
            "modality": candidate["pipeline_tag"],
            "hf_downloads": candidate["downloads"],
            "hf_likes": candidate["likes"],
            "created_at": candidate["created_at"],
            "last_modified": candidate["last_modified"],
        }
        model_rows.append(
            {
                "release_id": release_id,
                "name": candidate["name"],
                "category": candidate["category"],
                "lane": "onprem_adjacent",
                "lifecycle": "detected",
                "first_observed_at": candidate["first_observed_at"],
                "released_at": released_at,
                "lineage": dict(_EMPTY_LINEAGE),
                "is_official": official_family,
                "significance": candidate_significance.as_dict(),
                "public_ring": None,
                "reasons": [
                    "Detected from Hugging Face; verification and qualification are pending"
                ],
                "evidence_ids": [citation["evidence_id"]],
                "source_url": candidate["source_url"],
                "source_strength": "trusted_registry",
                "profile": profile,
                "claims": [
                    {
                        "predicate": predicate,
                        "state": "candidate",
                        "value": value,
                        "unit": None,
                        "reason": "Trusted-registry observation; verification is pending",
                        "observed_at": candidate["last_observed_at"],
                        "effective_range": None,
                        "citations": [
                            {
                                **citation,
                                "label": "Hugging Face model",
                            }
                        ],
                    }
                    for predicate, value in (
                        ("hf_repo", candidate["hf_repo"]),
                        ("pipeline_tag", candidate["pipeline_tag"]),
                        ("downloads", candidate["downloads"]),
                        ("likes", candidate["likes"]),
                        ("last_modified", candidate["last_modified"]),
                    )
                    if value is not None
                ],
            }
        )
    release_rows.sort(
        key=lambda item: (
            str(item.get("released_at") or item.get("first_observed_at") or ""),
            float(item.get("confidence") or 0),
        ),
        reverse=True,
    )
    model_rows.sort(key=_model_row_order)
    # Product guarantee: every curated model whose legacy pipeline computed
    # a ring shows that ring publicly. A missing bridge is a build error,
    # never a silently ringless catalog.
    ringless_curated = [
        row["release_id"]
        for row in model_rows
        if str(row.get("release_id", "")).startswith("release:legacy:")
        and isinstance(
            (
                profiles.get(
                    str(row["release_id"]).removeprefix("release:legacy:")
                )
                or {}
            ).get("ring"),
            str,
        )
        and not row.get("public_ring")
    ]
    if ringless_curated:
        raise SnapshotInvariantError(
            "Curated models lost their ring in the public snapshot: "
            + ", ".join(sorted(ringless_curated)[:5])
            + (
                f" (+{len(ringless_curated) - 5} more)"
                if len(ringless_curated) > 5
                else ""
            )
        )
    operation_payload = operations.model_dump(mode="json")
    canonical_health = operation_payload.get("source_health") or []
    health_by_id = {
        item["source_id"]: item
        for item in [*legacy_source_health, *canonical_health]
    }
    operation_payload["source_health"] = list(health_by_id.values())
    platform_rows = normalize_public_platforms(repository.list_platforms())
    expired_platform_claims = 0
    for platform in platform_rows:
        source_id = f"platform:{str(platform['id']).removeprefix('platform:legacy:')}"
        health = health_by_id.get(source_id)
        if health is not None:
            platform["checked_at"] = health.get("observed_at")
            platform["verification_status"] = health.get("status")
            if health.get("status") != "ok":
                expired_platform_claims += len(platform["hardware"]) + len(
                    platform["features"]
                )
        else:
            platform["verification_status"] = "stale"
            expired_platform_claims += len(platform["hardware"]) + len(
                platform["features"]
            )
    operation_payload["stale_claim_count"] = (
        int(operation_payload.get("stale_claim_count") or 0)
        + expired_platform_claims
    )
    return PublicSnapshot(
        generated_at=generated_at,
        releases=release_rows,
        models=model_rows,
        projects=projects,
        model_candidates=candidates,
        platforms=platform_rows,
        hardware=hardware,
        research=research,
        events=[
            {
                "schema_version": event.schema_version,
                "id": event.id,
                "type": event.type,
                "occurred_at": event.occurred_at,
                "subject_id": event.subject_id,
                "data": event.data,
                "evidence_ids": event.evidence_ids,
            }
            for event in repository.list_events(limit=500, public_only=True)
        ],
        source_health=operation_payload,
        project_data=project_data,
        model_index=ModelIndexReference(total=len(all_releases)),
        quality=_quality_metrics(model_rows, hardware, projects, research),
        source_coverage=_source_coverage(root),
        latest_digest=latest_digest,
        briefing=_build_briefing(projects, model_rows, generated_at, root),
        planner=_build_planner(root) if root is not None else None,
        trending=(
            _build_trending_section(root, generated_at)
            if root is not None
            else None
        ),
        advisor=_build_advisor(profiles),
        desk=_build_desk(root) if root is not None else None,
        newsroom=_build_newsroom(root) if root is not None else None,
        stack_demo=(
            _build_stack_demo(root, generated_at)
            if root is not None
            else None
        ),
    )


def write_public_snapshot(snapshot: PublicSnapshot, site_root: Path) -> Path:
    destination = site_root / "data" / "public-snapshot.v1.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(
            snapshot.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    return destination


def _compact_model_row(
    release: Release,
    metadata: dict[str, Any] | None = None,
    *,
    lineage_context: _LineageContext | None = None,
    now: datetime | None = None,
    legacy_rings: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    bridged = (legacy_rings or {}).get(release.id)
    metadata = metadata or {}
    hf_repo = metadata.get("hf_repo")
    source_url = f"https://huggingface.co/{hf_repo}" if hf_repo else None
    if source_url is None and release.id.startswith("release:hf:"):
        source_url = f"https://huggingface.co/{release.id.removeprefix('release:hf:')}"
    lineage = dict(_EMPTY_LINEAGE)
    significance_payload: dict[str, Any] | None = None
    if lineage_context is not None and now is not None:
        lineage, significance = _release_significance(
            release,
            metadata,
            lineage_context,
            now,
        )
        significance_payload = significance.as_dict()
    profile = {
        "publisher": release.publisher_id,
        "hf_repo": hf_repo,
        "license": metadata.get("license"),
        "modality": metadata.get("modality") or metadata.get("pipeline_tag"),
        "hardware_tier": metadata.get("hardware_tier"),
        "params_total": metadata.get("params_total"),
        "context_length": metadata.get("context_length"),
        "hf_downloads": metadata.get("downloads"),
        "hf_likes": metadata.get("likes"),
        "last_modified": metadata.get("last_modified"),
        "library_name": metadata.get("library_name"),
        "quantization_format": metadata.get("quantization_format"),
    }
    return {
        "release_id": release.id,
        "name": release.name,
        "category": release.category.value,
        "lane": release.lane.value,
        "lifecycle": release.lifecycle.value,
        "first_observed_at": release.first_observed_at.isoformat(),
        "released_at": _released_at(metadata, release.first_observed_at),
        "confidence": _confidence(
            metadata,
            official_publisher=not release.publisher_id.startswith(
                "publisher:provisional:"
            ),
        ),
        "lineage": lineage,
        "is_official": not release.publisher_id.startswith(
            "publisher:provisional:"
        ),
        "significance": significance_payload,
        "public_ring": bridged.ring.value if bridged is not None else None,
        "reasons": [],
        "evidence_ids": [],
        "source_url": source_url,
        "source_strength": (
            release.discovery_evidence_strength.value if source_url else None
        ),
        "profile": profile,
        "claims": [],
    }


def _write_compact_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )


def write_model_index(
    releases: Sequence[Release],
    site_root: Path,
    generated_at: datetime,
    *,
    shard_size: int = MODEL_INDEX_SHARD_SIZE,
    repository: Any | None = None,
    legacy_rings: Mapping[str, Any] | None = None,
) -> ModelIndexManifest:
    """Write a deterministic, compact index covering every canonical release."""
    if shard_size < 1:
        raise ValueError("shard_size must be positive")
    metadata = _claim_metadata(repository, releases) if repository is not None else {}
    lineage_context = (
        _LineageContext.load(repository)
        if repository is not None
        else _LineageContext()
    )
    rows = [
        _compact_model_row(
            release,
            metadata.get(release.id),
            lineage_context=lineage_context,
            now=generated_at,
            legacy_rings=legacy_rings,
        )
        for release in releases
    ]
    # Same ordering as the snapshot's model rows: significance class first,
    # score second, recency only as a tiebreak within equals.
    rows.sort(key=_model_row_order)
    shard_root = site_root / "data" / "model-index"
    shard_root.mkdir(parents=True, exist_ok=True)
    for stale in shard_root.glob("model-index-*.json"):
        stale.unlink()

    shards: list[ModelIndexShard] = []
    for index, offset in enumerate(range(0, len(rows), shard_size)):
        selected = rows[offset : offset + shard_size]
        relative = f"data/model-index/model-index-{index:05d}.json"
        _write_compact_json(
            site_root / relative,
            {
                "schema_version": "1.0",
                "generated_at": generated_at.isoformat(),
                "items": selected,
            },
        )
        shards.append(ModelIndexShard(path=relative, count=len(selected)))

    manifest = ModelIndexManifest(
        generated_at=generated_at,
        total=len(rows),
        shard_size=shard_size,
        shards=shards,
    )
    _write_compact_json(
        site_root / "data" / "model-index.v1.json",
        manifest.model_dump(mode="json"),
    )
    return manifest
