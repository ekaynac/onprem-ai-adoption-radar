# Differentiation Pass Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the six differentiation features from `docs/superpowers/specs/2026-07-28-differentiation-pass-design.md` — tenure credential, sparklines, trending time-window tabs, ring/fit badges, receipts-first cards, positioning copy — all rendering over data the radar already commits.

**Architecture:** Three new pure modules (`web/tenure.py`, `web/sparkline.py`, `web/badge.py`) generate text/SVG deterministically; existing routes (`web/app.py`) and the static exporter (`web/static_site.py`) thread the new data through paired context keys / `render_static_site` kwargs, following the repo's established optional-kwarg + back-compat-test convention. No new collectors, no schema changes, no JS.

**Tech Stack:** Python 3.12, FastAPI + Jinja2, hand-templated SVG (precedent: `src/radar/web/cards.py` social cards), pytest. Run everything with `uv run`.

## Global Constraints

- **Rendering over new pipelines** (spec §2): read only `history.jsonl`-backed stores, `trending-observations.jsonl`, model/project metrics stores. No new collectors, no `DecisionCard`/`ModelEntry` schema changes.
- **Static-site parity**: every surface change lands identically in the live template and its `static_*` twin. Every new `render_static_site` kwarg is optional with a paired `*_backcompat` test (house convention — see `tests/test_static_site.py:631,677,710`).
- **Self-contained SVG only**: no external assets/fonts beyond the system stack; all text through `xml.sax.saxutils.escape`; SVG well-formedness pinned with `xml.dom.minidom.parseString` (precedent: `tests/test_social_cards.py`).
- **`| safe` is allowed ONLY on strings our own SVG helpers produced** (they escape internally). Never on data.
- **Effective history for tenure** (spec §2): project tenure computes over `apply_corrections(...)`; a fully-corrected project gets NO tenure line (raw fallback is for timelines, not credentials).
- **No sponsored-placement mechanics of any kind.**
- Deterministic: `now`/`generated_at` always injected; no wall-clock in the new pure modules.
- Positioning line, verbatim everywhere it appears: `Trending tells you what's hot. The radar tells you what to adopt — and what it takes to run it.`
- Gates before every commit: `uv run pytest -q && uv run ruff check . && uv run mypy src` (suite starts at 1094 passed).
- Commit format `<type>: <description>`, NO Co-Authored-By. Never commit `data/` files.
- Branch: `feature/differentiation-pass/design-spec` (already checked out, spec+plan committed on it).

**Context map (from recon — exact contracts):**
- Cards flow as `DecisionCard` objects straight into Jinja; index context is built at `web/app.py:142-165` (live) and `static_site.py:193-212` (static). Neither has history or metrics today.
- `HistoryStore.history_for(project)` oldest-first; `apply_corrections(events)` module function (`storage/history_store.py:72`); `ProjectHistoryEvent.ring/observed_at/change_type`. Models: `load_model_events(path)` (`models_radar/history.py:70`), fields `model_id/ring/observed_at/change_type` — no corrections concept.
- Series: `load_observations(path)` → `TrendingObservation(repo, stars, observed_at, lane, ...)` (`storage/trending_observations_log.py:30`); `ModelMetricsStore.history_for(model_id)` oldest-first, `ModelMetrics.downloads` (`storage/model_metrics_store.py:76`); `MetricsStore.history_for(project)` oldest-first, `ProjectMetrics.stars/hn_mentions` (`storage/metrics_store.py:113`).
- Velocity: `trending_detect.py` — `VELOCITY_WINDOW_DAYS = 7`, `NEW_WINDOW_DAYS = 14`; `star_velocity(rows, now)`, `build_trending(observations, now)` — no window args yet.
- SVG precedent: `web/cards.py` `render_card` (f-string parts + `escape`); tests pin `parseString`, size substrings, `&`→`&amp;`.
- Badge route precedent: `app.py:167-179` (`/history.jsonl` via `FileResponse`); for SVG use `fastapi.Response(content=svg, media_type="image/svg+xml")` (import `Response`).
- Ring colors (light fg): adopt `#0082B3`, pilot `#005F85`, watch `#8C6200`, avoid `#B93025` (`_base_styles.html:127-140`).
- `minimum_viable_quant(quants)` (`models_radar/memory.py:46`) is the canonical min-quant picker (4-bit floor) — templates currently use a floor-less `mems|min`; badges MUST use the Python function.
- Test idioms: no conftest; `TestClient(create_app(tmp_path))` + substring asserts (`tests/test_web.py:18-41`); `_card(project, ring)` factory + `render_static_site([...], tmp_path/"_site", datetime(...))` (`tests/test_static_site.py:23-26`); `_seed_trending_obs(root)` helper (`tests/test_web.py:1063`).

---

### Task 1: Tenure credential (`web/tenure.py` + index/project/model wiring)

**Files:**
- Create: `src/radar/web/tenure.py`
- Modify: `src/radar/web/app.py` (index route context + project route + model route), `src/radar/web/static_site.py` (new kwargs, thread to index + project + model pages), `src/radar/cli.py` (static-site command: build the maps), `src/radar/web/templates/index.html`, `static_index.html`, `_project_detail.html`, `_model_detail.html`, `_base_styles.html` (`.tenure` style)
- Test: `tests/test_tenure.py` (new), `tests/test_web.py` (append), `tests/test_static_site.py` (append)

**Interfaces:**
- Consumes: `apply_corrections`, `ProjectHistoryEvent`, `ModelHistoryEvent` (existing).
- Produces (later tasks do not depend on these; surfaces only):
  - `class TenureLine(BaseModel, frozen)`: `days_on_radar: int`, `ring: str`, `ring_since: str` (ISO date), `change_count: int`; property `text -> str` formatted exactly `"On radar {days} days · {RING} since {ring_since} · {change_count} ring change{s}"` (ring uppercased; `1 ring change` singular; `days_on_radar==0` renders `"On radar since today"` prefix instead of `0 days`).
  - `def project_tenure(events: list[ProjectHistoryEvent], now: datetime) -> TenureLine | None` — applies `apply_corrections`; `None` when no effective events.
  - `def model_tenure(events: list[ModelHistoryEvent], now: datetime) -> TenureLine | None` — same math, no corrections.
  - Both delegate to a private `_tenure(points: list[tuple[datetime, str]], now) -> TenureLine | None` where points are `(observed_at, ring_value)` oldest-first: `days_on_radar = (now.date() - points[0][0].date()).days`; `ring` = last point's ring; `ring_since` = walk backward while ring equal, take that earliest point's date; `change_count` = number of actual ring TRANSITIONS: `sum(1 for prev, cur in pairwise(rings) if cur != prev)` — an `updated` event at the same ring is NOT a change (this deliberately differs from `ProjectHistorySummary.change_count`, which counts events).

