from datetime import UTC, datetime
from pathlib import Path

from radar.storage.source_health_log import (
    SourceHealthRecord,
    SourceOutcome,
    append_source_health,
    load_source_health,
)
from radar.storage.source_health_store import SourceHealthStore


def _record(run_id: str = "run-1") -> SourceHealthRecord:
    return SourceHealthRecord(
        run_id=run_id,
        observed_at=datetime(2026, 7, 27, tzinfo=UTC),
        sources={
            "github-vllm": SourceOutcome(count=3, status="ok"),
            "rss-dead": SourceOutcome(count=0, status="error"),
        },
    )


def test_append_and_load_roundtrip(tmp_path: Path):
    log = tmp_path / "source-health.jsonl"
    append_source_health(log, _record())
    (loaded,) = load_source_health(log)
    assert loaded.sources["rss-dead"].status == "error"
    assert load_source_health(tmp_path / "missing.jsonl") == []


def test_corrupt_line_skipped(tmp_path: Path):
    log = tmp_path / "source-health.jsonl"
    append_source_health(log, _record())
    log.write_text(log.read_text() + "{not json\n", encoding="utf-8")
    assert len(load_source_health(log)) == 1


def test_import_records_rehydrates_idempotently(tmp_path: Path):
    store = SourceHealthStore(tmp_path / "radar.db")
    store.initialize()
    records = [_record("run-1"), _record("run-2")]
    assert store.import_records(records) == 4  # 2 sources x 2 runs
    assert store.import_records(records) == 0  # second import: all present
    assert store.latest_counts()["github-vllm"] == 3
