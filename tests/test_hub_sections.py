"""Pure hub-section builders (rising ∪ new-this-week)."""

from __future__ import annotations

from datetime import UTC, datetime

from radar.models_radar.entities import ModelEntry
from radar.models_radar.history import ModelHistoryEvent
from radar.research_radar.entities import TechniqueEntry
from radar.research_radar.history import TechniqueHistoryEvent
from radar.storage.model_metrics_store import ModelMetrics
from radar.web.hub_sections import (
    build_model_section,
    build_technique_section,
)


NOW = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)  # ISO week 28: Mon 07-06 .. 07-13


def _mentry(mid: str, downloads: int, ring: str = "pilot") -> ModelEntry:
    return ModelEntry.model_validate({"id": mid, "name": mid.title(), "family": "Fam",
                                      "hf_downloads": downloads, "quants": [], "ring": ring})


def _mm(mid: str, downloads: int, day: int) -> ModelMetrics:
    return ModelMetrics(model_id=mid, run_id="r1",
                        observed_at=datetime(2026, 7, day, tzinfo=UTC), downloads=downloads)


def _mevent(mid: str, day: int, change: str = "new") -> ModelHistoryEvent:
    return ModelHistoryEvent(model_id=mid, family="Fam", change_type=change, ring="pilot",
                             previous_ring=None, run_id="r1",
                             observed_at=datetime(2026, 7, day, tzinfo=UTC), reasons=[])


def test_model_section_ranks_rising_by_growth():
    entries = [_mentry("fast", 100), _mentry("slow", 100), _mentry("flat", 100)]
    metrics = [
        *[_mm("fast", 100, 1), _mm("fast", 300, 6)],   # +200%
        *[_mm("slow", 100, 1), _mm("slow", 120, 6)],   # +20%
        *[_mm("flat", 100, 1), _mm("flat", 101, 6)],   # <5% → steady
    ]
    rows = build_model_section(entries, metrics, [], NOW)

    assert [r.id for r in rows] == ["fast", "slow"]   # rising only, fastest first
    assert rows[0].growth == 200.0 and rows[0].direction == "rising"
    assert rows[0].kind == "model"


def test_model_section_sorts_metrics_oldest_first():
    entries = [_mentry("fast", 100)]
    # rows deliberately newest-first — must still compute +200% rising, not falling
    metrics = [_mm("fast", 300, 6), _mm("fast", 100, 1)]
    rows = build_model_section(entries, metrics, [], NOW)

    assert [r.id for r in rows] == ["fast"]
    assert rows[0].growth == 200.0 and rows[0].direction == "rising"


def test_model_section_growth_bounded_to_recent_window():
    from radar.web.hub_sections import MODEL_METRICS_WINDOW
    entries = [_mentry("stale", 100)]
    # one ancient low point, then MODEL_METRICS_WINDOW flat-high points →
    # all-time growth is huge, but the recent window is flat → steady, not rising.
    metrics = [_mm("stale", 100, 1)] + [_mm("stale", 1000, 2) for _ in range(MODEL_METRICS_WINDOW)]
    rows = build_model_section(entries, metrics, [], NOW)

    assert rows == []   # bounded window sees no recent growth → not in the section


def test_model_section_unions_new_this_week():
    entries = [_mentry("newbie", 50)]
    events = [_mevent("newbie", 7, "new")]              # in week 28
    rows = build_model_section(entries, [], events, NOW)   # no metrics → no velocity

    assert [r.id for r in rows] == ["newbie"]
    assert rows[0].is_new is True and rows[0].direction == "steady"


def test_model_section_excludes_old_new_events():
    entries = [_mentry("old", 50)]
    rows = build_model_section(entries, [], [_mevent("old", 1, "new")], NOW)  # week 27
    assert rows == []


def _tentry(tid: str, momentum: int, citations: int) -> TechniqueEntry:
    return TechniqueEntry.model_validate({
        "id": tid, "name": tid.title(), "category": "ai_infrastructure", "domain": "inference",
        "onprem_impact": "reduces_latency", "citation_count": citations, "ring": "pilot",
        "score_breakdown": {"implementation_breadth": 3, "implementation_maturity": 3,
                            "validation": 3, "reproducibility": 3, "momentum": momentum,
                            "onprem_impact": 3, "average": 3.0},
    })


def _tevent(tid: str, day: int, change: str = "new") -> TechniqueHistoryEvent:
    return TechniqueHistoryEvent(technique_id=tid, domain="inference", change_type=change,
                                 ring="pilot", previous_ring=None, run_id="r1",
                                 observed_at=datetime(2026, 7, day, tzinfo=UTC), reasons=[])


def test_technique_section_ranks_high_momentum():
    entries = [_tentry("hot", 5, 900), _tentry("warm", 4, 100), _tentry("cold", 2, 999)]
    rows = build_technique_section(entries, [], NOW)

    assert [r.id for r in rows] == ["hot", "warm"]     # momentum >= 4 only
    assert rows[0].momentum == 5 and rows[0].direction == "rising"
    assert rows[0].kind == "technique"


def test_technique_section_unions_new_this_week():
    entries = [_tentry("fresh", 2, 10)]                # momentum 2 → not "rising"
    rows = build_technique_section(entries, [_tevent("fresh", 7, "promoted")], NOW)

    assert [r.id for r in rows] == ["fresh"] and rows[0].is_new is True


def test_load_hub_sections_empty_root_returns_empty(tmp_path):
    from radar.web.hub_sections import load_hub_sections
    # no runs / no data files → both sections empty, no raise
    assert load_hub_sections(tmp_path, NOW) == ([], [])


def test_load_hub_sections_swallows_errors(tmp_path, monkeypatch):
    from radar.web import hub_sections

    def _boom(*a, **k):
        raise RuntimeError("store exploded")

    # a raise inside the build must degrade to ([], []), never propagate
    monkeypatch.setattr(hub_sections, "build_model_section", _boom)
    assert hub_sections.load_hub_sections(tmp_path, NOW) == ([], [])


def test_load_hub_sections_model_failure_isolated(tmp_path, monkeypatch):
    from radar.web import hub_sections

    # a raise isolated to the model section must not empty the healthy technique section
    monkeypatch.setattr(hub_sections, "build_model_section",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    model_rows, technique_rows = hub_sections.load_hub_sections(tmp_path, NOW)
    assert model_rows == [] and technique_rows == []   # model failure caught, technique unaffected
