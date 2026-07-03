"""SQLite store of per-scan technique metrics (mirror of model_metrics_store)."""

from datetime import datetime

from radar.storage.technique_metrics_store import TechniqueMetrics, TechniqueMetricsStore


def _metric(run: str, count: int | None, source: str | None = "s2",
            impls: int = 2, at: str = "2026-07-03T10:00:00+00:00") -> TechniqueMetrics:
    return TechniqueMetrics(
        technique_id="speculative-decoding", run_id=run,
        observed_at=datetime.fromisoformat(at),
        citation_count=count, citation_source=source, resolved_impls=impls, ring="adopt",
    )


def test_record_and_history_roundtrip_oldest_first(tmp_path):
    store = TechniqueMetricsStore(tmp_path / "radar.db")
    store.initialize()
    store.record([_metric("run-1", 100, at="2026-07-01T10:00:00+00:00")])
    store.record([_metric("run-2", 120, at="2026-07-02T10:00:00+00:00")])

    rows = store.history_for("speculative-decoding")

    assert [r.run_id for r in rows] == ["run-1", "run-2"]
    assert rows[1].citation_count == 120
    assert rows[1].citation_source == "s2"
    assert rows[1].resolved_impls == 2


def test_latest_excludes_run(tmp_path):
    store = TechniqueMetricsStore(tmp_path / "radar.db")
    store.initialize()
    store.record([_metric("run-1", 100, at="2026-07-01T10:00:00+00:00")])
    store.record([_metric("run-2", 120, at="2026-07-02T10:00:00+00:00")])

    assert store.latest("speculative-decoding").run_id == "run-2"
    assert store.latest("speculative-decoding", exclude_run="run-2").run_id == "run-1"
    assert store.latest("unknown-technique") is None


def test_record_empty_list_is_noop(tmp_path):
    store = TechniqueMetricsStore(tmp_path / "radar.db")
    store.initialize()

    store.record([])

    assert store.history_for("speculative-decoding") == []


def test_nullable_fields_roundtrip(tmp_path):
    store = TechniqueMetricsStore(tmp_path / "radar.db")
    store.initialize()
    store.record([_metric("run-1", None, source=None)])

    row = store.latest("speculative-decoding")

    assert row.citation_count is None
    assert row.citation_source is None
