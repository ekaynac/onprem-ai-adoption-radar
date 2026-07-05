# Trending Radar — Plan A (Engine) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build sub-project 1 of the trending radar: a two-lane GitHub sweep that appends to a committed observation log, deterministic velocity/new detection over that log, a `radar trending` CLI, and daily CI wiring — the engine every later surface and the source autopilot derive from.

**Architecture:** New `src/radar/discovery/trending_*.py` modules + a storage log mirroring the technique-metrics-log pattern. The daily sweep queries GitHub search (two lanes × two query shapes) and appends one `TrendingObservation` row per repo to `data/trending-observations.jsonl` (committed by CI like the history logs). Growth cannot be read from GitHub, so velocity is *derived* from repeated observations across days. Everything downstream (page, digest, cards, autopilot) reads the same store.

**Tech Stack:** Python 3.12, pydantic v2, typer, httpx (all in-tree; **no new dependencies**), pytest + ruff + mypy.

**Spec:** `docs/superpowers/specs/2026-07-05-trending-radar-design.md` (approved), §1 fully; §2–§4 are later sub-projects.

## Global Constraints

- Deterministic core: identical inputs → identical output; the sweep is best-effort and never fails a scan (API failure → no new observations + warning).
- No LLM anywhere. No new third-party dependencies. Keyless-or-token public GitHub API only (no scraping, no BigQuery).
- ruff line-length = 100; `python_version = 3.12`; every file starts with `from __future__ import annotations`.
- Coverage ≥ 80% enforced; gates: `uv run pytest`, `uv run ruff check .`, `uv run mypy src/radar`.
- Commit format `<type>: <description>`; no attribution lines; `git add` specific paths only (the working tree carries an unrelated modified `data/history.jsonl` that must NEVER be committed).
- Entities are pydantic v2, frozen for value objects; the observation log mirrors `src/radar/storage/technique_metrics_log.py` (missing file → `[]`, corrupt lines skipped with a warning).
- **Two lanes**: `onprem` (strict radar identity) and `broader` (general AI heat). A repo matching both lands in `onprem` (strict wins). Tracked sources are excluded from the sweep.
- Verified live (2026-07-05, token'd GitHub search): `GET /search/repositories?q=<query>&sort=stars&order=desc&per_page=N` returns `{total_count, items:[…]}`; each item carries `full_name`, `stargazers_count`, `created_at` (ISO), `pushed_at`, `html_url`, `description`, `topics: [...]`, and **`license.spdx_id`** (`"Apache-2.0"`/`"MIT"`/`"NOASSERTION"` for unknown, or `license: null`). The `q` filters `topic:X`, `stars:>=N`, `pushed:>=YYYY-MM-DD`, `created:>=YYYY-MM-DD` all work. License comes FREE in the search payload — store it now so sub-project 2's autopilot needs no extra call.

## File Structure

```
src/radar/discovery/trending_entities.py        # NEW: Lane enum, TrendingObservation, TrendingEntry
src/radar/storage/trending_observations_log.py  # NEW: append_observations / load_observations (JSONL)
src/radar/discovery/trending_detect.py          # NEW: star_velocity, is_new, build_trending (pure)
src/radar/discovery/trending_sweep.py           # NEW: two-lane GitHub sweep → observations
src/radar/cli.py                                 # MODIFY: trending_app (scan / list)
.github/workflows/publish.yml                    # MODIFY: daily trending scan + commit the log
tests/test_trending_entities.py                   # NEW
tests/test_trending_observations_log.py          # NEW
tests/test_trending_detect.py                    # NEW
tests/test_trending_sweep.py                      # NEW
tests/test_trending_cli.py                        # NEW
tests/test_publish_workflow.py                    # MODIFY
README.md, CHANGELOG.md                           # MODIFY
```

Out of scope (later sub-projects, per spec): the source autopilot / promotion (sub-project 2), the `/trending` page + MCP tool (sub-project 3), the digest + cards (sub-project 4). This plan produces the observation store + detection + `radar trending scan|list` + CI persistence — nothing reads the store yet except the CLI list.

---

### Task 1: Trending entities

**Files:**
- Create: `src/radar/discovery/trending_entities.py`
- Test: `tests/test_trending_entities.py`

**Interfaces:**
- Consumes: nothing new (pydantic, enum, datetime).
- Produces (all later tasks import these exact names):
  - `Lane(str, Enum)`: `ONPREM = "onprem"`, `BROADER = "broader"`.
  - `TrendingObservation` (frozen, `extra="forbid"`): `repo: str` (owner/name), `lane: Lane`, `stars: int`, `observed_at: datetime`, `repo_created_at: datetime`, `description: str = ""`, `topics: list[str] = []`, `license: str | None = None`.
  - `TrendingEntry` (frozen): `repo: str`, `lane: Lane`, `stars: int`, `velocity_per_day: float | None`, `is_new: bool`, `first_seen: str` (ISO date), `description: str`, `topics: list[str]`, `license: str | None = None`.

- [ ] **Step 1: Write the failing tests**

```python
"""Trending entities: lane, observation row, derived entry."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from radar.discovery.trending_entities import Lane, TrendingEntry, TrendingObservation


def test_observation_round_trips_and_is_frozen():
    obs = TrendingObservation(
        repo="acme/rocket", lane=Lane.ONPREM, stars=1200,
        observed_at=datetime(2026, 7, 5, 7, 0, tzinfo=UTC),
        repo_created_at=datetime(2026, 6, 20, tzinfo=UTC),
        description="fast serving", topics=["llm", "inference"], license="Apache-2.0",
    )

    dumped = obs.model_dump_json()
    assert TrendingObservation.model_validate_json(dumped) == obs
    with pytest.raises(Exception):
        obs.stars = 5  # type: ignore[misc]


def test_observation_rejects_unknown_fields_and_defaults():
    obs = TrendingObservation(
        repo="a/b", lane=Lane.BROADER, stars=50,
        observed_at=datetime(2026, 7, 5, tzinfo=UTC),
        repo_created_at=datetime(2026, 7, 1, tzinfo=UTC),
    )
    assert obs.description == "" and obs.topics == [] and obs.license is None
    with pytest.raises(Exception):
        TrendingObservation(
            repo="a/b", lane=Lane.ONPREM, stars=1,
            observed_at=datetime(2026, 7, 5, tzinfo=UTC),
            repo_created_at=datetime(2026, 7, 1, tzinfo=UTC),
            bogus=True,  # type: ignore[call-arg]
        )


def test_entry_carries_derived_fields():
    entry = TrendingEntry(
        repo="acme/rocket", lane=Lane.ONPREM, stars=1200, velocity_per_day=40.0,
        is_new=True, first_seen="2026-07-01", description="d", topics=["llm"],
    )
    assert entry.velocity_per_day == 40.0 and entry.is_new is True
    assert entry.license is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_trending_entities.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'radar.discovery.trending_entities'`

- [ ] **Step 3: Write the implementation**

Create `src/radar/discovery/trending_entities.py`:

```python
"""Entities for the trending radar: lane, observation rows, derived entries."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class Lane(str, Enum):
    """Which net caught a repo. onprem = strict radar identity (can promote);
    broader = general AI heat (content only, never promotes)."""

    ONPREM = "onprem"
    BROADER = "broader"


class TrendingObservation(BaseModel):
    """One repo's state on one sweep day. Velocity is derived from many of these."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    repo: str  # "owner/name"
    lane: Lane
    stars: int
    observed_at: datetime
    repo_created_at: datetime
    description: str = ""
    topics: list[str] = Field(default_factory=list)
    license: str | None = None  # spdx_id from the search payload; None/"NOASSERTION" = unknown


class TrendingEntry(BaseModel):
    """A repo as seen across its observations (current state + derived growth)."""

    model_config = ConfigDict(frozen=True)

    repo: str
    lane: Lane
    stars: int
    velocity_per_day: float | None
    is_new: bool
    first_seen: str  # ISO date
    description: str = ""
    topics: list[str] = Field(default_factory=list)
    license: str | None = None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_trending_entities.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Lint + typecheck + commit**

```bash
uv run ruff check src/radar/discovery tests/test_trending_entities.py && uv run mypy src/radar
git add src/radar/discovery/trending_entities.py tests/test_trending_entities.py
git commit -m "feat: trending radar entities (lane, observation, entry)"
```

---

### Task 2: Observation log (append-only JSONL)

**Files:**
- Create: `src/radar/storage/trending_observations_log.py`
- Test: `tests/test_trending_observations_log.py`

**Interfaces:**
- Consumes: `TrendingObservation` (Task 1).
- Produces: `append_observations(path: Path, rows: list[TrendingObservation]) -> None` (append-only JSONL, mkdir parents, no-op on empty) and `load_observations(path: Path) -> list[TrendingObservation]` (missing file → `[]`; corrupt lines skipped with `logger.warning`). Direct mirror of `src/radar/storage/technique_metrics_log.py`.

- [ ] **Step 1: Write the failing tests**

```python
"""Append-only JSONL log of trending observations (mirror of technique_metrics_log)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from radar.discovery.trending_entities import Lane, TrendingObservation
from radar.storage.trending_observations_log import append_observations, load_observations


def _obs(repo: str, stars: int, at: str) -> TrendingObservation:
    return TrendingObservation(
        repo=repo, lane=Lane.ONPREM, stars=stars,
        observed_at=datetime.fromisoformat(at),
        repo_created_at=datetime(2026, 6, 20, tzinfo=UTC),
        topics=["llm"], license="MIT",
    )


def test_append_and_load_round_trip(tmp_path: Path):
    path = tmp_path / "trending-observations.jsonl"

    append_observations(path, [_obs("a/b", 100, "2026-07-01T07:00:00+00:00")])
    append_observations(path, [_obs("a/b", 130, "2026-07-02T07:00:00+00:00")])
    append_observations(path, [])  # no-op

    rows = load_observations(path)
    assert [r.stars for r in rows] == [100, 130]
    assert rows[1].license == "MIT"


def test_load_missing_file_returns_empty(tmp_path: Path):
    assert load_observations(tmp_path / "nope.jsonl") == []


def test_load_skips_corrupt_lines(tmp_path: Path):
    path = tmp_path / "trending-observations.jsonl"
    append_observations(path, [_obs("a/b", 100, "2026-07-01T07:00:00+00:00")])
    with path.open("a", encoding="utf-8") as handle:
        handle.write("{broken\n")

    assert len(load_observations(path)) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_trending_observations_log.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

Create `src/radar/storage/trending_observations_log.py`:

```python
"""Append-only JSONL log of trending observations (mirror of the history logs).

GitHub search reports stars-now, not growth. The daily sweep appends each
repo's current stars here; detection derives velocity by comparing rows across
days. The publish workflow commits this file back like the history logs, which
makes trend detection durable across CI runs.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from radar.discovery.trending_entities import TrendingObservation


logger = logging.getLogger(__name__)


def append_observations(path: Path, rows: list[TrendingObservation]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(r.model_dump(mode="json"), ensure_ascii=False) for r in rows]
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def load_observations(path: Path) -> list[TrendingObservation]:
    if not path.exists():
        return []
    rows: list[TrendingObservation] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, raw in enumerate(handle, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                rows.append(TrendingObservation.model_validate_json(line))
            except ValueError as exc:
                logger.warning("Skipping corrupt trending-observations line %d in %s: %s",
                               line_no, path, exc)
    return rows
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_trending_observations_log.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Lint + typecheck + commit**

```bash
uv run ruff check src/radar/storage tests/test_trending_observations_log.py && uv run mypy src/radar
git add src/radar/storage/trending_observations_log.py tests/test_trending_observations_log.py
git commit -m "feat: trending observations log (append-only JSONL)"
```

---

### Task 3: Detection (velocity, new, build_trending)

**Files:**
- Create: `src/radar/discovery/trending_detect.py`
- Test: `tests/test_trending_detect.py`

**Interfaces:**
- Consumes: `TrendingObservation`, `TrendingEntry`, `Lane` (Task 1).
- Produces (pure, no I/O, `now` always a parameter):
  - `VELOCITY_WINDOW_DAYS = 7`, `NEW_WINDOW_DAYS = 14` (module constants, tunable).
  - `star_velocity(rows: list[TrendingObservation], now: datetime) -> float | None` — over rows within `VELOCITY_WINDOW_DAYS` of `now`: `(latest.stars - earliest.stars) / days_between`, rounded to 1 decimal; `None` with fewer than 2 in-window rows or zero day-span.
  - `is_new(repo_created_at: datetime, now: datetime) -> bool` — created within `NEW_WINDOW_DAYS`.
  - `build_trending(observations: list[TrendingObservation], now: datetime) -> list[TrendingEntry]` — one entry per repo (from its rows: latest row supplies current stars/description/topics/lane/license; `first_seen` = earliest `observed_at` date; velocity + is_new derived). Sorted velocity-desc (None last), then stars-desc, then repo.

- [ ] **Step 1: Write the failing tests**

```python
"""Trending detection: velocity + new + assembly (pure, deterministic)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from radar.discovery.trending_entities import Lane, TrendingObservation
from radar.discovery.trending_detect import (
    NEW_WINDOW_DAYS,
    build_trending,
    is_new,
    star_velocity,
)


NOW = datetime(2026, 7, 8, 7, 0, tzinfo=UTC)


def _obs(repo: str, stars: int, day: int, lane: Lane = Lane.ONPREM,
         created: str = "2026-06-01") -> TrendingObservation:
    return TrendingObservation(
        repo=repo, lane=lane, stars=stars,
        observed_at=datetime(2026, 7, day, 7, 0, tzinfo=UTC),
        repo_created_at=datetime.fromisoformat(created).replace(tzinfo=UTC),
        topics=["llm"], license="Apache-2.0",
    )


def test_velocity_over_window():
    rows = [_obs("a/b", 100, 1), _obs("a/b", 250, 4)]  # +150 over 3 days
    assert star_velocity(rows, NOW) == 50.0


def test_velocity_none_with_single_observation():
    assert star_velocity([_obs("a/b", 100, 1)], NOW) is None


def test_velocity_ignores_rows_outside_window():
    rows = [_obs("a/b", 10, 1), _obs("a/b", 400, 5), _obs("a/b", 460, 8)]
    # window = 7 days back from 2026-07-08 → 07-01 inclusive; all three qualify.
    # earliest in-window is day 1 (10), latest day 8 (460): +450 over 7 days
    assert star_velocity(rows, NOW) == round(450 / 7, 1)


def test_velocity_none_on_zero_span():
    rows = [_obs("a/b", 100, 4), _obs("a/b", 120, 4)]  # same day
    assert star_velocity(rows, NOW) is None


def test_is_new_boundary():
    assert is_new(NOW - timedelta(days=NEW_WINDOW_DAYS - 1), NOW) is True
    assert is_new(NOW - timedelta(days=NEW_WINDOW_DAYS + 1), NOW) is False


def test_build_trending_groups_and_sorts():
    observations = [
        _obs("slow/repo", 500, 1), _obs("slow/repo", 520, 4),         # vel low
        _obs("fast/repo", 100, 1), _obs("fast/repo", 400, 4),         # vel high
        _obs("solo/repo", 900, 4),                                     # vel None
    ]
    entries = build_trending(observations, NOW)

    assert [e.repo for e in entries] == ["fast/repo", "slow/repo", "solo/repo"]
    fast = entries[0]
    assert fast.velocity_per_day == 100.0
    assert fast.stars == 400  # latest row wins for current state
    assert fast.first_seen == "2026-07-01"
    assert entries[2].velocity_per_day is None  # solo → sorts last


def test_build_trending_latest_row_supplies_lane_and_license():
    observations = [
        _obs("x/y", 100, 1, lane=Lane.BROADER),
        _obs("x/y", 200, 4, lane=Lane.ONPREM),  # lane can change; latest wins
    ]
    entry = build_trending(observations, NOW)[0]
    assert entry.lane == Lane.ONPREM and entry.license == "Apache-2.0"


def test_build_trending_marks_new_repo():
    entry = build_trending([
        _obs("new/repo", 60, 6, created="2026-07-01"),
        _obs("new/repo", 90, 7, created="2026-07-01"),
    ], NOW)[0]
    assert entry.is_new is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_trending_detect.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

Create `src/radar/discovery/trending_detect.py`:

```python
"""Derive trending signals from repeated observations (pure, no I/O).

GitHub cannot tell us growth, so velocity is the star delta across the
observation window. Day one of the system yields no velocity (one row per
repo); it fills in from day two.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from radar.discovery.trending_entities import TrendingEntry, TrendingObservation


VELOCITY_WINDOW_DAYS = 7
NEW_WINDOW_DAYS = 14

# Sort velocity high→low with None (unknown) last, then stars high→low, then repo.
_NO_VELOCITY = -1.0


def star_velocity(rows: list[TrendingObservation], now: datetime) -> float | None:
    """Stars/day across in-window rows; None with <2 rows or a zero day-span."""
    cutoff = now - timedelta(days=VELOCITY_WINDOW_DAYS)
    in_window = sorted(
        (r for r in rows if r.observed_at >= cutoff), key=lambda r: r.observed_at
    )
    if len(in_window) < 2:
        return None
    span_days = (in_window[-1].observed_at - in_window[0].observed_at).days
    if span_days <= 0:
        return None
    return round((in_window[-1].stars - in_window[0].stars) / span_days, 1)


def is_new(repo_created_at: datetime, now: datetime) -> bool:
    return repo_created_at >= now - timedelta(days=NEW_WINDOW_DAYS)


def build_trending(
    observations: list[TrendingObservation], now: datetime
) -> list[TrendingEntry]:
    by_repo: dict[str, list[TrendingObservation]] = {}
    for obs in observations:
        by_repo.setdefault(obs.repo, []).append(obs)
    entries: list[TrendingEntry] = []
    for repo, rows in by_repo.items():
        ordered = sorted(rows, key=lambda r: r.observed_at)
        latest = ordered[-1]
        entries.append(TrendingEntry(
            repo=repo, lane=latest.lane, stars=latest.stars,
            velocity_per_day=star_velocity(ordered, now),
            is_new=is_new(latest.repo_created_at, now),
            first_seen=ordered[0].observed_at.date().isoformat(),
            description=latest.description, topics=latest.topics, license=latest.license,
        ))
    return sorted(entries, key=lambda e: (
        -(e.velocity_per_day if e.velocity_per_day is not None else _NO_VELOCITY),
        -e.stars, e.repo,
    ))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_trending_detect.py -v`
Expected: PASS (8 tests). Note the `test_velocity_ignores_rows_outside_window` name is a slight misnomer (all three rows fall in the 7-day window from 2026-07-08); it verifies earliest-to-latest spanning — keep the assertion, it is correct.

- [ ] **Step 5: Lint + typecheck + commit**

```bash
uv run ruff check src/radar/discovery tests/test_trending_detect.py && uv run mypy src/radar
git add src/radar/discovery/trending_detect.py tests/test_trending_detect.py
git commit -m "feat: trending detection (star velocity + new-repo + assembly)"
```

---

### Task 4: Two-lane GitHub sweep

**Files:**
- Create: `src/radar/discovery/trending_sweep.py`
- Test: `tests/test_trending_sweep.py`

**Interfaces:**
- Consumes: `Lane`, `TrendingObservation` (Task 1); existing `SourceConfig` (`radar.models`); the `_tracked_repos` pattern from `discovery/github_trending.py` (owner/name set from github.com source URLs).
- Produces:
  - `ONPREM_TOPICS`, `BROADER_TOPICS` (module constants — lists of GitHub topic strings), `RISING_MIN_STARS = 800`, `BORN_MIN_STARS = 50`, `BORN_WINDOW_DAYS = 14`, `PUSHED_WINDOW_DAYS = 30`, `PER_LANE_CAP = 20`.
  - `async sweep_trending(tracked_sources: list[SourceConfig], client: Any, now: datetime, headers: dict[str, str] | None = None) -> list[TrendingObservation]` — for each lane, run TWO query shapes (rising: `topic:X stars:>=RISING_MIN_STARS pushed:>=<now-30d>`; born: `topic:X created:>=<now-14d> stars:>=BORN_MIN_STARS`), map items → observations stamped `observed_at=now` and `lane`, drop tracked repos, dedup by repo across the whole sweep with **onprem winning** (process the onprem lane first and skip repos already seen). Any single query failing degrades to skipping it (warning), never raises. Cap each lane at `PER_LANE_CAP` distinct repos.
  - `_search(client, query, headers)` and `_to_observation(item, lane, now)` helpers mirroring `github_trending.py`.

- [ ] **Step 1: Write the failing tests**

```python
"""Two-lane GitHub sweep → trending observations (canned search fixtures)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from radar.discovery.trending_entities import Lane
from radar.discovery.trending_sweep import sweep_trending
from radar.models import Category, SourceConfig, SourceType


NOW = datetime(2026, 7, 5, 7, 0, tzinfo=UTC)


def _item(full_name: str, stars: int, created: str = "2026-06-01T00:00:00Z",
          spdx: str | None = "Apache-2.0") -> dict[str, Any]:
    return {
        "full_name": full_name, "stargazers_count": stars,
        "created_at": created, "pushed_at": "2026-07-04T00:00:00Z",
        "html_url": f"https://github.com/{full_name}",
        "description": "d", "topics": ["llm", "inference"],
        "license": {"spdx_id": spdx} if spdx is not None else None,
    }


class _Client:
    """Returns items per query substring; records queries; can fail one query."""

    def __init__(self, by_topic: dict[str, list[dict]], fail_substr: str | None = None):
        self._by_topic = by_topic
        self._fail = fail_substr
        self.queries: list[str] = []

    async def get(self, url, **kwargs):
        query = kwargs.get("params", {}).get("q", "")
        self.queries.append(query)
        if self._fail and self._fail in query:
            raise RuntimeError("boom")
        items: list[dict] = []
        for topic, rows in self._by_topic.items():
            if f"topic:{topic}" in query:
                items = rows
                break
        return _Resp(items)


class _Resp:
    def __init__(self, items):
        self._items = items
        self.status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return {"items": self._items}


def _tracked(full_name: str) -> SourceConfig:
    return SourceConfig(
        id=f"github-{full_name.split('/')[-1]}", type=SourceType.GITHUB_REPO,
        project=full_name.split("/")[-1], category=Category.MODEL_SERVING,
        url=f"https://github.com/{full_name}",
    )


@pytest.mark.asyncio
async def test_sweep_maps_items_to_observations():
    client = _Client({"llm-inference": [_item("acme/rocket", 1500)]})

    observations = await sweep_trending([], client, NOW)

    rocket = next(o for o in observations if o.repo == "acme/rocket")
    assert rocket.lane == Lane.ONPREM
    assert rocket.stars == 1500
    assert rocket.observed_at == NOW
    assert rocket.license == "Apache-2.0"
    assert rocket.repo_created_at.year == 2026


@pytest.mark.asyncio
async def test_sweep_excludes_tracked_repos():
    client = _Client({"llm-inference": [_item("acme/rocket", 1500),
                                         _item("tracked/tool", 2000)]})

    observations = await sweep_trending([_tracked("tracked/tool")], client, NOW)

    assert {o.repo for o in observations} == {"acme/rocket"}


@pytest.mark.asyncio
async def test_sweep_onprem_wins_lane_dupes():
    # same repo returned under an onprem topic AND a broader topic
    client = _Client({
        "llm-inference": [_item("dual/repo", 1200)],  # onprem lane
        "generative-ai": [_item("dual/repo", 1200)],  # broader lane
    })

    observations = await sweep_trending([], client, NOW)

    dual = [o for o in observations if o.repo == "dual/repo"]
    assert len(dual) == 1 and dual[0].lane == Lane.ONPREM


@pytest.mark.asyncio
async def test_sweep_missing_license_is_none():
    client = _Client({"llm-inference": [_item("no/license", 900, spdx=None)]})

    observations = await sweep_trending([], client, NOW)

    assert observations[0].license is None


@pytest.mark.asyncio
async def test_sweep_one_failing_query_does_not_crash():
    client = _Client({"llm-inference": [_item("acme/rocket", 1500)]},
                     fail_substr="generative-ai")

    observations = await sweep_trending([], client, NOW)  # broader query raises

    assert any(o.repo == "acme/rocket" for o in observations)  # onprem still returned
```

NOTE for the implementer: check the real `SourceType` member name for a GitHub repo source in `src/radar/models.py` (the test uses `SourceType.GITHUB_REPO`); if the enum differs, fix the test's import to the real name — the assertions are the contract. Same for whether `SourceConfig` needs more required fields.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_trending_sweep.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

Create `src/radar/discovery/trending_sweep.py`:

```python
"""Two-lane GitHub sweep for trending repos → observations.

The strict `onprem` lane matches the radar's identity (drives the autopilot);
the `broader` lane catches general AI heat (content only). Each lane runs two
query shapes: rising (established + still-pushed) and born-recently (young).
Every query is best-effort — a failure skips that query with a warning, never
raising. Tracked sources are excluded; onprem wins repos seen in both lanes.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlparse

from dateutil import parser as date_parser

from radar.discovery.trending_entities import Lane, TrendingObservation
from radar.models import SourceConfig


logger = logging.getLogger(__name__)

GITHUB_SEARCH_URL = "https://api.github.com/search/repositories"
PER_PAGE = 30
PER_LANE_CAP = 20
RISING_MIN_STARS = 800
BORN_MIN_STARS = 50
BORN_WINDOW_DAYS = 14
PUSHED_WINDOW_DAYS = 30

ONPREM_TOPICS = [
    "llm-inference", "model-serving", "ai-agents", "agent-framework",
    "mcp-server", "model-context-protocol", "local-llm", "self-hosted-ai",
    "llmops", "ai-sandbox",
]
BROADER_TOPICS = [
    "llm", "generative-ai", "large-language-models", "ai",
]


async def sweep_trending(
    tracked_sources: list[SourceConfig],
    client: Any,
    now: datetime,
    headers: dict[str, str] | None = None,
) -> list[TrendingObservation]:
    tracked = _tracked_repos(tracked_sources)
    pushed_since = (now - timedelta(days=PUSHED_WINDOW_DAYS)).date().isoformat()
    born_since = (now - timedelta(days=BORN_WINDOW_DAYS)).date().isoformat()

    seen: set[str] = set()
    observations: list[TrendingObservation] = []
    # onprem first so it wins repos that also match a broader topic.
    for lane, topics in ((Lane.ONPREM, ONPREM_TOPICS), (Lane.BROADER, BROADER_TOPICS)):
        lane_repos: set[str] = set()
        for topic in topics:
            if len(lane_repos) >= PER_LANE_CAP:
                break
            queries = [
                f"topic:{topic} stars:>={RISING_MIN_STARS} pushed:>={pushed_since}",
                f"topic:{topic} created:>={born_since} stars:>={BORN_MIN_STARS}",
            ]
            for query in queries:
                for item in await _search(client, query, headers):
                    repo = (item.get("full_name") or "").strip()
                    if not repo or repo.lower() in tracked or repo in seen:
                        continue
                    observation = _to_observation(item, lane, now)
                    if observation is None:
                        continue
                    seen.add(repo)
                    lane_repos.add(repo)
                    observations.append(observation)
                    if len(lane_repos) >= PER_LANE_CAP:
                        break
    return observations


async def _search(
    client: Any, query: str, headers: dict[str, str] | None
) -> list[dict[str, Any]]:
    try:
        response = await client.get(
            GITHUB_SEARCH_URL,
            params={"q": query, "sort": "stars", "order": "desc", "per_page": PER_PAGE},
            headers=headers or {},
        )
        response.raise_for_status()
        return response.json().get("items") or []
    except Exception as exc:
        logger.warning("Trending sweep query failed (%s): %s", query, exc)
        return []


def _to_observation(
    item: dict[str, Any], lane: Lane, now: datetime
) -> TrendingObservation | None:
    repo = (item.get("full_name") or "").strip()
    created_raw = item.get("created_at")
    if not repo or not created_raw:
        return None
    try:
        created = date_parser.parse(created_raw)
    except (ValueError, OverflowError):
        return None
    spdx = (item.get("license") or {}).get("spdx_id")
    return TrendingObservation(
        repo=repo, lane=lane, stars=int(item.get("stargazers_count") or 0),
        observed_at=now, repo_created_at=created,
        description=(item.get("description") or "")[:200],
        topics=list(item.get("topics") or [])[:8],
        license=None if spdx in (None, "NOASSERTION") else spdx,
    )


def _tracked_repos(sources: list[SourceConfig]) -> set[str]:
    """owner/name (lowercased) for every github.com source — mirror of github_trending."""
    tracked: set[str] = set()
    for source in sources:
        parsed = urlparse(str(source.url))
        if parsed.netloc != "github.com":
            continue
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) >= 2:
            tracked.add(f"{parts[0]}/{parts[1]}".lower())
    return tracked
```

Add `from dateutil import parser as date_parser` to the module-top imports (dateutil is already a dependency — `enrichment/arxiv.py` uses it). `NOASSERTION` (GitHub's marker for an unrecognized license) normalizes to `None` so sub-project 2's allowlist gate treats it as unknown.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_trending_sweep.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Lint + typecheck + commit**

```bash
uv run ruff check src/radar/discovery tests/test_trending_sweep.py && uv run mypy src/radar
git add src/radar/discovery/trending_sweep.py tests/test_trending_sweep.py
git commit -m "feat: two-lane GitHub trending sweep"
```

---

### Task 5: CLI `radar trending scan | list` + CI wiring

**Files:**
- Modify: `src/radar/cli.py` (register `trending_app`; two commands), `.github/workflows/publish.yml`
- Test: `tests/test_trending_cli.py`, `tests/test_publish_workflow.py` (append)

**Interfaces:**
- Consumes: `sweep_trending` (Task 4), `append_observations`/`load_observations` (Task 2), `build_trending` (Task 3); existing `load_config` (`radar.storage.config`), the `GITHUB_TOKEN` header pattern from the existing `discover` command (read `src/radar/cli.py`'s `discover` for `_headers()`).
- Produces:
  - `radar trending scan [--root .]` — load config (best-effort: missing config → empty tracked list + warning, still sweeps), build a GitHub `httpx.AsyncClient`, `sweep_trending(sources, client, now=datetime.now(UTC), headers=_headers())`, `append_observations(root/"data"/"trending-observations.jsonl", rows)`, print `"Observed N trending repo(s) (X on-prem / Y broader) → data/trending-observations.jsonl"`.
  - `radar trending list [--lane onprem|broader] [--new] [--root .]` — `build_trending(load_observations(path), now)`, filter by lane / `is_new` if flagged, print a table (repo, stars, velocity/day, NEW badge, first-seen); "No trending observations yet" when the store is empty.
  - publish.yml: `uv run radar trending scan --root .` runs daily after `radar research scan`; `git add -f data/trending-observations.jsonl || true` joins the history-commit block after the technique-metrics line.

- [ ] **Step 1: Write the failing tests (tests/test_trending_cli.py)**

```python
"""CLI: radar trending scan / list."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from radar.cli import app
from radar.discovery.trending_entities import Lane, TrendingObservation
from radar.storage.trending_observations_log import append_observations, load_observations


def _obs(repo: str, stars: int, day: int, lane: Lane = Lane.ONPREM,
         created: str = "2026-06-01") -> TrendingObservation:
    return TrendingObservation(
        repo=repo, lane=lane, stars=stars,
        observed_at=datetime(2026, 7, day, 7, 0, tzinfo=UTC),
        repo_created_at=datetime.fromisoformat(created).replace(tzinfo=UTC),
        topics=["llm"], license="MIT",
    )


def _seed(root: Path, rows: list[TrendingObservation]) -> None:
    (root / "data").mkdir(parents=True, exist_ok=True)
    append_observations(root / "data" / "trending-observations.jsonl", rows)


def test_trending_scan_appends_observations(tmp_path, monkeypatch):
    async def _fake_sweep(tracked_sources, client, now, headers=None):
        return [_obs("acme/rocket", 1500, 5)]

    monkeypatch.setattr("radar.discovery.trending_sweep.sweep_trending", _fake_sweep)
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    runner = CliRunner()

    result = runner.invoke(app, ["trending", "scan", "--root", str(tmp_path)])

    assert result.exit_code == 0
    assert "1 trending repo" in result.stdout
    rows = load_observations(tmp_path / "data" / "trending-observations.jsonl")
    assert rows[0].repo == "acme/rocket"


def test_trending_scan_survives_missing_config(tmp_path, monkeypatch):
    async def _fake_sweep(tracked_sources, client, now, headers=None):
        assert tracked_sources == []  # missing config → empty tracked list
        return []

    monkeypatch.setattr("radar.discovery.trending_sweep.sweep_trending", _fake_sweep)
    runner = CliRunner()

    result = runner.invoke(app, ["trending", "scan", "--root", str(tmp_path)])

    assert result.exit_code == 0


def test_trending_list_shows_velocity_and_new(tmp_path):
    _seed(tmp_path, [
        _obs("fast/repo", 100, 1), _obs("fast/repo", 400, 4),
        _obs("new/repo", 60, 4, created="2026-07-01"),
    ])
    runner = CliRunner()

    result = runner.invoke(app, ["trending", "list", "--root", str(tmp_path)])

    assert result.exit_code == 0
    assert "fast/repo" in result.stdout
    assert "NEW" in result.stdout  # new/repo flagged


def test_trending_list_filters_by_lane(tmp_path):
    _seed(tmp_path, [
        _obs("on/repo", 100, 4, lane=Lane.ONPREM),
        _obs("broad/repo", 200, 4, lane=Lane.BROADER),
    ])
    runner = CliRunner()

    result = runner.invoke(app, ["trending", "list", "--root", str(tmp_path),
                                 "--lane", "broader"])

    assert result.exit_code == 0
    assert "broad/repo" in result.stdout and "on/repo" not in result.stdout


def test_trending_list_empty_store(tmp_path):
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    runner = CliRunner()

    result = runner.invoke(app, ["trending", "list", "--root", str(tmp_path)])

    assert result.exit_code == 0
    assert "No trending observations yet" in result.stdout
```

NOTE for the implementer: the scan tests monkeypatch `radar.discovery.trending_sweep.sweep_trending`, so the CLI command MUST call it as a module attribute (`from radar.discovery import trending_sweep` then `trending_sweep.sweep_trending(...)`) — the exact monkeypatch-friendly pattern used by `research discover`.

- [ ] **Step 2: Append the workflow test (tests/test_publish_workflow.py)**

```python
def test_publish_runs_trending_scan_and_commits_observations():
    text = Path(".github/workflows/publish.yml").read_text(encoding="utf-8")

    research_idx = text.index("radar research scan")
    trending_idx = text.index("radar trending scan")
    export_idx = text.index("radar export")

    assert research_idx < trending_idx < export_idx
    assert "data/trending-observations.jsonl" in text
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_trending_cli.py tests/test_publish_workflow.py -v -k "trending or observations"`
Expected: FAIL — `No such command 'trending'` / `ValueError: substring not found`

- [ ] **Step 4: Register the sub-app + commands**

In `src/radar/cli.py`, after the `research_app` registration, add:

```python
trending_app = typer.Typer(help="Trending & newly-created repos radar.", no_args_is_help=True)
app.add_typer(trending_app, name="trending")
```

Add the two commands near the other discovery commands (local imports, `console.print`, mirroring `research_scan`/`research_list` style; read the existing `discover` command's `_headers()` for the GITHUB_TOKEN pattern):

```python
@trending_app.command("scan")
def trending_scan(root: Path = typer.Option(Path("."), help="Project root.")) -> None:
    """Sweep GitHub for trending/new repos and append to the observation log."""
    import asyncio
    import os
    from datetime import UTC, datetime

    import httpx

    from radar.discovery import trending_sweep
    from radar.discovery.trending_entities import Lane
    from radar.storage.config import load_config
    from radar.storage.trending_observations_log import append_observations

    config_path = root / "data" / "config.yaml"
    try:
        sources = load_config(config_path).sources
    except Exception as exc:
        console.print(f"[yellow]No config ({exc}); sweeping without exclusions.[/yellow]")
        sources = []

    def _headers() -> dict[str, str]:
        token = os.environ.get("GITHUB_TOKEN")
        return {"Authorization": f"Bearer {token}"} if token else {}

    now = datetime.now(UTC)

    async def _run():
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            return await trending_sweep.sweep_trending(
                sources, client, now=now, headers=_headers(),
            )

    observations = asyncio.run(_run())
    out_path = root / "data" / "trending-observations.jsonl"
    append_observations(out_path, observations)
    onprem = sum(1 for o in observations if o.lane == Lane.ONPREM)
    broader = len(observations) - onprem
    console.print(
        f"Observed {len(observations)} trending repo(s) "
        f"({onprem} on-prem / {broader} broader) → {out_path.relative_to(root)}"
    )


@trending_app.command("list")
def trending_list(
    root: Path = typer.Option(Path("."), help="Project root."),
    lane: str = typer.Option("", help="Filter by lane: onprem | broader."),
    new: bool = typer.Option(False, "--new", help="Only newly-created repos."),
) -> None:
    """List trending repos derived from the observation log."""
    from datetime import UTC, datetime

    from radar.discovery.trending_detect import build_trending
    from radar.storage.trending_observations_log import load_observations

    path = root / "data" / "trending-observations.jsonl"
    entries = build_trending(load_observations(path), datetime.now(UTC))
    if not entries:
        console.print("No trending observations yet. Run [bold]radar trending scan[/bold] first.")
        return
    if lane:
        entries = [e for e in entries if e.lane.value == lane.lower()]
    if new:
        entries = [e for e in entries if e.is_new]
    console.print(f"{len(entries)} trending repo(s):")
    for e in entries:
        vel = f"{e.velocity_per_day:+.1f}/d" if e.velocity_per_day is not None else "   ?  "
        badge = "NEW" if e.is_new else "   "
        console.print(
            f"  {e.repo:<40} {e.stars:>7}★ {vel:<9} {badge} {e.lane.value:<8} "
            f"since {e.first_seen}",
            highlight=False, soft_wrap=True,
        )
```

- [ ] **Step 5: Wire publish.yml**

In `.github/workflows/publish.yml`, add after the `uv run radar research scan --root .` line:

```yaml
          uv run radar trending scan --root .
```

and in the history-commit block, after `git add -f data/technique-metrics.jsonl || true`:

```yaml
          git add -f data/trending-observations.jsonl || true
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_trending_cli.py tests/test_publish_workflow.py -v`
Expected: PASS

- [ ] **Step 7: Lint + typecheck + commit**

```bash
uv run ruff check src/radar/cli.py tests/test_trending_cli.py tests/test_publish_workflow.py && uv run mypy src/radar
git add src/radar/cli.py .github/workflows/publish.yml tests/test_trending_cli.py tests/test_publish_workflow.py
git commit -m "feat: radar trending scan/list CLI + daily CI observation commit"
```

---

### Task 6: README + CHANGELOG + full gates

**Files:**
- Modify: `README.md`, `CHANGELOG.md`
- Test: the full suite

- [ ] **Step 1: README**

Add to the CLI table, after the `radar research track-record` row:

```markdown
| `radar trending scan` | Sweep GitHub for trending/new repos (two lanes) and append to the observation log. |
| `radar trending list [--lane L] [--new]` | List trending repos with star velocity + NEW badges from the observation log. |
```

Add to Highlights, after the 🎓 research bullet:

```markdown
- 📈 **Trending radar** — a daily two-lane GitHub sweep (strict on-prem identity + broader AI heat) appends to a committed observation log, so the radar computes real star *velocity* and flags newly-created repos — the foundation for self-growing catalogs and a githubsignals-style trending feed.
```

- [ ] **Step 2: CHANGELOG**

Under `## [Unreleased]` → `### Added`, at the top:

```markdown
- **Trending radar engine** — a daily two-lane GitHub sweep (`radar trending
  scan`) appends repo observations to an append-only
  `data/trending-observations.jsonl` committed by CI; `radar trending list`
  derives star velocity and newly-created-repo flags from it. The strict
  `onprem` lane matches the radar's identity; the `broader` lane catches
  general AI heat. This is the engine the source autopilot and the trending
  surfaces (both coming next) build on.
```

- [ ] **Step 3: Full gates**

Run: `uv run pytest && uv run ruff check . && uv run mypy src/radar`
Expected: all pass, coverage ≥ 80%, ruff + mypy clean. Fix anything failing (implementation, not tests, unless a test is genuinely wrong).

- [ ] **Step 4: Commit**

```bash
git add README.md CHANGELOG.md
git commit -m "docs: trending radar engine in README + CHANGELOG"
```

---

## Self-Review Notes (already applied)

- Spec §1 coverage: observation store (T2), two-lane sweep with two query shapes (T4), velocity + new detection (T3), CLI scan/list (T5), daily CI wiring + commit (T5). Sub-projects 2–4 explicitly out of scope.
- Forward-looking, cost-free addition recorded: `license` is stored on the observation (it comes free in the search payload, verified live) so sub-project 2's autopilot license gate needs no extra API call — a targeted improvement, not scope creep.
- Type consistency: `TrendingObservation`/`TrendingEntry`/`Lane` (T1) flow through T2/T3/T4/T5; `sweep_trending(tracked_sources, client, now, headers)`, `build_trending(observations, now)`, `star_velocity(rows, now)`, `append_observations`/`load_observations` names identical across producer and consumer tasks.
- Determinism: the only nondeterministic input (the network sweep) is best-effort and stamped with a caller-provided `now`; detection is pure; the CLI passes `datetime.now(UTC)` at the boundary only.
- Monkeypatch-friendliness called out explicitly for T5 (module-attribute `sweep_trending` call), matching the `research discover` precedent the CLI tests rely on.
