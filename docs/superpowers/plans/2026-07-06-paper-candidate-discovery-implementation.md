# Untracked Paper Candidate Discovery (Phase 2b) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Observe untracked hot arXiv/HF papers over time in a committed store and surface them as an "Emerging — not yet tracked" sub-section under Trending Techniques on `/trending`, ranked by HF-upvote velocity — observe + surface only (techniques stay human-gated; no promotion gate).

**Architecture:** A daily `radar research candidates scan` reuses the existing paper fetchers (`discover_technique_candidates` HF + `discover_arxiv_candidates` arXiv, which already exclude tracked papers) and appends observations to a committed `data/technique-candidate-observations.jsonl`. A pure detection module derives upvote velocity; a guarded gateway filters currently-tracked papers + caps. The `/trending` Techniques area gains an "Emerging" sub-section. This is the Phase 2a shape (already merged) minus the promote gate.

**Tech Stack:** Python 3.12, pydantic v2, FastAPI + Jinja2, typer, httpx (all in-tree; **no new dependencies**), pytest + ruff + mypy.

**Spec:** `docs/superpowers/specs/2026-07-06-paper-candidate-discovery-design.md` (Phase 2b). Completes the trending-hub program (models 2a + papers 2b).

## Global Constraints

- Deterministic + offline except the daily sweep: detection is pure (`now` a parameter); only the sweep hits HF/arXiv (best-effort → no observations + warning).
- **Guarded reads (daily-publish invariant):** a corrupt/absent store → empty Emerging sub-section — never a 500 on `/trending`, never a crash in `radar export`. The JSONL loader uses `errors="replace"` + `except OSError` + per-line `except ValueError`, plus a naive→UTC `observed_at` `field_validator` (baked in from the start — the fix Phase 2a needed as a follow-up).
- No new fetching code — the sweep reuses the two existing fetchers + `enrich_proposals_with_velocity`. No new Python dependencies. No LLM. **No promotion gate** (techniques human-gated).
- Emerging rows link to `https://arxiv.org/abs/{arxiv_id}` (absolute — the live and static template snippets are identical, no divergence).
- ruff line-length = 100; `python_version = 3.12`; every file starts with `from __future__ import annotations`.
- Coverage ≥ 80%; gates `uv run pytest`, `uv run ruff check .`, `uv run mypy src/radar`.
- Commit format `<type>: <description>`; `git add` specific paths only (unrelated modified `data/history.jsonl` never committed).
- Existing symbols consumed (all on main): `discover_technique_candidates(seeds, client, min_upvotes=10, limit=20) -> list[TechniqueProposal]` (`radar.discovery.hf_technique_candidates`); `discover_arxiv_candidates(seeds, client, since, limit=20) -> list[TechniqueProposal]` (`radar.discovery.arxiv_technique_candidates`); `enrich_proposals_with_velocity(proposals, client, now, contact_email=None)` (`radar.discovery.technique_candidate_velocity`); `TechniqueProposal` (`arxiv_id, name, upvotes, citation_count, citations_per_day, published, suggested_domain: TechniqueDomain, suggested_category: Category, …`); `load_technique_seed` (`radar.research_radar.seed`); `TechniqueSeed.papers: list[PaperLink]` with `arxiv_id`; the `/trending` route + `trending.html`/`static_trending.html` (which already carry a `{% if kind == "model" %}` Emerging block from Phase 2a).

## File Structure

```
src/radar/storage/technique_candidate_log.py     # NEW: TechniqueCandidateObservation (+naive→UTC validator) + append/load
src/radar/discovery/technique_candidate_detect.py # NEW: TechniqueCandidateEntry + build_technique_candidates + load_emerging_techniques (pure builder + guarded gateway)
src/radar/discovery/technique_candidate_sweep.py  # NEW: sweep_technique_candidates (reuse both fetchers + enrich → observations)
src/radar/cli.py                                  # MODIFY: `research candidates scan`; export threads technique_candidates
.github/workflows/publish.yml                      # MODIFY: daily candidate scan + commit the store
src/radar/web/app.py                              # MODIFY: /trending passes technique_candidates
src/radar/web/static_site.py                      # MODIFY: static_trending gets technique_candidates
src/radar/web/templates/trending.html static_trending.html   # MODIFY: Emerging block under Techniques ({% if kind == "technique" %})
tests/test_technique_candidate_log.py test_technique_candidate_detect.py test_technique_candidate_sweep.py   # NEW
tests/test_publish_workflow.py test_web.py test_static_site.py    # MODIFY
README.md CHANGELOG.md                              # MODIFY
```

---

### Task 1: Candidate observation store

**Files:**
- Create: `src/radar/storage/technique_candidate_log.py`
- Test: `tests/test_technique_candidate_log.py`