**Scope note (spec deviation, deliberate):** the models *table* (`models.html`) stays untouched — it is a dense data table, not a card. Tenure renders on: index tool rows (summary cell), project detail pages, model detail pages. The spec's "every model card/page" is satisfied by the detail page.

- [ ] **Step 1: Write the failing pure tests** (`tests/test_tenure.py`):

```python
"""Tenure credential lines computed from ring timelines."""

from __future__ import annotations

from datetime import UTC, datetime

from radar.models import Category, Ring
from radar.pipeline.delta import ChangeType
from radar.storage.history_store import ProjectHistoryEvent
from radar.web.tenure import TenureLine, model_tenure, project_tenure


NOW = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)


def _ev(day: int, ring: Ring, change: ChangeType = ChangeType.UPDATED,
        run: str = "", corrects: str | None = None) -> ProjectHistoryEvent:
    return ProjectHistoryEvent(
        project="vLLM", category=Category.MODEL_SERVING, change_type=change,
        ring=ring, previous_ring=None, run_id=run or f"run-{day}",
        observed_at=datetime(2026, 7, day, tzinfo=UTC), reasons=[],
        corrects_run_id=corrects,
    )


def test_tenure_line_text_and_streak():
    events = [
        _ev(1, Ring.WATCH, ChangeType.NEW),
        _ev(10, Ring.PILOT, ChangeType.PROMOTED),
        _ev(20, Ring.ADOPT, ChangeType.PROMOTED),
        _ev(25, Ring.ADOPT, ChangeType.UPDATED),
    ]
    line = project_tenure(events, NOW)
    assert line is not None
    assert line.days_on_radar == 27
    assert line.ring == "adopt"
    assert line.ring_since == "2026-07-20"   # streak start, not last event
    # watch -> pilot -> adopt = 2 transitions; the day-25 `updated` at the
    # same ring is NOT a ring change.
    assert line.change_count == 2
    assert line.text == "On radar 27 days · ADOPT since 2026-07-20 · 2 ring changes"


def test_single_event_is_singular_free():
    line = project_tenure([_ev(28, Ring.WATCH, ChangeType.NEW)], NOW)
    assert line is not None
    assert line.change_count == 0
    assert "0 ring changes" in line.text
    assert line.text.startswith("On radar since today")


def test_corrected_events_do_not_inflate_tenure():
    artifact = _ev(15, Ring.ADOPT, ChangeType.PROMOTED, run="run-outage")
    marker = _ev(16, Ring.WATCH, ChangeType.CORRECTED, run="repair:run-outage",
                 corrects="run-outage")
    clean = [_ev(1, Ring.WATCH, ChangeType.NEW), _ev(20, Ring.WATCH, ChangeType.UPDATED)]
    with_noise = [clean[0], artifact, marker, clean[1]]
    assert project_tenure(with_noise, NOW) == project_tenure(clean, NOW)


def test_fully_corrected_project_has_no_tenure():
    events = [
        _ev(15, Ring.ADOPT, ChangeType.PROMOTED, run="run-x"),
        _ev(16, Ring.WATCH, ChangeType.CORRECTED, run="repair:run-x", corrects="run-x"),
    ]
    assert project_tenure(events, NOW) is None


def test_model_tenure_same_shape():
    from radar.models_radar.history import ModelHistoryEvent

    events = [
        ModelHistoryEvent(model_id="m", family="F", change_type=ChangeType.NEW,
                          ring=Ring.PILOT, previous_ring=None, run_id="r1",
                          observed_at=datetime(2026, 7, 1, tzinfo=UTC), reasons=[]),
        ModelHistoryEvent(model_id="m", family="F", change_type=ChangeType.PROMOTED,
                          ring=Ring.ADOPT, previous_ring=Ring.PILOT, run_id="r2",
                          observed_at=datetime(2026, 7, 10, tzinfo=UTC), reasons=[]),
    ]
    line = model_tenure(events, NOW)
    assert line is not None and line.ring == "adopt" and line.change_count == 1
    assert "1 ring change" in line.text and "changes" not in line.text
```

