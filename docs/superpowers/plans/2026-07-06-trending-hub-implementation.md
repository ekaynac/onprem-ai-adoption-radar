# Trending Hub (Models + Techniques) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give models and techniques frontend parity with the repo trending radar — a "Trending Models" and "Trending Techniques" section on `/trending` (dashboard + static site) showing the fastest-rising items + those new/promoted this week — and make model download-velocity durable in production via a committed metrics log.

**Architecture:** A committed `data/model-metrics.jsonl` (mirror of `technique_metrics_log.py`) makes model download-growth durable across CI runs. A pure `web/hub_sections.py` builds each section (rising ∪ new-this-week) from committed data, with a guarded loader so a corrupt store never breaks `/trending` or the daily export. The `/trending` route, static writer, and index strip render both sections below the existing repo lanes.

**Tech Stack:** Python 3.12, pydantic v2, FastAPI + Jinja2, typer (all in-tree; **no new dependencies**), pytest + ruff + mypy.

**Spec:** `docs/superpowers/specs/2026-07-06-trending-hub-design.md` (Phase 1). Phase 2 (untracked model/paper discovery) is a separate future spec.

## Global Constraints

- Deterministic + offline render: everything derives from committed files; only the route/CLI boundary reads `datetime.now(UTC)` — the builders take `now` as a parameter and are pure.
- **Guarded reads (daily-publish invariant):** a corrupt/absent metrics or history store degrades to an empty section — never a 500 on `/trending`, never a crash in `radar export`. New JSONL loaders use `errors="replace"` + `except OSError` + per-line `except ValueError` (the hardened pattern from `trending_observations_log.py`/`digest_log.py`, an improvement over the older `technique_metrics_log.py`).
- No untracked-candidate discovery (Phase 2); no new detail pages (rows link to `/model/{id}` and `/technique/{id}`); no network in render; no new Python dependencies.
- Focused cut, not a catalog dupe: each section shows top-N rising ∪ new-this-week; empty → a quiet note, not the full catalog.
- ISO-week window (Monday→Monday) for the NEW flag, reusing `radar.reports.digest.iso_week_bounds`.
- ruff line-length = 100; `python_version = 3.12`; every file starts with `from __future__ import annotations`.
- Coverage ≥ 80%; gates `uv run pytest`, `uv run ruff check .`, `uv run mypy src/radar`.
- Commit format `<type>: <description>`; `git add` specific paths only (unrelated modified `data/history.jsonl` never committed).
- Existing symbols consumed (all on main): `ModelMetrics` (`radar.storage.model_metrics_store`), `compute_model_momentum`/`ModelMomentum` (`radar.models_radar.momentum`), `ModelEntry` + `_latest_model_cards` (`radar.mcp_server.model_queries`), `load_model_events` (`radar.models_radar.history`), `persist_model_scan` (`radar.models_radar.pipeline`), `TechniqueEntry` (`radar.research_radar.entities`, carries `score_breakdown.momentum: int 1-5`, `citation_count`, `ring`), `load_technique_entries` (`radar.mcp_server.technique_queries`), `load_technique_events` (`radar.research_radar.history`), `iso_week_bounds` (`radar.reports.digest`), the `/trending` route + `trending.html`/`static_trending.html`/`_trending_summary.html` from the repo trending sub-project.

## File Structure

```
src/radar/storage/model_metrics_log.py       # NEW: append_model_metrics / load_model_metrics (committed JSONL)
src/radar/models_radar/pipeline.py            # MODIFY: persist_model_scan gains metrics_log_path
src/radar/cli.py                              # MODIFY: models scan passes the log path; export threads hub rows
.github/workflows/publish.yml                  # MODIFY: commit data/model-metrics.jsonl
src/radar/web/hub_sections.py                 # NEW: HubRow + build_model_section/build_technique_section (pure) + load_hub_sections (guarded gateway)
src/radar/web/app.py                          # MODIFY: /trending renders both sections; index strip top model/technique
src/radar/web/static_site.py                  # MODIFY: render both sections + static index strip
src/radar/web/templates/
    trending.html static_trending.html          # MODIFY: Models + Techniques sections
    _trending_summary.html                       # MODIFY: top rising model + technique in the strip
tests/test_model_metrics_log.py test_hub_sections.py   # NEW
tests/test_models_scan_metrics_log.py test_publish_workflow.py  # NEW / MODIFY
tests/test_web.py test_static_site.py          # MODIFY
README.md CHANGELOG.md                          # MODIFY
```

---

### Task 1: Committed model-metrics log

**Files:**
- Create: `src/radar/storage/model_metrics_log.py`
- Test: `tests/test_model_metrics_log.py`

