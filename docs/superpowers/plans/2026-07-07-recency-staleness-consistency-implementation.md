# Recency / Staleness Consistency Pass Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mark stale Emerging rows on `/trending` with a "Last seen" column + STALE badge, and window both autopilot momentum gates to the last 14 calendar days so they measure "rising right now" (fail-closed on stale data) instead of growth-since-the-earliest-ever-observation.

**Architecture:** Two independent parts. Part A (surface): both pure Emerging builders gain `last_seen` + `is_stale` derived fields; both Emerging template blocks (live + static) gain a "Last seen" column + STALE badge. Part B (gate): both momentum functions take `now` and filter observations to the last `MOMENTUM_WINDOW_DAYS` before the existing sustained-growth checks; `now` threads through `promotable_candidates` / `is_promotable_source` and the two promote CLIs.

**Tech Stack:** Python 3.12, pydantic v2, FastAPI + Jinja2, typer (all in-tree; **no new dependencies**), pytest + ruff + mypy.

**Spec:** `docs/superpowers/specs/2026-07-07-recency-staleness-consistency-design.md`.

## Global Constraints

- Deterministic + pure: detection + momentum stay pure — `now` is a parameter everywhere; only the CLI boundary reads the wall clock.
- Guarded gateways (`load_emerging_candidates`, `load_emerging_techniques`) and the daily-publish invariant are UNTOUCHED — this pass only adds derived fields + a window filter.
- `STALE_AFTER_DAYS = 4` (Emerging staleness); `MOMENTUM_WINDOW_DAYS = 14` (both gates). Defined per-module (each detect module + source_promotion already duplicate window constants — follow that pattern).
- Emerging staleness: keep the row + mark it (show `last_seen` + STALE badge). NO hard-drop, NO ranking change, NO cap change (`EMERGING_LIMIT = 15`).
- Momentum window anchored to `now` (calendar-recent): `observed_at >= now - timedelta(days=MOMENTUM_WINDOW_DAYS)`; < 2 recent rows → not sustained (fail-closed).
- No new fetch code, no new Python dependencies, no LLM.
- ruff line-length 100 (E501 ignored); `python_version = 3.12`; every file starts with `from __future__ import annotations`.
- Coverage ≥ 80%; gates `uv run pytest`, `uv run ruff check .`, `uv run mypy src/radar`.
- Commit format `<type>: <description>`; `git add` specific paths only (unrelated modified `data/history.jsonl` never committed).
- **`now`-threading breaks existing callers/tests** — every task that adds a `now` parameter MUST update all existing call sites AND their tests to pass a `now` consistent with the fixture observation dates (otherwise the 14-day window filters everything out). Grep for callers before finishing.

## Existing code being modified (all on main)

- `src/radar/discovery/model_candidate_detect.py`: `ModelCandidateEntry` (frozen): hf_repo, name, family, downloads, downloads_per_day: float|None, is_new: bool, first_seen: str. `build_model_candidates(observations, now)` constructs entries (downloads_per_day=_downloads_per_day(ordered, now); is_new=first_seen >= (now-NEW_WINDOW_DAYS).date(); first_seen=first_seen.isoformat()). `has_sustained_download_momentum(observations) -> bool` (distinct_days≥MIN_MOMENTUM_DAYS, span≥MIN_MOMENTUM_SPAN, growth≥MIN_GROWTH_PCT from ordered[0]).
- `src/radar/discovery/technique_candidate_detect.py`: `TechniqueCandidateEntry` (frozen): arxiv_id, name, upvotes, upvotes_per_day: float|None, citation_count: int|None, is_new: bool, first_seen: str. `build_technique_candidates(observations, now)`.
- `src/radar/discovery/model_promotion.py`: `promotable_candidates(proposals, observations, *, min_downloads, seeded_repos)` (line 106) calls `has_sustained_download_momentum(obs_by_repo.get(...))`.
- `src/radar/cli.py`: `models_promote` (calls `promotable_candidates(proposals, observations, min_downloads=..., seeded_repos=...)` ~line 386); `trending_promote` (line 912; calls `is_promotable_source(repo, rows, tracked_repos=..., existing_ids=..., existing_projects=...)` ~line 951 and `momentum_stats([...ONPREM...])` ~line 956; imports at 918-931).
- `src/radar/discovery/source_promotion.py`: `momentum_stats(rows) -> MomentumStats | None` (line 70), `has_sustained_momentum(rows) -> bool` (line 87, calls momentum_stats), `is_promotable_source(repo, rows, *, tracked_repos, existing_ids, existing_projects)` (calls `has_sustained_momentum(onprem_rows)` ~line 137).
- Templates `src/radar/web/templates/trending.html` + `static_trending.html`: each has a `{% if kind == "model" %}` and a `{% if kind == "technique" %}` Emerging block. Model block columns: Model | Downloads | Downloads/day | (badge) | First seen. Technique block columns: Paper | Upvotes | Upvotes/day | Citations | (badge) | First seen. Badge cell currently `{% if c.is_new %}NEW{% endif %}`.

