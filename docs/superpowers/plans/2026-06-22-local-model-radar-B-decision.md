# Local-Model Radar — Plan B: Decision Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the Plan-A model catalog into a decision tool — a deterministic adoption ring per model, persisted per-scan metrics, a durable model-history timeline, and "rising/falling" momentum — surfaced through `radar models scan`/`list`.

**Architecture:** Extend the existing `src/radar/models_radar/` package, mirroring the tool radar's scoring/rings/momentum/history idioms (`scoring/rings.py`, `pipeline/momentum.py`, `storage/metrics_store.py`, `storage/history_log.py`). A new model pipeline scores each `ModelEntry`, diffs rings vs the previous scan into history events, computes momentum, and persists metrics — all deterministic, no LLM. The dashboard/MCP/reports surface and HF-trending discovery are Plan C.

**Tech Stack:** Python 3.12, pydantic v2, SQLite, pytest + ruff + mypy. Builds on Plan A (`models_radar/entities.py`, `memory.py`, `scan.py`, the `radar models` CLI).

## Global Constraints

- Python ≥ 3.12; every new module begins with `from __future__ import annotations`.
- No new third-party dependencies.
- Deterministic core, no LLM: identical inputs → identical ring/score.
- Immutability: frozen pydantic models; never mutate inputs; `model_copy(update=...)`.
- Best-effort persistence: a scan never aborts on a storage hiccup; reuse the additive-migration idiom from `storage/metrics_store.py`.
- Reuse the existing `Ring` enum (adopt/pilot/watch/avoid) and the append-only JSONL history idiom (`storage/history_log.py`).
- ruff + mypy clean; coverage ≥ 80%.
- Models do NOT use the 7-dimension tool `ScoreBreakdown`; they get their own `ModelScore`.

---

### Task 1: Model scoring + ring + entity fields

**Files:**
- Modify: `src/radar/models_radar/entities.py` (add `score`, `score_breakdown`, `ring` to `ModelEntry`)
- Create: `src/radar/models_radar/scoring.py`
- Test: `tests/test_models_radar_scoring.py`

**Interfaces:**
- Consumes: `ModelEntry`, `Openness`, `HardwareTier`, `minimum_viable_quant` (Plan A).
- Produces: `ModelScore` (frozen pydantic: `openness:int, local_runnability:int, capability_tier:int, ecosystem_support:int` each 1-5, plus `average:float`); `score_model(entry: ModelEntry) -> ModelScore`; `model_ring(score: ModelScore) -> Ring`; `ModelEntry.score: float | None`, `ModelEntry.score_breakdown: ModelScore | None`, `ModelEntry.ring: Ring | None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_models_radar_scoring.py
from __future__ import annotations

from radar.models import Ring
from radar.models_radar.entities import (
    HardwareTier, ModelEntry, Openness, Platform, QuantVariant,
)
from radar.models_radar.scoring import ModelScore, model_ring, score_model


def _entry(**kw):
    base = dict(
        id="m", name="M", family="F",
        params_total=8_000_000_000, openness=Openness.OPEN_PERMISSIVE,
        hardware_tier=HardwareTier.LAPTOP,
        quants=[QuantVariant(format="Q4_K_M", bits_per_weight=4.5,
                             est_memory_gb_4k=8.0, source="hf:x")],
    )
    base.update(kw)
    return ModelEntry(**base)


def test_strong_open_laptop_model_scores_high_and_adopts():
    s = score_model(_entry(hf_downloads=5_000_000))
    assert 1 <= s.openness <= 5 and 1 <= s.local_runnability <= 5
    assert s.openness == 5            # permissive → top
    assert s.local_runnability == 5   # laptop tier → top
    assert model_ring(s) in (Ring.ADOPT, Ring.PILOT)


def test_gated_datacenter_model_scores_low():
    s = score_model(_entry(
        openness=Openness.GATED, hardware_tier=HardwareTier.DATACENTER,
        params_total=400_000_000_000, hf_downloads=100,
        quants=[QuantVariant(format="Q4_K_M", bits_per_weight=4.5,
                             est_memory_gb_4k=240.0, source="hf:x")],
    ))
    assert s.openness <= 2 and s.local_runnability <= 2
    assert model_ring(s) in (Ring.WATCH, Ring.AVOID)


def test_score_is_deterministic():
    e = _entry(hf_downloads=1234)
    assert score_model(e) == score_model(e)


def test_entry_carries_score_and_ring_fields():
    e = _entry().model_copy(update={"ring": Ring.ADOPT, "score": 4.2})
    assert e.ring == Ring.ADOPT and e.score == 4.2
    assert _entry().ring is None  # default
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_models_radar_scoring.py -v`
Expected: FAIL (`ModuleNotFoundError` / `ModelEntry` has no `ring`).