**Interfaces:**
- Consumes: `ModelMetrics` (`radar.storage.model_metrics_store`: `model_id, run_id, observed_at, downloads, likes, min_memory_gb, ring, hardware_tier`).
- Produces: `append_model_metrics(path: Path, rows: list[ModelMetrics]) -> None` (append-only JSONL, mkdir parents, no-op empty) and `load_model_metrics(path: Path) -> list[ModelMetrics]` (missing → `[]`; corrupt lines skipped with a warning; guarded file read via `errors="replace"` + `except OSError`). Task 2/4 import these.

- [ ] **Step 1: Write the failing tests**

```python
"""Append-only JSONL log of model metrics (makes download velocity durable)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from radar.storage.model_metrics_log import append_model_metrics, load_model_metrics
from radar.storage.model_metrics_store import ModelMetrics


def _m(model_id: str, downloads: int, day: int) -> ModelMetrics:
    return ModelMetrics(model_id=model_id, run_id="r1",
                        observed_at=datetime(2026, 7, day, tzinfo=UTC),
                        downloads=downloads, ring="pilot", hardware_tier="workstation")


def test_round_trip_and_noop_empty(tmp_path: Path):
    path = tmp_path / "model-metrics.jsonl"
    append_model_metrics(path, [_m("qwen3-0.6b", 100, 1)])
    append_model_metrics(path, [_m("qwen3-0.6b", 180, 4)])
    append_model_metrics(path, [])

    rows = load_model_metrics(path)
    assert [r.downloads for r in rows] == [100, 180]


def test_missing_and_corrupt(tmp_path: Path):
    assert load_model_metrics(tmp_path / "nope.jsonl") == []
    path = tmp_path / "model-metrics.jsonl"
    append_model_metrics(path, [_m("qwen3-0.6b", 100, 1)])
    with path.open("a", encoding="utf-8") as h:
        h.write("{broken\n")
    assert len(load_model_metrics(path)) == 1


def test_non_utf8_bytes_are_skipped(tmp_path: Path):
    path = tmp_path / "model-metrics.jsonl"
    append_model_metrics(path, [_m("qwen3-0.6b", 100, 1)])
    with path.open("ab") as h:
        h.write(b"\xff\xfe broken\n")
    assert len(load_model_metrics(path)) == 1  # guarded read, no raise
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_model_metrics_log.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

Create `src/radar/storage/model_metrics_log.py`:

```python
"""Append-only JSONL log of model metrics (mirror of the history/metrics logs).

CI does not persist ``radar.db`` between runs, so download velocity would
always read "first scan" on the published site. ``models scan`` appends each
run's metric rows here; the publish workflow commits the file, which makes
model download-growth durable — the same pattern technique-metrics.jsonl uses
for citation velocity.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from radar.storage.model_metrics_store import ModelMetrics


logger = logging.getLogger(__name__)


def append_model_metrics(path: Path, rows: list[ModelMetrics]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(r.model_dump(mode="json"), ensure_ascii=False) for r in rows]
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def load_model_metrics(path: Path) -> list[ModelMetrics]:
    if not path.exists():
        return []
    rows: list[ModelMetrics] = []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line_no, raw in enumerate(handle, start=1):
                line = raw.strip()
                if not line:
                    continue
                try:
                    rows.append(ModelMetrics.model_validate_json(line))
                except ValueError as exc:
                    logger.warning("Skipping corrupt model-metrics line %d in %s: %s",
                                   line_no, path, exc)
    except OSError as exc:
        logger.warning("Could not read model-metrics store %s: %s", path, exc)
    return rows
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_model_metrics_log.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Lint + typecheck + commit**

```bash
uv run ruff check src/radar/storage tests/test_model_metrics_log.py && uv run mypy src/radar
git add src/radar/storage/model_metrics_log.py tests/test_model_metrics_log.py
git commit -m "feat: committed model-metrics log (durable download velocity)"
```

---

### Task 2: Wire the log into `models scan` + CI

**Files:**
- Modify: `src/radar/models_radar/pipeline.py` (`persist_model_scan`), `src/radar/cli.py` (`models scan`), `.github/workflows/publish.yml`
- Test: `tests/test_models_scan_metrics_log.py`, `tests/test_publish_workflow.py` (append)

**Interfaces:**
- Consumes: `append_model_metrics` (Task 1).
- Produces: `persist_model_scan(entries, run_id, observed_at, db_path, history_path, metrics_log_path: Path | None = None) -> list[ModelHistoryEvent]` — after building the `rows: list[ModelMetrics]` and `store.record(rows)`, if `metrics_log_path` is not None, `append_model_metrics(metrics_log_path, rows)`. `models scan` passes `root/"data"/"model-metrics.jsonl"`. publish.yml commits it.

- [ ] **Step 1: Write the failing test (tests/test_models_scan_metrics_log.py)**

```python
"""persist_model_scan appends metrics to the committed log when a path is given."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from radar.models_radar.entities import ModelEntry
from radar.models_radar.pipeline import persist_model_scan
from radar.storage.model_metrics_log import load_model_metrics