(Verify `ModelHistoryEvent.change_type` accepts `ChangeType` — recon shows the model uses the same enum via string coercion; adjust to `"new"`/`"promoted"` strings if the field is typed differently.)

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_tenure.py -q` → ImportError.

- [ ] **Step 3: Implement** `src/radar/web/tenure.py`:

```python
"""Tenure credential: how long a project/model has been on the radar.

The differentiation-pass answer to trendshift's "Featured N times" archive —
except computed from the EFFECTIVE (outage-corrected) timeline, so the
credential can't be inflated by instrument noise (spec 2026-07-28 §F1).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from radar.models_radar.history import ModelHistoryEvent
from radar.storage.history_store import ProjectHistoryEvent, apply_corrections


class TenureLine(BaseModel):
    """One rendered credential line for a card or detail page."""

    model_config = ConfigDict(frozen=True)

    days_on_radar: int
    ring: str
    ring_since: str  # ISO date the current unbroken ring streak started
    change_count: int

    @property
    def text(self) -> str:
        prefix = (
            "On radar since today"
            if self.days_on_radar == 0
            else f"On radar {self.days_on_radar} days"
        )
        plural = "" if self.change_count == 1 else "s"
        return (
            f"{prefix} · {self.ring.upper()} since {self.ring_since} · "
            f"{self.change_count} ring change{plural}"
        )


def project_tenure(
    events: list[ProjectHistoryEvent], now: datetime
) -> TenureLine | None:
    """Tenure over the effective timeline; None when nothing effective remains."""
    effective = apply_corrections(events)
    return _tenure([(e.observed_at, e.ring.value) for e in effective], now)


def model_tenure(events: list[ModelHistoryEvent], now: datetime) -> TenureLine | None:
    return _tenure([(e.observed_at, e.ring.value) for e in events], now)


def _tenure(points: list[tuple[datetime, str]], now: datetime) -> TenureLine | None:
    if not points:
        return None
    points = sorted(points, key=lambda p: p[0])
    ring = points[-1][1]
    streak_start = points[-1][0]
    for observed_at, ring_value in reversed(points):
        if ring_value != ring:
            break
        streak_start = observed_at
    rings = [p[1] for p in points]
    transitions = sum(1 for prev, cur in zip(rings, rings[1:]) if cur != prev)
    return TenureLine(
        days_on_radar=(now.date() - points[0][0].date()).days,
        ring=ring,
        ring_since=streak_start.date().isoformat(),
        change_count=transitions,
    )
```

- [ ] **Step 4: Pure tests pass** — `uv run pytest tests/test_tenure.py -q`.

- [ ] **Step 5: Wire the surfaces (TDD per surface — write the web/static tests first, then thread).**

Web test (append to `tests/test_web.py`, reusing its card-seeding idiom; seed history via `HistoryStore` on `tmp_path/"data"/"radar.db"` + `append_events` to `tmp_path/"data"/"history.jsonl"` is NOT needed — the store alone feeds the route):

```python
def test_index_shows_tenure_credential(tmp_path: Path):
    from datetime import datetime

    from radar.pipeline.delta import ChangeType
    from radar.storage.history_store import HistoryStore, ProjectHistoryEvent

    db = RadarDatabase(tmp_path / "data" / "radar.db")
    db.initialize()
    db.upsert_cards([DecisionCard(project="vLLM", category=Category.MODEL_SERVING,
                                  ring=Ring.ADOPT, summary="s", workflow_fit={},
                                  risk_level="low")])
    history = HistoryStore(tmp_path / "data" / "radar.db")
    history.initialize()
    history.add_events([ProjectHistoryEvent(
        project="vLLM", category=Category.MODEL_SERVING, change_type=ChangeType.NEW,
        ring=Ring.ADOPT, previous_ring=None, run_id="r1",
        observed_at=datetime(2026, 5, 12, tzinfo=UTC), reasons=[])])

    text = TestClient(create_app(tmp_path)).get("/").text
    assert "ADOPT since 2026-05-12" in text
    assert 'class="tenure"' in text
```

Static test (append to `tests/test_static_site.py`):

```python
def test_static_index_shows_tenure_and_backcompat(tmp_path: Path):
    from radar.web.tenure import TenureLine

    tenure = {"vLLM": TenureLine(days_on_radar=77, ring="adopt",
                                 ring_since="2026-05-12", change_count=2)}
    render_static_site([_card("vLLM", Ring.ADOPT)], tmp_path / "_site",
                       datetime(2026, 7, 28, tzinfo=UTC), tenure_by_project=tenure)
    index = (tmp_path / "_site" / "index.html").read_text(encoding="utf-8")
    assert "On radar 77 days · ADOPT since 2026-05-12 · 2 ring changes" in index

    # Back-compat: omitting the kwarg renders without tenure chrome.
    render_static_site([_card("vLLM", Ring.ADOPT)], tmp_path / "_site2",
                       datetime(2026, 7, 28, tzinfo=UTC))
    index2 = (tmp_path / "_site2" / "index.html").read_text(encoding="utf-8")
    assert 'class="tenure"' not in index2
```

Implementation threading:
- `app.py` index route: construct `HistoryStore` (one already exists for `/history` — reuse the same instance pattern) and pass `"tenure_by_project": {c.project: project_tenure(history.history_for(c.project), now) for c in cards}` with `now = datetime.now(UTC)`; project route passes `tenure` for its card the same way; model route passes `model_tenure(events_for_model, now)` grouping `load_model_events(root/"data"/"model-history.jsonl")` by `model_id`.
- `static_site.py`: `render_static_site(..., tenure_by_project: dict[str, TenureLine] | None = None, model_tenure_by_id: dict[str, TenureLine] | None = None)`; thread to `static_index.html` (both tables), `_write_project_pages`, `_write_model_pages`.
- `cli.py` static-site command: build both maps next to the existing `timelines`/`metrics_by_project` blocks (`cli.py:1960-1971`), reusing `history.history_for(...)` and `load_model_events(...)`.
- Templates: in the Summary cell of `index.html`/`static_index.html` (both tables in static), directly under `{{ card.summary }}`:

```jinja
              {% set tl = tenure_by_project.get(card.project) if tenure_by_project else none %}
              {% if tl %}<div class="tenure">{{ tl.text }}</div>{% endif %}
```

  `_project_detail.html`: same `<div class="tenure">` under the ring pill block (context var `tenure`). `_model_detail.html`: under the ring/score line (context var `model_tenure_line`). `_base_styles.html`: `.tenure { color: var(--muted); font-size: 0.78rem; margin-top: 0.2rem; }` next to the `.evidence` rule (line ~166).

- [ ] **Step 6: Full gates** — `uv run pytest -q && uv run ruff check . && uv run mypy src` → PASS.
- [ ] **Step 7: Commit** — `git commit -am "feat: tenure credential line on cards and detail pages (effective timeline)"`

---

### Task 2: Sparkline helper (`web/sparkline.py`)

**Files:**
- Create: `src/radar/web/sparkline.py`
- Test: `tests/test_sparkline.py` (new)

**Interfaces:**
- Produces (Task 3 consumes): `def sparkline_svg(values: Sequence[float], *, label: str) -> str` — `""` when fewer than 3 finite values; else a self-contained `<svg>` 120×28 (`viewBox="0 0 120 28"`, `role="img"`, `aria-label=escape(label)`, `<title>` first child), one `<polyline>` (`fill="none" stroke="currentColor" stroke-width="1.5"`) plus a terminal `<circle r="2" fill="currentColor">`. Coordinates: x evenly spaced 2→118; y mapped from value range to 24→4 (padding 4); flat series (max==min) renders the mid line y=14. All numbers rounded to 2 decimals — deterministic output. Uses `currentColor` so light/dark theming is free.

- [ ] **Step 1: Write the failing tests** (`tests/test_sparkline.py`):

```python
"""Deterministic inline-SVG sparklines (no JS, no external assets)."""

from __future__ import annotations

from xml.dom.minidom import parseString

from radar.web.sparkline import sparkline_svg


def test_renders_wellformed_svg_with_a11y():
    svg = sparkline_svg([1, 5, 3, 8], label="stars, last 4 scans")
    parseString(svg)
    assert 'viewBox="0 0 120 28"' in svg
    assert 'role="img"' in svg
    assert "stars, last 4 scans" in svg
    assert "<polyline" in svg and "<circle" in svg
    assert "currentColor" in svg


def test_below_three_points_renders_nothing():
    assert sparkline_svg([], label="x") == ""
    assert sparkline_svg([1.0], label="x") == ""
    assert sparkline_svg([1.0, 2.0], label="x") == ""


def test_flat_series_has_no_nan_and_midline():
    svg = sparkline_svg([7, 7, 7], label="flat")
    parseString(svg)
    assert "nan" not in svg.lower()
    assert "14.0" in svg or "14," in svg or " 14" in svg


def test_label_is_escaped():
    svg = sparkline_svg([1, 2, 3], label="a<b&c")
    assert "a&lt;b&amp;c" in svg


def test_deterministic():
    a = sparkline_svg([1, 2, 3, 10], label="d")
    assert a == sparkline_svg([1, 2, 3, 10], label="d")
```

- [ ] **Step 2: Verify failure**, then **Step 3: Implement**:

```python
"""Inline-SVG sparklines: tiny, deterministic, theme-aware (currentColor).

