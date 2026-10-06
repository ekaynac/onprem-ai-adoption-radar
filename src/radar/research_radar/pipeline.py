"""Technique decision pipeline: assemble → momentum → score → persist."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from radar.models import Ring
from radar.research_radar.citations import CitationRecord, fetch_citations
from radar.research_radar.entities import TechniqueEntry, TechniqueSeed
from radar.research_radar.history import (
    TechniqueHistoryEvent,
    append_technique_events,
    diff_technique_rings,
    load_technique_events,
)
from radar.research_radar.momentum import MomentumSignal, momentum_signal
from radar.research_radar.resolve import (
    ResolutionContext,
    build_resolution_context,
    resolve_implementations,
)
from radar.research_radar.scoring import score_technique, technique_ring
from radar.research_radar.seed import load_technique_seed
from radar.storage.technique_metrics_log import append_metrics, load_metrics
from radar.storage.technique_metrics_store import TechniqueMetrics, TechniqueMetricsStore


logger = logging.getLogger(__name__)

_PRIMARY_CITATION_SOURCE = "s2"


def assemble_entries(
    seeds: list[TechniqueSeed],
    context: ResolutionContext,
    citations: dict[str, CitationRecord],
    store: TechniqueMetricsStore,
) -> list[TechniqueEntry]:
    """Pre-score entries: resolved impls + citations (fresh, else last-known)."""
    entries: list[TechniqueEntry] = []
    for seed in seeds:
        if not seed.enabled:
            continue
        resolved, warnings = resolve_implementations(seed.implementations, context)
        count, source, peer_reviewed, citation_warnings = _citation_fields(
            seed, citations, store
        )
        entries.append(TechniqueEntry(
            id=seed.id, name=seed.name, category=seed.category, domain=seed.domain,
            aliases=seed.aliases, papers=seed.papers,
            resolved_implementations=resolved, open_code=seed.open_code,
            onprem_impact=seed.onprem_impact, superseded_by=seed.superseded_by,
            notes=seed.notes, citation_count=count, citation_source=source,
            peer_reviewed=peer_reviewed, warnings=warnings + citation_warnings,
        ))
    return sorted(entries, key=lambda e: e.id)


def score_technique_entries(
    entries: list[TechniqueEntry], store: TechniqueMetricsStore,
) -> list[TechniqueEntry]:
    """New entries with score/breakdown/ring. Momentum reads the store PRE-persist."""
    scored: list[TechniqueEntry] = []
    for entry in entries:
        momentum = momentum_signal(
            entry.id, store.history_for(entry.id), entry.citation_count,
            entry.citation_source, len(entry.resolved_implementations),
        )
        breakdown = score_technique(entry, momentum)
        ring = technique_ring(
            breakdown, len(entry.resolved_implementations),
            superseded=entry.superseded_by is not None,
        )
        scored.append(entry.model_copy(update={
            "score": breakdown.average, "score_breakdown": breakdown, "ring": ring,
            "momentum_direction": momentum.direction, "momentum_note": momentum.note or None,
        }))
    return scored


def persist_technique_scan(
    entries: list[TechniqueEntry],
    run_id: str,
    observed_at: datetime,
    db_path: Path,
    history_path: Path,
    metrics_log_path: Path | None = None,
    computed_rings: dict[str, Ring | None] | None = None,
) -> list[TechniqueHistoryEvent]:
    """Diff rings vs the log, append new events, record + dual-write per-scan metrics.

    ``computed_rings`` are the rings this scan computed before stabilization;
    they are what the metrics rows store, so the next scan can confirm them.
    """
    previous = _latest_rings(history_path)
    events = diff_technique_rings(entries, previous, run_id, observed_at)
    append_technique_events(history_path, events)
    store = TechniqueMetricsStore(db_path)
    store.initialize()
    rows = [TechniqueMetrics(
        technique_id=entry.id, run_id=run_id, observed_at=observed_at,
        citation_count=entry.citation_count, citation_source=entry.citation_source,
        resolved_impls=len(entry.resolved_implementations),
        ring=_computed_ring(entry, computed_rings),
        peer_reviewed=entry.peer_reviewed,
    ) for entry in entries]
    store.record(rows)
    if metrics_log_path is not None:
        append_metrics(metrics_log_path, rows)
    return events


def momentum_for(
    entries: list[TechniqueEntry], db_path: Path,
) -> dict[str, MomentumSignal]:
    """Post-hoc momentum for display (history here includes the current scan)."""
    store = TechniqueMetricsStore(db_path)
    store.initialize()
    result: dict[str, MomentumSignal] = {}
    for entry in entries:
        rows = store.history_for(entry.id)
        result[entry.id] = momentum_signal(
            entry.id, rows[:-1], entry.citation_count, entry.citation_source,
            len(entry.resolved_implementations),
        )
    return result


async def run_research_scan(
    seed_path: Path,
    config_path: Path,
    db_path: Path,
    model_seed_path: Path,
    model_history_path: Path,
    history_path: Path,
    client: Any,
    contact_email: str | None = None,
    run_id: str | None = None,
    metrics_log_path: Path | None = None,
) -> tuple[list[TechniqueEntry], list[TechniqueHistoryEvent]]:
    """Full scan. Only the seed load may raise; everything else degrades."""
    seeds = load_technique_seed(seed_path)  # fails loud before any network
    context = build_resolution_context(
        config_path, db_path, model_seed_path, model_history_path
    )
    arxiv_ids = sorted({
        paper.arxiv_id for seed in seeds if seed.enabled for paper in seed.papers
    })
    citations = await fetch_citations(arxiv_ids, client, contact_email)
    store = TechniqueMetricsStore(db_path)
    store.initialize()
    if metrics_log_path is not None and store.is_empty():
        rehydrated = load_metrics(metrics_log_path)
        if rehydrated:
            store.record(rehydrated)
            logger.warning(
                "Rehydrated %d technique metric rows from %s (fresh database)",
                len(rehydrated), metrics_log_path,
            )
    entries = assemble_entries(seeds, context, citations, store)
    entries = score_technique_entries(entries, store)
    computed = {entry.id: entry.ring for entry in entries}
    entries = stabilize_rings(entries, _latest_rings(history_path), store)
    observed_at = datetime.now(UTC)
    resolved_run_id = run_id or observed_at.strftime("research-%Y%m%d-%H%M%S")
    events = persist_technique_scan(
        entries, resolved_run_id, observed_at, db_path, history_path,
        metrics_log_path=metrics_log_path, computed_rings=computed,
    )
    return entries, events


def stabilize_rings(
    entries: list[TechniqueEntry],
    published: dict[str, Ring],
    store: TechniqueMetricsStore,
) -> list[TechniqueEntry]:
    """A ring change takes effect only when two consecutive scans compute it.

    Any single-scan input blip (a citation API outage, a partial tool scan)
    used to publish a ring change and its reversal two hours later: 91 such
    changes in the week of 2026-09-23. A computed ring that differs from the
    published one is held back, with a visible warning, until the previous
    scan computed the same ring. New techniques publish immediately.
    """
    stable: list[TechniqueEntry] = []
    for entry in entries:
        current = published.get(entry.id)
        if entry.ring is None or current is None or entry.ring == current:
            stable.append(entry)
            continue
        previous = store.latest(entry.id)
        if previous is not None and previous.ring == entry.ring.value:
            stable.append(entry)  # second consecutive scan agrees: publish it
            continue
        stable.append(entry.model_copy(update={
            "ring": current,
            "warnings": [*entry.warnings,
                         f"ring change to {entry.ring.value} pending confirmation by the next scan"],
        }))
    return stable


def _computed_ring(entry: TechniqueEntry, computed: dict[str, Ring | None] | None) -> str | None:
    ring = computed.get(entry.id, entry.ring) if computed is not None else entry.ring
    return ring.value if ring else None


def _latest_rings(history_path: Path) -> dict[str, Ring]:
    rings: dict[str, Ring] = {}
    for event in load_technique_events(history_path):  # oldest-first → last wins
        rings[event.technique_id] = event.ring
    return rings


def _citation_fields(
    seed: TechniqueSeed,
    citations: dict[str, CitationRecord],
    store: TechniqueMetricsStore,
) -> tuple[int | None, str | None, bool | None, list[str]]:
    """(count, source, peer_reviewed, warnings): fresh max-over-papers, else last-known.

    Semantic Scholar is the primary source; OpenAlex is only the outage
    fallback and counts far fewer citations for the same paper. When a fresh
    OpenAlex figure arrives for a technique that already has an S2 history,
    the last-known S2 figure wins, otherwise every S2 outage flips the ring.
    """
    fresh = [citations[p.arxiv_id] for p in seed.papers if p.arxiv_id in citations]
    if fresh:
        best = max(fresh, key=lambda r: r.citation_count)
        peer_reviewed = any(r.peer_reviewed for r in fresh)
        if best.source != _PRIMARY_CITATION_SOURCE:
            anchored = store.latest(seed.id, source=_PRIMARY_CITATION_SOURCE)
            if anchored is not None and anchored.citation_count is not None:
                return (anchored.citation_count, anchored.citation_source, peer_reviewed,
                        [f"citations: kept last-known Semantic Scholar count; "
                         f"OpenAlex fallback reported {best.citation_count}"])
        return (best.citation_count, best.source, peer_reviewed, [])
    last = store.latest(seed.id)
    if last is not None and last.citation_count is not None:
        # peer_reviewed travels with the count: dropping it to None cost one
        # validation point and flipped rings at the 4.0 threshold whenever the
        # citation APIs were unreachable (2026-10-01..05).
        return (last.citation_count, last.citation_source, last.peer_reviewed,
                ["citations: using last-known value (APIs unavailable)"])
    if seed.papers:
        return None, None, None, ["citations unknown (never fetched)"]
    return None, None, None, ["citations unknown (no papers seeded)"]