**Interfaces:**
- Produces:
  - `TechniqueCandidateObservation` (frozen, `extra="forbid"`): `arxiv_id: str`, `name: str`, `upvotes: int = 0`, `citation_count: int | None = None`, `published: str | None = None`, `suggested_domain: str`, `suggested_category: str`, `observed_at: datetime` — with a `field_validator("observed_at")` normalizing naive → UTC.
  - `append_technique_candidates(path, rows) -> None` (append-only JSONL, mkdir parents, no-op empty) + `load_technique_candidates(path) -> list[TechniqueCandidateObservation]` (missing → `[]`; corrupt lines skipped with warning; hardened guarded read). Tasks 2/3/4/5 import these.

- [ ] **Step 1: Write the failing tests**

```python
"""Append-only JSONL log of untracked paper-candidate observations."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from radar.storage.technique_candidate_log import (
    TechniqueCandidateObservation,
    append_technique_candidates,
    load_technique_candidates,
)


def _obs(arxiv: str, upvotes: int, day: int) -> TechniqueCandidateObservation:
    return TechniqueCandidateObservation(
        arxiv_id=arxiv, name=f"Paper {arxiv}", upvotes=upvotes, citation_count=3,
        published="2026-06-20", suggested_domain="reasoning",
        suggested_category="inference", observed_at=datetime(2026, 7, day, tzinfo=UTC),
    )


def test_round_trip_and_noop_empty(tmp_path: Path):
    path = tmp_path / "technique-candidate-observations.jsonl"
    append_technique_candidates(path, [_obs("2501.1", 10, 1)])
    append_technique_candidates(path, [_obs("2501.1", 40, 4)])
    append_technique_candidates(path, [])

    rows = load_technique_candidates(path)
    assert [r.upvotes for r in rows] == [10, 40]
    assert rows[0].arxiv_id == "2501.1"


def test_missing_and_corrupt(tmp_path: Path):
    assert load_technique_candidates(tmp_path / "nope.jsonl") == []
    path = tmp_path / "technique-candidate-observations.jsonl"
    append_technique_candidates(path, [_obs("2501.1", 10, 1)])
    with path.open("a", encoding="utf-8") as h:
        h.write("{broken\n")
    assert len(load_technique_candidates(path)) == 1


def test_non_utf8_skipped(tmp_path: Path):
    path = tmp_path / "technique-candidate-observations.jsonl"
    append_technique_candidates(path, [_obs("2501.1", 10, 1)])
    with path.open("ab") as h:
        h.write(b"\xff\xfe broken\n")
    assert len(load_technique_candidates(path)) == 1


def test_naive_observed_at_normalized_to_utc(tmp_path: Path):
    path = tmp_path / "technique-candidate-observations.jsonl"
    path.write_text('{"arxiv_id":"2501.1","name":"P","upvotes":5,"citation_count":1,'
                    '"published":"2026-06-20","suggested_domain":"reasoning",'
                    '"suggested_category":"inference","observed_at":"2026-07-06T07:00:00"}\n',
                    encoding="utf-8")
    rows = load_technique_candidates(path)
    assert len(rows) == 1 and rows[0].observed_at.tzinfo is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_technique_candidate_log.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

Create `src/radar/storage/technique_candidate_log.py`:

```python
"""Append-only JSONL log of untracked paper-candidate observations.

The daily candidate sweep records untracked hot papers here so upvote velocity
becomes durable across CI runs (the publish workflow commits the file, like the
history/metrics logs). Detection reads it; there is no promotion gate.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, field_validator


logger = logging.getLogger(__name__)


class TechniqueCandidateObservation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    arxiv_id: str
    name: str
    upvotes: int = 0
    citation_count: int | None = None
    published: str | None = None
    suggested_domain: str
    suggested_category: str
    observed_at: datetime

    @field_validator("observed_at")
    @classmethod
    def _ensure_aware(cls, v: datetime) -> datetime:
        return v.replace(tzinfo=UTC) if v.tzinfo is None else v


def append_technique_candidates(path: Path, rows: list[TechniqueCandidateObservation]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(r.model_dump(mode="json"), ensure_ascii=False) for r in rows]
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def load_technique_candidates(path: Path) -> list[TechniqueCandidateObservation]:
    if not path.exists():
        return []
    rows: list[TechniqueCandidateObservation] = []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line_no, raw in enumerate(handle, start=1):
                line = raw.strip()
                if not line:
                    continue
                try:
                    rows.append(TechniqueCandidateObservation.model_validate_json(line))
                except ValueError as exc:
                    logger.warning("Skipping corrupt technique-candidate line %d in %s: %s",
                                   line_no, path, exc)
    except OSError as exc:
        logger.warning("Could not read technique-candidate store %s: %s", path, exc)
    return rows
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_technique_candidate_log.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Lint + typecheck + commit**

```bash
uv run ruff check src/radar/storage tests/test_technique_candidate_log.py && uv run mypy src/radar
git add src/radar/storage/technique_candidate_log.py tests/test_technique_candidate_log.py
git commit -m "feat: committed paper-candidate observation store"
```

---

### Task 2: Candidate detection (upvote velocity + guarded gateway)

**Files:**
- Create: `src/radar/discovery/technique_candidate_detect.py`
- Test: `tests/test_technique_candidate_detect.py`

**Interfaces:**
- Consumes: `TechniqueCandidateObservation` (Task 1); `load_technique_seed` (in the gateway).
- Produces (pure builder + guarded gateway):
  - Constants: `VELOCITY_WINDOW_DAYS = 7`, `NEW_WINDOW_DAYS = 14`, `EMERGING_LIMIT = 15`.
  - `TechniqueCandidateEntry` (frozen): `arxiv_id`, `name`, `upvotes: int`, `upvotes_per_day: float | None`, `citation_count: int | None`, `is_new: bool`, `first_seen: str`.
  - `build_technique_candidates(observations, now) -> list[TechniqueCandidateEntry]` (pure) — one entry per `arxiv_id`; `upvotes_per_day` = upvotes gained ÷ calendar-day span over the ≤7-day window, `None` with < 2 in-window rows or zero span; latest row → current upvotes/name/citations; `first_seen` = earliest `observed_at` date; `is_new` = first_seen within 14 days of `now`; ranked `(upvotes_per_day is None, -upvotes_per_day, -(citation_count or 0), arxiv_id)`.
  - `load_emerging_techniques(root, now, *, limit=EMERGING_LIMIT) -> list[TechniqueCandidateEntry]` — guarded gateway: load observations → build → drop any `arxiv_id` in the current technique seed's papers → cap → `try/except → []` with a warning.

- [ ] **Step 1: Write the failing tests**

```python
"""Paper-candidate detection: upvote velocity, new, ranking, emerging gateway."""

from __future__ import annotations

from datetime import UTC, datetime

from radar.discovery.technique_candidate_detect import (
    build_technique_candidates,
    load_emerging_techniques,
)
from radar.storage.technique_candidate_log import (
    TechniqueCandidateObservation,
    append_technique_candidates,
)


NOW = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)


def _obs(arxiv: str, upvotes: int, day: int, citations: int = 1) -> TechniqueCandidateObservation:
    return TechniqueCandidateObservation(
        arxiv_id=arxiv, name=f"Paper {arxiv}", upvotes=upvotes, citation_count=citations,
        published="2026-06-20", suggested_domain="reasoning", suggested_category="inference",
        observed_at=datetime(2026, 7, day, 7, 0, tzinfo=UTC),
    )


def test_upvote_velocity_over_window():
    rows = [_obs("2501.1", 10, 1), _obs("2501.1", 40, 4)]   # +30 over 3 days
    entry = build_technique_candidates(rows, NOW)[0]
    assert entry.upvotes_per_day == 10.0
    assert entry.upvotes == 40 and entry.first_seen == "2026-07-01"


def test_velocity_none_single_observation():
    assert build_technique_candidates([_obs("2501.1", 10, 1)], NOW)[0].upvotes_per_day is None


def test_ranking_upvote_desc_none_last_citation_tiebreak():
    rows = [_obs("hot/1", 10, 1), _obs("hot/1", 200, 4),      # +63/day
            _obs("warm/1", 10, 1), _obs("warm/1", 40, 4),     # +10/day
            _obs("solo/1", 90, 4, citations=99)]              # None velocity, high citations
    entries = build_technique_candidates(rows, NOW)
    assert [e.arxiv_id for e in entries] == ["hot/1", "warm/1", "solo/1"]


def test_is_new_flag():
    entry = build_technique_candidates([_obs("n/1", 5, 6), _obs("n/1", 9, 7)], NOW)[0]
    assert entry.is_new is True


def test_load_emerging_excludes_tracked_and_caps(tmp_path):
    from radar.discovery.technique_candidate_detect import EMERGING_LIMIT

    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    # a tracked technique whose paper is arxiv 2501.tracked → excluded from Emerging
    (tmp_path / "config" / "technique-seed.yaml").write_text(
        "techniques:\n  - id: tracked\n    name: Tracked\n    domain: reasoning\n"
        "    category: inference\n    onprem_impact: reduces_latency\n"
        "    papers:\n      - arxiv_id: 2501.tracked\n        title: T\n        role: primary\n",
        encoding="utf-8")
    obs = [_obs("2501.tracked", 100, 4), _obs("2501.tracked", 200, 6)]
    for i in range(EMERGING_LIMIT + 3):
        obs += [_obs(f"2501.c{i}", 10 + i, 4), _obs(f"2501.c{i}", 50 + i, 6)]
    append_technique_candidates(tmp_path / "data" / "technique-candidate-observations.jsonl", obs)

    rows = load_emerging_techniques(tmp_path, NOW)
    ids = {r.arxiv_id for r in rows}
    assert "2501.tracked" not in ids      # tracked paper excluded
    assert len(rows) == EMERGING_LIMIT     # capped
```

NOTE for the implementer: check the real minimal `technique-seed.yaml` shape + `TechniqueSeed`/`PaperLink`/`role` enum values (read `src/radar/research_radar/entities.py` + `seed.py`) and fix the fixture if `load_technique_seed` rejects it — the assertions are the contract. Likewise adapt the domain/category/onprem_impact strings to real enum values if needed.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_technique_candidate_detect.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

Create `src/radar/discovery/technique_candidate_detect.py`:

```python
"""Derive upvote velocity + the emerging surface from paper-candidate observations.

