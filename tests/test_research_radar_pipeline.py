"""Pipeline integration: assemble → momentum → score → persist, offline determinism."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from radar.models import Ring
from radar.research_radar.citations import CitationRecord
from radar.research_radar.entities import TechniqueSeed
from radar.research_radar.pipeline import (
    assemble_entries,
    persist_technique_scan,
    run_research_scan,
    score_technique_entries,
)
from radar.research_radar.resolve import ResolutionContext
from radar.storage.technique_metrics_store import TechniqueMetricsStore


NOW = datetime(2026, 7, 3, 10, 0, tzinfo=UTC)

SEED_YAML = """
techniques:
  - id: speculative-decoding
    name: Speculative Decoding
    category: model_serving
    domain: inference
    papers:
      - arxiv_id: "2211.17192"
        title: "Fast Inference from Transformers via Speculative Decoding"
    implementations:
      - kind: tool
        ref: github-vllm
      - kind: tool
        ref: github-llama-cpp
      - kind: tool
        ref: github-gone-tool
    open_code: true
    onprem_impact: reduces_latency
  - id: qlora
    name: QLoRA
    category: ai_infrastructure
    domain: fine_tuning
    papers:
      - arxiv_id: "2305.14314"
        title: "QLoRA"
    open_code: true
    onprem_impact: reduces_memory
  - id: disabled-one
    name: Disabled
    category: model_serving
    domain: inference
    onprem_impact: reduces_latency
    enabled: false
