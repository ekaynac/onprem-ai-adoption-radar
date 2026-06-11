"""Pipeline orchestration."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from radar.collectors.registry import build_collectors
from radar.models import DecisionCard, ScoredSignal
from radar.pipeline.cards import build_decision_cards
from radar.pipeline.dedupe import dedupe_signals
from radar.pipeline.quotas import apply_category_quotas
from radar.reports.markdown import render_markdown_report
from radar.scoring.deterministic import score_signal
from radar.storage.config import load_config
from radar.storage.database import RadarDatabase
from radar.storage.run_store import RunStore


@dataclass(frozen=True)
class ScanResult:
    """Result returned by a scan."""

    run_id: str
    cards: list[DecisionCard]
    report_path: Path


class RadarOrchestrator:
    """Compose collectors, scoring, storage, and reports."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.data_dir = self.root / "data"
        self.config_path = self.data_dir / "config.yaml"
        self.run_store = RunStore(self.data_dir / "runs")
        self.database = RadarDatabase(self.data_dir / "radar.db")

    def scan(self, days: int) -> ScanResult:
        """Run the scan pipeline synchronously for CLI callers."""
        return asyncio.run(self._scan(days))

    async def _scan(self, days: int) -> ScanResult:
        config = load_config(self.config_path)
        self.database.initialize()
        run_id = self.run_store.create_run()
        since = datetime.now(timezone.utc) - timedelta(days=days)

        async with httpx.AsyncClient(timeout=30.0) as client:
            collectors = build_collectors(config, client)
            raw = []
            for collector in collectors:
                try:
                    raw.extend(await collector.fetch(since))
                except Exception as exc:
                    self.run_store.update_meta(run_id, {"collector_warning": str(exc)})

        self.run_store.save_stage(
            run_id,
            "raw_signals",
            [signal.model_dump(mode="json") for signal in raw],
        )
        deduped = dedupe_signals(raw)
        scored: list[ScoredSignal] = [
            score_signal(signal, config.scoring) for signal in deduped
        ]
        self.run_store.save_stage(
            run_id,
            "scored_signals",
            [item.model_dump(mode="json") for item in scored],
        )
        cards = build_decision_cards(scored)
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
        self.database.upsert_cards(filtered_cards)
        report = render_markdown_report(filtered_cards, "Agent/Tooling Adoption Radar")
        report_path = self.run_store.save_report(run_id, report)
        return ScanResult(
            run_id=run_id,
            cards=filtered_cards,
            report_path=report_path,
        )

    def latest_cards(self) -> list[DecisionCard]:
        """Return cards from SQLite."""
        self.database.initialize()
        return self.database.list_cards()