Pure builder (``now`` a parameter) plus one guarded loader that reads the
committed store and drops now-tracked papers — a corrupt/absent store degrades
to an empty section, never a raise (mirror of model_candidate_detect).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from radar.storage.technique_candidate_log import TechniqueCandidateObservation


logger = logging.getLogger(__name__)

VELOCITY_WINDOW_DAYS = 7
NEW_WINDOW_DAYS = 14
EMERGING_LIMIT = 15


class TechniqueCandidateEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    arxiv_id: str
    name: str
    upvotes: int
    upvotes_per_day: float | None
    citation_count: int | None
    is_new: bool
    first_seen: str


def _upvotes_per_day(rows: list[TechniqueCandidateObservation], now: datetime) -> float | None:
    cutoff = now - timedelta(days=VELOCITY_WINDOW_DAYS)
    in_window = sorted((r for r in rows if r.observed_at >= cutoff),
                       key=lambda r: r.observed_at)
    if len(in_window) < 2:
        return None
    span = (in_window[-1].observed_at.date() - in_window[0].observed_at.date()).days
    if span <= 0:
        return None
    return round((in_window[-1].upvotes - in_window[0].upvotes) / span, 1)


def build_technique_candidates(
    observations: list[TechniqueCandidateObservation], now: datetime
) -> list[TechniqueCandidateEntry]:
    by_id: dict[str, list[TechniqueCandidateObservation]] = {}
    for obs in observations:
        by_id.setdefault(obs.arxiv_id, []).append(obs)
    entries: list[TechniqueCandidateEntry] = []
    for arxiv_id, rows in by_id.items():
        ordered = sorted(rows, key=lambda r: r.observed_at)
        latest = ordered[-1]
        first_seen = ordered[0].observed_at.date()
        entries.append(TechniqueCandidateEntry(
            arxiv_id=arxiv_id, name=latest.name, upvotes=latest.upvotes,
            upvotes_per_day=_upvotes_per_day(ordered, now),
            citation_count=latest.citation_count,
            is_new=first_seen >= (now - timedelta(days=NEW_WINDOW_DAYS)).date(),
            first_seen=first_seen.isoformat(),
        ))
    return sorted(entries, key=lambda e: (
        e.upvotes_per_day is None,
        -(e.upvotes_per_day if e.upvotes_per_day is not None else 0.0),
        -(e.citation_count or 0), e.arxiv_id,
    ))


