# Untracked Model Candidate Discovery (Phase 2a) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Observe untracked HF-trending models over time in a committed store, surface them as an "Emerging — not yet tracked" sub-section on `/trending`, and gate the catalog autopilot's model promotion on sustained download momentum (not just a high absolute count).

**Architecture:** A daily `radar models candidates scan` reuses the existing `discover_trending_models` (which already returns untracked HF-trending models) and appends observations to a committed `data/model-candidate-observations.jsonl`. A pure detection module derives download velocity + a sustained-momentum gate. The `/trending` Models area gains an "Emerging" sub-section; `models promote` requires sustained momentum. All guarded so a corrupt/absent store never breaks `/trending` or the daily export.

**Tech Stack:** Python 3.12, pydantic v2, FastAPI + Jinja2, typer, httpx (all in-tree; **no new dependencies**), pytest + ruff + mypy.

**Spec:** `docs/superpowers/specs/2026-07-06-model-candidate-discovery-design.md` (Phase 2a). Phase 2b (untracked papers) is a separate future spec.

## Global Constraints

- Deterministic + offline except the daily sweep: detection + the momentum gate are pure (`now` a parameter); only the sweep hits HF (best-effort → no observations + warning).
- **Guarded reads (daily-publish invariant):** a corrupt/absent store → empty Emerging sub-section and nothing promoted (fail-closed) — never a 500 on `/trending`, never a crash in `radar export`. New JSONL loaders use `errors="replace"` + `except OSError` + per-line `except ValueError` (the hardened pattern from `model_metrics_log.py`).
- No new HF-fetching code — the sweep reuses `discover_trending_models`. No new Python dependencies. No LLM.
- Emerging rows link to `https://huggingface.co/{repo}` (absolute — the live and static templates use the SAME snippet, no slug divergence).
- No change to `models promote`'s validate-or-abort write mechanism; the momentum check is an additional AND filter over the existing `is_promotable`.
- ruff line-length = 100; `python_version = 3.12`; every file starts with `from __future__ import annotations`.
- Coverage ≥ 80%; gates `uv run pytest`, `uv run ruff check .`, `uv run mypy src/radar`.
- Commit format `<type>: <description>`; `git add` specific paths only (unrelated modified `data/history.jsonl` never committed).
- Existing symbols consumed (all on main): `discover_trending_models(seeds, client, min_downloads=10000, limit=50, headers=None) -> list[ModelProposal]` (`radar.discovery.hf_trending_models`); `ModelProposal` (`model_id, name, family, hf_repo, downloads, likes, modality, reason, suggested_id`); `is_promotable(proposal, *, min_downloads, seeded_repos)` (`radar.discovery.model_promotion`); `load_model_seed` (`radar.models_radar.seed`); `iso_week_bounds` (`radar.reports.digest`); the `/trending` route + `trending.html`/`static_trending.html` from the trending sub-projects.

## File Structure

```
src/radar/storage/model_candidate_log.py     # NEW: ModelCandidateObservation + append/load (committed JSONL)
src/radar/discovery/model_candidate_detect.py # NEW: ModelCandidateEntry + build_model_candidates + has_sustained_download_momentum (pure)
src/radar/discovery/model_candidate_sweep.py  # NEW: sweep_model_candidates (reuse discover_trending_models → observations)
src/radar/discovery/model_promotion.py        # MODIFY: promotable_candidates (pure momentum gate)
src/radar/cli.py                              # MODIFY: `models candidates scan`; use promotable_candidates in `models promote`; export threads Emerging rows
.github/workflows/publish.yml                  # MODIFY: daily candidate scan + commit the store
src/radar/web/app.py                          # MODIFY: /trending passes model_candidates
src/radar/web/static_site.py                  # MODIFY: static_trending gets model_candidates
src/radar/web/templates/trending.html static_trending.html   # MODIFY: "Emerging" sub-section
tests/test_model_candidate_log.py test_model_candidate_detect.py test_model_candidate_sweep.py   # NEW
tests/test_model_promotion_momentum.py test_publish_workflow.py test_web.py test_static_site.py    # NEW / MODIFY
README.md CHANGELOG.md                          # MODIFY
```

---

### Task 1: Candidate observation store

**Files:**
- Create: `src/radar/storage/model_candidate_log.py`
- Test: `tests/test_model_candidate_log.py`

**Interfaces:**
- Produces:
  - `ModelCandidateObservation` (frozen, `extra="forbid"`): `hf_repo: str`, `name: str`, `family: str`, `downloads: int`, `likes: int = 0`, `observed_at: datetime`.
  - `append_model_candidates(path: Path, rows: list[ModelCandidateObservation]) -> None` (append-only JSONL, mkdir parents, no-op empty).
  - `load_model_candidates(path: Path) -> list[ModelCandidateObservation]` (missing → `[]`; corrupt lines skipped with warning; hardened guarded read). Tasks 2/3/4/5 import these.

- [ ] **Step 1: Write the failing tests**

