"""Corrective-event repair for outage-polluted history."""

from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from radar.cli import app


def _seed_source_health(db_path: Path, run_id: str, zero: int, ok: int) -> None:
    from radar.storage.source_health_store import SourceHealthStore

    store = SourceHealthStore(db_path)
    store.initialize()
    counts = {f"z{i}": 0 for i in range(zero)} | {f"s{i}": 1 for i in range(ok)}
    store.record(run_id, datetime(2026, 7, 1, tzinfo=UTC), counts)


def test_outage_run_ids_thresholds(tmp_path: Path):
    from radar.storage.history_repair import outage_run_ids

    db = tmp_path / "radar.db"
    _seed_source_health(db, "run-outage", zero=60, ok=6)  # 91% zero
    _seed_source_health(db, "run-healthy", zero=10, ok=58)  # 15% zero
    _seed_source_health(db, "run-tiny", zero=3, ok=0)  # < min_sources

    assert outage_run_ids(db) == {"run-outage"}


def _event(project, change_type, ring, previous_ring, run_id, corrects=None):
    # Deliberate copy of the helper in tests/test_history_store.py — tests
    # never import from other test modules here.
    from radar.models import Category, Ring
    from radar.pipeline.delta import ChangeType
    from radar.storage.history_store import ProjectHistoryEvent

    return ProjectHistoryEvent(
        project=project,
        category=Category.MCP_TOOLING,
        change_type=ChangeType(change_type),
        ring=Ring(ring),
        previous_ring=Ring(previous_ring) if previous_ring else None,
        run_id=run_id,
        observed_at=datetime(2026, 7, 1, tzinfo=UTC),
        reasons=[],
        corrects_run_id=corrects,
    )


def test_build_corrections_is_idempotent(tmp_path: Path):
    from radar.storage.history_repair import build_corrections

    when = datetime(2026, 7, 27, tzinfo=UTC)
    events = [
        _event("MCP", "promoted", "adopt", "pilot", "run-outage"),
        _event("MCP", "updated", "adopt", None, "run-healthy"),
    ]
    first = build_corrections(events, {"run-outage"}, when)
    assert len(first) == 1
    marker = first[0]
    assert marker.change_type.value == "corrected"
    assert marker.corrects_run_id == "run-outage"
    assert marker.run_id == "repair:run-outage"
    assert marker.ring.value == "pilot"  # reverts to pre-artifact ring
    assert marker.previous_ring.value == "adopt"

    # Second pass over the already-repaired timeline appends nothing.
    assert build_corrections(events + first, {"run-outage"}, when) == []


def test_cli_history_repair_appends_corrected_event_and_is_idempotent(tmp_path: Path):
    from radar.storage.history_log import append_events, load_events
    from radar.storage.history_store import HistoryStore

    runner = CliRunner()
    runner.invoke(app, ["init", "--root", str(tmp_path)])

    _seed_source_health(tmp_path / "data" / "radar.db", "run-x", zero=60, ok=6)

    promoted = _event("MCP", "promoted", "adopt", "pilot", "run-x")
    store = HistoryStore(tmp_path / "data" / "radar.db")
    store.initialize()
    store.add_events([promoted])
    append_events(tmp_path / "data" / "history.jsonl", [promoted])

    result = runner.invoke(app, ["history", "repair", "--root", str(tmp_path)])
    assert result.exit_code == 0, result.stdout

    events = load_events(tmp_path / "data" / "history.jsonl")
    corrected = [e for e in events if e.change_type.value == "corrected"]
    assert len(corrected) == 1
    assert corrected[0].corrects_run_id == "run-x"

    # Re-running is idempotent: no new corrected events appended.
    result_again = runner.invoke(app, ["history", "repair", "--root", str(tmp_path)])
    assert result_again.exit_code == 0, result_again.stdout
    events_after = load_events(tmp_path / "data" / "history.jsonl")
    corrected_after = [e for e in events_after if e.change_type.value == "corrected"]
    assert len(corrected_after) == 1


def test_cli_history_callback_preserved(tmp_path: Path):
    runner = CliRunner()
    runner.invoke(app, ["init", "--root", str(tmp_path)])

    result = runner.invoke(app, ["history", "--root", str(tmp_path)])

    assert result.exit_code == 0, result.stdout


def test_repair_heals_db_ahead_of_log(tmp_path: Path):
    """Regression test for the 2026-07-27 broken-repair incident.

    The DB's project_history table held 50 `corrected` markers that never
    reached data/history.jsonl (the durable log the DB merely projects).
    Because the old `history_repair()` built both the event stream AND the
    idempotence set from `orchestrator.history.all_events()` (the DB), it saw
    the marker as "already corrected" and reported "Corrections to append: 0"
    — the source of truth could never be healed. Repair must read from the
    log, so a marker present only in the DB is *not* treated as already done.
    """
    from radar.storage.history_log import append_events, load_events
    from radar.storage.history_store import HistoryStore

    runner = CliRunner()
    runner.invoke(app, ["init", "--root", str(tmp_path)])

    _seed_source_health(tmp_path / "data" / "radar.db", "run-x", zero=60, ok=6)

    promoted = _event("MCP", "promoted", "adopt", "pilot", "run-x")
    # The exact broken state: the corrected marker made it into the DB but
    # never into the log (simulating the earlier repair run's silent no-op).
    corrected_marker = _event(
        "MCP", "corrected", "pilot", "adopt", "repair:run-x", corrects="run-x"
    )

    store = HistoryStore(tmp_path / "data" / "radar.db")
    store.initialize()
    store.add_events([promoted, corrected_marker])
    append_events(tmp_path / "data" / "history.jsonl", [promoted])

    result = runner.invoke(app, ["history", "repair", "--root", str(tmp_path)])
    assert result.exit_code == 0, result.stdout
    assert "Corrections to append: 1" in result.stdout

    events = load_events(tmp_path / "data" / "history.jsonl")
    corrected = [e for e in events if e.change_type.value == "corrected"]
    assert len(corrected) == 1, "the marker must be appended to the LOG, not just the DB"
    assert corrected[0].corrects_run_id == "run-x"

    # Re-running is idempotent now that the log itself carries the marker.
    result_again = runner.invoke(app, ["history", "repair", "--root", str(tmp_path)])
    assert result_again.exit_code == 0, result_again.stdout
    assert "Corrections to append: 0" in result_again.stdout


def test_repair_on_root_without_source_health_table_exits_cleanly(tmp_path: Path):
    """A fresh clone that has never been scanned has no source_health table.

    `radar history repair` used to crash with a raw
    `sqlite3.OperationalError: no such table: source_health`. It must instead
    report there's nothing to do and exit 0.
    """
    runner = CliRunner()
    runner.invoke(app, ["init", "--root", str(tmp_path)])

    result = runner.invoke(app, ["history", "repair", "--root", str(tmp_path)])

    assert result.exit_code == 0, result.stdout
    assert "No outage evidence recorded." in result.stdout