"""


def _seeds() -> list[TechniqueSeed]:
    import yaml

    raw = yaml.safe_load(SEED_YAML)
    return [TechniqueSeed.model_validate(item) for item in raw["techniques"]]


def _context() -> ResolutionContext:
    return ResolutionContext(
        tool_rings={"github-vllm": Ring.ADOPT, "github-llama-cpp": Ring.ADOPT},
        model_rings={},
    )


def _citations() -> dict[str, CitationRecord]:
    return {"2211.17192": CitationRecord(
        arxiv_id="2211.17192", citation_count=1697, venue="ICML",
        peer_reviewed=True, source="s2",
    )}


def test_assemble_resolves_warns_and_skips_disabled(tmp_path):
    store = TechniqueMetricsStore(tmp_path / "radar.db")
    store.initialize()

    entries = assemble_entries(_seeds(), _context(), _citations(), store)

    assert [e.id for e in entries] == ["qlora", "speculative-decoding"]  # sorted, no disabled
    spec = entries[1]
    assert len(spec.resolved_implementations) == 2  # gone-tool dropped
    assert any("github-gone-tool" in w for w in spec.warnings)
    assert spec.citation_count == 1697
    assert spec.peer_reviewed is True
    qlora = entries[0]
    assert qlora.citation_count is None
    assert any("citations unknown" in w for w in qlora.warnings)


def test_assemble_falls_back_to_last_known_citations(tmp_path):
    from radar.storage.technique_metrics_store import TechniqueMetrics

    store = TechniqueMetricsStore(tmp_path / "radar.db")
    store.initialize()
    store.record([TechniqueMetrics(
        technique_id="qlora", run_id="run-0", observed_at=NOW,
        citation_count=800, citation_source="s2", resolved_impls=0,
    )])

    entries = assemble_entries(_seeds(), _context(), {}, store)

    qlora = next(e for e in entries if e.id == "qlora")
    assert qlora.citation_count == 800
    assert qlora.citation_source == "s2"
    assert any("last-known" in w for w in qlora.warnings)


def test_score_and_ring_closed_loop(tmp_path):
    store = TechniqueMetricsStore(tmp_path / "radar.db")
    store.initialize()
    entries = assemble_entries(_seeds(), _context(), _citations(), store)

    scored = score_technique_entries(entries, store)

    by_id = {e.id: e for e in scored}
    # Two adopt-ring impls + peer-reviewed 1697 citations + open code → ADOPT.
    spec = by_id["speculative-decoding"]
    assert spec.score_breakdown.implementation_maturity == 5
    assert spec.score_breakdown.validation == 5
    assert spec.ring == Ring.ADOPT
    # No resolved implementations → capped at WATCH despite open code.
    assert by_id["qlora"].ring == Ring.WATCH


def test_persist_appends_history_and_metrics_once(tmp_path):
    db = tmp_path / "radar.db"
    history = tmp_path / "technique-history.jsonl"
    store = TechniqueMetricsStore(db)
    store.initialize()
    entries = score_technique_entries(
        assemble_entries(_seeds(), _context(), _citations(), store), store
    )

    events_first = persist_technique_scan(entries, "run-1", NOW, db, history)
    events_second = persist_technique_scan(entries, "run-2", NOW, db, history)

    assert {e.technique_id for e in events_first} == {"speculative-decoding", "qlora"}
    assert events_second == []  # unchanged rings emit nothing
    assert len(store.history_for("speculative-decoding")) == 2


@pytest.mark.asyncio
async def test_run_research_scan_offline_is_deterministic(tmp_path):
    """Both citation APIs down → warnings, neutral validation, same rings twice."""

    class _DownClient:
        async def post(self, url, **kwargs):
            raise RuntimeError("offline")

        async def get(self, url, **kwargs):
            raise RuntimeError("offline")

    seed_path = tmp_path / "technique-seed.yaml"
    seed_path.write_text(SEED_YAML, encoding="utf-8")

    async def _scan():
        return await run_research_scan(
            seed_path=seed_path,
            config_path=tmp_path / "missing-config.yaml",
            db_path=tmp_path / "radar.db",
            model_seed_path=tmp_path / "missing-model-seed.yaml",
            model_history_path=tmp_path / "model-history.jsonl",
            history_path=tmp_path / "technique-history.jsonl",
            client=_DownClient(),
        )

    entries_a, _events_a = await _scan()
    entries_b, events_b = await _scan()

    assert [e.ring for e in entries_a] == [e.ring for e in entries_b]
    # config missing → vllm/llama-cpp unresolved → spec-decoding also capped at WATCH
    assert all(e.ring == Ring.WATCH for e in entries_a)
    assert events_b == []  # second scan: nothing changed
    assert all(any("citations unknown" in w for w in e.warnings) for e in entries_a)


@pytest.mark.asyncio
async def test_rehydration_restores_velocity_after_db_loss(tmp_path):
    """Fresh DB + metrics log == warm DB: momentum sees the prior scan."""
    from radar.storage.technique_metrics_log import load_metrics
    from radar.storage.technique_metrics_store import TechniqueMetricsStore

    class _DownClient:
        async def post(self, url, **kwargs):
            raise RuntimeError("offline")

        async def get(self, url, **kwargs):
            raise RuntimeError("offline")

    seed_path = tmp_path / "technique-seed.yaml"
    seed_path.write_text(SEED_YAML, encoding="utf-8")
    log_path = tmp_path / "technique-metrics.jsonl"

    async def _scan(db_name: str):
        return await run_research_scan(
            seed_path=seed_path,
            config_path=tmp_path / "missing-config.yaml",
            db_path=tmp_path / db_name,
            model_seed_path=tmp_path / "missing-model-seed.yaml",
            model_history_path=tmp_path / "model-history.jsonl",
            history_path=tmp_path / "technique-history.jsonl",
            client=_DownClient(),
            metrics_log_path=log_path,
        )

    await _scan("radar.db")                      # scan 1: writes rows to db + log
    assert len(load_metrics(log_path)) > 0       # dual-write happened

    _entries, _ = await _scan("fresh-radar.db")  # scan 2: NEW empty db, log present

    fresh_store = TechniqueMetricsStore(tmp_path / "fresh-radar.db")
    fresh_store.initialize()
    rows = fresh_store.history_for("qlora")
    assert len(rows) >= 2                        # rehydrated scan-1 row + scan-2 row


@pytest.mark.asyncio
async def test_warm_store_is_never_rehydrated(tmp_path):
    """A non-empty store ignores the log entirely (no duplicate rows)."""
    from datetime import UTC as _UTC
    from datetime import datetime as _dt

    from radar.storage.technique_metrics_log import append_metrics
    from radar.storage.technique_metrics_store import (
        TechniqueMetrics,
        TechniqueMetricsStore,
    )

    class _DownClient:
        async def post(self, url, **kwargs):
            raise RuntimeError("offline")

        async def get(self, url, **kwargs):
            raise RuntimeError("offline")

    seed_path = tmp_path / "technique-seed.yaml"
    seed_path.write_text(SEED_YAML, encoding="utf-8")
    db_path = tmp_path / "radar.db"
    store = TechniqueMetricsStore(db_path)
    store.initialize()
    store.record([TechniqueMetrics(
        technique_id="qlora", run_id="warm-run",
        observed_at=_dt(2026, 7, 1, tzinfo=_UTC), citation_count=1,
        citation_source="s2", resolved_impls=0,
    )])
    log_path = tmp_path / "technique-metrics.jsonl"
    append_metrics(log_path, [TechniqueMetrics(
        technique_id="qlora", run_id="log-only-run",
        observed_at=_dt(2026, 6, 1, tzinfo=_UTC), citation_count=99,
        citation_source="s2", resolved_impls=0,
    )])

    await run_research_scan(
        seed_path=seed_path, config_path=tmp_path / "missing-config.yaml",
        db_path=db_path, model_seed_path=tmp_path / "missing-model-seed.yaml",
        model_history_path=tmp_path / "model-history.jsonl",
        history_path=tmp_path / "technique-history.jsonl",
        client=_DownClient(), metrics_log_path=log_path,
    )

    runs = {r.run_id for r in TechniqueMetricsStore(db_path).history_for("qlora")}
    assert "log-only-run" not in runs  # warm store untouched by the log