def load_emerging_techniques(
    root: Path, now: datetime, *, limit: int = EMERGING_LIMIT
) -> list[TechniqueCandidateEntry]:
    """Guarded: emerging (untracked, still not in the seed) papers, capped. [] on any failure."""
    try:
        from radar.research_radar.seed import load_technique_seed
        from radar.storage.technique_candidate_log import load_technique_candidates

        root = Path(root)
        seed_path = root / "config" / "technique-seed.yaml"
        tracked = {p.arxiv_id for s in (load_technique_seed(seed_path) if seed_path.exists() else [])
                   for p in s.papers}
        entries = build_technique_candidates(
            load_technique_candidates(root / "data" / "technique-candidate-observations.jsonl"), now)
        return [e for e in entries if e.arxiv_id not in tracked][:limit]
    except Exception as exc:
        logger.warning("Emerging paper candidates unavailable under %s: %s", root, exc)
        return []
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_technique_candidate_detect.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Lint + typecheck + commit**

```bash
uv run ruff check src/radar/discovery/technique_candidate_detect.py tests/test_technique_candidate_detect.py && uv run mypy src/radar
git add src/radar/discovery/technique_candidate_detect.py tests/test_technique_candidate_detect.py
git commit -m "feat: paper-candidate upvote-velocity detection + guarded emerging gateway"
```

---

### Task 3: Sweep + `research candidates scan` CLI + CI

**Files:**
- Create: `src/radar/discovery/technique_candidate_sweep.py`
- Modify: `src/radar/cli.py` (a `candidates` sub-app under `research_app` with `scan`), `.github/workflows/publish.yml`
- Test: `tests/test_technique_candidate_sweep.py`, `tests/test_publish_workflow.py` (append)

**Interfaces:**
- Consumes: `discover_technique_candidates`, `discover_arxiv_candidates`, `enrich_proposals_with_velocity` (called as module attributes for monkeypatchability), `TechniqueCandidateObservation`, `load_technique_seed`, `append_technique_candidates`.
- Produces:
  - `async sweep_technique_candidates(seeds, client, now, *, days=7, min_upvotes=10, limit=20, contact_email=None) -> list[TechniqueCandidateObservation]` — mirror of `research discover`'s gather+dedup+enrich, then map each `TechniqueProposal` → `TechniqueCandidateObservation(arxiv_id, name, upvotes, citation_count, published, suggested_domain=p.suggested_domain.value, suggested_category=p.suggested_category.value, observed_at=now)`.
  - `radar research candidates scan [--root .]` — load the technique seed, httpx client, sweep, append to `data/technique-candidate-observations.jsonl`, print a one-line count.
  - publish.yml: `uv run radar research candidates scan --root .` after `radar research scan`; `git add -f data/technique-candidate-observations.jsonl || true` in the history-commit block.

