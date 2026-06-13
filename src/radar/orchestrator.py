"""Pipeline orchestration."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from radar.collectors.registry import build_collectors
from radar.enrichment.runner import run_enrichment
from radar.models import DecisionCard, ScoredSignal
from radar.pipeline.cards import build_decision_cards
from radar.pipeline.classify import build_project_index, reclassify_firehose
from radar.pipeline.dedupe import dedupe_signals
from radar.pipeline.delta import CardDelta, ChangeType, compute_deltas
from radar.pipeline.evidence import build_evidence, collect_project_metrics
from radar.pipeline.llm_classify import build_analyst
from radar.pipeline.quotas import apply_category_quotas
from radar.reports.history import render_history_report
from radar.reports.markdown import render_markdown_report
from radar.reports.try_this_week import render_try_this_week_report
from radar.scoring.deterministic import score_signal
from radar.storage.config import load_config
from radar.storage.database import RadarDatabase
from radar.storage.history_log import append_events, load_events
from radar.storage.history_store import HistoryStore, deltas_to_events
from radar.storage.metrics_store import MetricsStore
from radar.storage.run_store import RunStore


@dataclass(frozen=True)
class ScanResult:
    """Result returned by a scan."""

    run_id: str
    cards: list[DecisionCard]
    report_path: Path
    delta_report_path: Path
    history_report_path: Path
    deltas: list[CardDelta]


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
        # Durable, portable source of truth for the timeline (the DB is a cache).
        self.history_log = self.data_dir / "history.jsonl"

    def scan(self, days: int) -> ScanResult:
        """Run the scan pipeline synchronously for CLI callers."""
        return asyncio.run(self._scan(days))

    async def _scan(self, days: int) -> ScanResult:
        config = load_config(self.config_path)
        self.database.initialize()
        self.history.initialize()
        # Reconcile the durable log (source of truth) with the DB projection:
        # rebuild the DB from the log if present, or backfill the log from a
        # legacy DB that predates the log. Either way the log ends up complete.
        log_events = load_events(self.history_log)
        if log_events:
            self.history.import_events(log_events)
        elif self.history.has_events():
            append_events(self.history_log, self.history.all_events())
        run_id = self.run_store.create_run()
        since = datetime.now(UTC) - timedelta(days=days)

        async with httpx.AsyncClient(timeout=30.0) as client:
            collectors = build_collectors(config, client)
            raw = []
            collector_warnings: list[str] = []
            for collector in collectors:
                try:
                    raw.extend(await collector.fetch(since))
                except Exception as exc:
                    collector_warnings.append(
                        f"{collector.__class__.__name__}: {exc}"
                    )
            if collector_warnings:
                self.run_store.update_meta(
                    run_id, {"collector_warnings": collector_warnings}
                )

        self.run_store.save_stage(
            run_id,
            "raw_signals",
            [signal.model_dump(mode="json") for signal in raw],
        )
        # Re-attribute high-volume firehose entries to tracked projects before
        # dedupe/scoring. Unmatched entries are dropped (not silently): their
        # count and a sample are recorded in the run meta for visibility.
        index = build_project_index(config.sources)
        # Optional LLM analyst (off by default) takes a second pass at entries
        # the deterministic matcher dropped. build_analyst returns None unless
        # config.llm.enabled, so the default path stays fully offline.
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
        deduped = dedupe_signals(firehose.kept)
        # Observed evidence: reduce this scan's signals to per-project metrics,
        # enrich them (advisories / HN / downloads — additive, never fatal),
        # compare against the previous scan's rows (read BEFORE recording the
        # new ones), and let scoring see the result.
        observed_at = datetime.now(UTC)
        self.metrics.initialize()
        current_metrics = collect_project_metrics(deduped, run_id, observed_at)
        advisories: dict[str, list] = {}
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
            if enrichment.warnings:
                self.run_store.update_meta(
                    run_id, {"enrichment_warnings": enrichment.warnings}
                )
        evidence = {
            project: build_evidence(
                metrics,
                self.metrics.latest(project, exclude_run=run_id),
                now=observed_at,
                advisories=advisories.get(project),
            )
            for project, metrics in current_metrics.items()
        }
        self.metrics.record(list(current_metrics.values()))
        scored: list[ScoredSignal] = [
            score_signal(signal, config.scoring, evidence.get(signal.project))
            for signal in deduped
        ]
        self.run_store.save_stage(
            run_id,
            "scored_signals",
            [item.model_dump(mode="json") for item in scored],
        )
        cards = build_decision_cards(scored, evidence_by_project=evidence)
        filtered_cards = apply_category_quotas(cards, config.quotas)
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
        self.run_store.save_stage(
            run_id,
            "decision_cards",
            [card.model_dump(mode="json") for card in filtered_cards],
        )
        # Capture the prior persisted state BEFORE upserting so the delta
        # reflects what changed since the last scan.
        previous_cards = self.database.list_cards()
        deltas = compute_deltas(previous=previous_cards, current=filtered_cards)

        self.database.upsert_cards(filtered_cards)
        # Persist this scan's changes to BOTH the durable JSONL log (source of
        # truth) and the DB projection. Drop "new" events for projects already
        # in the timeline: after a DB/snapshot wipe every project would look new
        # again, which would pollute the durable record on a re-scan.
        seen = self.history.seen_projects()
        persistable = [
            d
            for d in deltas
            if not (d.change_type == ChangeType.NEW and d.project in seen)
        ]
        events = deltas_to_events(
            persistable, run_id=run_id, observed_at=datetime.now(UTC)
        )
        self.history.add_events(events)
        append_events(self.history_log, events)

        report = render_markdown_report(filtered_cards, "Agent/Tooling Adoption Radar")
        report_path = self.run_store.save_report(run_id, report)

        delta_report = render_try_this_week_report(deltas, "Try This Week")
        delta_report_path = self.run_store.save_try_this_week(run_id, delta_report)

        history_report = render_history_report(
            summaries=self.history.summaries(),
            events_by_project=self._history_by_project(),
            title="Adoption History",
        )
        history_report_path = self.run_store.save_history(run_id, history_report)

        return ScanResult(
            run_id=run_id,
            cards=filtered_cards,
            report_path=report_path,
            delta_report_path=delta_report_path,
            history_report_path=history_report_path,
            deltas=deltas,
        )

    def _history_by_project(self) -> dict[str, list]:
        """Group all recorded history events by project for report rendering."""
        return {
            summary.project: self.history.history_for(summary.project)
            for summary in self.history.summaries()
        }

    def latest_cards(self) -> list[DecisionCard]:
        """Return cards from SQLite."""
        self.database.initialize()
        return self.database.list_cards()