def _entry() -> ModelEntry:
    # Minimal valid ModelEntry — adjust required fields to the real schema if needed;
    # the load-bearing assertion is that a metrics row lands in the log.
    return ModelEntry.model_validate({
        "id": "qwen3-0.6b", "name": "Qwen3-0.6B", "family": "Qwen3",
        "hf_downloads": 1234, "quants": [],
    })


def test_persist_appends_to_metrics_log(tmp_path: Path):
    log = tmp_path / "data" / "model-metrics.jsonl"
    persist_model_scan(
        [_entry()], "r1", datetime(2026, 7, 6, tzinfo=UTC),
        tmp_path / "data" / "radar.db", tmp_path / "data" / "model-history.jsonl",
        metrics_log_path=log,
    )

    rows = load_model_metrics(log)
    assert len(rows) == 1 and rows[0].model_id == "qwen3-0.6b"
    assert rows[0].downloads == 1234


def test_persist_without_log_path_is_unchanged(tmp_path: Path):
    # back-compat: omitting metrics_log_path writes no log, doesn't raise
    persist_model_scan(
        [_entry()], "r1", datetime(2026, 7, 6, tzinfo=UTC),
        tmp_path / "data" / "radar.db", tmp_path / "data" / "model-history.jsonl",
    )
    assert not (tmp_path / "data" / "model-metrics.jsonl").exists()
```

NOTE for the implementer: construct `_entry()` to satisfy the real `ModelEntry` schema (read `src/radar/models_radar/entities.py`); if `minimum_viable_quant(entry.quants)` needs a non-empty `quants`, give it a minimal valid quant. The contract is "a ModelMetrics row is appended per entry."

- [ ] **Step 2: Append the workflow test (tests/test_publish_workflow.py)**

```python
def test_publish_commits_model_metrics_log():
    text = Path(".github/workflows/publish.yml").read_text(encoding="utf-8")
    assert "data/model-metrics.jsonl" in text
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_models_scan_metrics_log.py tests/test_publish_workflow.py -v -k "metrics_log or model_metrics"`
Expected: FAIL — `TypeError` (no `metrics_log_path`) / substring not found

- [ ] **Step 4: Wire persist_model_scan**

In `src/radar/models_radar/pipeline.py`: add `from radar.storage.model_metrics_log import append_model_metrics` at the top; change the signature to `def persist_model_scan(entries, run_id, observed_at, db_path, history_path, metrics_log_path: Path | None = None) -> list[ModelHistoryEvent]:`; after `store.record(rows)` and before `return events`, add:

```python
    if metrics_log_path is not None:
        append_model_metrics(metrics_log_path, rows)
```

- [ ] **Step 5: Wire models scan + publish.yml**

In `src/radar/cli.py` `models_scan`, change the `persist_model_scan(...)` call to pass the log path:

```python
    persist_model_scan(
        entries, run_id, observed_at,
        root / "data" / "radar.db", root / "data" / "model-history.jsonl",
        metrics_log_path=root / "data" / "model-metrics.jsonl",
    )
```

In `.github/workflows/publish.yml`, in the history-commit block, after the `git add -f data/model-history.jsonl` line, add:

```yaml
          git add -f data/model-metrics.jsonl || true
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_models_scan_metrics_log.py tests/test_publish_workflow.py -v`
Expected: PASS

- [ ] **Step 7: Lint + typecheck + commit**

```bash
uv run ruff check src/radar tests/test_models_scan_metrics_log.py tests/test_publish_workflow.py && uv run mypy src/radar
git add src/radar/models_radar/pipeline.py src/radar/cli.py .github/workflows/publish.yml \
  tests/test_models_scan_metrics_log.py tests/test_publish_workflow.py