- [ ] **Step 1: Write the failing tests (tests/test_technique_candidate_sweep.py)**

```python
"""Sweep untracked HF/arXiv paper candidates → observations (monkeypatched fetchers)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from radar.discovery import (
    arxiv_technique_candidates,
    hf_technique_candidates,
    technique_candidate_velocity,
)
from radar.discovery.technique_candidate_sweep import sweep_technique_candidates
from radar.discovery.technique_proposals import TechniqueProposal


NOW = datetime(2026, 7, 8, 7, 0, tzinfo=UTC)


def _proposal(arxiv: str, upvotes: int, via: str) -> TechniqueProposal:
    return TechniqueProposal(
        suggested_id=f"t-{arxiv}", name=f"Paper {arxiv}", arxiv_id=arxiv, published="2026-06-20",
        upvotes=upvotes, suggested_domain="reasoning", suggested_category="inference",
        matched_keyword="reasoning", discovered_via=via, citation_count=5, citations_per_day=1.0,
    )


@pytest.mark.asyncio
async def test_sweep_maps_and_dedups_hf_wins(monkeypatch):
    async def _hf(seeds, client, **kw):
        return [_proposal("2501.dup", 120, "hf-daily-papers"), _proposal("2501.hf", 80, "hf-daily-papers")]

    async def _arxiv(seeds, client, since, **kw):
        return [_proposal("2501.dup", 5, "arxiv"), _proposal("2501.ax", 0, "arxiv")]  # dup → HF wins

    async def _enrich(proposals, client, now, contact_email=None):
        return proposals  # citations already on the fixtures

    monkeypatch.setattr(hf_technique_candidates, "discover_technique_candidates", _hf)
    monkeypatch.setattr(arxiv_technique_candidates, "discover_arxiv_candidates", _arxiv)
    monkeypatch.setattr(technique_candidate_velocity, "enrich_proposals_with_velocity", _enrich)

    rows = await sweep_technique_candidates([], object(), NOW)

    by_id = {r.arxiv_id: r for r in rows}
    assert set(by_id) == {"2501.dup", "2501.hf", "2501.ax"}      # deduped
    assert by_id["2501.dup"].upvotes == 120                       # HF won the duplicate
    assert by_id["2501.hf"].observed_at == NOW
    assert by_id["2501.hf"].suggested_domain == "reasoning"


@pytest.mark.asyncio
async def test_sweep_fetch_failure_degrades_empty(monkeypatch):
    async def _boom(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(hf_technique_candidates, "discover_technique_candidates", _boom)
    monkeypatch.setattr(arxiv_technique_candidates, "discover_arxiv_candidates", _boom)
    # the sweep must not raise even if a fetcher does — mirror discover's best-effort intent
    rows = await sweep_technique_candidates([], object(), NOW)
    assert rows == []
```

NOTE for the implementer: check the real `TechniqueProposal` field requirements (read `src/radar/discovery/technique_proposals.py`) and the real `TechniqueDomain`/`Category` enum values — fix the fixture strings if validation rejects them. For the fetch-failure test to pass, `sweep_technique_candidates` must itself wrap the gather in a `try/except → []` (the real fetchers already degrade to `[]` internally, but the test monkeypatches them to raise, so the sweep needs its own guard to honor the best-effort contract — add one).

- [ ] **Step 2: Append the workflow test (tests/test_publish_workflow.py)**

```python
def test_publish_runs_paper_candidate_scan_and_commits_store():
    text = Path(".github/workflows/publish.yml").read_text(encoding="utf-8")
    research_idx = text.index("radar research scan")
    cand_idx = text.index("radar research candidates scan")
    export_idx = text.index("radar export")
    assert research_idx < cand_idx < export_idx
    assert "data/technique-candidate-observations.jsonl" in text
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_technique_candidate_sweep.py tests/test_publish_workflow.py -v -k "sweep or paper_candidate"`
Expected: FAIL — `ModuleNotFoundError` / substring not found

- [ ] **Step 4: Write the sweep**

Create `src/radar/discovery/technique_candidate_sweep.py`:

```python
"""Sweep untracked HF/arXiv paper candidates into observations.

Mirrors `research discover`'s gather+dedup+enrich (HF wins duplicates), then
stamps each with observed_at so upvote velocity can emerge across daily runs.
Best-effort: any fetch failure degrades to [] (the fetchers already degrade
internally; this outer guard honors the contract even if one raises).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from radar.discovery import (
    arxiv_technique_candidates,
    hf_technique_candidates,
    technique_candidate_velocity,
)
from radar.research_radar.entities import TechniqueSeed
from radar.storage.technique_candidate_log import TechniqueCandidateObservation


logger = logging.getLogger(__name__)


async def sweep_technique_candidates(
    seeds: list[TechniqueSeed],
    client: Any,
    now: datetime,
    *,
    days: int = 7,
    min_upvotes: int = 10,
    limit: int = 20,
    contact_email: str | None = None,
) -> list[TechniqueCandidateObservation]:
    try:
        gathered = await hf_technique_candidates.discover_technique_candidates(
            seeds, client, min_upvotes=min_upvotes, limit=limit)
        arxiv_found = await arxiv_technique_candidates.discover_arxiv_candidates(
            seeds, client, since=now - timedelta(days=days), limit=limit)
        seen = {p.arxiv_id for p in gathered}  # HF entries win duplicates
        gathered = [*gathered, *(p for p in arxiv_found if p.arxiv_id not in seen)]
        enriched = await technique_candidate_velocity.enrich_proposals_with_velocity(
            gathered, client, now=now, contact_email=contact_email)
    except Exception as exc:
        logger.warning("Paper-candidate sweep failed: %s", exc)
        return []
    return [
        TechniqueCandidateObservation(
            arxiv_id=p.arxiv_id, name=p.name, upvotes=p.upvotes,
            citation_count=p.citation_count, published=p.published,
            suggested_domain=p.suggested_domain.value,
            suggested_category=p.suggested_category.value, observed_at=now,
        )
        for p in enriched
    ]
```

- [ ] **Step 5: Add the CLI command**