Static-site constraint: no JS chart libraries, no external assets — the
whole chart is one self-contained <svg> string (spec 2026-07-28 §F2).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from xml.sax.saxutils import escape

_W, _H = 120, 28
_PAD = 4
_MIN_POINTS = 3


def sparkline_svg(values: Sequence[float], *, label: str) -> str:
    """A 120x28 polyline sparkline, or '' below 3 finite points."""
    finite = [float(v) for v in values if v is not None and math.isfinite(float(v))]
    if len(finite) < _MIN_POINTS:
        return ""
    lo, hi = min(finite), max(finite)
    span = hi - lo
    step = (_W - 2 * _PAD) / (len(finite) - 1)

    def _y(v: float) -> float:
        if span == 0:
            return _H / 2
        return _H - _PAD - ((v - lo) / span) * (_H - 2 * _PAD)

    points = [
        (round(_PAD + i * step, 2), round(_y(v), 2)) for i, v in enumerate(finite)
    ]
    pts = " ".join(f"{x},{y}" for x, y in points)
    end_x, end_y = points[-1]
    safe_label = escape(label)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{_W}" height="{_H}" '
        f'viewBox="0 0 {_W} {_H}" role="img" aria-label="{safe_label}">'
        f"<title>{safe_label}</title>"
        f'<polyline points="{pts}" fill="none" stroke="currentColor" '
        f'stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/>'
        f'<circle cx="{end_x}" cy="{end_y}" r="2" fill="currentColor"/>'
        "</svg>"
    )
```

- [ ] **Step 4: Tests pass; full gates.**
- [ ] **Step 5: Commit** — `git commit -am "feat: deterministic inline-SVG sparkline helper"`

---

### Task 3: Sparkline wiring — trending rows, project pages, model pages

**Files:**
- Create: `src/radar/web/spark_series.py`
- Modify: `src/radar/web/app.py` (trending, project, model routes), `src/radar/web/static_site.py` (`_write_trending_page`, `_write_project_pages`, `_write_model_pages` + kwargs), `src/radar/cli.py` (static-site command: model metrics map), templates `trending.html`, `static_trending.html`, `_project_detail.html`, `_model_detail.html`, `_base_styles.html` (`.spark` cell style)
- Test: `tests/test_spark_series.py` (new), `tests/test_web.py` (append), `tests/test_static_site.py` (append)

**Interfaces:**
- Consumes: `sparkline_svg` (Task 2), `TrendingObservation`, `ProjectMetrics`, `ModelMetrics`.
- Produces:
  - `def trending_sparklines(observations: list[TrendingObservation], limit: int = 14) -> dict[str, str]` — per repo, stars series oldest-first (last `limit` observations), label `f"{repo} stars, last {n} sweeps"`; repos below 3 points map to `""`.
  - `def star_sparkline(rows: list[ProjectMetrics]) -> str` — stars series (None stars skipped), label `"stars, last {n} scans"`.
  - `def downloads_sparkline(rows: list[ModelMetrics]) -> str` — downloads series, label `"downloads, last {n} scans"`.
  - Template contract: cells render `{{ spark | safe }}` — safe is legitimate because Task 2's helper escapes everything it interpolates.

**Scope note (spec deviation, deliberate):** the models *table* (`models.html`) does not get a sparkline column — the download series lands on model detail pages, mirroring how project star history lives on project pages. The spec's "model rows/pages" is satisfied by pages; adding a 10th column to an already-dense filterable table hurts more than it helps. Documented for the final review.

- [ ] **Step 1: Write the failing pure tests** (`tests/test_spark_series.py`):

```python
"""Series extraction feeding the sparkline helper."""

from __future__ import annotations

from datetime import UTC, datetime

from radar.discovery.trending_entities import Lane, TrendingObservation
from radar.storage.metrics_store import ProjectMetrics
from radar.storage.model_metrics_store import ModelMetrics
from radar.web.spark_series import downloads_sparkline, star_sparkline, trending_sparklines


def _obs(repo: str, stars: int, day: int) -> TrendingObservation:
    return TrendingObservation(
        repo=repo, lane=Lane.ONPREM, stars=stars,
        observed_at=datetime(2026, 7, day, 7, 0, tzinfo=UTC),
        repo_created_at=datetime(2026, 6, 1, tzinfo=UTC),
        description="", topics=[], license="MIT",
    )