```python
"""Append-only JSONL log of untracked model-candidate observations."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from radar.storage.model_candidate_log import (
    ModelCandidateObservation,
    append_model_candidates,
    load_model_candidates,
)


def _obs(repo: str, downloads: int, day: int) -> ModelCandidateObservation:
    return ModelCandidateObservation(
        hf_repo=repo, name=repo.split("/")[-1], family=repo.split("/")[0],
        downloads=downloads, likes=5, observed_at=datetime(2026, 7, day, tzinfo=UTC),
    )


def test_round_trip_and_noop_empty(tmp_path: Path):
    path = tmp_path / "model-candidate-observations.jsonl"
    append_model_candidates(path, [_obs("a/b", 100, 1)])
    append_model_candidates(path, [_obs("a/b", 180, 4)])
    append_model_candidates(path, [])

    rows = load_model_candidates(path)
    assert [r.downloads for r in rows] == [100, 180]
    assert rows[0].hf_repo == "a/b"


def test_missing_and_corrupt(tmp_path: Path):
    assert load_model_candidates(tmp_path / "nope.jsonl") == []
    path = tmp_path / "model-candidate-observations.jsonl"
    append_model_candidates(path, [_obs("a/b", 100, 1)])
    with path.open("a", encoding="utf-8") as h:
        h.write("{broken\n")
    assert len(load_model_candidates(path)) == 1


def test_non_utf8_skipped(tmp_path: Path):
    path = tmp_path / "model-candidate-observations.jsonl"
    append_model_candidates(path, [_obs("a/b", 100, 1)])
    with path.open("ab") as h:
        h.write(b"\xff\xfe broken\n")
    assert len(load_model_candidates(path)) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_model_candidate_log.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

Create `src/radar/storage/model_candidate_log.py`:

```python
"""Append-only JSONL log of untracked model-candidate observations.

The daily candidate sweep records untracked HF-trending models here so download
velocity becomes durable across CI runs (the publish workflow commits the file,
like the history/metrics logs). Detection and the promote gate read it.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict


logger = logging.getLogger(__name__)


class ModelCandidateObservation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    hf_repo: str
    name: str
    family: str
    downloads: int
    likes: int = 0
    observed_at: datetime


def append_model_candidates(path: Path, rows: list[ModelCandidateObservation]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(r.model_dump(mode="json"), ensure_ascii=False) for r in rows]
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def load_model_candidates(path: Path) -> list[ModelCandidateObservation]:
    if not path.exists():
        return []
    rows: list[ModelCandidateObservation] = []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line_no, raw in enumerate(handle, start=1):
                line = raw.strip()
                if not line:
                    continue
                try:
                    rows.append(ModelCandidateObservation.model_validate_json(line))
                except ValueError as exc:
                    logger.warning("Skipping corrupt model-candidate line %d in %s: %s",
                                   line_no, path, exc)
    except OSError as exc:
        logger.warning("Could not read model-candidate store %s: %s", path, exc)
    return rows
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_model_candidate_log.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Lint + typecheck + commit**

```bash
uv run ruff check src/radar/storage tests/test_model_candidate_log.py && uv run mypy src/radar
git add src/radar/storage/model_candidate_log.py tests/test_model_candidate_log.py
git commit -m "feat: committed model-candidate observation store"
```

---

### Task 2: Candidate detection (velocity + sustained momentum, pure)

**Files:**
- Create: `src/radar/discovery/model_candidate_detect.py`
- Test: `tests/test_model_candidate_detect.py`

**Interfaces:**
- Consumes: `ModelCandidateObservation` (Task 1); `iso_week_bounds` is NOT needed (is_new uses first_seen vs now).
- Produces (pure, `now` a parameter):
  - Constants: `VELOCITY_WINDOW_DAYS = 7`, `NEW_WINDOW_DAYS = 14`, `MIN_MOMENTUM_DAYS = 3`, `MIN_MOMENTUM_SPAN = 5`, `MIN_GROWTH_PCT = 25.0`.
  - `ModelCandidateEntry` (frozen): `hf_repo`, `name`, `family`, `downloads: int`, `downloads_per_day: float | None`, `is_new: bool`, `first_seen: str`.
  - `build_model_candidates(observations: list[ModelCandidateObservation], now: datetime) -> list[ModelCandidateEntry]` — one entry per repo; `downloads_per_day` = downloads gained ÷ calendar-day span across the ≤`VELOCITY_WINDOW_DAYS` window, `None` with < 2 in-window rows or zero span; latest row supplies current downloads/name/family; `first_seen` = earliest `observed_at` date; `is_new` = first_seen within `NEW_WINDOW_DAYS` of `now`; ranked velocity-desc (None last), then downloads-desc, then repo.
  - `has_sustained_download_momentum(observations: list[ModelCandidateObservation]) -> bool` — for one repo's rows: ≥`MIN_MOMENTUM_DAYS` distinct observation days spanning ≥`MIN_MOMENTUM_SPAN` calendar days with total growth ≥ `MIN_GROWTH_PCT` (growth % is scale-robust for downloads). The gate the autopilot uses.

- [ ] **Step 1: Write the failing tests**

```python
"""Model-candidate detection: velocity, new, sustained momentum (pure)."""

from __future__ import annotations

from datetime import UTC, datetime

from radar.storage.model_candidate_log import ModelCandidateObservation
from radar.discovery.model_candidate_detect import (
    build_model_candidates,
    has_sustained_download_momentum,
)


NOW = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)


def _obs(repo: str, downloads: int, day: int, created: int = 1) -> ModelCandidateObservation:
    return ModelCandidateObservation(
        hf_repo=repo, name=repo.split("/")[-1], family=repo.split("/")[0],
        downloads=downloads, likes=1, observed_at=datetime(2026, 7, day, 7, 0, tzinfo=UTC),
    )


def test_velocity_over_window():
    rows = [_obs("a/b", 100, 1), _obs("a/b", 400, 4)]   # +300 over 3 days
    entry = build_model_candidates(rows, NOW)[0]
    assert entry.downloads_per_day == 100.0
    assert entry.downloads == 400            # latest row = current
    assert entry.first_seen == "2026-07-01"


def test_velocity_none_single_observation():
    entry = build_model_candidates([_obs("a/b", 100, 1)], NOW)[0]
    assert entry.downloads_per_day is None


def test_ranking_velocity_desc_none_last():
    rows = [_obs("fast/x", 100, 1), _obs("fast/x", 700, 4),   # +200/day
            _obs("slow/y", 100, 1), _obs("slow/y", 130, 4),   # +10/day
            _obs("solo/z", 900, 4)]                            # None
    entries = build_model_candidates(rows, NOW)
    assert [e.hf_repo for e in entries] == ["fast/x", "slow/y", "solo/z"]


def test_is_new_flag():
    # first_seen 2026-07-06 → within 14 days of NOW(07-08)
    entry = build_model_candidates([_obs("n/m", 60, 6), _obs("n/m", 90, 7)], NOW)[0]
    assert entry.is_new is True


def test_sustained_momentum_requires_days_span_growth():
    strong = [_obs("a/b", 100, 1), _obs("a/b", 110, 4), _obs("a/b", 130, 6)]  # 3 days, span 5, +30%
    assert has_sustained_download_momentum(strong) is True

    too_few_days = [_obs("a/b", 100, 1), _obs("a/b", 200, 6)]                 # 2 days
    assert has_sustained_download_momentum(too_few_days) is False

    flat = [_obs("a/b", 100, 1), _obs("a/b", 101, 4), _obs("a/b", 102, 6)]    # +2% < 25%
    assert has_sustained_download_momentum(flat) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_model_candidate_detect.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

Create `src/radar/discovery/model_candidate_detect.py`:

```python
"""Derive velocity + sustained-momentum signals from candidate observations (pure)."""

from __future__ import annotations

from datetime import datetime, timedelta

from pydantic import BaseModel, ConfigDict

from radar.storage.model_candidate_log import ModelCandidateObservation


VELOCITY_WINDOW_DAYS = 7
NEW_WINDOW_DAYS = 14
MIN_MOMENTUM_DAYS = 3
MIN_MOMENTUM_SPAN = 5
MIN_GROWTH_PCT = 25.0


class ModelCandidateEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    hf_repo: str
    name: str
    family: str
    downloads: int
    downloads_per_day: float | None
    is_new: bool
    first_seen: str


def _downloads_per_day(rows: list[ModelCandidateObservation], now: datetime) -> float | None:
    cutoff = now - timedelta(days=VELOCITY_WINDOW_DAYS)
    in_window = sorted((r for r in rows if r.observed_at >= cutoff),
                       key=lambda r: r.observed_at)
    if len(in_window) < 2:
        return None
    span = (in_window[-1].observed_at.date() - in_window[0].observed_at.date()).days
    if span <= 0:
        return None
    return round((in_window[-1].downloads - in_window[0].downloads) / span, 1)


def build_model_candidates(
    observations: list[ModelCandidateObservation], now: datetime
) -> list[ModelCandidateEntry]:
    by_repo: dict[str, list[ModelCandidateObservation]] = {}
    for obs in observations:
        by_repo.setdefault(obs.hf_repo, []).append(obs)
    entries: list[ModelCandidateEntry] = []
    for repo, rows in by_repo.items():
        ordered = sorted(rows, key=lambda r: r.observed_at)
        latest = ordered[-1]
        first_seen = ordered[0].observed_at.date()
        entries.append(ModelCandidateEntry(
            hf_repo=repo, name=latest.name, family=latest.family,
            downloads=latest.downloads,
            downloads_per_day=_downloads_per_day(ordered, now),
            is_new=first_seen >= (now - timedelta(days=NEW_WINDOW_DAYS)).date(),
            first_seen=first_seen.isoformat(),
        ))
    return sorted(entries, key=lambda e: (
        e.downloads_per_day is None,
        -(e.downloads_per_day if e.downloads_per_day is not None else 0.0),
        -e.downloads, e.hf_repo,
    ))


def has_sustained_download_momentum(observations: list[ModelCandidateObservation]) -> bool:
    if len(observations) < 2:
        return False
    ordered = sorted(observations, key=lambda r: r.observed_at)
    distinct_days = len({r.observed_at.date() for r in ordered})
    span = (ordered[-1].observed_at.date() - ordered[0].observed_at.date()).days
    if distinct_days < MIN_MOMENTUM_DAYS or span < MIN_MOMENTUM_SPAN:
        return False
    earliest = ordered[0].downloads
    if earliest <= 0:
        return False
    growth_pct = (ordered[-1].downloads - earliest) / earliest * 100
    return growth_pct >= MIN_GROWTH_PCT
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_model_candidate_detect.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Lint + typecheck + commit**

```bash
uv run ruff check src/radar/discovery tests/test_model_candidate_detect.py && uv run mypy src/radar
git add src/radar/discovery/model_candidate_detect.py tests/test_model_candidate_detect.py
git commit -m "feat: model-candidate velocity + sustained-momentum detection"
```

---

### Task 3: Sweep + `models candidates scan` CLI + CI

**Files:**
- Create: `src/radar/discovery/model_candidate_sweep.py`
- Modify: `src/radar/cli.py` (a `candidates` sub-app under `models_app` with `scan`), `.github/workflows/publish.yml`
- Test: `tests/test_model_candidate_sweep.py`, `tests/test_publish_workflow.py` (append)

**Interfaces:**
- Consumes: `discover_trending_models`, `ModelCandidateObservation`, `load_model_seed`, `append_model_candidates`.
- Produces:
  - `async sweep_model_candidates(seeds, client, now, headers=None) -> list[ModelCandidateObservation]` — call `discover_trending_models(seeds, client, headers=headers)`, map each `ModelProposal` → `ModelCandidateObservation(hf_repo=p.hf_repo, name=p.name, family=p.family, downloads=p.downloads, likes=p.likes, observed_at=now)`.
  - `radar models candidates scan [--root .]` — load the model seed, build an httpx client, sweep, append to `data/model-candidate-observations.jsonl`, print a one-line count.
  - publish.yml: `uv run radar models candidates scan --root .` in the scan block after `radar models scan`; `git add -f data/model-candidate-observations.jsonl || true` in the history-commit block.

- [ ] **Step 1: Write the failing tests (tests/test_model_candidate_sweep.py)**

```python
"""Sweep untracked trending HF models → observations (canned client)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from radar.discovery.model_candidate_sweep import sweep_model_candidates
from radar.models_radar.entities import ModelSeed