- [ ] **Step 3: Add entity fields**

In `src/radar/models_radar/entities.py`, add to `ModelEntry` (after `hardware_tier`), importing `Ring`:

```python
from radar.models import Backer, Ring  # update existing import
```
```python
    score: float | None = None
    score_breakdown: "ModelScore | None" = None
    ring: Ring | None = None
```

`ModelScore` lives in `scoring.py`; to avoid a circular import, type the field as `object | None` is NOT allowed (mypy). Instead, define `ModelScore` in `entities.py` (it is a pure data model and belongs with the other entities), and have `scoring.py` import it from there. Add to `entities.py`:

```python
class ModelScore(BaseModel):
    """Deterministic model-adoption score dimensions (1-5)."""

    model_config = ConfigDict(frozen=True)

    openness: int = Field(ge=1, le=5)
    local_runnability: int = Field(ge=1, le=5)
    capability_tier: int = Field(ge=1, le=5)
    ecosystem_support: int = Field(ge=1, le=5)
    average: float
```

Then `ModelEntry.score_breakdown: ModelScore | None = None` (no forward-ref needed once `ModelScore` is defined above `ModelEntry`).

- [ ] **Step 4: Implement scoring**

```python
# src/radar/models_radar/scoring.py
"""Deterministic adoption scoring + ring for local models.

Model-specific dimensions (1-5), no LLM. Mirrors the tool radar's
ring_from_score gate style but over model criteria.
"""

from __future__ import annotations

from radar.models import Ring
from radar.models_radar.entities import HardwareTier, ModelEntry, ModelScore, Openness
from radar.models_radar.memory import minimum_viable_quant


_OPENNESS_SCORE = {
    Openness.OPEN_PERMISSIVE: 5,
    Openness.OPEN_RESTRICTED: 3,
    Openness.GATED: 2,
    Openness.CLOSED: 1,
}
_TIER_SCORE = {
    HardwareTier.LAPTOP: 5,
    HardwareTier.APPLE_HIGH_RAM: 4,
    HardwareTier.SINGLE_GPU: 3,
    HardwareTier.WORKSTATION: 2,
    HardwareTier.DATACENTER: 1,
    HardwareTier.UNKNOWN: 2,
}


def _capability(entry: ModelEntry) -> int:
    """Bigger models score higher capability (by total params)."""
    p = entry.params_total or 0
    if p >= 100_000_000_000:
        return 5
    if p >= 30_000_000_000:
        return 4
    if p >= 12_000_000_000:
        return 3
    if p >= 3_000_000_000:
        return 2
    return 1


def _ecosystem(entry: ModelEntry) -> int:
    """More resident quant formats + Ollama presence → better support."""
    formats = {q.format for q in entry.quants}
    score = 1 + min(3, len(formats))
    if entry.ollama_name:
        score = min(5, score + 1)
    return min(5, score)


def score_model(entry: ModelEntry) -> ModelScore:
    openness = _OPENNESS_SCORE.get(entry.openness, 2) if entry.openness else 2
    mv = minimum_viable_quant(entry.quants)
    runnability = _TIER_SCORE[entry.hardware_tier] if mv else 2
    capability = _capability(entry)
    ecosystem = _ecosystem(entry)
    average = round((openness + runnability + capability + ecosystem) / 4, 2)
    return ModelScore(
        openness=openness, local_runnability=runnability,
        capability_tier=capability, ecosystem_support=ecosystem, average=average,
    )


def model_ring(score: ModelScore) -> Ring:
    """Absolute ring gate over the model score average + openness floor."""
    if score.average < 2.0 or score.openness <= 1:
        return Ring.AVOID
    if score.average >= 4.0 and score.openness >= 3:
        return Ring.ADOPT
    if score.average >= 3.0:
        return Ring.PILOT
    return Ring.WATCH
```

- [ ] **Step 5: Run test + commit**

Run: `pytest tests/test_models_radar_scoring.py -v` → PASS. Then full gate (`ruff check src tests && mypy src && pytest -q`).

```bash
git add src/radar/models_radar/entities.py src/radar/models_radar/scoring.py tests/test_models_radar_scoring.py
git commit -m "feat(models): deterministic adoption score + ring"
```

---

### Task 2: model_metrics store (persistence + migration)

**Files:**
- Create: `src/radar/storage/model_metrics_store.py`
- Test: `tests/test_model_metrics_store.py`