def test_trending_sparklines_grouped_and_ordered():
    obs = [_obs("a/r", 300, 3), _obs("a/r", 100, 1), _obs("a/r", 200, 2),
           _obs("b/r", 50, 1), _obs("b/r", 60, 2)]  # b/r: only 2 points
    sparks = trending_sparklines(obs)
    assert "<svg" in sparks["a/r"]
    assert sparks["b/r"] == ""


def test_trending_sparklines_respect_limit():
    obs = [_obs("a/r", 100 + d, d) for d in range(1, 20)]
    spark_all = trending_sparklines(obs, limit=14)
    # 14 points -> 14 coordinate pairs in the polyline
    assert spark_all["a/r"].count(",") >= 14


def test_star_and_download_sparklines_skip_none():
    rows = [ProjectMetrics(project="p", run_id=f"r{i}",
                           observed_at=datetime(2026, 7, i + 1, tzinfo=UTC),
                           stars=s)
            for i, s in enumerate([100, None, 120, 130])]
    assert "<svg" in star_sparkline(rows)

    mrows = [ModelMetrics(model_id="m", run_id=f"r{i}",
                          observed_at=datetime(2026, 7, i + 1, tzinfo=UTC),
                          downloads=d)
             for i, d in enumerate([10, 20, None])]
    assert downloads_sparkline(mrows) == ""  # only 2 usable points
```

- [ ] **Step 2: Verify failure**, then **Step 3: Implement** `src/radar/web/spark_series.py`:

```python
"""Build per-entity value series from stores/logs and render sparklines."""

from __future__ import annotations

from radar.discovery.trending_entities import TrendingObservation
from radar.storage.metrics_store import ProjectMetrics
from radar.storage.model_metrics_store import ModelMetrics
from radar.web.sparkline import sparkline_svg


def trending_sparklines(
    observations: list[TrendingObservation], limit: int = 14
) -> dict[str, str]:
    """repo -> sparkline SVG of its star counts (last ``limit`` sweeps)."""
    by_repo: dict[str, list[TrendingObservation]] = {}
    for obs in observations:
        by_repo.setdefault(obs.repo, []).append(obs)
    sparks: dict[str, str] = {}
    for repo, rows in by_repo.items():
        series = [r.stars for r in sorted(rows, key=lambda r: r.observed_at)][-limit:]
        sparks[repo] = sparkline_svg(
            series, label=f"{repo} stars, last {len(series)} sweeps"
        )
    return sparks


def star_sparkline(rows: list[ProjectMetrics]) -> str:
    series = [float(r.stars) for r in rows if r.stars is not None]
    return sparkline_svg(series, label=f"stars, last {len(series)} scans")


def downloads_sparkline(rows: list[ModelMetrics]) -> str:
    series = [float(r.downloads) for r in rows if r.downloads is not None]
    return sparkline_svg(series, label=f"downloads, last {len(series)} scans")
```

- [ ] **Step 4: Wire surfaces (tests first, per surface).**

Web test (append to `tests/test_web.py`, reusing `_seed_trending_obs`):

```python
def test_trending_rows_show_sparklines(tmp_path: Path):
    _seed_trending_obs(tmp_path)
    # third observation so acme/rocket clears the 3-point floor
    from datetime import datetime as _dt

    from radar.discovery.trending_entities import Lane as _L
    from radar.discovery.trending_entities import TrendingObservation as _O
    from radar.storage.trending_observations_log import append_observations

    append_observations(tmp_path / "data" / "trending-observations.jsonl", [
        _O(repo="acme/rocket", lane=_L.ONPREM, stars=500,
           observed_at=_dt(2026, 7, 5, 7, 0, tzinfo=UTC),
           repo_created_at=_dt(2026, 6, 1, tzinfo=UTC),
           description="fast serving", topics=["llm"], license="MIT"),
    ])
    text = TestClient(create_app(tmp_path)).get("/trending").text
    assert 'class="spark"' in text
    assert "acme/rocket stars" in text  # aria-label made it through