NOW = datetime(2026, 7, 8, 7, 0, tzinfo=UTC)


class _Resp:
    def __init__(self, items): self._items = items
    def raise_for_status(self): return None
    def json(self): return self._items


class _Client:
    def __init__(self, items): self._items = items
    async def get(self, url, **kwargs): return _Resp(self._items)


@pytest.mark.asyncio
async def test_sweep_maps_untracked_trending_to_observations():
    # discover_trending_models drops seeded repos; "tracked/m" is seeded, so excluded.
    items = [
        {"id": "acme/rocket", "downloads": 50000, "likes": 10, "pipeline_tag": "text-generation"},
        {"id": "tracked/m", "downloads": 90000, "likes": 3, "pipeline_tag": "text-generation"},
    ]
    seeds = [ModelSeed.model_validate({"id": "tracked-m", "name": "M", "family": "T",
                                       "hf_repo": "tracked/m"})]

    rows = await sweep_model_candidates(seeds, _Client(items), NOW)

    repos = {r.hf_repo for r in rows}
    assert "acme/rocket" in repos and "tracked/m" not in repos
    rocket = next(r for r in rows if r.hf_repo == "acme/rocket")
    assert rocket.downloads == 50000 and rocket.observed_at == NOW


@pytest.mark.asyncio
async def test_sweep_network_failure_degrades_empty():
    class _Boom:
        async def get(self, url, **kwargs): raise RuntimeError("down")
    rows = await sweep_model_candidates([], _Boom(), NOW)
    assert rows == []   # discover_trending_models is best-effort → []