git commit -m "feat: models scan appends the committed model-metrics log"
```

---

### Task 3: Pure hub-section builders

**Files:**
- Create: `src/radar/web/hub_sections.py`
- Test: `tests/test_hub_sections.py`

**Interfaces:**
- Consumes: `ModelEntry`, `ModelMetrics`, `ModelHistoryEvent`, `compute_model_momentum`; `TechniqueEntry`, `TechniqueHistoryEvent`; `iso_week_bounds`.
- Produces (pure):
  - `HubRow` (frozen): `id: str`, `name: str`, `subtitle: str`, `metric: int | None`, `growth: float | None`, `momentum: int | None`, `direction: str`, `ring: str | None`, `is_new: bool`, `kind: str` (`"model"` | `"technique"`). The row carries `kind`+`id`, NOT a baked href, because live (`/model/{id}`) and static (`model_{slug}.html`) detail-page URLs differ — the template builds the link per surface.
  - `RISING_MOMENTUM = 4` (technique momentum score at/above which a technique counts as rising).
  - `build_model_section(entries: list[ModelEntry], model_metrics: list[ModelMetrics], model_events: list[ModelHistoryEvent], now: datetime, *, top_n: int = 10) -> list[HubRow]` — per model, `compute_model_momentum` from its metrics (grouped by id) + its events; the top `top_n` with `direction == "rising"` sorted by `downloads_growth_pct` desc, then any model with a `new`/`promoted` event in `iso_week_bounds(now)` not already included (`is_new=True`). Rows: rising first, then new, then name.
  - `build_technique_section(entries: list[TechniqueEntry], technique_events: list[TechniqueHistoryEvent], now: datetime, *, top_n: int = 10) -> list[HubRow]` — techniques with momentum `>= RISING_MOMENTUM` sorted by momentum desc then citation_count desc (the top `top_n`), unioned with new/promoted-this-week. (Techniques carry momentum on the entry — no metrics load needed.)

- [ ] **Step 1: Write the failing tests**

```python
"""Pure hub-section builders (rising ∪ new-this-week)."""

from __future__ import annotations

from datetime import UTC, datetime

from radar.models_radar.entities import ModelEntry
from radar.models_radar.history import ModelHistoryEvent
from radar.research_radar.entities import TechniqueEntry
from radar.research_radar.history import TechniqueHistoryEvent
from radar.storage.model_metrics_store import ModelMetrics
from radar.web.hub_sections import (
    HubRow,
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
    metrics = ([_mm("fast", 100, 1), _mm("fast", 300, 6)]      # +200%
               + [_mm("slow", 100, 1), _mm("slow", 120, 6)]    # +20%
               + [_mm("flat", 100, 1), _mm("flat", 101, 6)])   # <5% → steady
    rows = build_model_section(entries, metrics, [], NOW)

    assert [r.id for r in rows] == ["fast", "slow"]   # rising only, fastest first
    assert rows[0].growth == 200.0 and rows[0].direction == "rising"
    assert rows[0].kind == "model"


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
        "id": tid, "name": tid.title(), "category": "reasoning", "domain": "reasoning",
        "onprem_impact": "high", "citation_count": citations, "ring": "pilot",
        "score_breakdown": {"implementation_breadth": 3, "implementation_maturity": 3,
                            "validation": 3, "reproducibility": 3, "momentum": momentum,
                            "onprem_impact": 3, "average": 3.0},
    })