```

Static test (append to `tests/test_static_site.py`): render with `trending_observations=_trending_obs() + [third obs]` (extend the existing `_trending_obs` helper locally) and assert `trending.html` contains `class="spark"`; back-compat: existing exports without observations unchanged (already covered by `test_static_site_backcompat_without_trending` — extend nothing).

Threading:
- Trending: `app.py` trending route loads observations (same loader `_trending_entries` uses underneath — call `load_observations(root / "data" / "trending-observations.jsonl")` directly) and passes `spark_by_repo=trending_sparklines(observations)`. `static_site.py` computes it where `trending_entries` is derived (line ~178) and passes into `_write_trending_page(..., spark_by_repo=...)` (new optional param, default `None` → `{}`).
- Row markup (BOTH `trending.html:26-35` and `static_trending.html:26-35`): new `<th>14d</th>` after "Velocity" header and new cell `<td class="spark">{{ (spark_by_repo or {}).get(e.repo, "") | safe }}</td>`. Update the empty-state `colspan` in both templates (recon: count existing columns; 6 → 7).
- Project pages: routes/static pass `star_spark = star_sparkline(metric_rows_oldest_first)` — NOTE both surfaces currently reverse to newest-first for the table (`app.py:201`); compute the spark from the oldest-first list BEFORE reversing. `_project_detail.html` renders it beside the "Observed metrics" heading: `{% if star_spark %}<span class="spark">{{ star_spark | safe }}</span>{% endif %}`.
- Model pages: `app.py` model route reads `ModelMetricsStore(root / "data" / "radar.db").history_for(model_id)` → `download_spark`; static path: `cli.py` builds `model_metrics_by_id = {e.id: store.history_for(e.id) for e in entries}` and `render_static_site` gains optional `model_metrics_by_id` kwarg → `_write_model_pages` computes `download_spark` per model. `_model_detail.html` renders next to the downloads stat.
- `_base_styles.html`: `.spark svg { vertical-align: middle; color: var(--blue-dark); } td.spark { min-width: 128px; }`.

- [ ] **Step 5: Full gates.**
- [ ] **Step 6: Commit** — `git commit -am "feat: star/download sparklines on trending rows and detail pages"`

---

### Task 4: Trending time-window tabs (7d / 30d / 90d)

**Files:**
- Modify: `src/radar/discovery/trending_detect.py` (window param), `src/radar/web/app.py` (trending route param), `src/radar/web/static_site.py` (three-variant export), templates `trending.html`, `static_trending.html`, `_base_styles.html` (`.tabs`)
- Test: `tests/test_trending_detect.py` (append), `tests/test_web.py` (append), `tests/test_static_site.py` (append)

**Interfaces:**
- Consumes: existing `VELOCITY_WINDOW_DAYS = 7`, `build_trending`, `star_velocity`.
- Produces:
  - `star_velocity(rows, now, window_days: int = VELOCITY_WINDOW_DAYS)` and `build_trending(observations, now, window_days: int = VELOCITY_WINDOW_DAYS)` — purely additive kwargs, `NEW` logic unchanged.
  - `TRENDING_WINDOWS: dict[str, int] = {"7d": 7, "30d": 30, "90d": 90}` exported from `trending_detect.py`.
  - Live route: `/trending?window=30d` (unknown values fall back to `7d`); context gains `active_window: str` and `windows: list[str]`.
  - Static: `trending.html` (7d) + `trending-30d.html` + `trending-90d.html`; tabs link between files (static) or query params (live). Sparkline map (Task 3) is window-independent (always last 14 sweeps) — pass through unchanged.

- [ ] **Step 1: Failing pure test** (append to `tests/test_trending_detect.py`, reusing its observation helpers):

```python
def test_velocity_window_parameter():
    from datetime import UTC, datetime, timedelta

    now = datetime(2026, 7, 28, tzinfo=UTC)
    rows = [
        _obs_at("a/r", 100, now - timedelta(days=20)),
        _obs_at("a/r", 400, now - timedelta(days=1)),
    ]  # adapt to the file's existing observation factory name/signature
    assert star_velocity(rows, now) is None            # outside 7d window
    v30 = star_velocity(rows, now, window_days=30)
    assert v30 is not None and v30 > 0


def test_trending_windows_mapping():
    from radar.discovery.trending_detect import TRENDING_WINDOWS

    assert TRENDING_WINDOWS == {"7d": 7, "30d": 30, "90d": 90}
```

(Read `tests/test_trending_detect.py`'s existing factory first — it imports `NEW_WINDOW_DAYS` by name already, so extending the module surface is in-pattern.)

- [ ] **Step 2: Verify failure**, then **Step 3: Implement** — `trending_detect.py`: add `window_days` kwarg to `star_velocity` (replace the hardcoded constant in the `cutoff` line), thread through `build_trending`, add `TRENDING_WINDOWS`. Route (`app.py:318`):

```python
    @app.get("/trending", response_class=HTMLResponse)
    def trending_page(request: Request, window: str = "7d"):
        days = TRENDING_WINDOWS.get(window)
        if days is None:
            window, days = "7d", TRENDING_WINDOWS["7d"]
        observations = _trending_observations()
        entries = build_trending(observations, datetime.now(UTC), window_days=days)
        ...
        # context adds: "active_window": window, "windows": list(TRENDING_WINDOWS)
```

(Refactor note: `_trending_entries()` currently returns pre-built entries via `load_trending_entries`; the route needs raw observations to rebuild per-window — add `_trending_observations()` helper beside it; keep `_trending_entries()` for the index strip.)

Static (`static_site.py`): where trending is derived, loop:

```python
    for window_key, days in TRENDING_WINDOWS.items():
        entries_w = build_trending(trending_observations, generated_at, window_days=days) if trending_observations else []
        filename = "trending.html" if window_key == "7d" else f"trending-{window_key}.html"
        _write_trending_page(..., filename=filename, active_window=window_key, ...)
```

(`_write_trending_page` gains `filename: str = "trending.html"` and `active_window: str = "7d"` params; hub/candidate sections render identically on all three.) Templates: above the lane tables in both:

```jinja
<nav class="tabs" aria-label="Velocity window">
  {% for w in windows %}
  {% if w == active_window %}<span class="tab tab-active">{{ w }}</span>
  {% else %}<a class="tab" href="{{ window_href(w) }}">{{ w }}</a>{% endif %}
  {% endfor %}