```

NOTE for the implementer: check the real `ModelSeed` required fields (read `src/radar/models_radar/entities.py`) and adapt the `model_validate` dict if needed; the assertions are the contract. `discover_trending_models`' default `min_downloads=10000` keeps the 50000 candidate.

- [ ] **Step 2: Append the workflow test (tests/test_publish_workflow.py)**

```python
def test_publish_runs_candidate_scan_and_commits_store():
    text = Path(".github/workflows/publish.yml").read_text(encoding="utf-8")
    models_idx = text.index("radar models scan")
    cand_idx = text.index("radar models candidates scan")
    export_idx = text.index("radar export")
    assert models_idx < cand_idx < export_idx
    assert "data/model-candidate-observations.jsonl" in text
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_model_candidate_sweep.py tests/test_publish_workflow.py -v -k "candidate or model_candidate"`
Expected: FAIL — `ModuleNotFoundError` / substring not found

- [ ] **Step 4: Write the sweep**

Create `src/radar/discovery/model_candidate_sweep.py`:

```python
"""Sweep untracked HF-trending models into candidate observations.

Reuses discover_trending_models (which already excludes seeded/tracked repos and
degrades to [] on network failure) — we just stamp each result with observed_at
so velocity can emerge across daily runs.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from radar.discovery.hf_trending_models import discover_trending_models
from radar.models_radar.entities import ModelSeed
from radar.storage.model_candidate_log import ModelCandidateObservation


async def sweep_model_candidates(
    seeds: list[ModelSeed],
    client: Any,
    now: datetime,
    headers: dict[str, str] | None = None,
) -> list[ModelCandidateObservation]:
    proposals = await discover_trending_models(seeds, client, headers=headers)
    return [
        ModelCandidateObservation(
            hf_repo=p.hf_repo, name=p.name, family=p.family,
            downloads=p.downloads, likes=p.likes, observed_at=now,
        )
        for p in proposals
    ]
```

- [ ] **Step 5: Add the CLI command**

In `src/radar/cli.py`, register a `candidates` sub-app under `models_app` and add `scan` (mirror `models_scan`'s seed-load + httpx client):

```python
candidates_app = typer.Typer(help="Untracked model-candidate discovery.", no_args_is_help=True)
models_app.add_typer(candidates_app, name="candidates")


@candidates_app.command("scan")
def candidates_scan(root: Path = typer.Option(Path("."), help="Project root.")) -> None:
    """Sweep untracked HF-trending models and append to the candidate observation log."""
    import asyncio
    from datetime import UTC, datetime

    import httpx

    from radar.discovery.model_candidate_sweep import sweep_model_candidates
    from radar.models_radar.seed import load_model_seed
    from radar.storage.model_candidate_log import append_model_candidates

    seed_path = root / "config" / "model-seed.yaml"
    if not seed_path.exists():
        seed_path = Path(__file__).resolve().parents[2] / "config" / "model-seed.yaml"
    seeds = load_model_seed(seed_path)
    now = datetime.now(UTC)

    async def _run():
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            return await sweep_model_candidates(seeds, client, now)

    observations = asyncio.run(_run())
    out_path = root / "data" / "model-candidate-observations.jsonl"
    append_model_candidates(out_path, observations)
    console.print(f"Observed {len(observations)} untracked model candidate(s) "
                  f"→ {out_path.relative_to(root)}")
```

- [ ] **Step 6: Wire publish.yml**

After `uv run radar models scan --root .`, add:

```yaml
          uv run radar models candidates scan --root .
```

In the history-commit block, after `git add -f data/model-metrics.jsonl || true`, add:

```yaml
          git add -f data/model-candidate-observations.jsonl || true
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/test_model_candidate_sweep.py tests/test_publish_workflow.py -v`
Expected: PASS

- [ ] **Step 8: Lint + typecheck + commit**

```bash
uv run ruff check src/radar tests/test_model_candidate_sweep.py tests/test_publish_workflow.py && uv run mypy src/radar
git add src/radar/discovery/model_candidate_sweep.py src/radar/cli.py .github/workflows/publish.yml \
  tests/test_model_candidate_sweep.py tests/test_publish_workflow.py
git commit -m "feat: radar models candidates scan (daily untracked-model sweep) + CI"
```

---

### Task 4: Sustained-velocity gate on `models promote`

**Files:**
- Modify: `src/radar/discovery/model_promotion.py` (add `promotable_candidates`), `src/radar/cli.py` (`models_promote` uses it)
- Test: `tests/test_model_promotion_momentum.py`

**Interfaces:**
- Consumes: `is_promotable` (existing, same module); `ModelProposal`; `ModelCandidateObservation` + `has_sustained_download_momentum` (Tasks 1–2); `load_model_candidates` (Task 1, in the CLI).
- Produces a PURE, HF-free gate (unit-testable without the CLI): `promotable_candidates(proposals: list[ModelProposal], observations: list[ModelCandidateObservation], *, min_downloads: int, seeded_repos: set[str]) -> list[ModelProposal]` — keep each proposal that passes `is_promotable(p, min_downloads=..., seeded_repos=...)` **AND** `has_sustained_download_momentum(obs_by_repo.get(p.hf_repo.lower(), []))` (obs grouped by lowercased `hf_repo`). A proposal with no/insufficient observations is dropped (fail-closed). The CLI's `models_promote` calls this in place of its current inline `is_promotable` list-comp. (Extracting the gate as a pure function keeps it testable without HF/CLI — `models promote --dry-run` fetches HF per finalist, which a CLI test can't do.)

- [ ] **Step 1: Write the failing test**

```python
"""promotable_candidates gates promotion on sustained download momentum (pure, no HF)."""

from __future__ import annotations

from datetime import UTC, datetime

from radar.discovery.model_promotion import promotable_candidates
from radar.discovery.model_proposals import ModelProposal
from radar.storage.model_candidate_log import ModelCandidateObservation


def _proposal(repo: str, downloads: int) -> ModelProposal:
    name = repo.split("/")[-1]
    return ModelProposal(model_id=name, name=name, family=repo.split("/")[0], hf_repo=repo,
                         downloads=downloads, likes=10, modality="text", reason="t",
                         suggested_id=f"hf-{name}")


def _obs(repo: str, downloads: int, day: int) -> ModelCandidateObservation:
    return ModelCandidateObservation(hf_repo=repo, name=repo.split("/")[-1],
                                     family=repo.split("/")[0], downloads=downloads, likes=1,
                                     observed_at=datetime(2026, 7, day, tzinfo=UTC))


def test_sustained_candidate_passes_flat_popular_gated_out():
    proposals = [_proposal("acme/rocket", 200000), _proposal("bigco/flat", 500000)]
    observations = [
        _obs("acme/rocket", 100000, 1), _obs("acme/rocket", 130000, 4), _obs("acme/rocket", 150000, 6),
        _obs("bigco/flat", 500000, 1), _obs("bigco/flat", 501000, 4), _obs("bigco/flat", 502000, 6),
    ]  # rocket +50% (sustained); flat +0.4% (flat)

    kept = promotable_candidates(proposals, observations, min_downloads=100000, seeded_repos=set())

    assert [p.hf_repo for p in kept] == ["acme/rocket"]   # popular-but-flat is gated out


def test_no_observations_gates_everything_out():
    proposals = [_proposal("acme/rocket", 200000)]
    kept = promotable_candidates(proposals, [], min_downloads=100000, seeded_repos=set())
    assert kept == []   # fail-closed: no momentum evidence → not promoted
```

NOTE: read `src/radar/discovery/model_proposals.py` for the exact `ModelProposal` fields (the constructor above uses `model_id/name/family/hf_repo/downloads/likes/modality/reason/suggested_id`); fix the constructor if the schema differs. The assertions are the contract.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_model_promotion_momentum.py -v`
Expected: FAIL — `ImportError: cannot import name 'promotable_candidates'`

- [ ] **Step 3: Add the pure gate + wire the CLI**

In `src/radar/discovery/model_promotion.py`, add (import `ModelCandidateObservation` and `has_sustained_download_momentum` at the top):

```python
from radar.discovery.model_candidate_detect import has_sustained_download_momentum
from radar.storage.model_candidate_log import ModelCandidateObservation


def promotable_candidates(
    proposals: list[ModelProposal],
    observations: list[ModelCandidateObservation],
    *,
    min_downloads: int,
    seeded_repos: set[str],
) -> list[ModelProposal]:
    """Proposals that pass the existing gate AND show sustained download momentum."""
    obs_by_repo: dict[str, list[ModelCandidateObservation]] = {}
    for o in observations:
        obs_by_repo.setdefault(o.hf_repo.lower(), []).append(o)
    return [
        p for p in proposals
        if is_promotable(p, min_downloads=min_downloads, seeded_repos=seeded_repos)
        and has_sustained_download_momentum(obs_by_repo.get(p.hf_repo.lower(), []))
    ]
```

In `src/radar/cli.py` `models_promote`, import `promotable_candidates` + `load_model_candidates`, and replace the inline `candidates = [p for p in proposals if is_promotable(...)]` filter with:

```python
    from radar.storage.model_candidate_log import load_model_candidates

    observations = load_model_candidates(root / "data" / "model-candidate-observations.jsonl")
    candidates = promotable_candidates(
        proposals, observations, min_downloads=min_downloads, seeded_repos=seeded_repos)
```

(Adjust the `from radar.discovery.model_promotion import ...` line in the command to add `promotable_candidates`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_model_promotion_momentum.py -v`
Expected: PASS

- [ ] **Step 5: Lint + typecheck + commit**

```bash
uv run ruff check src/radar/discovery/model_promotion.py src/radar/cli.py tests/test_model_promotion_momentum.py && uv run mypy src/radar
git add src/radar/discovery/model_promotion.py src/radar/cli.py tests/test_model_promotion_momentum.py
git commit -m "feat: models promote requires sustained download momentum"
```

---

### Task 5: Live "Emerging" sub-section on `/trending`

**Files:**
- Modify: `src/radar/web/app.py`, `src/radar/web/templates/trending.html`
- Test: `tests/test_web.py` (append)

**Interfaces:**
- Consumes: `build_model_candidates` (Task 2), `load_model_candidates` (Task 1).
- Produces: a guarded loader `load_model_candidate_rows(root, now) -> list[ModelCandidateEntry]` (build from the store; `[]` on any failure); `/trending` passes `model_candidates` alongside `model_hub`/`technique_hub`; `trending.html` renders the "Emerging — not yet tracked" sub-section under the Models "Rising in the catalog" table, linking to `https://huggingface.co/{hf_repo}`.

- [ ] **Step 1: Write the failing tests (append to tests/test_web.py)**

```python
def _seed_candidates(root: Path) -> None:
    from datetime import UTC, datetime

    from radar.storage.model_candidate_log import (ModelCandidateObservation,
                                                    append_model_candidates)
    (root / "data").mkdir(parents=True, exist_ok=True)
    append_model_candidates(root / "data" / "model-candidate-observations.jsonl", [
        ModelCandidateObservation(hf_repo="acme/emerging", name="emerging", family="acme",
                                  downloads=d, likes=2,
                                  observed_at=datetime(2026, 7, day, 7, 0, tzinfo=UTC))
        for day, d in ((1, 1000), (4, 4000))
    ])


def test_trending_shows_emerging_candidates(tmp_path):
    _seed_candidates(tmp_path)
    client = TestClient(create_app(tmp_path))

    r = client.get("/trending")

    assert r.status_code == 200
    assert "Emerging" in r.text
    assert "acme/emerging" in r.text
    assert 'href="https://huggingface.co/acme/emerging"' in r.text


def test_trending_emerging_empty_survives(tmp_path):
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    client = TestClient(create_app(tmp_path))

    r = client.get("/trending")

    assert r.status_code == 200
    assert "Emerging" in r.text   # header present even when empty
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_web.py -v -k emerging`
Expected: FAIL — Emerging section not rendered

- [ ] **Step 3: Add the guarded loader + route wiring**

In `src/radar/web/app.py`, add a guarded loader near `_hub_sections`:

```python
    def _model_candidates():
        from datetime import UTC, datetime

        from radar.discovery.model_candidate_detect import build_model_candidates
        from radar.storage.model_candidate_log import load_model_candidates
        try:
            obs = load_model_candidates(root / "data" / "model-candidate-observations.jsonl")
            return build_model_candidates(obs, datetime.now(UTC))
        except Exception:
            return []
```

In the `/trending` route, pass it:

```python
        return TEMPLATES.TemplateResponse(request, "trending.html", {
            "onprem": onprem, "broader": broader,
            "model_hub": model_hub, "technique_hub": technique_hub,
            "model_candidates": _model_candidates(),
        })
```

- [ ] **Step 4: Add the template sub-section**

In `src/radar/web/templates/trending.html`, inside the Models portion (right after the "Trending Models" / model_hub table, before the Techniques section), add the Emerging sub-section (this exact snippet is reused byte-for-byte in the static template in Task 6 — HF links are absolute, so no live/static difference):

```html
      <h3>Emerging — not yet tracked</h3>
      {% if not model_candidates %}<p>No emerging models yet.</p>{% endif %}
      {% if model_candidates %}
      <table>
        <thead><tr><th>Model</th><th>Downloads</th><th>Downloads/day</th>
          <th></th><th>First seen</th></tr></thead>
        <tbody>
          {% for c in model_candidates %}
          <tr>
            <td><a href="https://huggingface.co/{{ c.hf_repo }}">{{ c.hf_repo }}</a></td>
            <td>{{ c.downloads }}</td>
            <td>{% if c.downloads_per_day is not none %}{{ "%+.0f"|format(c.downloads_per_day) }}{% else %}—{% endif %}</td>
            <td>{% if c.is_new %}NEW{% endif %}</td>
            <td>{{ c.first_seen }}</td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
      {% endif %}
```

NOTE for the implementer: place this so it reads as a sub-section of "Trending Models" (an `<h3>` under the section's `<h2>`). If the Phase-1 Models/Techniques loop makes that awkward, render the Models `<h2>` + its "Rising in the catalog" table + this Emerging block explicitly, and keep the Techniques section as-is — the load-bearing outcome is: Emerging appears within the Models area, headers present when empty.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_web.py -v`
Expected: PASS (new + existing)

- [ ] **Step 6: Lint + typecheck + commit**

```bash
uv run ruff check src/radar/web tests/test_web.py && uv run mypy src/radar
git add src/radar/web/app.py src/radar/web/templates/trending.html tests/test_web.py
git commit -m "feat: /trending Emerging (untracked model candidates) sub-section"
```

---

### Task 6: Static "Emerging" sub-section + export

**Files:**
- Modify: `src/radar/web/static_site.py`, `src/radar/web/templates/static_trending.html`, `src/radar/cli.py` (export)
- Test: `tests/test_static_site.py` (append)

**Interfaces:**
- Consumes: `build_model_candidates`/`load_model_candidates` (via the export); `ModelCandidateEntry`.
- Produces: `render_static_site(..., model_candidates: list[ModelCandidateEntry] | None = None)` renders the Emerging sub-section in `static_trending.html`; `radar export` builds `model_candidates` from the store at `generated_at` and threads it in.

- [ ] **Step 1: Write the failing tests (append to tests/test_static_site.py)**

```python
def test_static_site_renders_emerging(tmp_path):
    from radar.discovery.model_candidate_detect import ModelCandidateEntry

    cands = [ModelCandidateEntry(hf_repo="acme/emerging", name="emerging", family="acme",
                                 downloads=4000, downloads_per_day=1000.0, is_new=True,
                                 first_seen="2026-07-01")]
    render_static_site([], tmp_path / "_site", datetime(2026, 7, 8, tzinfo=UTC),
                       model_candidates=cands)
    page = (tmp_path / "_site" / "trending.html").read_text(encoding="utf-8")

    assert "Emerging" in page and "acme/emerging" in page
    assert 'href="https://huggingface.co/acme/emerging"' in page


def test_static_site_emerging_backcompat(tmp_path):
    render_static_site([], tmp_path / "_site", datetime(2026, 7, 8, tzinfo=UTC))
    assert (tmp_path / "_site" / "index.html").exists()   # no candidates → still renders
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_static_site.py -v -k emerging`
Expected: FAIL — `TypeError` on `model_candidates` kwarg

- [ ] **Step 3: Create the static template block**

In `src/radar/web/templates/static_trending.html`, add the SAME Emerging snippet from Task 4 (byte-for-byte — it references `model_candidates` + HF absolute links only, no live-vs-static difference) in the Models area, mirroring where the live template placed it.

- [ ] **Step 4: Wire static_site.py**

In `src/radar/web/static_site.py`: import `from radar.discovery.model_candidate_detect import ModelCandidateEntry`; add a param `model_candidates: list[ModelCandidateEntry] | None = None`; pass it into the `static_trending.html` render context (next to `model_hub`/`technique_hub`). The `trending.html` write-guard should also fire when candidates exist — extend it: `if trending_entries or model_hub or technique_hub or model_candidates:`.

- [ ] **Step 5: Wire the export CLI**

In `src/radar/cli.py` `export`, near the hub-sections load:

```python
    from radar.discovery.model_candidate_detect import build_model_candidates
    from radar.storage.model_candidate_log import load_model_candidates

    _model_candidates = build_model_candidates(
        load_model_candidates(root / "data" / "model-candidate-observations.jsonl"), generated_at)
```

and thread into `render_static_site(...)`: `model_candidates=_model_candidates or None`. (`generated_at` is the export's datetime, added in the trending-hub work.)

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_static_site.py tests/test_web.py tests/test_cli.py -v`
Expected: PASS (new + existing; back-compat proves no-candidate exports unchanged)

- [ ] **Step 7: Lint + typecheck + commit**

```bash
uv run ruff check src/radar tests/test_static_site.py && uv run mypy src/radar
git add src/radar/web/static_site.py src/radar/web/templates/static_trending.html \
  src/radar/cli.py tests/test_static_site.py
git commit -m "feat: static export Emerging model-candidates sub-section"
```

---

### Task 7: README + CHANGELOG + full gates

**Files:**
- Modify: `README.md`, `CHANGELOG.md`
- Test: the full suite

- [ ] **Step 1: README**

Extend the 📈 Trending radar Highlights bullet with a closing sentence:

```markdown
 `/trending` also surfaces **emerging models** — untracked HF-trending models observed over time in `data/model-candidate-observations.jsonl`, ranked by download velocity — and the catalog autopilot only auto-adds a model once it shows **sustained** download momentum, not just a high absolute count.
```

- [ ] **Step 2: CHANGELOG**

Under `## [Unreleased]` → `### Added`, at the top:

```markdown
- **Untracked model candidate discovery** — a daily `radar models candidates
  scan` records untracked HF-trending models (via the existing
  `discover_trending_models`) into a committed
  `data/model-candidate-observations.jsonl`; `/trending` shows them in an
  "Emerging — not yet tracked" sub-section ranked by download velocity, and
  `radar models promote` now requires **sustained download momentum** (≥3
  observation days over ≥5 with ≥25% growth) before auto-adding a model —
  not just a high absolute download count. Guarded reads keep a corrupt store
  from breaking `/trending`, the export, or promotion. (Trending hub Phase 2a;
  untracked papers are a future phase.)
```

- [ ] **Step 3: Full gates**

Run: `uv run pytest && uv run ruff check . && uv run mypy src/radar`
Expected: all pass, coverage ≥ 80%, ruff + mypy clean. Fix anything failing (implementation, not tests, unless a test is genuinely wrong).

- [ ] **Step 4: Commit**

```bash
git add README.md CHANGELOG.md
git commit -m "docs: untracked model candidate discovery (trending hub Phase 2a)"
```

---

## Self-Review Notes (already applied)

- Spec coverage: observation store (T1); daily sweep reusing `discover_trending_models` + CLI + CI (T3); pure velocity + `has_sustained_download_momentum` (T2); the promote momentum gate (T4); the Emerging surface live (T5) + static (T6); docs (T7). Phase 2b (papers) explicitly out of scope.
- Guarded/daily-publish invariant: `load_model_candidates` uses the hardened read; the sweep is best-effort via `discover_trending_models`; the live loader + static build + promote gate all fail-closed to empty/no-promotion.
- Determinism: `build_model_candidates`/`has_sustained_download_momentum` pure with `now`; only the sweep (`datetime.now(UTC)`), the route, and the export read the clock.
- No live/static link divergence: emerging rows use absolute `huggingface.co` URLs, so the Task-4 and Task-6 template snippets are identical (unlike the Phase-1 tracked rows).
- Momentum gate uses growth-% (scale-robust for downloads) not an absolute downloads/day floor; the `min_downloads` sanity floor stays (default 100k, tunable via `--min-downloads`). Promotion = existing checks AND sustained momentum → a flat-but-popular model no longer auto-adds.
- Type consistency: `ModelCandidateObservation` (T1) → detect/sweep/gate/surface; `ModelCandidateEntry`/`build_model_candidates`/`has_sustained_download_momentum` (T2) → T4/T5/T6; `sweep_model_candidates` (T3); `model_candidates` template var identical in `trending.html` (T5) and `static_trending.html` (T6).