## File Structure

```
src/radar/discovery/model_candidate_detect.py      # MODIFY: ModelCandidateEntry +last_seen +is_stale; STALE_AFTER_DAYS; has_sustained_download_momentum(obs, now) + MOMENTUM_WINDOW_DAYS
src/radar/discovery/technique_candidate_detect.py   # MODIFY: TechniqueCandidateEntry +last_seen +is_stale; STALE_AFTER_DAYS
src/radar/discovery/model_promotion.py              # MODIFY: promotable_candidates(..., now) threads now
src/radar/discovery/source_promotion.py             # MODIFY: momentum_stats(rows, now), has_sustained_momentum(rows, now), is_promotable_source(..., now); MOMENTUM_WINDOW_DAYS
src/radar/cli.py                                    # MODIFY: models_promote + trending_promote thread now
src/radar/web/templates/trending.html static_trending.html   # MODIFY: Last seen column + STALE badge in both Emerging blocks
tests/test_model_candidate_detect.py test_technique_candidate_detect.py test_model_promotion_momentum.py test_source_promotion.py test_web.py test_static_site.py test_models_radar_cli.py   # MODIFY
README.md CHANGELOG.md                              # MODIFY
```

---

### Task 1: Model Emerging staleness (build_model_candidates)

**Files:**
- Modify: `src/radar/discovery/model_candidate_detect.py`
- Test: `tests/test_model_candidate_detect.py`

**Interfaces:**
- Produces: `STALE_AFTER_DAYS = 4`; `ModelCandidateEntry` gains `last_seen: str`, `is_stale: bool`; `build_model_candidates(observations, now)` sets `last_seen` = latest observation date, `is_stale` = last_seen older than `STALE_AFTER_DAYS` before `now`. Task 3 (template) consumes `last_seen`/`is_stale`.

- [ ] **Step 1: Write the failing tests (append to tests/test_model_candidate_detect.py)**

```python
def test_last_seen_and_not_stale_when_recent():
    # NOW = 2026-07-08; latest obs 2026-07-06 → 2 days → not stale
    rows = [_obs("a/b", 100, 1), _obs("a/b", 400, 6)]
    entry = build_model_candidates(rows, NOW)[0]
    assert entry.last_seen == "2026-07-06"
    assert entry.is_stale is False


def test_is_stale_when_latest_observation_old():
    from radar.discovery.model_candidate_detect import STALE_AFTER_DAYS
    assert STALE_AFTER_DAYS == 4
    # latest obs 2026-07-01, NOW 2026-07-08 → 7 days > 4 → stale
    rows = [_obs("a/b", 100, 1), _obs("a/b", 400, 1)]  # both day 1 (velocity None); latest = 07-01
    entry = build_model_candidates(rows, NOW)[0]
    assert entry.last_seen == "2026-07-01"
    assert entry.is_stale is True
```