</nav>
```

Live passes `window_href = lambda w: "/trending?window=" + w` equivalent via context dict `window_hrefs: dict[str,str]` (Jinja-friendlier: precompute hrefs; static: `trending.html`/`trending-30d.html`/`trending-90d.html`). `.tabs`/`.tab`/`.tab-active` styles mirror the existing filter-bar pill styling in `_base_styles.html`.

Web/static tests: `/trending?window=30d` returns 200 + `tab-active">30d`; unknown `?window=1h` falls back (assert `tab-active">7d`); static export writes all three files, `trending-30d.html` contains the tab nav and links back to `trending.html`.

- [ ] **Step 4: Full gates.** (Watch for: `test_publish_workflow`/site tests pinning trending.html column counts — update deliberately with the new spark column from Task 3 if not already done there.)
- [ ] **Step 5: Commit** — `git commit -am "feat: 7d/30d/90d velocity window tabs on trending"`

---

### Task 5: Badges — ring + fit, export dir, dashboard routes, page sections

**Files:**
- Create: `src/radar/web/badge.py`
- Modify: `src/radar/web/app.py` (three GET routes + `Response` import), `src/radar/web/static_site.py` (`_write_badges` + call + downloads note), templates `_project_detail.html`, `_model_detail.html` (Badge section), `_base_styles.html` (badge-snippet styling)
- Test: `tests/test_badge.py` (new), `tests/test_web.py` (append), `tests/test_static_site.py` (append)

**Interfaces:**
- Consumes: `project_slug`/`build_slug_map` (`web/slugs.py`), `minimum_viable_quant` (`models_radar/memory.py:46` — the 4-bit-floor picker, NOT the template's `mems|min`), `DecisionCard.ring` (pinned decisions already resolved into `ring`; nothing special to do — document in the Badge section title tooltip when `card.pinned`).
- Produces:
  - `RING_BADGE_COLORS: dict[str, str]` — right-cell background per ring; starting values `{"adopt": "#00719E", "pilot": "#005F85", "watch": "#8C6200", "avoid": "#B93025"}`. A unit test computes WCAG relative-luminance contrast of white text on each and asserts `>= 4.5`; if a value fails, darken it until the test passes (the test is the authority, not these literals).
  - `def ring_badge_svg(ring: str) -> str` — shields-style two-cell pill: left cell `on-prem radar` on `#555`, right cell the ring name uppercased on `RING_BADGE_COLORS[ring]`, white text, `font-family="Verdana,Geneva,DejaVu Sans,sans-serif" font-size="11"`, height 20, `rx="3"`, `<title>on-prem radar: {ring}</title>`. Width from a deterministic `_text_width(s) = round(len(s) * 6.8) + 12` estimate.
  - `def fit_badge_svg(tier: str, quant_format: str | None) -> str` — left `runs on`, right `{tier}` plus ` ({quant_format})` when given, on `#005F85`.
  - `def badge_markdown(badge_url: str, target_url: str, alt: str) -> str` → `f"[![{alt}]({badge_url})]({target_url})"`.
  - Static export: `badges/` subdir — `badges/{slug}.svg` per card, `badges/model-{id}.svg` per model with a ring, `badges/fit-{id}.svg` per model whose `hardware_tier` is not `unknown` (quant label from `minimum_viable_quant(entry.quants)`, e.g. `Q5_K_M`; omitted when None). Path-only URLs — forward-compatible with sub-project D swapping fit-badge CONTENT without changing URLs.
  - Live routes: `GET /badge/{slug}.svg`, `GET /badge/model-{model_id}.svg`, `GET /badge/fit-{model_id}.svg` → `Response(content=svg, media_type="image/svg+xml")`; 404 `PlainTextResponse` for unknown slug/id (match the `/history.jsonl` idiom at `app.py:167-179`).
  - Page sections: `_project_detail.html` and `_model_detail.html` get an `<h2>Badge</h2>` block — inline badge preview (`| safe`) + a `<pre class="badge-snippet">` with the copy-ready Markdown (context vars `badge_svg`, `badge_snippet` threaded like the rest; static uses `badge_base` = the export's `self_base_url` or `""` → relative).

- [ ] **Step 1: Failing pure tests** (`tests/test_badge.py`):

```python
"""Shields-style ring/fit badges (deterministic, self-contained SVG)."""

from __future__ import annotations

from xml.dom.minidom import parseString

from radar.web.badge import (
    RING_BADGE_COLORS,
    badge_markdown,
    fit_badge_svg,
    ring_badge_svg,
)


def _rel_luminance(hex_color: str) -> float:
    channels = [int(hex_color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def test_white_text_contrast_is_aa_on_every_ring_color():
    for ring, color in RING_BADGE_COLORS.items():
        contrast = (1.0 + 0.05) / (_rel_luminance(color) + 0.05)
        assert contrast >= 4.5, f"{ring}: {color} fails AA ({contrast:.2f})"


def test_ring_badge_shape_and_escaping():
    svg = ring_badge_svg("adopt")
    parseString(svg)
    assert "on-prem radar" in svg and "ADOPT" in svg
    assert RING_BADGE_COLORS["adopt"] in svg
    assert 'height="20"' in svg
    assert svg == ring_badge_svg("adopt")  # deterministic


def test_fit_badge_with_and_without_quant():
    svg = fit_badge_svg("workstation", "Q5_K_M")
    parseString(svg)
    assert "runs on" in svg and "workstation (Q5_K_M)" in svg
    assert "workstation (" not in fit_badge_svg("workstation", None)


def test_badge_markdown():
    md = badge_markdown("https://x/badges/vllm.svg", "https://x/project_vllm.html",
                        "On-Prem Radar: ADOPT")
    assert md == "[![On-Prem Radar: ADOPT](https://x/badges/vllm.svg)](https://x/project_vllm.html)"
```

- [ ] **Step 2: Verify failure**, then **Step 3: Implement** `badge.py` following `web/cards.py`'s f-string style (module docstring: badges are earned, never sold — spec §2). Two `<rect>` cells + two centered `<text>` elements; total width = left + right cell widths.

- [ ] **Step 4: Export + routes + sections (tests first).** Static test:

```python
def test_static_export_writes_badges_and_snippet(tmp_path: Path):
    render_static_site([_card("vLLM", Ring.ADOPT)], tmp_path / "_site",
                       datetime(2026, 7, 28, tzinfo=UTC),
                       self_base_url="https://radar.example")
    badge = tmp_path / "_site" / "badges" / "vllm.svg"
    assert badge.exists() and "ADOPT" in badge.read_text(encoding="utf-8")
    page = (tmp_path / "_site" / "project_vllm.html").read_text(encoding="utf-8")
    assert "https://radar.example/badges/vllm.svg" in page  # snippet uses base url
```

Web test: `TestClient(...).get("/badge/vllm.svg")` → 200, `image/svg+xml`, "ADOPT" in body; unknown slug → 404. Implementation: `_write_badges(out_dir, cards, slug_by_project, model_entries)` writes into `(out_dir / "badges").mkdir(...)`; call it unconditionally in `render_static_site` (empty inputs → empty dir is fine, or skip when no cards — match the `if trending_entries or ...:` guard style). Badge section templates + snippet threading per the Interfaces block. Model fit badge uses `minimum_viable_quant`.

- [ ] **Step 5: Full gates.**
- [ ] **Step 6: Commit** — `git commit -am "feat: embeddable ring and fit badges with copy-ready snippets"`

---

### Task 6: Receipts-first cards + HN chip

**Files:**
- Modify: `src/radar/web/app.py` (index context: hn map), `src/radar/web/static_site.py` (index kwarg), `src/radar/cli.py` (derive hn map from the `metrics_by_project` it already builds at `cli.py:1969-1971`), templates `index.html`, `static_index.html`, `_base_styles.html` (`.chip`)
- Test: `tests/test_web.py` (append), `tests/test_static_site.py` (append)

**Interfaces:**
- Receipts: both index surfaces cap evidence to the top TWO notes — `{% for note in card.evidence_notes[:2] %}` — and add `{% if card.evidence_notes|length > 2 %}<li class="evidence-more">+{{ card.evidence_notes|length - 2 }} more →</li>{% endif %}` (the whole summary cell already links to the project page on static; on live wrap the `+N more` in the project link). The static "All Tracked Projects" table (which today shows NO evidence — recon §5b asymmetry) gains the same 2-line block under `{{ card.on_prem_fit }}`.
- HN chip: context key `hn_by_project: dict[str, int]` (only projects with a positive latest `hn_mentions`); renders before the summary text: `<span class="chip chip-hn" title="Hacker News mentions in the scan window">{{ n }} HN</span>`. Live: build from `MetricsStore.latest(project)` per card in the index route. Static: `render_static_site` gains optional `hn_by_project` kwarg; `cli.py` derives `{p: rows[-1].hn_mentions for p, rows in metrics_by_project.items() if rows and rows[-1].hn_mentions}`.

- [ ] **Step 1: Failing tests.** Web:

```python
def test_index_caps_evidence_and_shows_hn_chip(tmp_path: Path):
    from radar.storage.metrics_store import MetricsStore, ProjectMetrics

    db = RadarDatabase(tmp_path / "data" / "radar.db")
    db.initialize()
    card = DecisionCard(project="vLLM", category=Category.MODEL_SERVING,
                        ring=Ring.ADOPT, summary="s", workflow_fit={},
                        risk_level="low",
                        evidence_notes=["note one", "note two", "note three"])
    db.upsert_cards([card])
    metrics = MetricsStore(tmp_path / "data" / "radar.db")
    metrics.initialize()
    metrics.record([ProjectMetrics(project="vLLM", run_id="r1",
                                   observed_at=datetime(2026, 7, 28, tzinfo=UTC),
                                   hn_mentions=12)])

    text = TestClient(create_app(tmp_path)).get("/").text
    assert "note one" in text and "note two" in text
    assert "note three" not in text
    assert "+1 more" in text
    assert ">12 HN<" in text
```

(Adapt `MetricsStore.record` call to its real signature — read `storage/metrics_store.py` record method first.) Static: same shape via `render_static_site(..., hn_by_project={"vLLM": 12})` + back-compat test (no kwarg → no `chip-hn` in output).

- [ ] **Step 2: Verify failure → implement → Step 3: Full gates.** (`.chip` CSS: reuse `.badge` base with `--blue-dark` border/text; place next to `.badge-pinned` rules ~`_base_styles.html:143`.)
- [ ] **Step 4: Commit** — `git commit -am "feat: receipts-first cards — top-2 evidence lines and HN mention chip"`

---

### Task 7: Positioning copy (hero, README, digest)

**Files:**
- Modify: `src/radar/web/templates/_hero.html` (optional `positioning` var), `index.html`, `static_index.html`, `digest.html` (set the var), `_base_styles.html` (`.positioning`), `README.md` (top section), `src/radar/web/templates/_footer.html` (no change unless needed)
- Test: `tests/test_web.py` (append one assertion to an existing index test or a tiny new one), `tests/test_static_site.py` (append), `tests/test_digest.py` or the digest-render test file (append — grep `digest.html` render tests first)

**Interfaces:** `_hero.html` gains, directly under the tagline line:

```jinja
    {% if positioning %}<p class="positioning">{{ positioning }}</p>{% endif %}
```

`index.html`/`static_index.html`/`digest.html` add `{% set positioning = "Trending tells you what's hot. The radar tells you what to adopt — and what it takes to run it." %}` beside their existing `{% set tagline = ... %}`. CSS: `.positioning { color: rgba(255,255,255,0.85); font-style: italic; font-size: 0.9rem; margin: 0 0 0.6rem; max-width: 62ch; }` next to `.tagline` (`_base_styles.html:74`).

README: under the bold one-liner (line 3), add the positioning line as a quote plus a three-bullet block:

```markdown
> **Trending tells you what's hot. The radar tells you what to adopt — and what it takes to run it.**

**How this differs from trending trackers:**
- 🧭 **Computed, not sponsored** — rings come from a deterministic rubric and an append-only, auditable timeline. Placement cannot be bought.
- 🧾 **Every number cited** — model specs carry per-number provenance (source, date, human-verified flag); a weekly job re-verifies them against upstream.
- 🤖 **Agent-queryable** — a built-in MCP server lets Claude/Codex/any MCP client ask the radar questions mid-task.
```

- [ ] **Step 1: Failing tests** — index (live+static) contain the positioning sentence; hero without the var renders no `.positioning` element (back-compat: assert an existing non-index page, e.g. `/models`, lacks `class="positioning"`).
- [ ] **Step 2: Implement; full gates** (README changes are gate-neutral; check no test pins the README head — `grep -rn "not a generic AI news digest" tests/` first).
- [ ] **Step 3: Commit** — `git commit -am "feat: positioning line on hero, README, and digest"`

---

## Final verification (whole sub-project)

- [ ] `uv run pytest -q && uv run ruff check . && uv run mypy src` — all green.
- [ ] Live smoke: `uv run radar export --out /tmp/dp-site --base-url https://ekaynac.github.io/onprem-ai-adoption-radar` on the real repo data → open `index.html`: tenure lines present, sparklines render, tabs navigate, `badges/` populated, badge snippets carry absolute URLs, positioning line visible; `trending-30d.html`/`trending-90d.html` exist.
- [ ] Dashboard smoke: `uv run radar serve` → `/`, `/trending?window=30d`, `/badge/<some-slug>.svg` respond correctly.
- [ ] Old-data back-compat: an export with no trending observations / no metrics renders without empty chrome (covered by the per-task back-compat tests; eyeball once).
- [ ] Subagent-driven per-task reviews + final whole-branch review; PR per repo convention — **checks verified green BEFORE merge**.
