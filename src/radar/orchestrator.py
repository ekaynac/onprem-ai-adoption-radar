"""Pipeline orchestration."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from radar.analysis.backtest import (
    BacktestReport,
    RunBacktest,
    build_backtest_report,
)
from radar.collectors.registry import build_collectors
from radar.constants import DEGRADED_SOURCE_ERROR_THRESHOLD
from radar.enrichment.runner import run_enrichment
from radar.models import Backer, Config, DecisionCard, ScoredSignal, Signal
from radar.notify.webhook import send_notification
from radar.pipeline.cards import build_decision_cards
from radar.pipeline.classify import build_project_index, reclassify_firehose
from radar.pipeline.dedupe import dedupe_signals
from radar.pipeline.delta import CardDelta, ChangeType, compute_deltas
from radar.pipeline.evidence import build_evidence, collect_project_metrics
from radar.pipeline.llm_classify import build_analyst
from radar.pipeline.momentum import compute_momentum
from radar.pipeline.quotas import apply_category_quotas
from radar.reports.history import render_history_report
from radar.reports.markdown import render_markdown_report
from radar.reports.movers import build_mover_lines
from radar.reports.try_this_week import render_try_this_week_report
from radar.scoring.deterministic import score_signal
from radar.scoring.profiles import resolve_weights, reweight_cards
from radar.storage.config import load_config
from radar.storage.database import RadarDatabase
from radar.storage.history_log import append_events, load_events
from radar.storage.history_store import HistoryStore, apply_corrections, deltas_to_events
from radar.storage.metrics_store import MetricsStore
from radar.storage.overrides_store import OverridesStore, apply_overrides
from radar.storage.run_store import RunStore
from radar.storage.source_health_log import (
    SourceHealthRecord,
    SourceOutcome,
    append_source_health,
    load_source_health,
)
from radar.storage.source_health_store import SourceHealthStore


logger = logging.getLogger(__name__)


def _backers_by_project(config: Config) -> dict[str, Backer]:
    """Map each configured project to its backer, skipping uncurated sources."""
    return {s.project: s.backer for s in config.sources if s.backer is not None}


@dataclass(frozen=True)
class CollectionHealth:
    """How collection went: the input for the degraded-run gate."""

    total_sources: int
    errored_sources: int

    @property
    def error_fraction(self) -> float:
        if self.total_sources == 0:
            return 0.0
        return self.errored_sources / self.total_sources


@dataclass(frozen=True)
class ReplayResult:
    """Result of an offline re-score of a past run."""

    run_id: str
    cards: list[DecisionCard]
    report_path: Path


@dataclass(frozen=True)
class ScanResult:
    """Result returned by a scan."""

    run_id: str
    cards: list[DecisionCard]
    report_path: Path
    delta_report_path: Path
    history_report_path: Path
    deltas: list[CardDelta]
    degraded: bool = False
    degraded_reason: str | None = None


class RadarOrchestrator:
    """Compose collectors, scoring, storage, and reports."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.data_dir = self.root / "data"
        self.config_path = self.data_dir / "config.yaml"
        self.run_store = RunStore(self.data_dir / "runs")
        self.database = RadarDatabase(self.data_dir / "radar.db")
        self.history = HistoryStore(self.data_dir / "radar.db")
        self.metrics = MetricsStore(self.data_dir / "radar.db")
        self.source_health = SourceHealthStore(self.data_dir / "radar.db")
        # Durable, portable source of truth for the timeline (the DB is a cache).
        self.history_log = self.data_dir / "history.jsonl"
        # Durable, portable source of truth for source health (the DB is a cache).
        self.source_health_log = self.data_dir / "source-health.jsonl"
        # Human decisions: pinned rings + trial journal (portable YAML).
        self.overrides_path = self.data_dir / "overrides.yaml"

    def scan(
        self, days: int, profile: str | None = None, publish_history: bool = False
    ) -> ScanResult:
        """Run the scan pipeline synchronously for CLI callers."""
        return asyncio.run(self._scan(days, profile, publish_history))

    async def _scan(
        self, days: int, profile: str | None = None, publish_history: bool = False
    ) -> ScanResult:
        config = load_config(self.config_path)
        weights = resolve_weights(config.profiles, profile) if profile else None
        self.database.initialize()
        self.history.initialize()
        self._reconcile_history()
        self.source_health.initialize()
        self.source_health.import_records(load_source_health(self.source_health_log))
        run_id = self.run_store.create_run()
        since = datetime.now(UTC) - timedelta(days=days)

        raw, health = await self._collect_raw(config, run_id, since, publish_history)
        if health.error_fraction >= DEGRADED_SOURCE_ERROR_THRESHOLD:
            reason = (
                f"collection outage: {health.errored_sources}/{health.total_sources} "
                "sources failed — run recorded but not scored"
            )
            self.run_store.update_meta(run_id, {"degraded": True, "degraded_reason": reason})
            report_path = self.run_store.save_report(
                run_id, f"# Degraded run\n\n{reason}\n"
            )
            return ScanResult(
                run_id=run_id, cards=[], report_path=report_path,
                delta_report_path=report_path, history_report_path=report_path,
                deltas=[], degraded=True, degraded_reason=reason,
            )
        deduped = self._classify(config, raw, run_id)
        evidence = await self._assemble_evidence(config, deduped, run_id, since)
        scored: list[ScoredSignal] = [
            score_signal(signal, config.scoring, evidence.get(signal.project)) for signal in deduped
        ]
        self.run_store.save_stage(
            run_id,
            "scored_signals",
            [item.model_dump(mode="json") for item in scored],
        )
        cards = build_decision_cards(
            scored,
            evidence_by_project=evidence,
            weights=weights,
            backer_by_project=_backers_by_project(config),
        )
        cards = self._attach_pedigree(cards, config)
        if profile:
            self.run_store.update_meta(run_id, {"profile": profile})
        filtered_cards = apply_category_quotas(cards, config.quotas)
        # Human pins win over computed rings (and surface drift) BEFORE deltas,
        # so pin changes land in the timeline like any other ring move.
        overrides = OverridesStore(self.overrides_path).load()
        filtered_cards = apply_overrides(filtered_cards, overrides.overrides)
        filtered_projects = {card.project for card in filtered_cards}
        self.run_store.save_stage(
            run_id,
            "filtered_signals",
            [
                item.model_dump(mode="json")
                for item in scored
                if item.signal.project in filtered_projects
            ],
        )
        # Capture the prior persisted state BEFORE upserting so the delta
        # reflects what changed since the last scan.
        previous_cards = self.database.list_cards()
        deltas = compute_deltas(previous=previous_cards, current=filtered_cards)
        self._persist_history(deltas, run_id, publish_history)

        # Momentum reads metrics + ring history INCLUDING this scan, so it runs
        # after both were persisted; trend is attached before cards persist.
        momentums = self._compute_momentums(filtered_cards)
        filtered_cards = [
            card.model_copy(update={"trend": momentums[card.project].direction})
            for card in filtered_cards
        ]
        self.run_store.save_stage(
            run_id,
            "decision_cards",
            [card.model_dump(mode="json") for card in filtered_cards],
        )
        self.database.upsert_cards(filtered_cards)

        mover_lines = build_mover_lines(deltas, list(momentums.values()))
        report = render_markdown_report(
            filtered_cards, "Agent/Tooling Adoption Radar", movers=mover_lines
        )
        report_path = self.run_store.save_report(run_id, report)

        delta_report = render_try_this_week_report(deltas, "Try This Week")
        delta_report_path = self.run_store.save_try_this_week(run_id, delta_report)

        history_report = render_history_report(
            summaries=self.history.all_summaries(),
            events_by_project=self._history_by_project(),
            title="Adoption History",
        )
        history_report_path = self.run_store.save_history(run_id, history_report)

        await self._notify(config, deltas, run_id)

        return ScanResult(
            run_id=run_id,
            cards=filtered_cards,
            report_path=report_path,
            delta_report_path=delta_report_path,
            history_report_path=history_report_path,
            deltas=deltas,
        )

    # --- scan phases (extracted from _scan for readability) -----------------

    def reconcile_history(self) -> None:
        """Public entry point for callers outside the scan pipeline (e.g. CLI).

        Delegates to `_reconcile_history`; see there for what "reconcile" means.
        """
        self._reconcile_history()

    def _reconcile_history(self) -> None:
        """Reconcile the durable JSONL log (source of truth) with the DB.

        Rebuild the DB projection from the log if present, or backfill the log
        from a legacy DB that predates it. Either way the log ends up complete.
        """
        log_events = load_events(self.history_log)
        if log_events:
            self.history.import_events(log_events)
        elif self.history.has_events():
            append_events(self.history_log, self.history.all_events())

    async def _collect_raw(
        self, config, run_id: str, since: datetime, publish_history: bool
    ) -> tuple[list[Signal], CollectionHealth]:
        """Fetch from all collectors, persist raw signals, record source health.

        A failing collector costs at most its own signals; the failure is
        recorded in the run meta rather than aborting the scan.
        """
        async with httpx.AsyncClient(timeout=30.0) as client:
            collectors = build_collectors(config, client)
            raw: list[Signal] = []
            collector_warnings: list[str] = []
            failed_source_ids: set[str] = set()
            for collector in collectors:
                try:
                    raw.extend(await collector.fetch(since))
                except Exception as exc:
                    collector_warnings.append(f"{collector.__class__.__name__}: {exc}")
                    # The whole collector died: every enabled source it owns errored.
                    failed_source_ids.update(
                        s.id for s in getattr(collector, "sources", []) if s.enabled
                    )
                # Per-source soft failures (e.g. a feed that returned an HTML
                # challenge) are surfaced without aborting the whole collector.
                collector_warnings.extend(getattr(collector, "warnings", []))
                failed_source_ids.update(getattr(collector, "failed_source_ids", set()))
            if collector_warnings:
                self.run_store.update_meta(run_id, {"collector_warnings": collector_warnings})

        self.run_store.save_stage(
            run_id, "raw_signals", [signal.model_dump(mode="json") for signal in raw]
        )
        # Per-source counts (zero when a source produced nothing) feed dead-feed
        # detection in `radar seed list`.
        self.source_health.initialize()
        source_counts = {s.id: 0 for s in config.sources if s.enabled}
        for signal in raw:
            if signal.source_id in source_counts:
                source_counts[signal.source_id] += 1
        statuses = {
            source_id: (
                "error" if source_id in failed_source_ids
                else "ok" if count > 0
                else "empty"
            )
            for source_id, count in source_counts.items()
        }
        self.source_health.record(run_id, datetime.now(UTC), source_counts, statuses)
        # D5 (2026-07-27 spec): only CI writes the committed source-health
        # lane. Local scans still record evidence (this runs BEFORE the
        # degraded-run gate, so outages are never silently dropped) but to the
        # gitignored `data/local/source-health.jsonl` lane, same as history.jsonl,
        # so laptop runs never diverge the committed timeline (see D5's
        # rationale in `_persist_history`).
        target = (
            self.source_health_log
            if publish_history
            else self.data_dir / "local" / "source-health.jsonl"
        )
        append_source_health(
            target,
            SourceHealthRecord(
                run_id=run_id,
                observed_at=datetime.now(UTC),
                sources={
                    sid: SourceOutcome(count=count, status=statuses[sid])
                    for sid, count in source_counts.items()
                },
            ),
        )
        health = CollectionHealth(
            total_sources=len(source_counts),
            errored_sources=sum(1 for s in statuses.values() if s == "error"),
        )
        return raw, health

    def _classify(self, config, raw: list[Signal], run_id: str) -> list[Signal]:
        """Re-attribute firehose entries to tracked projects, then dedupe.

        Unmatched firehose entries are dropped but counted/sampled into the run
        meta. The optional LLM analyst (off by default) handles the tail.
        """
        index = build_project_index(config.sources)
        analyst = build_analyst(config.llm)
        firehose = reclassify_firehose(raw, index, analyst=analyst)
        if firehose.dropped_titles or firehose.llm_recovered:
            self.run_store.update_meta(
                run_id,
                {
                    "firehose_dropped_count": len(firehose.dropped_titles),
                    "firehose_dropped_sample": firehose.dropped_titles[:10],
                    "firehose_llm_recovered": firehose.llm_recovered,
                },
            )
        return dedupe_signals(firehose.kept)

    async def _assemble_evidence(
        self, config, deduped: list[Signal], run_id: str, since: datetime
    ) -> dict:
        """Reduce signals to metrics, enrich them, and build per-project evidence.

        Enrichment (advisories / HN / downloads) is best-effort. Evidence
        compares against the PREVIOUS scan's metrics (read before the current
        rows are recorded), then the new rows are persisted.
        """
        observed_at = datetime.now(UTC)
        self.metrics.initialize()
        current_metrics = collect_project_metrics(deduped, run_id, observed_at)
        advisories: dict[str, list] = {}
        papers: dict[str, list] = {}
        if current_metrics:
            async with httpx.AsyncClient(
                timeout=float(config.enrichment.timeout_seconds)
            ) as enrich_client:
                enrichment = await run_enrichment(
                    config.enrichment,
                    sources=config.sources,
                    metrics=current_metrics,
                    since=since,
                    now=observed_at,
                    client=enrich_client,
                )
            current_metrics = enrichment.metrics
            advisories = dict(enrichment.advisories)
            papers = dict(enrichment.papers)
            if enrichment.warnings:
                self.run_store.update_meta(run_id, {"enrichment_warnings": enrichment.warnings})
        evidence = {
            project: build_evidence(
                metrics,
                self.metrics.latest(project, exclude_run=run_id),
                now=observed_at,
                advisories=advisories.get(project),
                papers=papers.get(project),
            )
            for project, metrics in current_metrics.items()
        }
        self.metrics.record(list(current_metrics.values()))
        return evidence

    def _persist_history(
        self, deltas: list[CardDelta], run_id: str, publish_history: bool
    ) -> None:
        """Append ring-change events to the DB and durable log.

        Drops "new" events for projects already in the timeline: after a
        DB/snapshot wipe every project would look new again, which would
        pollute the durable record on a re-scan.
        """
        seen = self.history.seen_projects()
        persistable = [
            d for d in deltas if not (d.change_type == ChangeType.NEW and d.project in seen)
        ]
        events = deltas_to_events(persistable, run_id=run_id, observed_at=datetime.now(UTC))
        self.history.add_events(events)
        # D5 (2026-07-27 spec): only CI writes the committed timeline. Local
        # scans keep the DB projection + reports but log to an ignored lane,
        # so laptop runs never pollute the shared history.
        target = (
            self.history_log
            if publish_history
            else self.data_dir / "local" / "history.jsonl"
        )
        append_events(target, events)

    def _attach_pedigree(self, cards: list[DecisionCard], config: Config) -> list[DecisionCard]:
        """Append a research-pedigree evidence line per card. Best-effort:
        no research run (or any failure) leaves the cards untouched."""
        try:
            from radar.mcp_server.technique_queries import load_technique_entries
            from radar.research_radar.pedigree import (
                build_pedigree_index,
                pedigree_for_refs,
                pedigree_note,
            )

            entries = load_technique_entries(self.root)
            if not entries:
                return cards
            index = build_pedigree_index(entries)
            ids_by_project: dict[str, list[str]] = {}
            for source in config.sources:
                ids_by_project.setdefault(source.project, []).append(source.id)
            updated: list[DecisionCard] = []
            for card in cards:
                items = pedigree_for_refs(
                    index.by_tool_ref, ids_by_project.get(card.project, [])
                )
                note = pedigree_note(items)
                if note is None:
                    updated.append(card)
                else:
                    updated.append(card.model_copy(
                        update={"evidence_notes": [*card.evidence_notes, note]}
                    ))
            return updated
        except Exception as exc:  # pedigree must never fail a scan
            logger.warning("Research pedigree unavailable: %s", exc)
            return cards

    def _compute_momentums(self, cards: list[DecisionCard]) -> dict:
        """Direction of travel per project from metrics + ring history."""
        return {
            card.project: compute_momentum(
                card.project,
                metric_rows=self.metrics.history_for(card.project),
                ring_events=apply_corrections(self.history.history_for(card.project)),
            )
            for card in cards
        }

    async def _notify(self, config, deltas: list[CardDelta], run_id: str) -> None:
        """Fire-and-forget outbound webhook on ring changes (off by default)."""
        if not config.notify.enabled:
            return
        async with httpx.AsyncClient(timeout=float(config.notify.timeout_seconds)) as notify_client:
            sent = await send_notification(
                config.notify, deltas, run_id=run_id, client=notify_client
            )
        if sent:
            self.run_store.update_meta(run_id, {"notified": True})

    def replay(self, source_run_id: str) -> ReplayResult:
        """Re-score a past run's persisted raw signals with CURRENT config.

        Fully offline and side-effect-free for the timeline: no collectors, no
        enrichment, no history events, no metrics rows, no DB card upserts.
        Evidence is rebuilt against the metrics recorded BEFORE the original
        run (advisory lists were network data and are not replayed). This is
        the loop for tuning scoring config: edit, replay, diff the report.
        """
        config = load_config(self.config_path)
        raw_payload = self.run_store.load_stage(source_run_id, "raw_signals")
        raw = [Signal.model_validate(item) for item in raw_payload]

        run_id = self.run_store.create_run()
        self.run_store.update_meta(run_id, {"replay_of": source_run_id})

        filtered_cards = self._rescore(raw, config, source_run_id=source_run_id)
        self.run_store.save_stage(
            run_id,
            "decision_cards",
            [card.model_dump(mode="json") for card in filtered_cards],
        )
        report = render_markdown_report(
            filtered_cards, f"Replay of {source_run_id} (current config)"
        )
        report_path = self.run_store.save_report(run_id, report)
        return ReplayResult(run_id=run_id, cards=filtered_cards, report_path=report_path)

    def _rescore(
        self,
        raw: list[Signal],
        config,
        source_run_id: str | None = None,
        weights: dict[str, float] | None = None,
    ) -> list[DecisionCard]:
        """Re-score raw signals to cards with current config — no side effects.

        Pure with respect to persistence: creates no run dir and writes no
        metrics/history/DB rows (it reads ``metrics.latest`` for growth context
        but never records). Used by ``replay`` (which adds its own persistence)
        and ``backtest`` (which must not litter ``data/runs``).
        """
        index = build_project_index(config.sources)
        firehose = reclassify_firehose(raw, index, analyst=None)
        deduped = dedupe_signals(firehose.kept)

        observed_at = datetime.now(UTC)
        self.metrics.initialize()
        current_metrics = collect_project_metrics(deduped, source_run_id or "rescore", observed_at)
        papers: dict[str, list] = {}
        evidence = {
            project: build_evidence(
                metrics,
                self.metrics.latest(project, exclude_run=source_run_id),
                now=observed_at,
                papers=papers.get(project),
            )
            for project, metrics in current_metrics.items()
        }
        scored = [
            score_signal(signal, config.scoring, evidence.get(signal.project)) for signal in deduped
        ]
        cards = build_decision_cards(
            scored,
            evidence_by_project=evidence,
            weights=weights,
            backer_by_project=_backers_by_project(config),
        )
        filtered_cards = apply_category_quotas(cards, config.quotas)
        overrides = OverridesStore(self.overrides_path).load()
        return apply_overrides(filtered_cards, overrides.overrides)

    def backtest(self, profile: str | None = None, runs: int | None = None) -> BacktestReport:
        """Re-score historical runs and report how rings would differ.

        ``profile`` → compare current config vs that profile's weights per run.
        No ``profile`` → compare current config vs each run's persisted cards
        (config drift). Read-only: creates no runs, mutates no stored state.
        """
        config = load_config(self.config_path)
        weights = resolve_weights(config.profiles, profile) if profile else None
        run_ids = self.run_store.list_runs()
        if runs is not None:
            run_ids = run_ids[-runs:]
        mode = f"profile:{profile}" if profile else "config-drift"

        run_backtests = []
        for run_id in run_ids:
            try:
                raw_payload = self.run_store.load_stage(run_id, "raw_signals")
            except FileNotFoundError:
                continue
            raw = [Signal.model_validate(item) for item in raw_payload]
            created_at = self._run_created_at(run_id)
            if weights is not None:
                baseline = self._rescore(raw, config, source_run_id=run_id)
                candidate = self._rescore(raw, config, source_run_id=run_id, weights=weights)
            else:
                candidate = self._rescore(raw, config, source_run_id=run_id)
                baseline = self._persisted_cards(run_id)
            run_backtests.append(
                RunBacktest.from_card_sets(
                    run_id=run_id,
                    created_at=created_at,
                    baseline=baseline,
                    candidate=candidate,
                )
            )
        return build_backtest_report(mode=mode, runs=run_backtests)

    def _run_created_at(self, run_id: str) -> datetime:
        meta = self.run_store.read_meta(run_id)
        stamp = meta.get("created_at")
        if stamp:
            return datetime.fromisoformat(stamp)
        return datetime.now(UTC)

    def _persisted_cards(self, run_id: str) -> list[DecisionCard]:
        try:
            payload = self.run_store.load_stage(run_id, "decision_cards")
        except FileNotFoundError:
            return []
        return [DecisionCard.model_validate(item) for item in payload]

    def _history_by_project(self) -> dict[str, list]:
        """Group all recorded history events by project for report rendering.

        Uses `all_summaries()` (never omits a project), not `summaries()`, so
        a project whose entire timeline was corrected away still gets its raw
        events rendered in the report — the raw view must never drop a row.
        """
        return {
            summary.project: self.history.history_for(summary.project)
            for summary in self.history.all_summaries()
        }

    def latest_cards(self, profile: str | None = None) -> list[DecisionCard]:
        """Return cards from SQLite, optionally re-ranked through a profile.

        Re-ranking is a view only — it never persists. Cards are re-sorted by
        the reweighted score so the report reflects the profile's ordering.
        """
        self.database.initialize()
        cards = self.database.list_cards()
        if not profile:
            return cards
        config = load_config(self.config_path)
        weights = resolve_weights(config.profiles, profile)
        reweighted = reweight_cards(cards, weights)
        return sorted(reweighted, key=lambda c: (c.category.value, -c.score, c.project.lower()))