**Interfaces:**
- Consumes: nothing from Plan B (standalone store).
- Produces: `ModelMetrics` (pydantic: `model_id:str, run_id:str, observed_at:datetime, downloads:int|None, likes:int|None, min_memory_gb:float|None, ring:str|None, hardware_tier:str|None`); `ModelMetricsStore(path: Path)` with `initialize()`, `record(list[ModelMetrics])`, `latest(model_id, exclude_run=None) -> ModelMetrics | None`, `history_for(model_id, limit=50) -> list[ModelMetrics]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_model_metrics_store.py
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from radar.storage.model_metrics_store import ModelMetrics, ModelMetricsStore


def _m(model_id, run_id, day, **kw):
    base = dict(model_id=model_id, run_id=run_id,
                observed_at=datetime(2026, 6, day, tzinfo=UTC))
    base.update(kw)
    return ModelMetrics(**base)


def test_record_and_latest_round_trip(tmp_path):
    store = ModelMetricsStore(tmp_path / "radar.db")
    store.initialize()
    store.record([_m("qwen3-8b", "r1", 19, downloads=1000, ring="pilot",
                     min_memory_gb=8.4, hardware_tier="laptop")])
    got = store.latest("qwen3-8b")
    assert got.downloads == 1000 and got.ring == "pilot" and got.min_memory_gb == 8.4


def test_latest_excludes_current_run(tmp_path):
    store = ModelMetricsStore(tmp_path / "radar.db")
    store.initialize()
    store.record([_m("m", "r1", 18, downloads=100)])
    store.record([_m("m", "r2", 19, downloads=200)])
    assert store.latest("m", exclude_run="r2").downloads == 100


def test_initialize_is_idempotent(tmp_path):
    store = ModelMetricsStore(tmp_path / "radar.db")
    store.initialize()
    store.initialize()  # must not raise
    cols = {r[1] for r in sqlite3.connect(tmp_path / "radar.db").execute(
        "PRAGMA table_info(model_metrics)")}
    assert {"model_id", "downloads", "ring", "min_memory_gb", "hardware_tier"} <= cols
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_model_metrics_store.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement** (mirror `src/radar/storage/metrics_store.py` exactly in structure)

```python
# src/radar/storage/model_metrics_store.py
"""SQLite store of per-scan model metrics (mirror of metrics_store.py)."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel


class ModelMetrics(BaseModel):
    model_id: str
    run_id: str
    observed_at: datetime
    downloads: int | None = None
    likes: int | None = None
    min_memory_gb: float | None = None
    ring: str | None = None
    hardware_tier: str | None = None


_COLUMNS = (
    "model_id, run_id, observed_at, downloads, likes, "
    "min_memory_gb, ring, hardware_tier"
)


class ModelMetricsStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def initialize(self) -> None:
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS model_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    model_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    downloads INTEGER,
                    likes INTEGER,
                    min_memory_gb REAL,
                    ring TEXT,
                    hardware_tier TEXT
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_model_metrics_model "
                "ON model_metrics(model_id, observed_at)"
            )

    def record(self, metrics: list[ModelMetrics]) -> None:
        if not metrics:
            return
        with sqlite3.connect(self.path) as conn:
            conn.executemany(
                f"INSERT INTO model_metrics({_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [self._row(m) for m in metrics],
            )

    def latest(self, model_id: str, exclude_run: str | None = None) -> ModelMetrics | None:
        query = f"SELECT {_COLUMNS} FROM model_metrics WHERE model_id = ?"
        params: list[str] = [model_id]
        if exclude_run is not None:
            query += " AND run_id != ?"
            params.append(exclude_run)
        query += " ORDER BY observed_at DESC, id DESC LIMIT 1"
        with sqlite3.connect(self.path) as conn:
            row = conn.execute(query, params).fetchone()
        return self._to_metrics(row) if row else None

    def history_for(self, model_id: str, limit: int = 50) -> list[ModelMetrics]:
        with sqlite3.connect(self.path) as conn:
            rows = conn.execute(
                f"SELECT {_COLUMNS} FROM model_metrics WHERE model_id = ? "
                "ORDER BY observed_at DESC, id DESC LIMIT ?",
                (model_id, limit),
            ).fetchall()
        return [self._to_metrics(r) for r in reversed(rows)]

    @staticmethod
    def _row(m: ModelMetrics) -> tuple:
        return (m.model_id, m.run_id, m.observed_at.isoformat(), m.downloads,
                m.likes, m.min_memory_gb, m.ring, m.hardware_tier)

    @staticmethod
    def _to_metrics(row: tuple) -> ModelMetrics:
        return ModelMetrics(
            model_id=row[0], run_id=row[1], observed_at=datetime.fromisoformat(row[2]),
            downloads=row[3], likes=row[4], min_memory_gb=row[5],
            ring=row[6], hardware_tier=row[7],
        )
```

- [ ] **Step 4: Run test + commit**

Run: `pytest tests/test_model_metrics_store.py -v` → PASS, then full gate.

```bash
git add src/radar/storage/model_metrics_store.py tests/test_model_metrics_store.py
git commit -m "feat(models): model_metrics SQLite store"
```

---

### Task 3: Model-history events + log + diff

**Files:**
- Create: `src/radar/models_radar/history.py`
- Test: `tests/test_models_radar_history.py`

**Interfaces:**
- Consumes: `Ring` (`radar.models`), `ChangeType` (`radar.storage.history_store`), `ModelEntry` (Plan A), `ModelMetrics` (Task 2).
- Produces: `ModelHistoryEvent` (pydantic: `model_id, family, change_type:ChangeType, ring:Ring, previous_ring:Ring|None, run_id, observed_at:datetime, reasons:list[str]`); `diff_model_rings(entries, previous_rings, run_id, observed_at) -> list[ModelHistoryEvent]` where `previous_rings: dict[str, Ring]`; `append_model_events(path, events)` + `load_model_events(path)` (JSONL, mirror `history_log.py`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_models_radar_history.py
from __future__ import annotations

from datetime import UTC, datetime

from radar.models import Ring
from radar.models_radar.entities import ModelEntry
from radar.models_radar.history import (
    ModelHistoryEvent, append_model_events, diff_model_rings, load_model_events,
)

NOW = datetime(2026, 6, 22, tzinfo=UTC)


def _e(mid, ring):
    return ModelEntry(id=mid, name=mid, family="F", ring=ring)


def test_new_model_yields_new_event():
    events = diff_model_rings([_e("a", Ring.PILOT)], {}, "r1", NOW)
    assert len(events) == 1 and events[0].change_type.value == "new"
    assert events[0].ring == Ring.PILOT and events[0].previous_ring is None


def test_promotion_and_demotion_detected():
    prev = {"a": Ring.WATCH, "b": Ring.ADOPT}
    events = {e.model_id: e for e in diff_model_rings(
        [_e("a", Ring.ADOPT), _e("b", Ring.PILOT)], prev, "r2", NOW)}
    assert events["a"].change_type.value == "promoted"
    assert events["b"].change_type.value == "demoted"


def test_unchanged_ring_emits_no_event():
    assert diff_model_rings([_e("a", Ring.PILOT)], {"a": Ring.PILOT}, "r2", NOW) == []


def test_log_round_trip(tmp_path):
    path = tmp_path / "model-history.jsonl"
    events = diff_model_rings([_e("a", Ring.PILOT)], {}, "r1", NOW)
    append_model_events(path, events)
    loaded = load_model_events(path)
    assert len(loaded) == 1 and loaded[0].model_id == "a"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_models_radar_history.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement**

```python
# src/radar/models_radar/history.py
"""Model ring-change events + append-only JSONL log (mirror of history_log)."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field