def _tevent(tid: str, day: int, change: str = "new") -> TechniqueHistoryEvent:
    return TechniqueHistoryEvent(technique_id=tid, domain="reasoning", change_type=change,
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
```

NOTE: adjust the minimal `ModelEntry`/`TechniqueEntry`/event `model_validate` dicts to the real required fields (read the entity modules); the assertions are the contract.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_hub_sections.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

Create `src/radar/web/hub_sections.py`:

```python
"""Trending-hub sections for models & techniques (rising ∪ new-this-week).

Pure builders (``now`` is a parameter) plus one guarded loader that reads the
committed stores. A corrupt/absent store degrades to an empty section — never a
raise — so ``/trending`` and the daily export can never break on hub data.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from radar.models_radar.entities import ModelEntry
from radar.models_radar.history import ModelHistoryEvent
from radar.models_radar.momentum import compute_model_momentum
from radar.reports.digest import iso_week_bounds
from radar.research_radar.entities import TechniqueEntry
from radar.research_radar.history import TechniqueHistoryEvent
from radar.storage.model_metrics_store import ModelMetrics


logger = logging.getLogger(__name__)

RISING_MOMENTUM = 4
_NEW_CHANGES = {"new", "promoted"}


class HubRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    subtitle: str
    metric: int | None
    growth: float | None
    momentum: int | None
    direction: str
    ring: str | None
    is_new: bool
    kind: str  # "model" | "technique" — template builds the per-surface link


def _new_ids(events: list, now: datetime, id_attr: str) -> set[str]:
    start, end = iso_week_bounds(now)
    return {
        getattr(ev, id_attr) for ev in events
        if ev.change_type.value in _NEW_CHANGES and start <= ev.observed_at < end
    }


def build_model_section(
    entries: list[ModelEntry],
    model_metrics: list[ModelMetrics],
    model_events: list[ModelHistoryEvent],
    now: datetime,
    *,
    top_n: int = 10,
) -> list[HubRow]:
    metrics_by_id: dict[str, list[ModelMetrics]] = {}
    for m in model_metrics:
        metrics_by_id.setdefault(m.model_id, []).append(m)
    events_by_id: dict[str, list[ModelHistoryEvent]] = {}
    for ev in model_events:
        events_by_id.setdefault(ev.model_id, []).append(ev)
    new_ids = _new_ids(model_events, now, "model_id")

    def _row(entry: ModelEntry, mom, is_new: bool) -> HubRow:
        return HubRow(
            id=entry.id, name=entry.name, subtitle=entry.family,
            metric=entry.hf_downloads, growth=mom.downloads_growth_pct, momentum=None,
            direction=mom.direction, ring=entry.ring.value if entry.ring else None,
            is_new=is_new, kind="model",
        )

    scored = [
        (e, compute_model_momentum(e.id, metrics_by_id.get(e.id, []), events_by_id.get(e.id, [])))
        for e in entries
    ]
    rising = sorted(
        (em for em in scored if em[1].direction == "rising"),
        key=lambda em: -(em[1].downloads_growth_pct or 0.0),
    )[:top_n]
    rows = [_row(e, m, e.id in new_ids) for e, m in rising]
    seen = {e.id for e, _ in rising}
    rows += [_row(e, m, True) for e, m in scored if e.id in new_ids and e.id not in seen]
    return rows


def build_technique_section(
    entries: list[TechniqueEntry],
    technique_events: list[TechniqueHistoryEvent],
    now: datetime,
    *,
    top_n: int = 10,
) -> list[HubRow]:
    new_ids = _new_ids(technique_events, now, "technique_id")

    def _momentum(e: TechniqueEntry) -> int:
        return e.score_breakdown.momentum if e.score_breakdown else 0

    def _row(entry: TechniqueEntry, is_new: bool) -> HubRow:
        mom = _momentum(entry)
        direction = "rising" if mom >= RISING_MOMENTUM else "falling" if mom <= 2 else "steady"
        return HubRow(
            id=entry.id, name=entry.name, subtitle=entry.domain.value,
            metric=entry.citation_count, growth=None, momentum=mom, direction=direction,
            ring=entry.ring.value if entry.ring else None, is_new=is_new,
            kind="technique",
        )

    rising = sorted(
        (e for e in entries if _momentum(e) >= RISING_MOMENTUM),
        key=lambda e: (-_momentum(e), -(e.citation_count or 0), e.name),
    )[:top_n]
    rows = [_row(e, e.id in new_ids) for e in rising]
    seen = {e.id for e in rising}
    rows += [_row(e, True) for e in entries if e.id in new_ids and e.id not in seen]
    return rows


def load_hub_sections(root: Path, now: datetime) -> tuple[list[HubRow], list[HubRow]]:
    """Guarded gateway: build both sections from committed stores; ([], []) on any failure."""
    from radar.mcp_server.model_queries import _latest_model_cards
    from radar.mcp_server.technique_queries import load_technique_entries
    from radar.models_radar.history import load_model_events
    from radar.research_radar.history import load_technique_events
    from radar.storage.model_metrics_log import load_model_metrics

    try:
        root = Path(root)
        model_entries = [ModelEntry.model_validate(c) for c in _latest_model_cards(root)]
        model_rows = build_model_section(
            model_entries,
            load_model_metrics(root / "data" / "model-metrics.jsonl"),
            load_model_events(root / "data" / "model-history.jsonl"),
            now,
        )
        technique_rows = build_technique_section(
            load_technique_entries(root),
            load_technique_events(root / "data" / "technique-history.jsonl"),
            now,
        )
        return model_rows, technique_rows
    except Exception as exc:
        logger.warning("Trending-hub sections unavailable under %s: %s", root, exc)
        return [], []
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_hub_sections.py -v`
Expected: PASS. If `ChangeType`/enum coercion or a required entity field trips validation, fix the test fixtures to the real schema (not the assertions).

- [ ] **Step 5: Lint + typecheck + commit**

```bash
uv run ruff check src/radar/web/hub_sections.py tests/test_hub_sections.py && uv run mypy src/radar
git add src/radar/web/hub_sections.py tests/test_hub_sections.py
git commit -m "feat: pure trending-hub section builders (models + techniques)"
```

---

### Task 4: Live `/trending` sections + index strip

**Files:**
- Modify: `src/radar/web/app.py`, `src/radar/web/templates/trending.html`, `src/radar/web/templates/_trending_summary.html`
- Test: `tests/test_web.py` (append)

**Interfaces:**
- Consumes: `load_hub_sections` (Task 3).
- Produces: `/trending` renders `model_hub` + `technique_hub` (`list[HubRow]`) below the repo lanes; the index route passes `top_model`/`top_technique` (first rising HubRow of each, or `None`) into `_trending_summary.html`.

- [ ] **Step 1: Write the failing tests (append to tests/test_web.py)**

```python
def _seed_model_run_and_metrics(root: Path) -> None:
    """A models run + a 2-point metrics log so a model reads 'rising'."""
    from datetime import UTC, datetime

    from radar.models_radar.entities import ModelEntry
    from radar.storage.model_metrics_log import append_model_metrics
    from radar.storage.model_metrics_store import ModelMetrics
    from radar.storage.run_store import RunStore

    (root / "data").mkdir(parents=True, exist_ok=True)
    entry = ModelEntry.model_validate({"id": "risingmodel", "name": "RisingModel",
                                       "family": "Fam", "hf_downloads": 5000,
                                       "quants": [], "ring": "pilot"})
    rs = RunStore(root / "data" / "runs")
    rid = rs.create_run()
    rs.update_meta(rid, {"kind": "models"})
    rs.save_stage(rid, "model_cards", [entry.model_dump(mode="json")])
    append_model_metrics(root / "data" / "model-metrics.jsonl", [
        ModelMetrics(model_id="risingmodel", run_id="r0",
                     observed_at=datetime(2026, 7, 1, tzinfo=UTC), downloads=1000),
        ModelMetrics(model_id="risingmodel", run_id="r1",
                     observed_at=datetime(2026, 7, 6, tzinfo=UTC), downloads=5000),
    ])


def test_trending_page_shows_model_and_technique_sections(tmp_path):
    _seed_model_run_and_metrics(tmp_path)
    client = TestClient(create_app(tmp_path))

    r = client.get("/trending")

    assert r.status_code == 200
    assert "Trending Models" in r.text
    assert "Trending Techniques" in r.text
    assert "risingmodel" in r.text
    assert 'href="/model/risingmodel"' in r.text


def test_trending_page_survives_empty_hub(tmp_path):
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    client = TestClient(create_app(tmp_path))

    r = client.get("/trending")

    assert r.status_code == 200                 # no run/metrics → empty sections, still 200
    assert "Trending Models" in r.text          # section header present even when empty
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_web.py -v -k "model_and_technique or empty_hub"`
Expected: FAIL — sections not rendered

- [ ] **Step 3: Wire the route + index**

In `src/radar/web/app.py`: import `from radar.web.hub_sections import load_hub_sections`. Add a helper near `_trending_entries`:

```python
    def _hub_sections():
        from datetime import UTC, datetime
        return load_hub_sections(root, datetime.now(UTC))
```

In the `/trending` route, build and pass both sections:

```python
    @app.get("/trending", response_class=HTMLResponse)
    def trending_page(request: Request):
        entries = _trending_entries()
        onprem = [e for e in entries if e.lane == Lane.ONPREM]
        broader = [e for e in entries if e.lane == Lane.BROADER]
        model_hub, technique_hub = _hub_sections()
        return TEMPLATES.TemplateResponse(request, "trending.html", {
            "onprem": onprem, "broader": broader,
            "model_hub": model_hub, "technique_hub": technique_hub,
        })
```

In the index route context, add the top rising of each for the strip:

```python
                "top_model": next((r for r in _hub_sections()[0] if not r.is_new), None),
                "top_technique": next((r for r in _hub_sections()[1] if not r.is_new), None),
```

(Prefer one `_hub_sections()` call: compute `mh, th = _hub_sections()` once in `index()` and reference `mh`/`th`.)

- [ ] **Step 4: Add the template sections + strip**

In `src/radar/web/templates/trending.html`, after the repo-lanes block and before `</main>`, add the hub sections (this exact snippet is reused byte-for-byte in the static template in Task 5):

```html
      {% for title, rows, kind in [("Trending Models", model_hub, "model"),
                                    ("Trending Techniques", technique_hub, "technique")] %}
      <h2>{{ title }}</h2>
      {% if not rows %}<p>No trending {{ kind }}s this week.</p>{% endif %}
      {% if rows %}
      <table>
        <thead><tr><th>{{ kind|capitalize }}</th><th>{{ "Family" if kind == "model" else "Domain" }}</th>
          <th>{{ "Downloads" if kind == "model" else "Citations" }}</th>
          <th>Momentum</th><th>Ring</th><th></th></tr></thead>
        <tbody>
          {% for r in rows %}
          <tr>
            <td><a href="/{{ r.kind }}/{{ r.id }}">{{ r.name }}</a></td>
            <td>{{ r.subtitle }}</td>
            <td>{% if r.metric is not none %}{{ r.metric }}{% else %}—{% endif %}</td>
            <td>{% if r.growth is not none %}{{ "%+.1f"|format(r.growth) }}%{% elif r.momentum is not none %}{{ r.momentum }}/5{% else %}—{% endif %} {{ r.direction }}</td>
            <td>{{ r.ring or "—" }}</td>
            <td>{% if r.is_new %}NEW{% endif %}</td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
      {% endif %}
      {% endfor %}
```

The link `/{{ r.kind }}/{{ r.id }}` matches the LIVE routes (`/model/{id}`, `/technique/{id}`). The static template (Task 5) uses the same section body but a slug-based link line — the one line that differs between the live and static templates (the established live/static convention).

In `src/radar/web/templates/_trending_summary.html`, inside the `<details>` (after the repo `<ul>`), add the top rising model + technique as plain text (no link — the strip is a teaser that works identically on the live and static index; the linked table lives on `/trending`):

```html
    {% if top_model %}<p>🤖 Top model: {{ top_model.name }}
        {% if top_model.growth is not none %}({{ "%+.1f"|format(top_model.growth) }}%){% endif %}</p>{% endif %}
    {% if top_technique %}<p>🎓 Top technique: {{ top_technique.name }}
        {% if top_technique.momentum is not none %}({{ top_technique.momentum }}/5){% endif %}</p>{% endif %}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_web.py -v`
Expected: PASS (new + existing)

- [ ] **Step 6: Lint + typecheck + commit**

```bash
uv run ruff check src/radar/web tests/test_web.py && uv run mypy src/radar
git add src/radar/web/app.py src/radar/web/templates/trending.html \
  src/radar/web/templates/_trending_summary.html tests/test_web.py
git commit -m "feat: /trending Models + Techniques sections + index strip"
```

---

### Task 5: Static export sections + strip

**Files:**
- Modify: `src/radar/web/static_site.py`, `src/radar/web/templates/static_trending.html`, `src/radar/web/templates/static_index.html`, `src/radar/cli.py` (export)
- Test: `tests/test_static_site.py` (append)

**Interfaces:**
- Consumes: `load_hub_sections` (Task 3); the live `trending.html` hub snippet.
- Produces: `render_static_site(..., model_hub: list[HubRow] | None = None, technique_hub: list[HubRow] | None = None, top_model: HubRow | None = None, top_technique: HubRow | None = None)` renders the sections in `static_trending.html` and the strip in `static_index.html`; `radar export` computes them via `load_hub_sections(root, generated_at)`.

- [ ] **Step 1: Write the failing tests (append to tests/test_static_site.py)**

```python
def test_static_site_renders_hub_sections(tmp_path):
    from radar.web.hub_sections import HubRow

    model_hub = [HubRow(id="m1", name="M One", subtitle="Fam", metric=5000, growth=120.0,
                        momentum=None, direction="rising", ring="pilot", is_new=False,
                        kind="model")]
    technique_hub = [HubRow(id="t1", name="T One", subtitle="reasoning", metric=900,
                            growth=None, momentum=5, direction="rising", ring="adopt",
                            is_new=True, kind="technique")]

    render_static_site([], tmp_path / "_site", datetime(2026, 7, 8, tzinfo=UTC),
                       model_hub=model_hub, technique_hub=technique_hub,
                       top_model=model_hub[0], top_technique=technique_hub[0])
    trending = (tmp_path / "_site" / "trending.html").read_text(encoding="utf-8")

    assert "Trending Models" in trending and "M One" in trending
    assert "Trending Techniques" in trending and "T One" in trending
    index = (tmp_path / "_site" / "index.html").read_text(encoding="utf-8")
    assert "M One" in index or "T One" in index   # strip shows a top hub item


def test_static_site_hub_backcompat(tmp_path):
    render_static_site([], tmp_path / "_site", datetime(2026, 7, 8, tzinfo=UTC))
    assert (tmp_path / "_site" / "index.html").exists()   # no hub data → still renders
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_static_site.py -v -k "hub"`
Expected: FAIL — `TypeError` on `model_hub` kwarg

- [ ] **Step 3: Create the static template section**

In `src/radar/web/templates/static_trending.html`, add the hub-sections snippet from Task 4 after the repo lanes, with ONE changed line — the detail link is slug-based (static pages are `model_{slug}.html` / `technique_{slug}.html`), guarded so a missing slug degrades to plain text (never a template crash):

```html
            <td>
              {% set slug = (model_slugs.get(r.id) if r.kind == "model" else technique_slugs.get(r.id)) %}
              {% if slug %}<a href="{{ r.kind }}_{{ slug }}.html">{{ r.name }}</a>{% else %}{{ r.name }}{% endif %}
            </td>
```

(This `<td>` replaces the live template's `<td><a href="/{{ r.kind }}/{{ r.id }}">…</a></td>`; the rest of the section body — headers, other columns, NEW badge, empty note — is identical to Task 4's snippet.)

- [ ] **Step 4: Wire static_site.py + static index**

In `src/radar/web/static_site.py`: import `from radar.web.hub_sections import HubRow`. Add params `model_hub: list[HubRow] | None = None`, `technique_hub: list[HubRow] | None = None`, `top_model: HubRow | None = None`, `top_technique: HubRow | None = None`. Build the slug maps the trending template needs (reuse `build_slug_map` — the same helper `_write_model_pages`/`_write_technique_pages` use):

```python
    from radar.web.slugs import build_slug_map

    model_slugs = build_slug_map([e.id for e in (model_entries or [])])
    technique_slugs = build_slug_map([t.id for t in (technique_entries or [])])
```

Pass `model_hub`/`technique_hub` + `model_slugs`/`technique_slugs` into the `static_trending.html` render (next to `onprem`/`broader`), and `top_model`/`top_technique` into the `static_index.html` render context. In `static_index.html`, the `_trending_summary.html` include already handles `top_model`/`top_technique` (added in Task 4) — no separate edit needed beyond passing the context. (In the T5 test, `model_entries` isn't passed, so the slug maps are empty and rows render as plain text — the assertion only checks the name is present; production passes `model_entries`, so links resolve.)

- [ ] **Step 5: Wire the export CLI**

In `src/radar/cli.py` `export`, near the trending-observations load:

```python
    from radar.web.hub_sections import load_hub_sections

    _model_hub, _technique_hub = load_hub_sections(root, generated_at)
```

and thread into the `render_static_site(...)` call: `model_hub=_model_hub or None, technique_hub=_technique_hub or None, top_model=next((r for r in _model_hub if not r.is_new), None), top_technique=next((r for r in _technique_hub if not r.is_new), None)`. (`generated_at` is the export's datetime; confirm its name in the export command.)

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_static_site.py tests/test_web.py tests/test_cli.py -v`
Expected: PASS (new + existing; back-compat proves no-hub exports unchanged)

- [ ] **Step 7: Lint + typecheck + commit**

```bash
uv run ruff check src/radar tests/test_static_site.py && uv run mypy src/radar
git add src/radar/web/static_site.py src/radar/web/templates/static_trending.html \
  src/radar/web/templates/static_index.html src/radar/cli.py tests/test_static_site.py
git commit -m "feat: static export trending-hub sections + index strip"
```

---

### Task 6: README + CHANGELOG + full gates

**Files:**
- Modify: `README.md`, `CHANGELOG.md`
- Test: the full suite

- [ ] **Step 1: README**

Extend the 📈 Trending radar Highlights bullet with a closing sentence:

```markdown
 `/trending` is now a hub — alongside repos it surfaces **trending models** (fastest-rising by download growth) and **trending techniques** (by citation momentum), each with the items new or promoted this week; model download-velocity is made durable by a committed `data/model-metrics.jsonl` log.
```

- [ ] **Step 2: CHANGELOG**

Under `## [Unreleased]` → `### Added`, at the top:

```markdown
- **Trending hub for models & techniques** — `/trending` (dashboard + static
  site) now shows "Trending Models" (fastest-rising by download growth) and
  "Trending Techniques" (by citation momentum) sections, each unioned with the
  items added/promoted this ISO week, with a top-model/technique line on the
  index strip. Model download-velocity is made durable across CI runs by a new
  committed `data/model-metrics.jsonl` log (mirroring the technique-metrics
  log). Guarded reads keep a corrupt store from breaking `/trending` or the
  daily export. (Phase 1 — untracked model/paper discovery is a future phase.)
```

- [ ] **Step 3: Full gates**

Run: `uv run pytest && uv run ruff check . && uv run mypy src/radar`
Expected: all pass, coverage ≥ 80%, ruff + mypy clean. Fix anything failing (implementation, not tests, unless a test is genuinely wrong).

- [ ] **Step 4: Commit**

```bash
git add README.md CHANGELOG.md
git commit -m "docs: trending hub for models + techniques"
```

---

## Self-Review Notes (already applied)

- Spec coverage: committed model-metrics log (T1) + scan/CI wiring (T2); pure hub builders rising ∪ new-this-week (T3); live `/trending` sections + index strip (T4); static export + strip (T5); docs (T6). Phase 2 explicitly out of scope.
- Durability: T1/T2 make model download-velocity durable (the spec's enabling change); techniques already carry momentum on the entry, so no technique-metrics load is needed in the hub (recorded simplification vs the spec's data-flow sketch — the entry's `score_breakdown.momentum` already encodes citation velocity durably).
- Guarded/daily-publish invariant: `load_model_metrics` uses the hardened read; `load_hub_sections` wraps the whole build in `try/except → ([], [])`; the route and export both degrade to empty sections (T4/T5 back-compat tests).
- Determinism: builders pure with `now`; only the route (`datetime.now(UTC)`) and export (`generated_at`) read the clock.
- Type consistency: `HubRow`/`build_model_section`/`build_technique_section`/`load_hub_sections` (T3) flow into T4/T5; `persist_model_scan(..., metrics_log_path=)` (T2) matches the `append_model_metrics` name (T1); the hub-sections template snippet is identical in `trending.html` (T4) and `static_trending.html` (T5).
- Recorded plan-time checks for the implementer: the minimal `ModelEntry`/`TechniqueEntry`/event `model_validate` fixtures must match the real required schema (assertions are the contract); confirm `generated_at` is the export command's datetime variable name.