In `src/radar/cli.py`, register a `candidates` sub-app under `research_app` and add `scan` (mirror `research_discover`'s seed-load + client + `os.environ` contact email):

```python
research_candidates_app = typer.Typer(help="Untracked paper-candidate discovery.", no_args_is_help=True)
research_app.add_typer(research_candidates_app, name="candidates")


@research_candidates_app.command("scan")
def research_candidates_scan(root: Path = typer.Option(Path("."), help="Project root.")) -> None:
    """Sweep untracked HF/arXiv paper candidates and append to the observation log."""
    import asyncio
    import os
    from datetime import UTC, datetime

    import httpx

    from radar.discovery.technique_candidate_sweep import sweep_technique_candidates
    from radar.research_radar.seed import load_technique_seed
    from radar.storage.technique_candidate_log import append_technique_candidates

    seed_path = root / "config" / "technique-seed.yaml"
    if not seed_path.exists():
        seed_path = Path(__file__).resolve().parents[2] / "config" / "technique-seed.yaml"
    seeds = load_technique_seed(seed_path)
    now = datetime.now(UTC)

    async def _run():
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            return await sweep_technique_candidates(
                seeds, client, now, contact_email=os.environ.get("RADAR_CONTACT_EMAIL"))

    observations = asyncio.run(_run())
    out_path = root / "data" / "technique-candidate-observations.jsonl"
    append_technique_candidates(out_path, observations)
    console.print(f"Observed {len(observations)} untracked paper candidate(s) "
                  f"→ {out_path.relative_to(root)}")
```

- [ ] **Step 6: Wire publish.yml**

After `uv run radar research scan --root .`, add:

```yaml
          uv run radar research candidates scan --root .
```

In the history-commit block, after `git add -f data/model-candidate-observations.jsonl || true`, add:

```yaml
          git add -f data/technique-candidate-observations.jsonl || true
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/test_technique_candidate_sweep.py tests/test_publish_workflow.py -v`
Expected: PASS

- [ ] **Step 8: Lint + typecheck + commit**

```bash
uv run ruff check src/radar tests/test_technique_candidate_sweep.py tests/test_publish_workflow.py && uv run mypy src/radar
git add src/radar/discovery/technique_candidate_sweep.py src/radar/cli.py .github/workflows/publish.yml \
  tests/test_technique_candidate_sweep.py tests/test_publish_workflow.py
git commit -m "feat: radar research candidates scan (daily untracked-paper sweep) + CI"
```

---

### Task 4: Live "Emerging" sub-section under Trending Techniques

**Files:**
- Modify: `src/radar/web/app.py`, `src/radar/web/templates/trending.html`
- Test: `tests/test_web.py` (append)

**Interfaces:**
- Consumes: `load_emerging_techniques` (Task 2).
- Produces: `/trending` passes `technique_candidates` (via a thin `_technique_candidates()` helper calling the guarded `load_emerging_techniques(root, datetime.now(UTC))`); `trending.html` renders the "Emerging — not yet tracked" sub-section within the Techniques area (`{% if kind == "technique" %}`), linking to `https://arxiv.org/abs/{{ c.arxiv_id }}`.

- [ ] **Step 1: Write the failing tests (append to tests/test_web.py)**

```python
def _seed_paper_candidates(root: Path) -> None:
    from datetime import UTC, datetime

    from radar.storage.technique_candidate_log import (TechniqueCandidateObservation,
                                                       append_technique_candidates)
    (root / "data").mkdir(parents=True, exist_ok=True)
    append_technique_candidates(root / "data" / "technique-candidate-observations.jsonl", [
        TechniqueCandidateObservation(arxiv_id="2501.9999", name="Hot Paper", upvotes=u,
                                      citation_count=3, published="2026-06-20",
                                      suggested_domain="reasoning", suggested_category="inference",
                                      observed_at=datetime(2026, 7, day, 7, 0, tzinfo=UTC))
        for day, u in ((1, 10), (4, 130))
    ])


def test_trending_shows_emerging_papers(tmp_path):
    _seed_paper_candidates(tmp_path)
    client = TestClient(create_app(tmp_path))

    r = client.get("/trending")

    assert r.status_code == 200
    assert "Hot Paper" in r.text
    assert 'href="https://arxiv.org/abs/2501.9999"' in r.text


def test_trending_emerging_papers_empty_survives(tmp_path):
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    client = TestClient(create_app(tmp_path))

    r = client.get("/trending")

    assert r.status_code == 200   # no store → empty sub-section, page still renders
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_web.py -v -k "emerging_paper"`
Expected: FAIL — Emerging papers not rendered

- [ ] **Step 3: Add the route wiring**

In `src/radar/web/app.py`, add a thin helper near `_model_candidates` (the Phase-2a one):

```python
    def _technique_candidates():
        from datetime import UTC, datetime

        from radar.discovery.technique_candidate_detect import load_emerging_techniques
        return load_emerging_techniques(root, datetime.now(UTC))
```

In the `/trending` route, pass it alongside `model_candidates`:

```python
            "technique_candidates": _technique_candidates(),
```

- [ ] **Step 4: Add the template sub-section**

In `src/radar/web/templates/trending.html`, inside the Models/Techniques loop, add the Techniques-side Emerging block guarded by `{% if kind == "technique" %}` (mirroring the existing `{% if kind == "model" %}` block; this exact snippet is reused byte-for-byte in the static template in Task 5 — arxiv links are absolute):

```html
      {% if kind == "technique" %}
      <h3>Emerging — not yet tracked</h3>
      {% if not technique_candidates %}<p>No emerging papers yet.</p>{% endif %}
      {% if technique_candidates %}
      <table>
        <thead><tr><th>Paper</th><th>Upvotes</th><th>Upvotes/day</th>
          <th>Citations</th><th></th><th>First seen</th></tr></thead>
        <tbody>
          {% for c in technique_candidates %}
          <tr>
            <td><a href="https://arxiv.org/abs/{{ c.arxiv_id }}">{{ c.name }}</a></td>
            <td>{{ c.upvotes }}</td>
            <td>{% if c.upvotes_per_day is not none %}{{ "%+.0f"|format(c.upvotes_per_day) }}{% else %}—{% endif %}</td>
            <td>{% if c.citation_count is not none %}{{ c.citation_count }}{% else %}—{% endif %}</td>
            <td>{% if c.is_new %}NEW{% endif %}</td>
            <td>{{ c.first_seen }}</td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
      {% endif %}
      {% endif %}
```

Place it symmetrically to the Phase-2a `{% if kind == "model" %}` Emerging block (read the current trending.html to match its position inside the loop).

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_web.py -v`
Expected: PASS (new + existing)

- [ ] **Step 6: Lint + typecheck + commit**

```bash
uv run ruff check src/radar/web tests/test_web.py && uv run mypy src/radar
git add src/radar/web/app.py src/radar/web/templates/trending.html tests/test_web.py
git commit -m "feat: /trending Emerging (untracked paper candidates) sub-section"
```

---

### Task 5: Static "Emerging" sub-section + export

**Files:**
- Modify: `src/radar/web/static_site.py`, `src/radar/web/templates/static_trending.html`, `src/radar/cli.py` (export)
- Test: `tests/test_static_site.py` (append)

**Interfaces:**
- Consumes: `TechniqueCandidateEntry` + `load_emerging_techniques` (Task 2).
- Produces: `render_static_site(..., technique_candidates: list[TechniqueCandidateEntry] | None = None)` renders the Emerging block in `static_trending.html`; `radar export` builds `technique_candidates` via `load_emerging_techniques(root, generated_at)` and threads it in.

- [ ] **Step 1: Write the failing tests (append to tests/test_static_site.py)**

```python
def test_static_site_renders_emerging_papers(tmp_path):
    from radar.discovery.technique_candidate_detect import TechniqueCandidateEntry

    cands = [TechniqueCandidateEntry(arxiv_id="2501.9999", name="Hot Paper", upvotes=130,
                                     upvotes_per_day=40.0, citation_count=3, is_new=True,
                                     first_seen="2026-07-01")]
    render_static_site([], tmp_path / "_site", datetime(2026, 7, 8, tzinfo=UTC),
                       technique_candidates=cands)
    page = (tmp_path / "_site" / "trending.html").read_text(encoding="utf-8")

    assert "Hot Paper" in page
    assert 'href="https://arxiv.org/abs/2501.9999"' in page


def test_static_site_emerging_papers_backcompat(tmp_path):
    render_static_site([], tmp_path / "_site", datetime(2026, 7, 8, tzinfo=UTC))
    assert (tmp_path / "_site" / "index.html").exists()   # no candidates → still renders
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_static_site.py -v -k "emerging_paper"`
Expected: FAIL — `TypeError` on `technique_candidates` kwarg

- [ ] **Step 3: Create the static template block**

In `src/radar/web/templates/static_trending.html`, add the SAME Emerging-under-Techniques block from Task 4 (byte-for-byte — it references `technique_candidates` + arxiv absolute links only, no live-vs-static difference), placed symmetrically to the existing `{% if kind == "model" %}` block.

- [ ] **Step 4: Wire static_site.py**

In `src/radar/web/static_site.py`: import `from radar.discovery.technique_candidate_detect import TechniqueCandidateEntry`; add a param `technique_candidates: list[TechniqueCandidateEntry] | None = None`; pass it into the `static_trending.html` render context (next to `model_candidates`); extend the `trending.html` write-guard to also fire on `technique_candidates` (`if trending_entries or model_hub or technique_hub or model_candidates or technique_candidates:`).

- [ ] **Step 5: Wire the export CLI**

In `src/radar/cli.py` `export`, near the `_model_candidates` build:

```python
    from radar.discovery.technique_candidate_detect import load_emerging_techniques

    _technique_candidates = load_emerging_techniques(root, generated_at)
```

and thread into `render_static_site(...)`: `technique_candidates=_technique_candidates or None`. (`generated_at` is the export's datetime var.)

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_static_site.py tests/test_web.py tests/test_cli.py -v`
Expected: PASS (new + existing; back-compat proves no-candidate exports unchanged)

- [ ] **Step 7: Lint + typecheck + commit**

```bash
uv run ruff check src/radar tests/test_static_site.py && uv run mypy src/radar
git add src/radar/web/static_site.py src/radar/web/templates/static_trending.html \
  src/radar/cli.py tests/test_static_site.py
git commit -m "feat: static export Emerging paper-candidates sub-section"
```

---

### Task 6: README + CHANGELOG + full gates

**Files:**
- Modify: `README.md`, `CHANGELOG.md`
- Test: the full suite

- [ ] **Step 1: README**

Extend the 📈 Trending radar Highlights bullet with a closing sentence:

```markdown
 …and **emerging papers** — untracked hot arXiv/HF papers observed over time in `data/technique-candidate-observations.jsonl`, ranked by HF-upvote velocity — round out the hub; papers stay human-reviewed (no auto-add), surfaced for a person to promote.
```

- [ ] **Step 2: CHANGELOG**

Under `## [Unreleased]` → `### Added`, at the top:

```markdown
- **Untracked paper candidate discovery** — a daily `radar research candidates
  scan` records untracked hot arXiv/HF papers (via the existing candidate
  fetchers) into a committed `data/technique-candidate-observations.jsonl`;
  `/trending` shows them in an "Emerging — not yet tracked" sub-section under
  Trending Techniques, ranked by HF-upvote velocity (citations shown as
  secondary), linking to arxiv.org. Papers stay human-gated — no promotion
  gate; the surface just makes emerging work visible for review. Guarded reads
  keep a corrupt store from breaking `/trending` or the export. (Trending hub
  Phase 2b — this completes the models + papers hub.)
```

- [ ] **Step 3: Full gates**

Run: `uv run pytest && uv run ruff check . && uv run mypy src/radar`
Expected: all pass, coverage ≥ 80%, ruff + mypy clean. Fix anything failing (implementation, not tests, unless a test is genuinely wrong).

- [ ] **Step 4: Commit**

```bash
git add README.md CHANGELOG.md
git commit -m "docs: untracked paper candidate discovery (trending hub Phase 2b)"
```

---

## Self-Review Notes (already applied)

- Spec coverage: observation store + naive→UTC validator (T1); pure upvote-velocity detection + guarded `load_emerging_techniques` with tracked-filter + cap (T2); daily sweep reusing both fetchers + dedup HF-wins + enrich + CLI + CI (T3); Emerging surface live (T4) + static (T5); docs (T6). No promote-gate task — techniques human-gated (spec §Non-goals).
- Guarded/daily-publish invariant: hardened loader + `observed_at` validator baked in from the start (T1); `load_emerging_techniques` wraps load+build+filter in `try/except → []` (T2); the sweep's own `try/except → []` honors best-effort even if a monkeypatched fetcher raises (T3); route + export both use the guarded gateway (T4/T5).
- No live/static divergence: emerging rows use absolute `arxiv.org` URLs, so the Task-4 and Task-5 template snippets are identical (like Phase 2a's HF-linked models block).
- Ranking: upvote velocity primary (None last), citation_count secondary tiebreak, arxiv_id final — matches the spec's "upvotes primary, citations secondary".
- Type consistency: `TechniqueCandidateObservation` (T1) → detect/sweep/surface; `TechniqueCandidateEntry`/`build_technique_candidates`/`load_emerging_techniques` (T2) → T4/T5; `sweep_technique_candidates` (T3); `technique_candidates` template var identical in `trending.html` (T4) and `static_trending.html` (T5); the CLI sub-app is `research_candidates_app` (distinct from Phase 2a's models `candidates_app`).