from radar.models import Ring
from radar.models_radar.entities import ModelEntry
from radar.storage.history_store import ChangeType


logger = logging.getLogger(__name__)

_RING_ORDER = {Ring.AVOID: 0, Ring.WATCH: 1, Ring.PILOT: 2, Ring.ADOPT: 3}


class ModelHistoryEvent(BaseModel):
    model_id: str
    family: str
    change_type: ChangeType
    ring: Ring
    previous_ring: Ring | None = None
    run_id: str
    observed_at: datetime
    reasons: list[str] = Field(default_factory=list)


def diff_model_rings(
    entries: list[ModelEntry],
    previous_rings: dict[str, Ring],
    run_id: str,
    observed_at: datetime,
) -> list[ModelHistoryEvent]:
    """Emit new/promoted/demoted events. Unchanged rings emit nothing."""
    events: list[ModelHistoryEvent] = []
    for entry in entries:
        if entry.ring is None:
            continue
        prev = previous_rings.get(entry.id)
        if prev is None:
            change = ChangeType.NEW
        elif _RING_ORDER[entry.ring] > _RING_ORDER[prev]:
            change = ChangeType.PROMOTED
        elif _RING_ORDER[entry.ring] < _RING_ORDER[prev]:
            change = ChangeType.DEMOTED
        else:
            continue
        events.append(ModelHistoryEvent(
            model_id=entry.id, family=entry.family, change_type=change,
            ring=entry.ring, previous_ring=prev, run_id=run_id, observed_at=observed_at,
            reasons=[f"{change.value} to {entry.ring.value}"],
        ))
    return events