(Reuse the file's existing `_obs` helper + `NOW = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)`.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_model_candidate_detect.py -v -k "stale or last_seen"`
Expected: FAIL — `AttributeError: ... 'last_seen'` / unexpected keyword

- [ ] **Step 3: Implement**

In `src/radar/discovery/model_candidate_detect.py`: add the constant near the others:

```python
STALE_AFTER_DAYS = 4
```

Add the two fields to `ModelCandidateEntry` (after `first_seen`):

```python
    first_seen: str
    last_seen: str
    is_stale: bool
```

In `build_model_candidates`, where each entry is constructed (`first_seen` is the earliest `ordered[0]` date), also compute the latest and set the new fields:

```python
        first_seen = ordered[0].observed_at.date()
        last_seen = ordered[-1].observed_at.date()
        entries.append(ModelCandidateEntry(
            hf_repo=repo, name=latest.name, family=latest.family,
            downloads=latest.downloads,
            downloads_per_day=_downloads_per_day(ordered, now),
            is_new=first_seen >= (now - timedelta(days=NEW_WINDOW_DAYS)).date(),
            first_seen=first_seen.isoformat(),
            last_seen=last_seen.isoformat(),
            is_stale=last_seen < (now - timedelta(days=STALE_AFTER_DAYS)).date(),
        ))
```

(Keep the rest of the function — `ordered`, `latest`, the ranking `return sorted(...)` — unchanged.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_model_candidate_detect.py -v`
Expected: PASS (new + existing)

- [ ] **Step 5: Lint + typecheck + commit**

```bash
uv run ruff check src/radar/discovery/model_candidate_detect.py tests/test_model_candidate_detect.py && uv run mypy src/radar
git add src/radar/discovery/model_candidate_detect.py tests/test_model_candidate_detect.py
git commit -m "feat: model Emerging rows expose last_seen + is_stale"
```

---

### Task 2: Technique Emerging staleness (build_technique_candidates)

**Files:**
- Modify: `src/radar/discovery/technique_candidate_detect.py`
- Test: `tests/test_technique_candidate_detect.py`

**Interfaces:**
- Produces: `STALE_AFTER_DAYS = 4`; `TechniqueCandidateEntry` gains `last_seen: str`, `is_stale: bool`; `build_technique_candidates(observations, now)` sets them (latest observation date; stale if older than `STALE_AFTER_DAYS` before `now`). Task 3 consumes them.

- [ ] **Step 1: Write the failing tests (append to tests/test_technique_candidate_detect.py)**

```python
def test_last_seen_and_not_stale_when_recent():
    rows = [_obs("2501.x", 10, 1), _obs("2501.x", 90, 6)]   # latest 07-06, NOW 07-08 → not stale
    entry = build_technique_candidates(rows, NOW)[0]
    assert entry.last_seen == "2026-07-06"
    assert entry.is_stale is False


def test_is_stale_when_latest_observation_old():
    from radar.discovery.technique_candidate_detect import STALE_AFTER_DAYS
    assert STALE_AFTER_DAYS == 4
    rows = [_obs("2501.x", 10, 1), _obs("2501.x", 90, 1)]   # latest 07-01, NOW 07-08 → stale
    entry = build_technique_candidates(rows, NOW)[0]
    assert entry.last_seen == "2026-07-01"
    assert entry.is_stale is True
```

(Reuse the file's existing `_obs` helper + `NOW`.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_technique_candidate_detect.py -v -k "stale or last_seen"`
Expected: FAIL — unexpected keyword / AttributeError

- [ ] **Step 3: Implement**

In `src/radar/discovery/technique_candidate_detect.py`: add `STALE_AFTER_DAYS = 4` near the other constants; add to `TechniqueCandidateEntry` (after `first_seen`):

```python
    first_seen: str
    last_seen: str
    is_stale: bool
```

In `build_technique_candidates`, at the entry construction (where `first_seen = ordered[0].observed_at.date()`):

```python
        first_seen = ordered[0].observed_at.date()
        last_seen = ordered[-1].observed_at.date()
        entries.append(TechniqueCandidateEntry(
            arxiv_id=arxiv_id, name=latest.name, upvotes=latest.upvotes,
            upvotes_per_day=_upvotes_per_day(ordered, now),
            citation_count=latest.citation_count,
            is_new=first_seen >= (now - timedelta(days=NEW_WINDOW_DAYS)).date(),
            first_seen=first_seen.isoformat(),
            last_seen=last_seen.isoformat(),
            is_stale=last_seen < (now - timedelta(days=STALE_AFTER_DAYS)).date(),
        ))
```

(Keep `ordered`, `latest`, and the ranking `return sorted(...)` unchanged.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_technique_candidate_detect.py -v`
Expected: PASS

- [ ] **Step 5: Lint + typecheck + commit**

```bash
uv run ruff check src/radar/discovery/technique_candidate_detect.py tests/test_technique_candidate_detect.py && uv run mypy src/radar
git add src/radar/discovery/technique_candidate_detect.py tests/test_technique_candidate_detect.py
git commit -m "feat: technique Emerging rows expose last_seen + is_stale"
```

---

### Task 3: "Last seen" column + STALE badge in both Emerging blocks (live + static)

**Files:**
- Modify: `src/radar/web/templates/trending.html`, `src/radar/web/templates/static_trending.html`
- Test: `tests/test_web.py`, `tests/test_static_site.py` (append)

**Interfaces:**
- Consumes: `last_seen`, `is_stale` on both entry types (Tasks 1–2).
- Produces: both Emerging blocks (model + technique) in BOTH templates render a "Last seen" column + a STALE badge when `is_stale`. Live/static snippets stay byte-identical per block.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_web.py` (reuse the Phase-2a/2b seed helpers `_seed_candidates` / `_seed_paper_candidates` if present; otherwise seed two observations whose latest is > 4 days before the app's `now`). Because the live route uses `datetime.now(UTC)`, seed the latest observation well in the past so it is unambiguously stale:

```python
def test_trending_marks_stale_model_candidate(tmp_path):
    from datetime import UTC, datetime
    from radar.storage.model_candidate_log import (ModelCandidateObservation,
                                                    append_model_candidates)
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    # both observations far in the past → latest is > 4 days before now → stale
    append_model_candidates(tmp_path / "data" / "model-candidate-observations.jsonl", [
        ModelCandidateObservation(hf_repo="acme/old", name="old", family="acme", downloads=d,
                                  likes=1, observed_at=datetime(2020, 1, day, 7, 0, tzinfo=UTC))
        for day, d in ((1, 1000), (2, 2000))
    ])
    r = TestClient(create_app(tmp_path)).get("/trending")
    assert r.status_code == 200
    assert "Last seen" in r.text
    assert "STALE" in r.text
```

Append to `tests/test_static_site.py` (use the entry type directly for determinism):

```python
def test_static_site_marks_stale_and_shows_last_seen(tmp_path):
    from radar.discovery.model_candidate_detect import ModelCandidateEntry

    cands = [ModelCandidateEntry(hf_repo="acme/old", name="old", family="acme", downloads=2000,
                                 downloads_per_day=None, is_new=False, first_seen="2026-06-01",
                                 last_seen="2026-06-02", is_stale=True)]
    render_static_site([], tmp_path / "_site", datetime(2026, 7, 8, tzinfo=UTC),
                       model_candidates=cands)
    page = (tmp_path / "_site" / "trending.html").read_text(encoding="utf-8")
    assert "Last seen" in page and "2026-06-02" in page and "STALE" in page
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_web.py tests/test_static_site.py -v -k "stale or last_seen"`
Expected: FAIL — "Last seen"/"STALE" not present

- [ ] **Step 3: Edit the MODEL Emerging block in both templates**

In `src/radar/web/templates/trending.html` AND `src/radar/web/templates/static_trending.html`, inside the `{% if kind == "model" %}` Emerging table: add a `<th>Last seen</th>` header after `First seen`, add the cell after the `first_seen` cell, and change the badge cell to show STALE too. The row becomes:

```html
          <tr>
            <td><a href="https://huggingface.co/{{ c.hf_repo }}">{{ c.hf_repo }}</a></td>
            <td>{{ c.downloads }}</td>
            <td>{% if c.downloads_per_day is not none %}{{ "%+.0f"|format(c.downloads_per_day) }}{% else %}—{% endif %}</td>
            <td>{% if c.is_new %}NEW{% elif c.is_stale %}STALE{% endif %}</td>
            <td>{{ c.first_seen }}</td>
            <td>{{ c.last_seen }}</td>
          </tr>
```

and the header row gains `<th>Last seen</th>` after the `First seen` `<th>`. Apply the SAME edit to both templates (byte-identical).

- [ ] **Step 4: Edit the TECHNIQUE Emerging block in both templates**

In both templates, inside the `{% if kind == "technique" %}` Emerging table, the row becomes:

```html
          <tr>
            <td><a href="https://arxiv.org/abs/{{ c.arxiv_id }}">{{ c.name }}</a></td>
            <td>{{ c.upvotes }}</td>
            <td>{% if c.upvotes_per_day is not none %}{{ "%+.0f"|format(c.upvotes_per_day) }}{% else %}—{% endif %}</td>
            <td>{% if c.citation_count is not none %}{{ c.citation_count }}{% else %}—{% endif %}</td>
            <td>{% if c.is_new %}NEW{% elif c.is_stale %}STALE{% endif %}</td>
            <td>{{ c.first_seen }}</td>
            <td>{{ c.last_seen }}</td>
          </tr>
```

and the header row gains `<th>Last seen</th>` after `First seen`. Apply to both templates.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_web.py tests/test_static_site.py -v`
Expected: PASS (new + existing)

- [ ] **Step 6: Lint + typecheck + commit**

```bash
uv run ruff check src/radar/web tests/test_web.py tests/test_static_site.py && uv run mypy src/radar
git add src/radar/web/templates/trending.html src/radar/web/templates/static_trending.html \
  tests/test_web.py tests/test_static_site.py
git commit -m "feat: Emerging rows show Last seen + STALE badge (live + static)"
```

---

### Task 4: Window the model momentum gate to `now`

**Files:**
- Modify: `src/radar/discovery/model_candidate_detect.py`, `src/radar/discovery/model_promotion.py`, `src/radar/cli.py`
- Test: `tests/test_model_candidate_detect.py`, `tests/test_model_promotion_momentum.py`, `tests/test_models_radar_cli.py`

**Interfaces:**
- Produces: `MOMENTUM_WINDOW_DAYS = 14`; `has_sustained_download_momentum(observations, now)` filters to `observed_at >= now - MOMENTUM_WINDOW_DAYS` before the existing checks; `promotable_candidates(proposals, observations, *, min_downloads, seeded_repos, now)` threads `now`; `models promote` CLI passes `now`.

- [ ] **Step 1: Write the failing tests (append to tests/test_model_candidate_detect.py)**

```python
def test_momentum_windowed_out_when_no_recent_observation():
    from radar.discovery.model_candidate_detect import has_sustained_download_momentum
    # strong sustained growth, but ALL observations are > 14 days before NOW → windowed out
    old = [_obs("a/b", 100000, 1), _obs("a/b", 130000, 4), _obs("a/b", 160000, 6)]
    assert has_sustained_download_momentum(old, datetime(2026, 8, 1, tzinfo=UTC)) is False


def test_momentum_holds_for_recent_window():
    from radar.discovery.model_candidate_detect import has_sustained_download_momentum
    recent = [_obs("a/b", 100000, 1), _obs("a/b", 130000, 4), _obs("a/b", 160000, 6)]
    assert has_sustained_download_momentum(recent, NOW) is True   # NOW 07-08, obs within 14d
```

Update the EXISTING momentum tests in this file (the Phase-2a guard/momentum tests that call `has_sustained_download_momentum(...)` with one argument) to pass `NOW` as the second argument.

- [ ] **Step 2: Run to verify the new tests fail**

Run: `uv run pytest tests/test_model_candidate_detect.py -v -k momentum`
Expected: FAIL — `has_sustained_download_momentum()` takes 1 positional arg

- [ ] **Step 3: Implement the window**

In `src/radar/discovery/model_candidate_detect.py`, add `MOMENTUM_WINDOW_DAYS = 14` near the constants and rewrite the function to filter first:

```python
def has_sustained_download_momentum(
    observations: list[ModelCandidateObservation], now: datetime
) -> bool:
    recent = [o for o in observations
              if o.observed_at >= now - timedelta(days=MOMENTUM_WINDOW_DAYS)]
    if len(recent) < 2:
        return False
    ordered = sorted(recent, key=lambda r: r.observed_at)
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

- [ ] **Step 4: Thread `now` through `promotable_candidates`**

In `src/radar/discovery/model_promotion.py`, add `now` to the signature and pass it down:

```python
def promotable_candidates(
    proposals: list[ModelProposal],
    observations: list[ModelCandidateObservation],
    *,
    min_downloads: int,
    seeded_repos: set[str],
    now: datetime,
) -> list[ModelProposal]:
    obs_by_repo: dict[str, list[ModelCandidateObservation]] = {}
    for o in observations:
        obs_by_repo.setdefault(o.hf_repo.lower(), []).append(o)
    return [
        p for p in proposals
        if is_promotable(p, min_downloads=min_downloads, seeded_repos=seeded_repos)
        and has_sustained_download_momentum(obs_by_repo.get(p.hf_repo.lower(), []), now)
    ]
```

(Add `from datetime import datetime` to the imports if not already present.)

- [ ] **Step 5: Thread `now` at the CLI**

In `src/radar/cli.py` `models_promote`, ensure a `now` exists (add `now = datetime.now(UTC)` near the observation load if absent — check the imports include `from datetime import UTC, datetime`), and pass it:

```python
    now = datetime.now(UTC)
    candidates = promotable_candidates(
        proposals, observations, min_downloads=min_downloads,
        seeded_repos=seeded_repos, now=now)
```

- [ ] **Step 6: Update the existing promote-gate tests**

- In `tests/test_model_promotion_momentum.py`: every `promotable_candidates(...)` call gains `now=datetime(2026, 7, 8, tzinfo=UTC)` (or a `NOW` matching the fixtures' observation dates so the window includes them). Import `datetime`/`UTC` if needed.
- In `tests/test_models_radar_cli.py`: the promote-CLI fixtures seed observations dated in January (`datetime(2026, 1, ...)`); the CLI now uses real `datetime.now(UTC)`, so those January observations fall outside the 14-day window → the model would no longer promote and the test would break. Re-date those fixture observations to within `MOMENTUM_WINDOW_DAYS` of "now" — use a helper that stamps them relative to `datetime.now(UTC)` (e.g. `now - timedelta(days=6/3/1)` for the three rows) so the promote test stays valid regardless of the calendar date. Keep the +growth so the momentum gate still passes.

- [ ] **Step 7: Run tests**

Run: `uv run pytest tests/test_model_candidate_detect.py tests/test_model_promotion_momentum.py tests/test_models_radar_cli.py -v`
Expected: PASS (new window tests + updated existing)

- [ ] **Step 8: Lint + typecheck + commit**

```bash
uv run ruff check src/radar tests/test_model_candidate_detect.py tests/test_model_promotion_momentum.py tests/test_models_radar_cli.py && uv run mypy src/radar
git add src/radar/discovery/model_candidate_detect.py src/radar/discovery/model_promotion.py src/radar/cli.py \
  tests/test_model_candidate_detect.py tests/test_model_promotion_momentum.py tests/test_models_radar_cli.py
git commit -m "feat: window model promote momentum gate to recent observations"
```

---

### Task 5: Window the repo source-autopilot momentum gate to `now`

**Files:**
- Modify: `src/radar/discovery/source_promotion.py`, `src/radar/cli.py`
- Test: `tests/test_source_promotion.py` (+ any trending-promote CLI test that seeds observations)

**Interfaces:**
- Produces: `MOMENTUM_WINDOW_DAYS = 14`; `momentum_stats(rows, now)` filters to the recent window before stats; `has_sustained_momentum(rows, now)` passes `now`; `is_promotable_source(repo, rows, *, tracked_repos, existing_ids, existing_projects, now)` threads `now`; `trending promote` CLI passes `now` to both `is_promotable_source` and `momentum_stats`.

- [ ] **Step 1: Write the failing tests (append to tests/test_source_promotion.py)**

Read the top of `tests/test_source_promotion.py` for its existing ONPREM-`TrendingObservation` builder helper and mirror its exact signature. The test below assumes a helper `_obs(stars, observed_at)` that builds a `Lane.ONPREM` row — adapt the `_obs(...)` calls to the file's real helper (it may take a `day` int instead of an `observed_at`, and may require `repo`/`source_id`/`lane`; keep the two rows' stars = 100 then 400 for a clear +growth):

```python
def test_momentum_stats_windowed_to_recent():
    from datetime import UTC, datetime, timedelta

    from radar.discovery.source_promotion import momentum_stats
    now = datetime(2026, 7, 8, tzinfo=UTC)
    recent = [_obs(100, now - timedelta(days=6)), _obs(400, now - timedelta(days=1))]
    stats = momentum_stats(recent, now)
    assert stats is not None and stats.avg_velocity > 0

    old = [_obs(100, now - timedelta(days=40)), _obs(400, now - timedelta(days=30))]
    assert momentum_stats(old, now) is None   # both rows outside the 14-day window
```

Also update EVERY existing `momentum_stats(...)` / `has_sustained_momentum(...)` / `is_promotable_source(...)` call in this test file to pass a `now` consistent with each test's fixture observation dates (so the window includes them).

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_source_promotion.py -v -k momentum`
Expected: FAIL — `momentum_stats()` takes 1 positional arg

- [ ] **Step 3: Implement the window in source_promotion.py**

Add `MOMENTUM_WINDOW_DAYS = 14` near the other constants (and `from datetime import timedelta` if not imported — the module likely already imports datetime types). Rewrite `momentum_stats` to filter first, and thread `now` through the two callers:

```python
def momentum_stats(rows: list[TrendingObservation], now: datetime) -> MomentumStats | None:
    """Momentum over one repo's recent (<= MOMENTUM_WINDOW_DAYS) observation rows."""
    recent = [r for r in rows if r.observed_at >= now - timedelta(days=MOMENTUM_WINDOW_DAYS)]
    if len(recent) < 2:
        return None
    ordered = sorted(recent, key=lambda r: r.observed_at)
    distinct_days = len({r.observed_at.date() for r in ordered})
    span_days = (ordered[-1].observed_at.date() - ordered[0].observed_at.date()).days
    if span_days <= 0:
        return None
    delta = ordered[-1].stars - ordered[0].stars
    avg_velocity = round(delta / span_days, 1)
    earliest = ordered[0].stars
    growth_pct = round(delta / earliest * 100, 1) if earliest else 0.0
    return MomentumStats(distinct_days=distinct_days, span_days=span_days,
                         avg_velocity=avg_velocity, growth_pct=growth_pct)


def has_sustained_momentum(rows: list[TrendingObservation], now: datetime) -> bool:
    stats = momentum_stats(rows, now)
    if stats is None:
        return False
    if stats.distinct_days < MIN_OBSERVATION_DAYS or stats.span_days < MIN_SPAN_DAYS:
        return False
    return (stats.avg_velocity >= MIN_AVG_VELOCITY
            or stats.growth_pct >= MIN_TOTAL_GROWTH_PCT)
```

(Confirm `datetime` + `timedelta` are imported at the top of source_promotion.py; add `from datetime import datetime, timedelta` if missing.)

- [ ] **Step 4: Thread `now` through `is_promotable_source`**

Add `now: datetime` as a keyword-only parameter to `is_promotable_source` and update its internal call:

```python
    onprem_rows = [r for r in rows if r.lane == Lane.ONPREM]
    if not has_sustained_momentum(onprem_rows, now):
        return False
```

(Add `now` to the signature after the existing keyword params: `..., existing_projects: ..., now: datetime`.)

- [ ] **Step 5: Thread `now` at the CLI**

In `src/radar/cli.py` `trending_promote`, add `now = datetime.now(UTC)` after the observations are loaded (before the `candidates` comprehension), and pass `now` to both call sites:

```python
    now = datetime.now(UTC)
    candidates = [
        (repo, rows) for repo, rows in by_repo.items()
        if is_promotable_source(repo, rows, tracked_repos=tracked_repos,
                                existing_ids=existing_ids, existing_projects=existing_projects,
                                now=now)
    ]

    def _velocity(rows: list[TrendingObservation]) -> float:
        stats = momentum_stats([r for r in rows if r.lane == Lane.ONPREM], now)
        return stats.avg_velocity if stats else 0.0
```

(`trending_promote` imports `datetime`/`UTC` at its top already — confirm; it does `from datetime import UTC, datetime`.)

- [ ] **Step 6: Update existing callers/tests**

Grep for any other caller: `grep -rn "momentum_stats\|has_sustained_momentum\|is_promotable_source" src tests`. Update each remaining call (and any trending-promote CLI test that seeds `trending-observations.jsonl`) to pass a `now` consistent with its fixture observation dates — re-date CLI-test fixture observations relative to `datetime.now(UTC)` (as in Task 4) if they were absolute past dates, so the window includes them.

- [ ] **Step 7: Run tests**

Run: `uv run pytest tests/test_source_promotion.py tests/test_cli.py -v -k "momentum or promote or trending"`
Expected: PASS

- [ ] **Step 8: Lint + typecheck + commit**

```bash
uv run ruff check src/radar tests/test_source_promotion.py && uv run mypy src/radar
git add src/radar/discovery/source_promotion.py src/radar/cli.py tests/test_source_promotion.py
git commit -m "feat: window repo autopilot momentum gate to recent observations"
```

---

### Task 6: README + CHANGELOG + full gates

**Files:**
- Modify: `README.md`, `CHANGELOG.md`
- Test: the full suite

- [ ] **Step 1: CHANGELOG**

Under `## [Unreleased]` → add a `### Changed` entry (or append to Changed if present):

```markdown
- **Recency/staleness pass** — Emerging rows on `/trending` now show a "Last
  seen" date and a STALE badge once a candidate stops appearing in the daily
  sweep (its frozen numbers are no longer misleading), and both autopilot
  momentum gates (`models promote`, `trending promote`) now measure sustained
  growth over the last 14 days relative to now — "rising right now", fail-closed
  on stale data — instead of growth since the earliest-ever observation, so the
  gates no longer saturate over time.
```

- [ ] **Step 2: README**

Extend the 📈 Trending radar Highlights bullet with a closing clause about Emerging rows showing recency (Last seen + STALE) and the momentum gates being windowed to recent activity. Keep it to one sentence.

- [ ] **Step 3: Full gates**

Run: `uv run pytest && uv run ruff check . && uv run mypy src/radar`
Expected: all pass, coverage ≥ 80%, ruff + mypy clean. If the README has a test-count badge and the count changed, update it to the EXACT number from this run.

- [ ] **Step 4: Commit**

```bash
git add README.md CHANGELOG.md
git commit -m "docs: recency/staleness consistency pass"
```

---

## Self-Review Notes (already applied)

- Spec coverage: Part A surface — model Emerging staleness (T1), technique Emerging staleness (T2), both template blocks live+static (T3). Part B gate — model momentum window + now-threading (T4), repo momentum window + now-threading (T5). Docs (T6). Guarded gateways untouched (only derived fields + a window filter added).
- `now`-threading breakage handled explicitly: T4 updates test_model_promotion_momentum + test_models_radar_cli (re-dating January fixtures relative to now); T5 updates test_source_promotion + any trending-promote CLI test; both grep for stragglers.
- Determinism: `now` a parameter in every detection/momentum function; only the two CLIs read `datetime.now(UTC)`. Windowing is a pure filter; empty window → existing `<2 rows → not sustained/None` (fail-closed), guarded gateways unchanged.
- Type consistency: `last_seen: str` + `is_stale: bool` added to both entry types (T1/T2) and consumed identically in both template blocks (T3); `STALE_AFTER_DAYS = 4` per detect module; `MOMENTUM_WINDOW_DAYS = 14` in model_candidate_detect (T4) and source_promotion (T5); `has_sustained_download_momentum(obs, now)` / `promotable_candidates(..., now)` / `momentum_stats(rows, now)` / `has_sustained_momentum(rows, now)` / `is_promotable_source(..., now)` signatures match their call sites.
- Badge cell shows `NEW` else `STALE` (a stale row can't be new), so the two badges never collide.