def append_model_events(path: Path, events: list[ModelHistoryEvent]) -> None:
    if not events:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(e.model_dump(mode="json"), ensure_ascii=False) for e in events]
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def load_model_events(path: Path) -> list[ModelHistoryEvent]:
    if not path.exists():
        return []
    events: list[ModelHistoryEvent] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, raw in enumerate(handle, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                events.append(ModelHistoryEvent.model_validate_json(line))
            except ValueError as exc:
                logger.warning("Skipping corrupt model-history line %d in %s: %s",
                               line_no, path, exc)
    return events
```

- [ ] **Step 4: Run test + commit**

Run: `pytest tests/test_models_radar_history.py -v` → PASS, then full gate.

```bash
git add src/radar/models_radar/history.py tests/test_models_radar_history.py
git commit -m "feat(models): model ring-change events + JSONL history log"
```

---

### Task 4: Model momentum (rising/falling)

**Files:**
- Create: `src/radar/models_radar/momentum.py`
- Test: `tests/test_models_radar_momentum.py`

**Interfaces:**
- Consumes: `ModelMetrics` (Task 2), `ModelHistoryEvent` (Task 3), `ChangeType`.
- Produces: `ModelMomentum` (pydantic: `model_id, direction:str, downloads_growth_pct:float|None, note:str`); `compute_model_momentum(model_id, metric_rows: list[ModelMetrics], ring_events: list[ModelHistoryEvent]) -> ModelMomentum`; constants `RISING_PCT=5.0`, `FALLING_PCT=-5.0`, `RECENT_EVENTS=3`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_models_radar_momentum.py
from __future__ import annotations

from datetime import UTC, datetime

from radar.models import Ring
from radar.models_radar.history import ModelHistoryEvent
from radar.models_radar.momentum import ModelMomentum, compute_model_momentum
from radar.storage.history_store import ChangeType
from radar.storage.model_metrics_store import ModelMetrics

NOW = datetime(2026, 6, 22, tzinfo=UTC)


def _row(day, downloads):
    return ModelMetrics(model_id="m", run_id=f"r{day}",
                        observed_at=datetime(2026, 6, day, tzinfo=UTC), downloads=downloads)


def test_download_growth_marks_rising():
    rows = [_row(18, 1000), _row(22, 1100)]  # +10%
    m = compute_model_momentum("m", rows, [])
    assert m.direction == "rising" and m.downloads_growth_pct == 10.0


def test_download_drop_marks_falling():
    rows = [_row(18, 1000), _row(22, 900)]  # -10%
    assert compute_model_momentum("m", rows, []).direction == "falling"


def test_promotion_event_marks_rising():
    ev = ModelHistoryEvent(model_id="m", family="F", change_type=ChangeType.PROMOTED,
                           ring=Ring.ADOPT, run_id="r2", observed_at=NOW)
    assert compute_model_momentum("m", [_row(22, 100)], [ev]).direction == "rising"


def test_flat_is_steady():
    rows = [_row(18, 1000), _row(22, 1000)]
    assert compute_model_momentum("m", rows, []).direction == "steady"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_models_radar_momentum.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement** (mirror `pipeline/momentum.py`, downloads instead of stars)

```python
# src/radar/models_radar/momentum.py
"""Model momentum: rising/falling by downloads growth + ring events."""

from __future__ import annotations

from pydantic import BaseModel

from radar.models_radar.history import ModelHistoryEvent
from radar.storage.history_store import ChangeType
from radar.storage.model_metrics_store import ModelMetrics


RISING_PCT = 5.0
FALLING_PCT = -5.0
RECENT_EVENTS = 3


class ModelMomentum(BaseModel):
    model_id: str
    direction: str  # rising | falling | steady
    downloads_growth_pct: float | None = None
    note: str = ""


def _downloads_growth_pct(rows: list[ModelMetrics]) -> float | None:
    points = [r.downloads for r in rows if r.downloads is not None]
    if len(points) < 2 or not points[0]:
        return None
    return round((points[-1] - points[0]) / points[0] * 100, 1)


def compute_model_momentum(
    model_id: str,
    metric_rows: list[ModelMetrics],
    ring_events: list[ModelHistoryEvent],
) -> ModelMomentum:
    """Direction of travel (rows + events oldest-first)."""
    growth = _downloads_growth_pct(metric_rows)
    for event in reversed(ring_events[-RECENT_EVENTS:]):
        if event.change_type == ChangeType.PROMOTED:
            return ModelMomentum(model_id=model_id, direction="rising",
                                 downloads_growth_pct=growth,
                                 note=f"Promoted to {event.ring.value} on {event.observed_at.date()}.")
        if event.change_type == ChangeType.DEMOTED:
            return ModelMomentum(model_id=model_id, direction="falling",
                                 downloads_growth_pct=growth,
                                 note=f"Demoted to {event.ring.value} on {event.observed_at.date()}.")
    if growth is not None:
        if growth >= RISING_PCT:
            return ModelMomentum(model_id=model_id, direction="rising",
                                 downloads_growth_pct=growth,
                                 note=f"Downloads {growth:+.1f}% across recent scans.")
        if growth <= FALLING_PCT:
            return ModelMomentum(model_id=model_id, direction="falling",
                                 downloads_growth_pct=growth,
                                 note=f"Downloads {growth:+.1f}% across recent scans.")
    return ModelMomentum(model_id=model_id, direction="steady", downloads_growth_pct=growth)
```

- [ ] **Step 4: Run test + commit**

Run: `pytest tests/test_models_radar_momentum.py -v` → PASS, then full gate.

```bash
git add src/radar/models_radar/momentum.py tests/test_models_radar_momentum.py
git commit -m "feat(models): model momentum (downloads growth + ring events)"
```

---

### Task 5: Decision pipeline — score, diff, persist, momentum

**Files:**
- Create: `src/radar/models_radar/pipeline.py`
- Test: `tests/test_models_radar_pipeline.py`

**Interfaces:**
- Consumes: `ModelEntry` (Plan A), `score_model`/`model_ring` (Task 1), `ModelMetricsStore`/`ModelMetrics` (Task 2), `diff_model_rings`/`append_model_events`/`load_model_events` (Task 3), `compute_model_momentum`/`ModelMomentum` (Task 4), `minimum_viable_quant` (Plan A).
- Produces: `score_entries(entries) -> list[ModelEntry]` (returns new entries with `ring`/`score`/`score_breakdown` set); `persist_model_scan(entries, run_id, observed_at, db_path, history_path) -> list[ModelHistoryEvent]` (scores already set; reads previous rings from the log, diffs, appends history, records metrics); `momentum_for(entries, db_path, history_path) -> dict[str, ModelMomentum]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_models_radar_pipeline.py
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from radar.models import Ring
from radar.models_radar.entities import (
    HardwareTier, ModelEntry, Openness, QuantVariant,
)
from radar.models_radar.pipeline import persist_model_scan, score_entries

NOW = datetime(2026, 6, 22, tzinfo=UTC)


def _entry(mid, **kw):
    base = dict(id=mid, name=mid, family="F", params_total=8_000_000_000,
                openness=Openness.OPEN_PERMISSIVE, hardware_tier=HardwareTier.LAPTOP,
                hf_downloads=1_000_000,
                quants=[QuantVariant(format="Q4_K_M", bits_per_weight=4.5,
                                     est_memory_gb_4k=8.0, source="hf:x")])
    base.update(kw)
    return ModelEntry(**base)


def test_score_entries_sets_ring_and_score():
    [e] = score_entries([_entry("qwen3-8b")])
    assert e.ring is not None and e.score is not None and e.score_breakdown is not None


def test_persist_records_metrics_and_new_event_then_no_event(tmp_path: Path):
    db = tmp_path / "radar.db"
    hist = tmp_path / "model-history.jsonl"
    entries = score_entries([_entry("qwen3-8b")])
    events1 = persist_model_scan(entries, "r1", NOW, db, hist)
    assert len(events1) == 1 and events1[0].change_type.value == "new"
    # second identical scan → ring unchanged → no new event, metrics still recorded
    events2 = persist_model_scan(entries, "r2", NOW, db, hist)
    assert events2 == []
    from radar.storage.model_metrics_store import ModelMetricsStore
    store = ModelMetricsStore(db)
    assert store.latest("qwen3-8b").ring == entries[0].ring.value
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_models_radar_pipeline.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement**

```python
# src/radar/models_radar/pipeline.py
"""Model decision pipeline: score → diff rings → persist metrics + history."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from radar.models import Ring
from radar.models_radar.entities import ModelEntry
from radar.models_radar.history import (
    ModelHistoryEvent, append_model_events, diff_model_rings, load_model_events,
)
from radar.models_radar.memory import minimum_viable_quant
from radar.models_radar.momentum import ModelMomentum, compute_model_momentum
from radar.models_radar.scoring import model_ring, score_model
from radar.storage.model_metrics_store import ModelMetrics, ModelMetricsStore


def score_entries(entries: list[ModelEntry]) -> list[ModelEntry]:
    """Return new entries with score/score_breakdown/ring populated."""
    scored: list[ModelEntry] = []
    for entry in entries:
        breakdown = score_model(entry)
        ring = model_ring(breakdown)
        scored.append(entry.model_copy(update={
            "score": breakdown.average, "score_breakdown": breakdown, "ring": ring,
        }))
    return scored


def _latest_rings(history_path: Path) -> dict[str, Ring]:
    """Most recent ring per model from the durable log."""
    rings: dict[str, Ring] = {}
    for event in load_model_events(history_path):  # oldest-first → last wins
        rings[event.model_id] = event.ring
    return rings


def persist_model_scan(
    entries: list[ModelEntry],
    run_id: str,
    observed_at: datetime,
    db_path: Path,
    history_path: Path,
) -> list[ModelHistoryEvent]:
    """Diff rings vs the log, append new events, record per-scan metrics."""
    previous = _latest_rings(history_path)
    events = diff_model_rings(entries, previous, run_id, observed_at)
    append_model_events(history_path, events)

    store = ModelMetricsStore(db_path)
    store.initialize()
    rows: list[ModelMetrics] = []
    for entry in entries:
        mv = minimum_viable_quant(entry.quants)
        rows.append(ModelMetrics(
            model_id=entry.id, run_id=run_id, observed_at=observed_at,
            downloads=entry.hf_downloads, likes=entry.hf_likes,
            min_memory_gb=(mv.est_memory_gb_4k if mv else None),
            ring=(entry.ring.value if entry.ring else None),
            hardware_tier=entry.hardware_tier.value,
        ))
    store.record(rows)
    return events


def momentum_for(
    entries: list[ModelEntry], db_path: Path, history_path: Path,
) -> dict[str, ModelMomentum]:
    """Momentum per model from its metric history + ring events."""
    store = ModelMetricsStore(db_path)
    store.initialize()
    events = load_model_events(history_path)
    events_by_model: dict[str, list[ModelHistoryEvent]] = {}
    for ev in events:
        events_by_model.setdefault(ev.model_id, []).append(ev)
    result: dict[str, ModelMomentum] = {}
    for entry in entries:
        result[entry.id] = compute_model_momentum(
            entry.id, store.history_for(entry.id), events_by_model.get(entry.id, []),
        )
    return result
```

- [ ] **Step 4: Run test + commit**

Run: `pytest tests/test_models_radar_pipeline.py -v` → PASS, then full gate.

```bash
git add src/radar/models_radar/pipeline.py tests/test_models_radar_pipeline.py
git commit -m "feat(models): decision pipeline (score, diff, persist, momentum)"
```

---

### Task 6: Wire decision pipeline into `radar models scan` / `list`

**Files:**
- Modify: `src/radar/cli.py` (the `models_scan` and `models_list` commands from Plan A)
- Test: `tests/test_models_radar_cli.py` (extend)

**Interfaces:**
- Consumes: `score_entries`, `persist_model_scan`, `momentum_for` (Task 5); existing `run_model_scan` (Plan A), `RunStore`.
- Produces: `models scan` scores entries, persists metrics+history (db at `data/radar.db`, log at `data/model-history.jsonl`), and saves scored cards; `models list` prints `ring` and a momentum arrow per model.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_models_radar_cli.py — add
def test_models_scan_persists_rings_and_list_shows_them(tmp_path, monkeypatch):
    from typer.testing import CliRunner
    from radar.cli import app
    from radar.models_radar.entities import (
        HardwareTier, ModelEntry, Openness, QuantVariant,
    )

    runner = CliRunner()
    runner.invoke(app, ["init", "--root", str(tmp_path)])

    async def fake_scan(seed_path, client):
        return [ModelEntry(id="qwen3-8b", name="Qwen3 8B", family="Qwen3",
                           params_total=8_000_000_000, openness=Openness.OPEN_PERMISSIVE,
                           hardware_tier=HardwareTier.LAPTOP, hf_downloads=1_000_000,
                           quants=[QuantVariant(format="Q4_K_M", bits_per_weight=4.5,
                                                est_memory_gb_4k=8.0, source="hf:x")])]
    monkeypatch.setattr("radar.models_radar.scan.run_model_scan", fake_scan)

    assert runner.invoke(app, ["models", "scan", "--root", str(tmp_path)]).exit_code == 0
    out = runner.invoke(app, ["models", "list", "--root", str(tmp_path)])
    assert out.exit_code == 0, out.stdout
    assert "qwen3-8b" in out.stdout
    assert any(r in out.stdout for r in ("adopt", "pilot", "watch"))
    # history log written
    assert (tmp_path / "data" / "model-history.jsonl").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_models_radar_cli.py::test_models_scan_persists_rings_and_list_shows_them -v`
Expected: FAIL (no ring in output / no history file).

- [ ] **Step 3: Implement** — update the two commands

In `models_scan`, after obtaining `entries` from `run_model_scan`, score + persist before saving the stage:

```python
    from radar.models_radar.pipeline import persist_model_scan, score_entries
    from datetime import UTC, datetime

    entries = asyncio.run(_run())
    entries = score_entries(entries)
    run_store = RunStore(root / "data" / "runs")
    run_id = run_store.create_run()
    observed_at = datetime.now(UTC)
    persist_model_scan(
        entries, run_id, observed_at,
        root / "data" / "radar.db", root / "data" / "model-history.jsonl",
    )
    run_store.save_stage(run_id, "model_cards", [m.model_dump(mode="json") for m in entries])
    run_store.update_meta(run_id, {"kind": "models", "model_count": len(entries)})
    console.print(f"Scanned {len(entries)} models → run {run_id}")
```

In `models_list`, after loading `entries` from `model_cards.json`, compute momentum and include `ring` + arrow in each line:

```python
    from radar.models_radar.pipeline import momentum_for
    from radar.models_radar.entities import ModelEntry as _ME

    parsed = [_ME.model_validate(m) for m in entries]
    moms = momentum_for(parsed, root / "data" / "radar.db",
                        root / "data" / "model-history.jsonl")
    _ARROW = {"rising": "↑", "falling": "↓", "steady": "→"}
    for m in parsed:
        quants = m.quants
        mems = [q.est_memory_gb_4k for q in quants
                if q.est_memory_gb_4k and q.bits_per_weight >= 4.0]
        min_mem = f"{min(mems):.1f}GB" if mems else "?"
        arrow = _ARROW.get(moms[m.id].direction, "")
        ring = m.ring.value if m.ring else "-"
        console.print(
            f"  {m.id:<28} {ring:<7} {m.hardware_tier.value:<16} "
            f"min~{min_mem:<9} {arrow} {m.family}",
            highlight=False,
        )
```

(Replace the Plan-A loop body that printed only tier/min-memory/family.)

- [ ] **Step 4: Run test + commit**

Run: `pytest tests/test_models_radar_cli.py -v` → PASS, then full gate (`ruff check src tests && mypy src && pytest -q`).

```bash
git add src/radar/cli.py tests/test_models_radar_cli.py
git commit -m "feat(models): scan scores+persists rings; list shows ring + momentum"
```

---

### Task 7: Full-gate + live smoke + merge

**Files:** none (verification only).

- [ ] **Step 1: Gates** — `ruff check src tests && mypy src && pytest -q` → all green.
- [ ] **Step 2: Live end-to-end** — `radar models scan --root .` then `radar models list --root .` → every model shows a ring (adopt/pilot/watch) and a momentum arrow; `data/model-history.jsonl` is created with `new` events on the first scan; a second `radar models scan` adds no duplicate `new` events (ring unchanged). Spot-check a permissive laptop model (e.g. qwen3-8b) lands `adopt`/`pilot` and a gated/huge model lands lower.
- [ ] **Step 3: Merge** to main (`--no-ff`) and delete the branch:

```bash
git checkout main && git merge --no-ff feature/local-model-radar-b \
  -m "Merge feature/local-model-radar-b (Plan B): model decision layer"
git branch -d feature/local-model-radar-b
```

---

## Self-Review

**Spec coverage (Plan B scope):** §3 adoption ring/scoring → Tasks 1 (+ pipeline 5). §5 model_metrics time-series → Task 2; model-history log → Task 3; momentum → Task 4. Scan/CLI integration of the decision layer (part of §7) → Tasks 5-6. **Deferred to Plan C (stated in header):** §5 discovery proposals (HF-trending → proposed-model-seeds.yaml); §6 dashboard "Models" section + MCP tools + reports/feeds; §7 folding the model stage into the main daily `radar scan` + publish. No in-scope Plan-B item unmapped.

**Placeholder scan:** No TBD/TODO/"handle edge cases". Every code step carries complete code. Task 6 shows the exact replacement loop bodies for both CLI commands.

**Type consistency:** `ModelScore` defined in `entities.py` (Task 1) and consumed by `scoring.py` (Task 1) + `ModelEntry.score_breakdown` — no circular import (entities defines it; scoring imports from entities). `score_model(entry)->ModelScore` / `model_ring(score)->Ring` consistent Task 1 ↔ 5. `ModelMetrics` fields consistent Task 2 ↔ 4 ↔ 5. `ModelHistoryEvent` + `diff_model_rings(entries, previous_rings:dict[str,Ring], run_id, observed_at)` consistent Task 3 ↔ 5. `compute_model_momentum(model_id, metric_rows, ring_events)` consistent Task 4 ↔ 5. `ModelEntry.ring` (Plan B Task 1 field) consumed by Task 3 `diff_model_rings` and Task 6. `ChangeType` reused from the tool history_store (values new/promoted/demoted/updated).
