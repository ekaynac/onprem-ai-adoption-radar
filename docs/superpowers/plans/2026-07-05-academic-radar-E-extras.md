# Academic Research Radar — Plan E (Discovery Extras + Hardening) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the spec-deferred discovery extras — an arXiv category sweep, citation-velocity signals on proposals, and a minimal track-record view — and land the hardening ticket: one guarded loader so research data can structurally never break any surface.

**Architecture:** (1) `load_technique_entries(root)` becomes the single guarded gateway for reading research runs ([] on ANY failure); all five call sites (web app, CLI export, CLI list/show helper, orchestrator pedigree, both MCP services) swap to it. (2) A second candidate source, `discover_arxiv_candidates` (arXiv API listing sweep over the AI categories, keyword-gated with the existing `KEYWORD_MAP`), joins the HF source behind `radar research discover --source hf|arxiv|all`. (3) Proposals gain `discovered_via`/`citation_count`/`citations_per_day` — velocity is approximated deterministically as citations ÷ days-since-published from a single S2 observation (best-effort batch via the existing `fetch_citations`), and ranking prefers velocity so arXiv candidates (which have no upvotes) compete fairly. (4) `radar research track-record` reports the honest, computable-today lag table (canonical-paper date → first radar flag → current ring); flag-to-implementation hit-rate explicitly stays deferred until history accumulates.

**Tech Stack:** Python 3.12, feedparser + httpx (in-tree), pytest + ruff + mypy. **No new dependencies.**

**Spec:** `docs/superpowers/specs/2026-07-03-academic-research-radar-design.md` §9 Discovery bullet (deferred items) + the Plan-C final-review hardening recommendation.

## Global Constraints

- Discovery stays human-gated: proposals file only, never auto-added.
- The guarded loader replaces EVERY `TechniqueEntry.model_validate(...)`-over-run-data call site; after this plan, `grep -rn "model_validate" src/radar | grep -i technique` outside `technique_queries.py`/tests must come up empty for run-data reads (seed loading is separate and stays fail-loud).
- Velocity is a single-observation proxy (citations ÷ days since published), deterministic given fetched counts; enrichment is best-effort and never fails discover; `now` is passed in for testability (never `datetime.now()` inside library code).
- Everything degrades: arXiv sweep failure → [] + warning; enrichment failure → proposals unchanged; corrupt research run → [] from the loader with one warning.
- ruff line-length 100; `from __future__ import annotations`; gates `uv run pytest` (≥80%), `uv run ruff check .`, `uv run mypy src/radar`; `git add` specific paths only (unrelated modified `data/history.jsonl` never committed).
- Existing symbols consumed: `_latest_technique_cards`, `TechniqueEntry`, `KEYWORD_MAP`/`match_keyword` (`discovery/hf_technique_candidates.py`), `TechniqueProposal`/`write_technique_proposals` (`discovery/technique_proposals.py`), `fetch_citations` (`research_radar/citations.py`), `get_with_retry`, `ARXIV_API_URL`/`ARXIV_CATEGORIES` (`enrichment/arxiv.py`), `load_technique_events`, `load_technique_seed`, `project_slug`.

## File Structure

```
src/radar/mcp_server/technique_queries.py       # MODIFY: + load_technique_entries (guarded gateway)
src/radar/web/app.py                            # MODIFY: swap loader; simplify _technique_hrefs
src/radar/cli.py                                # MODIFY: swap loader (export + _latest_technique_entries);
                                                #   discover gains --source/merge/enrich; + track-record cmd
src/radar/orchestrator.py                       # MODIFY: _attach_pedigree uses loader
src/radar/mcp_server/queries.py                 # MODIFY: _project_techniques uses loader
src/radar/mcp_server/model_queries.py           # MODIFY: _model_techniques uses loader
src/radar/discovery/arxiv_technique_candidates.py   # NEW: category-sweep source
src/radar/discovery/technique_candidate_velocity.py # NEW: citations/day enrichment + ranking
src/radar/discovery/technique_proposals.py      # MODIFY: + discovered_via/citation_count/citations_per_day
src/radar/research_radar/track_record.py        # NEW: lag rows (paper date → first flag)
tests/test_technique_queries.py, tests/test_web.py, tests/test_cli.py  # MODIFY (loader/corrupt-run)
tests/test_arxiv_technique_candidates.py        # NEW
tests/test_technique_candidate_velocity.py      # NEW
tests/test_research_cli.py                      # MODIFY: discover --source/enrich; track-record
tests/test_track_record.py                      # NEW
README.md, CHANGELOG.md, docs/superpowers/specs/2026-07-03-academic-research-radar-design.md  # MODIFY
```

Out of scope: flag-to-implementation hit-rate (needs months of accumulated history — the track-record command prints this caveat); spike detection requiring two observations of untracked papers (the single-shot citations/day proxy is the deliberate design); per-item salvage in the guarded loader (whole-run [] on corruption is the contract — simple and sufficient).

---

### Task 1: Guarded loader + swap all call sites (the hardening ticket)

**Files:**
- Modify: `src/radar/mcp_server/technique_queries.py`, `src/radar/web/app.py`, `src/radar/cli.py` (export + `_latest_technique_entries`), `src/radar/orchestrator.py` (`_attach_pedigree`), `src/radar/mcp_server/queries.py` (`_project_techniques`), `src/radar/mcp_server/model_queries.py` (`_model_techniques`)
- Test: `tests/test_technique_queries.py`, `tests/test_web.py`, `tests/test_cli.py` (append)

**Interfaces:**
- Produces: `load_technique_entries(root: Path) -> list[TechniqueEntry]` in `technique_queries.py` — validated entries from the latest research run; `[]` on ANY failure (missing run, unreadable JSON, schema drift) with ONE `logger.warning`. `TechniqueQueryService._entries` delegates to it. Every other call site swaps its `[TechniqueEntry.model_validate(c) for c in _latest_technique_cards(...)]` for the loader (keeping their outer guards where they also do other fallible work). `app.py`'s `_technique_hrefs` drops its now-dead try/except (the loader cannot raise).
- `cli.py` `_latest_technique_entries` keeps its `None`-when-empty contract: `entries = load_technique_entries(root); return entries or None`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_technique_queries.py`:

```python
def test_load_technique_entries_guards_corrupt_run(tmp_path):
    from radar.mcp_server.technique_queries import load_technique_entries

    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    store = RunStore(tmp_path / "data" / "runs")
    run_id = store.create_run()
    store.update_meta(run_id, {"kind": "research"})
    store.save_stage(run_id, "technique_cards", [{"bogus": True}])

    assert load_technique_entries(tmp_path) == []


def test_load_technique_entries_returns_validated_entries(tmp_path):
    from radar.mcp_server.technique_queries import load_technique_entries

    _seed_research_run(tmp_path, [_entry("qlora", Ring.WATCH, TechniqueDomain.FINE_TUNING)])

    entries = load_technique_entries(tmp_path)

    assert [e.id for e in entries] == ["qlora"]
    assert entries[0].ring == Ring.WATCH
```

Append to `tests/test_web.py` (the corrupt-run seeding pattern already exists in `test_project_page_survives_corrupt_research_run` — reuse its style):

```python
def _seed_corrupt_research_run(root: Path) -> None:
    from radar.storage.run_store import RunStore as _RS

    (root / "data").mkdir(parents=True, exist_ok=True)
    store = _RS(root / "data" / "runs")
    run_id = store.create_run()
    store.update_meta(run_id, {"kind": "research"})
    store.save_stage(run_id, "technique_cards", [{"bogus": True}])


def test_index_survives_corrupt_research_run(tmp_path: Path):
    db = RadarDatabase(tmp_path / "data" / "radar.db")
    db.initialize()
    _seed_corrupt_research_run(tmp_path)

    response = TestClient(create_app(tmp_path)).get("/")

    assert response.status_code == 200
    assert "Research:" not in response.text  # banner absent, not broken


def test_research_page_survives_corrupt_research_run(tmp_path: Path):
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    _seed_corrupt_research_run(tmp_path)

    response = TestClient(create_app(tmp_path)).get("/research")

    assert response.status_code == 200
    assert "No research scan yet" in response.text


def test_technique_page_corrupt_run_is_404_not_500(tmp_path: Path):
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    _seed_corrupt_research_run(tmp_path)

    assert TestClient(create_app(tmp_path)).get("/technique/anything").status_code == 404
```

Append to `tests/test_cli.py`:

```python
def test_export_survives_corrupt_research_run(tmp_path):
    from radar.storage.run_store import RunStore

    runner = CliRunner()
    runner.invoke(app, ["init", "--root", str(tmp_path)])
    store = RunStore(tmp_path / "data" / "runs")
    run_id = store.create_run()
    store.update_meta(run_id, {"kind": "research"})
    store.save_stage(run_id, "technique_cards", [{"bogus": True}])

    result = runner.invoke(app, ["export", "--root", str(tmp_path),
                                 "--out", str(tmp_path / "_site")])

    assert result.exit_code == 0
    assert (tmp_path / "_site" / "index.html").exists()
    assert not (tmp_path / "_site" / "techniques.html").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_technique_queries.py tests/test_web.py tests/test_cli.py -v -k corrupt`
Expected: FAIL — `ImportError` for the loader; index/export corrupt-run tests error (500 / exit 1)

- [ ] **Step 3: Implement the loader**

In `src/radar/mcp_server/technique_queries.py` add (with `import logging` + module `logger` if absent, and the `TechniqueEntry` import which already exists):

```python
def load_technique_entries(root: Path) -> list[TechniqueEntry]:
    """Validated entries from the latest research run; [] on ANY failure.

    The single guarded gateway for research-run data: a corrupt or
    schema-drifted technique_cards.json can never break a tool, model, or web
    surface — consumers see "no research data" instead of an exception.
    """
    try:
        return [TechniqueEntry.model_validate(c) for c in _latest_technique_cards(root)]
    except Exception as exc:
        logger.warning("Research run unreadable under %s: %s", root, exc)
        return []
```

Change `TechniqueQueryService._entries` to `return load_technique_entries(self.root)`.

- [ ] **Step 4: Swap every call site**

- `src/radar/web/app.py`: `_technique_entries` body → `return load_technique_entries(root)` (import the loader; drop the now-unused `_latest_technique_cards`/`TechniqueEntry` imports if nothing else uses them). `_technique_hrefs` drops its try/except (dead code once the loader cannot raise) — keep the dict comprehension. `_project_pedigree`/`_model_pedigree` keep their outer try/except (they also load config) but read entries via `_technique_entries()` as they already do.
- `src/radar/cli.py` export: `technique_entries = load_technique_entries(root)` (drop the local `_latest_technique_cards`/`TechniqueEntry` import lines for this block).
- `src/radar/cli.py` `_latest_technique_entries`: body → `from radar.mcp_server.technique_queries import load_technique_entries` / `entries = load_technique_entries(root)` / `return entries or None`.
- `src/radar/orchestrator.py` `_attach_pedigree`: replace the two-line validate comprehension with `entries = load_technique_entries(self.root)` (import inside the method next to the other local imports; keep the outer try/except).
- `src/radar/mcp_server/queries.py` `_project_techniques` and `src/radar/mcp_server/model_queries.py` `_model_techniques`: same swap (keep outer guards).

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_technique_queries.py tests/test_web.py tests/test_cli.py tests/test_orchestrator.py tests/test_mcp_queries.py tests/test_model_queries.py tests/test_research_cli.py -q`
Expected: PASS (new + all existing consumers)

- [ ] **Step 6: Verify the structural claim, lint, commit**

Run: `grep -rn "TechniqueEntry.model_validate" src/radar | grep -v technique_queries.py` — expected: no run-data call sites remain (seed/pipeline construction sites don't use `model_validate` over run payloads; anything left must be justified in the commit message).

```bash
uv run ruff check src/radar tests && uv run mypy src/radar
git add src/radar/mcp_server/technique_queries.py src/radar/web/app.py src/radar/cli.py \
  src/radar/orchestrator.py src/radar/mcp_server/queries.py src/radar/mcp_server/model_queries.py \
  tests/test_technique_queries.py tests/test_web.py tests/test_cli.py
git commit -m "refactor: single guarded loader for research-run data (hardening)"
```

---

### Task 2: arXiv category-sweep candidate source

**Files:**
- Create: `src/radar/discovery/arxiv_technique_candidates.py`
- Test: `tests/test_arxiv_technique_candidates.py`

**Interfaces:**
- Consumes: `ARXIV_API_URL`, `ARXIV_CATEGORIES` (`radar.enrichment.arxiv`), `get_with_retry`, `feedparser`, `match_keyword` (`radar.discovery.hf_technique_candidates`), `TechniqueProposal`, `TechniqueSeed`, `project_slug`.
- Produces: `async discover_arxiv_candidates(seeds: list[TechniqueSeed], client: Any, since: datetime, limit: int = 20) -> list[TechniqueProposal]` — queries the arXiv API (`search_query` = the OR of `cat:` over `ARXIV_CATEGORIES`, `sortBy=submittedDate`, `sortOrder=descending`, `max_results=100`), keeps entries published on/after `since`, keyword-gates titles via `match_keyword` (no triage fallback), dedups vs seed papers/ids and within-batch, and returns proposals with `upvotes=0`, `discovered_via="arxiv-sweep"`, `published=YYYY-MM-DD`. Any failure → `logger.warning` + `[]`. The arXiv id is extracted from `entry.id` (e.g. `http://arxiv.org/abs/2501.12345v2` → `2501.12345`).

- [ ] **Step 1: Write the failing tests**

```python
"""arXiv category sweep → keyword-gated technique candidates."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from radar.discovery.arxiv_technique_candidates import discover_arxiv_candidates


FEED_XML = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2607.01111v1</id>
    <title>Blazing Fast KV Cache Inference</title>
    <published>2026-07-02T00:00:00Z</published>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2607.02222v2</id>
    <title>A Dataset of Cats</title>
    <published>2026-07-02T00:00:00Z</published>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2606.03333v1</id>
    <title>Old Agent Planning Paper</title>
    <published>2026-06-01T00:00:00Z</published>
  </entry>
</feed>"""


class _Response:
    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.status_code = status_code
        self.headers: dict[str, str] = {}

    def raise_for_status(self):
        return None


class _Client:
    def __init__(self, text: str | None = FEED_XML, fail: bool = False):
        self._text = text
        self._fail = fail
        self.params: dict | None = None

    async def get(self, url, **kwargs):
        if self._fail:
            raise RuntimeError("arXiv down")
        self.params = kwargs.get("params")
        return _Response(self._text or "")


SINCE = datetime(2026, 6, 28, tzinfo=UTC)


@pytest.mark.asyncio
async def test_sweep_keyword_gates_and_respects_since():
    client = _Client()

    proposals = await discover_arxiv_candidates([], client, since=SINCE)

    assert [p.arxiv_id for p in proposals] == ["2607.01111"]  # cats dropped, old dropped
    proposal = proposals[0]
    assert proposal.discovered_via == "arxiv-sweep"
    assert proposal.upvotes == 0
    assert proposal.published == "2026-07-02"
    assert proposal.suggested_id == "blazing-fast-kv-cache-inference"
    assert "sortBy" in (client.params or {})


@pytest.mark.asyncio
async def test_sweep_dedups_against_seeds():
    from radar.models import Category
    from radar.research_radar.entities import (
        OnPremImpact,
        PaperLink,
        TechniqueDomain,
        TechniqueSeed,
    )

    seed = TechniqueSeed(
        id="kv-cache-quantization", name="x", category=Category.MODEL_SERVING,
        domain=TechniqueDomain.INFERENCE, onprem_impact=OnPremImpact.REDUCES_MEMORY,
        papers=[PaperLink(arxiv_id="2607.01111", title="t")],
    )

    proposals = await discover_arxiv_candidates([seed], _Client(), since=SINCE)

    assert proposals == []


@pytest.mark.asyncio
async def test_sweep_degrades_on_failure():
    assert await discover_arxiv_candidates([], _Client(fail=True), since=SINCE) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_arxiv_technique_candidates.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

Create `src/radar/discovery/arxiv_technique_candidates.py`:

```python
"""Discover candidate techniques from a recent arXiv category sweep.

Same keyword gate as the HF daily-papers source (no triage fallback — raw
arXiv listings are far noisier than HF's curated feed, so unmatched titles
are dropped). arXiv has no popularity signal; candidates carry upvotes=0 and
rely on the citations/day enrichment for ranking. Failures degrade to "no
proposals". Human-gated like every discovery source.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any

import feedparser
from dateutil import parser as date_parser

from radar.discovery.hf_technique_candidates import match_keyword
from radar.discovery.technique_proposals import TechniqueProposal
from radar.enrichment.arxiv import ARXIV_API_URL, ARXIV_CATEGORIES
from radar.enrichment.retry import get_with_retry
from radar.research_radar.entities import TechniqueSeed
from radar.web.slugs import project_slug


logger = logging.getLogger(__name__)

_ABS_ID_RE = re.compile(r"arxiv\.org/abs/(\d{4}\.\d{4,5})")
_SWEEP_MAX_RESULTS = 100


async def discover_arxiv_candidates(
    seeds: list[TechniqueSeed],
    client: Any,
    since: datetime,
    limit: int = 20,
) -> list[TechniqueProposal]:
    known_arxiv = {p.arxiv_id for s in seeds for p in s.papers}
    known_ids = {s.id for s in seeds}
    try:
        cats = " OR ".join(f"cat:{c}" for c in ARXIV_CATEGORIES)
        response = await get_with_retry(
            client,
            ARXIV_API_URL,
            label="arxiv-sweep",
            params={
                "search_query": cats,
                "sortBy": "submittedDate",
                "sortOrder": "descending",
                "start": 0,
                "max_results": _SWEEP_MAX_RESULTS,
            },
            follow_redirects=True,
        )
        entries = feedparser.parse(response.text).entries
    except Exception as exc:
        logger.warning("arXiv sweep failed: %s", exc)
        return []

    by_arxiv: dict[str, TechniqueProposal] = {}
    for entry in entries:
        match = _ABS_ID_RE.search(entry.get("id") or "")
        title = (entry.get("title") or "").strip().replace("\n", " ")
        published = _published(entry)
        if not match or not title or published is None or published < since:
            continue
        arxiv_id = match.group(1)
        if arxiv_id in known_arxiv or arxiv_id in by_arxiv:
            continue
        matched = match_keyword(title)
        if matched is None:
            continue
        suggested_id = project_slug(title)
        if suggested_id in known_ids:
            continue
        keyword, domain, category = matched
        by_arxiv[arxiv_id] = TechniqueProposal(
            suggested_id=suggested_id, name=title, arxiv_id=arxiv_id,
            published=published.date().isoformat(), upvotes=0,
            suggested_domain=domain, suggested_category=category,
            matched_keyword=keyword, discovered_via="arxiv-sweep",
        )
    return list(by_arxiv.values())[:limit]


def _published(entry: Any) -> datetime | None:
    raw = entry.get("published") or entry.get("updated")
    if not raw:
        return None
    try:
        parsed = date_parser.parse(raw)
    except (ValueError, OverflowError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
```

NOTE: this imports `discovered_via` on `TechniqueProposal`, which Task 3 adds — implement Tasks 2 and 3's schema change in whichever order keeps tests green; if you hit the missing field here, add the three schema fields from Task 3's Step 3 first (they are backward-compatible defaults) and note it in your report.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_arxiv_technique_candidates.py tests/test_technique_proposals.py -v`
Expected: PASS

- [ ] **Step 5: Lint + typecheck + commit**

```bash
uv run ruff check src/radar/discovery tests/test_arxiv_technique_candidates.py && uv run mypy src/radar
git add src/radar/discovery/arxiv_technique_candidates.py tests/test_arxiv_technique_candidates.py \
  src/radar/discovery/technique_proposals.py
git commit -m "feat: arXiv category-sweep technique candidates"
```

(Include `technique_proposals.py` only if you had to add the schema fields here per the NOTE.)

---

### Task 3: Citation-velocity enrichment + ranking

**Files:**
- Modify: `src/radar/discovery/technique_proposals.py` (3 new fields, if not already added in Task 2)
- Create: `src/radar/discovery/technique_candidate_velocity.py`
- Test: `tests/test_technique_candidate_velocity.py`

**Interfaces:**
- `TechniqueProposal` gains: `discovered_via: str = "hf-daily-papers"`, `citation_count: int | None = None`, `citations_per_day: float | None = None` (defaults keep all existing constructors/tests valid).
- Produces `async enrich_proposals_with_velocity(proposals: list[TechniqueProposal], client: Any, now: datetime, contact_email: str | None = None) -> list[TechniqueProposal]` — batch-fetches citations via `fetch_citations` (best-effort: failure → proposals returned unchanged), computes `citations_per_day = round(citation_count / max(days_since_published, 1), 2)` (needs `published`; `YYYY-MM` treated as the 1st; unparseable/missing → count only, velocity None), returns NEW proposal objects (`model_copy`). And `rank_proposals(proposals) -> list[TechniqueProposal]` — sorted by `citations_per_day` desc (None last), then `upvotes` desc, then `arxiv_id` for determinism.

- [ ] **Step 1: Write the failing tests**

```python
"""Citations/day enrichment for discovery proposals (single-shot velocity proxy)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from radar.discovery.technique_candidate_velocity import (
    enrich_proposals_with_velocity,
    rank_proposals,
)
from radar.discovery.technique_proposals import TechniqueProposal
from radar.models import Category
from radar.research_radar.entities import TechniqueDomain


NOW = datetime(2026, 7, 5, tzinfo=UTC)


def _proposal(arxiv_id: str, published: str | None, upvotes: int = 0) -> TechniqueProposal:
    return TechniqueProposal(
        suggested_id=f"t-{arxiv_id.replace('.', '-')}", name="T", arxiv_id=arxiv_id,
        published=published, upvotes=upvotes,
        suggested_domain=TechniqueDomain.INFERENCE,
        suggested_category=Category.MODEL_SERVING, matched_keyword="inference",
    )


class _FetchOK:
    """Patch target double for fetch_citations."""


@pytest.mark.asyncio
async def test_enrich_computes_citations_per_day(monkeypatch):
    from radar.research_radar.citations import CitationRecord

    async def _fake_fetch(arxiv_ids, client, contact_email=None):
        return {"2606.00001": CitationRecord(
            arxiv_id="2606.00001", citation_count=50, source="s2")}

    monkeypatch.setattr(
        "radar.discovery.technique_candidate_velocity.fetch_citations", _fake_fetch,
    )
    proposals = [_proposal("2606.00001", "2026-06-25")]  # 10 days before NOW

    enriched = await enrich_proposals_with_velocity(proposals, client=None, now=NOW)

    assert enriched[0].citation_count == 50
    assert enriched[0].citations_per_day == 5.0
    assert proposals[0].citation_count is None  # originals untouched (immutability)


@pytest.mark.asyncio
async def test_enrich_month_precision_and_missing_dates(monkeypatch):
    from radar.research_radar.citations import CitationRecord

    async def _fake_fetch(arxiv_ids, client, contact_email=None):
        return {
            "2606.00002": CitationRecord(arxiv_id="2606.00002", citation_count=34,
                                         source="s2"),
            "2606.00003": CitationRecord(arxiv_id="2606.00003", citation_count=7,
                                         source="s2"),
        }

    monkeypatch.setattr(
        "radar.discovery.technique_candidate_velocity.fetch_citations", _fake_fetch,
    )
    proposals = [_proposal("2606.00002", "2026-06"),   # treated as 2026-06-01 → 34 days
                 _proposal("2606.00003", None)]        # no date → velocity None

    enriched = await enrich_proposals_with_velocity(proposals, client=None, now=NOW)

    assert enriched[0].citations_per_day == 1.0
    assert enriched[1].citation_count == 7
    assert enriched[1].citations_per_day is None


@pytest.mark.asyncio
async def test_enrich_degrades_when_fetch_fails(monkeypatch):
    async def _boom(arxiv_ids, client, contact_email=None):
        raise RuntimeError("apis down")

    monkeypatch.setattr(
        "radar.discovery.technique_candidate_velocity.fetch_citations", _boom,
    )
    proposals = [_proposal("2606.00004", "2026-06-25", upvotes=9)]

    enriched = await enrich_proposals_with_velocity(proposals, client=None, now=NOW)

    assert enriched == proposals  # unchanged, no raise


def test_rank_velocity_first_then_upvotes_then_id():
    a = _proposal("2606.00005", "2026-06-25", upvotes=100)
    b = _proposal("2606.00006", "2026-06-25", upvotes=1).model_copy(
        update={"citations_per_day": 9.9, "citation_count": 99})
    c = _proposal("2606.00007", "2026-06-25", upvotes=100)

    ranked = rank_proposals([a, b, c])

    assert ranked[0].arxiv_id == "2606.00006"          # velocity wins
    assert [p.arxiv_id for p in ranked[1:]] == ["2606.00005", "2606.00007"]  # id tiebreak
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_technique_candidate_velocity.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

Add to `TechniqueProposal` in `src/radar/discovery/technique_proposals.py` (after `matched_keyword`) — skip if Task 2 already added them:

```python
    discovered_via: str = "hf-daily-papers"
    citation_count: int | None = None
    citations_per_day: float | None = None
```

Create `src/radar/discovery/technique_candidate_velocity.py`:

```python
"""Citations/day enrichment for discovery proposals.

A deterministic single-observation velocity proxy: citations ÷ days since
publication. Real spike detection needs two observations over time of papers
we do not track; this proxy ranks fresh-but-already-cited papers first, which
is the actionable part of "citation-velocity spikes" for a human reviewer.
Best-effort: enrichment failure returns the proposals unchanged.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from radar.discovery.technique_proposals import TechniqueProposal
from radar.research_radar.citations import fetch_citations


logger = logging.getLogger(__name__)


async def enrich_proposals_with_velocity(
    proposals: list[TechniqueProposal],
    client: Any,
    now: datetime,
    contact_email: str | None = None,
) -> list[TechniqueProposal]:
    if not proposals:
        return []
    try:
        records = await fetch_citations(
            [p.arxiv_id for p in proposals], client, contact_email
        )
    except Exception as exc:  # fetch_citations already degrades; belt and braces
        logger.warning("Velocity enrichment failed: %s", exc)
        return proposals
    if not records:
        return proposals
    enriched: list[TechniqueProposal] = []
    for proposal in proposals:
        record = records.get(proposal.arxiv_id)
        if record is None:
            enriched.append(proposal)
            continue
        enriched.append(proposal.model_copy(update={
            "citation_count": record.citation_count,
            "citations_per_day": _velocity(record.citation_count, proposal.published, now),
        }))
    return enriched


def rank_proposals(proposals: list[TechniqueProposal]) -> list[TechniqueProposal]:
    """Velocity desc (unknown last), then upvotes desc, then arxiv_id."""
    return sorted(proposals, key=lambda p: (
        -(p.citations_per_day if p.citations_per_day is not None else -1.0),
        -p.upvotes,
        p.arxiv_id,
    ))


def _velocity(count: int, published: str | None, now: datetime) -> float | None:
    if not published:
        return None
    normalized = f"{published}-01" if len(published) == 7 else published
    try:
        start = datetime.fromisoformat(normalized).replace(tzinfo=UTC)
    except ValueError:
        return None
    days = max((now - start).days, 1)
    return round(count / days, 2)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_technique_candidate_velocity.py tests/test_technique_proposals.py tests/test_hf_technique_candidates.py -v`
Expected: PASS (new + existing proposal/candidate tests unaffected by the added defaults)

- [ ] **Step 5: Lint + typecheck + commit**

```bash
uv run ruff check src/radar/discovery tests/test_technique_candidate_velocity.py && uv run mypy src/radar
git add src/radar/discovery/technique_candidate_velocity.py src/radar/discovery/technique_proposals.py \
  tests/test_technique_candidate_velocity.py
git commit -m "feat: citations-per-day velocity on discovery proposals"
```

---

### Task 4: `research discover` gains --source, merge, and velocity ranking

**Files:**
- Modify: `src/radar/cli.py` (`research_discover`)
- Test: `tests/test_research_cli.py` (modify the two existing discover tests + add)

**Interfaces:**
- `radar research discover [--source all|hf|arxiv] [--days 7] [--min-upvotes 10] [--limit 20]`:
  - `hf` → HF candidates only; `arxiv` → sweep only (`since = now - days`); `all` (default) → both, merged with within-run dedup by `arxiv_id` (HF entry wins — it carries upvotes).
  - After gathering: `enrich_proposals_with_velocity(..., now=datetime.now(UTC), contact_email=os.environ.get("RADAR_CONTACT_EMAIL"))`, then `rank_proposals`, then cap at `--limit`, then write (still unconditionally, empty included).
  - All three network functions imported via their modules (monkeypatch-friendly): `hf_technique_candidates.discover_technique_candidates`, `arxiv_technique_candidates.discover_arxiv_candidates`, `technique_candidate_velocity.enrich_proposals_with_velocity` (module-level import of the velocity module too).
- The two existing discover tests are UPDATED to patch the arxiv + velocity functions as well (identity enrichment), keeping their assertions unchanged.

- [ ] **Step 1: Update + write the failing tests**

In `tests/test_research_cli.py`, add a helper near the discover tests and update both existing discover tests to use it:

```python
def _patch_discover_network(monkeypatch, hf_result=None, arxiv_result=None):
    async def _hf(seeds, client, min_upvotes=10, limit=20):
        return list(hf_result or [])

    async def _arxiv(seeds, client, since, limit=20):
        return list(arxiv_result or [])

    async def _identity_enrich(proposals, client, now, contact_email=None):
        return proposals

    monkeypatch.setattr(
        "radar.discovery.hf_technique_candidates.discover_technique_candidates", _hf)
    monkeypatch.setattr(
        "radar.discovery.arxiv_technique_candidates.discover_arxiv_candidates", _arxiv)
    monkeypatch.setattr(
        "radar.discovery.technique_candidate_velocity.enrich_proposals_with_velocity",
        _identity_enrich)
```

(Update `test_research_discover_writes_proposals`, `test_research_discover_no_candidates_message`, and `test_research_discover_empty_run_clears_stale_proposals` to call `_patch_discover_network(monkeypatch, hf_result=[...])` instead of their inline monkeypatches — assertions unchanged.)

Add:

```python
def test_research_discover_merges_sources_hf_wins_dupes(tmp_path, monkeypatch):
    from radar.discovery.technique_proposals import TechniqueProposal, load_technique_proposals
    from radar.models import Category as _Cat
    from radar.research_radar.entities import TechniqueDomain as _Dom

    def _p(arxiv_id, via, upvotes=0):
        return TechniqueProposal(
            suggested_id=f"t-{arxiv_id.replace('.', '-')}", name="T", arxiv_id=arxiv_id,
            upvotes=upvotes, suggested_domain=_Dom.INFERENCE,
            suggested_category=_Cat.MODEL_SERVING, matched_keyword="inference",
            discovered_via=via,
        )

    _patch_discover_network(
        monkeypatch,
        hf_result=[_p("2607.00001", "hf-daily-papers", upvotes=40)],
        arxiv_result=[_p("2607.00001", "arxiv-sweep"), _p("2607.00002", "arxiv-sweep")],
    )
    runner = CliRunner()
    root = _project(tmp_path)

    result = runner.invoke(app, ["research", "discover", "--root", str(root)])

    assert result.exit_code == 0
    proposals = load_technique_proposals(root / "data" / "proposed-technique-seeds.yaml")
    assert len(proposals) == 2
    merged = {p.arxiv_id: p for p in proposals}
    assert merged["2607.00001"].discovered_via == "hf-daily-papers"  # HF wins the dupe
    assert merged["2607.00002"].discovered_via == "arxiv-sweep"


def test_research_discover_source_hf_skips_arxiv(tmp_path, monkeypatch):
    calls = {"arxiv": 0}

    async def _hf(seeds, client, min_upvotes=10, limit=20):
        return []

    async def _arxiv(seeds, client, since, limit=20):
        calls["arxiv"] += 1
        return []

    async def _identity_enrich(proposals, client, now, contact_email=None):
        return proposals

    monkeypatch.setattr(
        "radar.discovery.hf_technique_candidates.discover_technique_candidates", _hf)
    monkeypatch.setattr(
        "radar.discovery.arxiv_technique_candidates.discover_arxiv_candidates", _arxiv)
    monkeypatch.setattr(
        "radar.discovery.technique_candidate_velocity.enrich_proposals_with_velocity",
        _identity_enrich)
    runner = CliRunner()
    root = _project(tmp_path)

    result = runner.invoke(app, ["research", "discover", "--root", str(root),
                                 "--source", "hf"])

    assert result.exit_code == 0
    assert calls["arxiv"] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_research_cli.py -v -k discover`
Expected: FAIL — `--source` unknown / merge behavior missing

- [ ] **Step 3: Implement**

Rework `research_discover` in `src/radar/cli.py`:

```python
@research_app.command("discover")
def research_discover(
    root: Path = typer.Option(Path("."), help="Project root."),
    source: str = typer.Option("all", help="Candidate source: all | hf | arxiv."),
    days: int = typer.Option(7, help="arXiv sweep window in days."),
    min_upvotes: int = typer.Option(10, help="Minimum HF daily-papers upvotes."),
    limit: int = typer.Option(20, help="Maximum proposals to write."),
) -> None:
    """Propose technique candidates (HF daily papers + arXiv sweep, human-reviewed)."""
    import asyncio
    import os
    from datetime import UTC, datetime, timedelta

    import httpx

    from radar.discovery import (
        arxiv_technique_candidates,
        hf_technique_candidates,
        technique_candidate_velocity,
    )
    from radar.discovery.technique_proposals import write_technique_proposals
    from radar.research_radar.seed import TechniqueSeedError, load_technique_seed

    if source not in {"all", "hf", "arxiv"}:
        console.print(f"[red]Unknown --source: {source} (use all | hf | arxiv)[/red]")
        raise typer.Exit(code=1)
    seed_path = root / "config" / "technique-seed.yaml"
    if not seed_path.exists():
        seed_path = Path(__file__).resolve().parents[2] / "config" / "technique-seed.yaml"
    try:
        seeds = load_technique_seed(seed_path)
    except TechniqueSeedError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc

    now = datetime.now(UTC)

    async def _run():
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            gathered = []
            if source in {"all", "hf"}:
                gathered.extend(await hf_technique_candidates.discover_technique_candidates(
                    seeds, client, min_upvotes=min_upvotes, limit=limit,
                ))
            if source in {"all", "arxiv"}:
                arxiv_found = await arxiv_technique_candidates.discover_arxiv_candidates(
                    seeds, client, since=now - timedelta(days=days), limit=limit,
                )
                seen = {p.arxiv_id for p in gathered}  # HF entries win duplicates
                gathered.extend(p for p in arxiv_found if p.arxiv_id not in seen)
            return await technique_candidate_velocity.enrich_proposals_with_velocity(
                gathered, client, now=now,
                contact_email=os.environ.get("RADAR_CONTACT_EMAIL"),
            )

    proposals = technique_candidate_velocity.rank_proposals(asyncio.run(_run()))[:limit]
    out_path = root / "data" / "proposed-technique-seeds.yaml"
    write_technique_proposals(out_path, proposals)
    if not proposals:
        console.print("No technique candidates found (or sources unavailable).")
        return
    console.print(
        f"{len(proposals)} technique candidate(s) → {out_path.relative_to(root)}"
    )
```

NOTE: `rank_proposals` is pure — calling it via the module keeps monkeypatch symmetry but is not required; the network functions MUST be module-attribute calls as shown. The old zero-candidates message text changes from "No technique candidates found (or HF API unavailable)." to the new wording — update the existing test's asserted substring if it pinned the old suffix (it asserts "No technique candidates", which still matches).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_research_cli.py -v`
Expected: PASS (updated + 2 new)

- [ ] **Step 5: Lint + typecheck + commit**

```bash
uv run ruff check src/radar/cli.py tests/test_research_cli.py && uv run mypy src/radar
git add src/radar/cli.py tests/test_research_cli.py
git commit -m "feat: discover merges HF + arXiv sources with velocity ranking"
```

---

### Task 5: Track-record view (minimal, honest)

**Files:**
- Create: `src/radar/research_radar/track_record.py`
- Modify: `src/radar/cli.py` (new `research track-record` command)
- Test: `tests/test_track_record.py`, `tests/test_research_cli.py` (append)

**Interfaces:**
- Produces `TrackRecordRow` (frozen: `technique_id: str`, `paper_published: str | None`, `first_flagged: str` (ISO date), `lag_days: int | None`, `ring: str | None`, `implementations: int`) and `build_track_record(entries: list[TechniqueEntry], events: list[TechniqueHistoryEvent]) -> list[TrackRecordRow]` — one row per entry that has at least one history event; `first_flagged` = earliest event date; `paper_published` = the canonical paper's date (`role == canonical`, first such paper; None when absent); `lag_days` = days between them (month precision treated as the 1st; None when no paper date); sorted by `lag_days` asc with None last, then id.
- CLI `radar research track-record`: prints the rows plus a median-lag summary and the honest caveat that flag-to-implementation hit-rate needs accumulated history.

- [ ] **Step 1: Write the failing tests**

```python
"""Track record: paper date → first radar flag lag (the computable-today view)."""

from __future__ import annotations

from datetime import UTC, datetime

from radar.models import Category, Ring
from radar.research_radar.entities import (
    OnPremImpact,
    PaperLink,
    PaperRole,
    TechniqueDomain,
    TechniqueEntry,
)
from radar.research_radar.history import TechniqueHistoryEvent
from radar.research_radar.track_record import TrackRecordRow, build_track_record
from radar.storage.history_store import ChangeType


def _entry(technique_id: str, papers: list[PaperLink], ring: Ring = Ring.PILOT):
    return TechniqueEntry(
        id=technique_id, name=technique_id, category=Category.MODEL_SERVING,
        domain=TechniqueDomain.INFERENCE, onprem_impact=OnPremImpact.REDUCES_LATENCY,
        ring=ring, papers=papers,
    )


def _event(technique_id: str, at: str) -> TechniqueHistoryEvent:
    return TechniqueHistoryEvent(
        technique_id=technique_id, domain=TechniqueDomain.INFERENCE,
        change_type=ChangeType.NEW, ring=Ring.PILOT, run_id="run-1",
        observed_at=datetime.fromisoformat(at),
    )


def test_rows_compute_lag_and_sort():
    entries = [
        _entry("young", [PaperLink(arxiv_id="1", title="t", published="2026-06-01")]),
        _entry("old", [PaperLink(arxiv_id="2", title="t", published="2022-11")]),
        _entry("undated", [PaperLink(arxiv_id="3", title="t")]),
    ]
    events = [
        _event("young", "2026-07-03T10:00:00+00:00"),
        _event("old", "2026-07-03T10:00:00+00:00"),
        _event("old", "2026-07-05T10:00:00+00:00"),  # later event ignored (first wins)
        _event("undated", "2026-07-03T10:00:00+00:00"),
    ]

    rows = build_track_record(entries, events)

    assert [r.technique_id for r in rows] == ["young", "old", "undated"]  # lag asc, None last
    assert rows[0].lag_days == 32
    assert rows[1].first_flagged == "2026-07-03"
    assert rows[1].lag_days == (datetime(2026, 7, 3, tzinfo=UTC)
                                - datetime(2022, 11, 1, tzinfo=UTC)).days
    assert rows[2].lag_days is None


def test_entries_without_events_are_excluded():
    entries = [_entry("never-flagged", [])]

    assert build_track_record(entries, []) == []


def test_only_canonical_paper_counts():
    papers = [
        PaperLink(arxiv_id="1", title="f", role=PaperRole.FOLLOWUP, published="2020-01"),
        PaperLink(arxiv_id="2", title="c", published="2024-01"),
    ]
    rows = build_track_record([_entry("t", papers)],
                              [_event("t", "2026-07-03T10:00:00+00:00")])

    assert rows[0].paper_published == "2024-01"
```

Append to `tests/test_research_cli.py`:

```python
def test_research_track_record_prints_rows_and_caveat(tmp_path):
    runner = CliRunner()
    root = _project(tmp_path)
    runner.invoke(app, ["research", "scan", "--root", str(root)])

    result = runner.invoke(app, ["research", "track-record", "--root", str(root)])

    assert result.exit_code == 0
    assert "qlora" in result.stdout
    assert "hit-rate" in result.stdout  # honest caveat present


def test_research_track_record_without_scan_prompts(tmp_path):
    runner = CliRunner()

    result = runner.invoke(app, ["research", "track-record",
                                 "--root", str(_project(tmp_path))])

    assert result.exit_code == 0
    assert "radar research scan" in result.stdout
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_track_record.py tests/test_research_cli.py -v -k track`
Expected: FAIL — `ModuleNotFoundError` / `No such command 'track-record'`

- [ ] **Step 3: Implement**

Create `src/radar/research_radar/track_record.py`:

```python
"""Track record: how long after publication did the radar flag each technique?

The honest, computable-today slice of the spec's track-record idea. The
predictive metric — how early a flag preceded a technique's first mainstream
implementation — needs months of accumulated implementation history and stays
deferred; callers should say so.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict

from radar.research_radar.entities import PaperRole, TechniqueEntry
from radar.research_radar.history import TechniqueHistoryEvent


class TrackRecordRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    technique_id: str
    paper_published: str | None = None
    first_flagged: str
    lag_days: int | None = None
    ring: str | None = None
    implementations: int = 0


def build_track_record(
    entries: list[TechniqueEntry], events: list[TechniqueHistoryEvent],
) -> list[TrackRecordRow]:
    first_flag: dict[str, datetime] = {}
    for event in events:
        seen = first_flag.get(event.technique_id)
        if seen is None or event.observed_at < seen:
            first_flag[event.technique_id] = event.observed_at
    rows: list[TrackRecordRow] = []
    for entry in entries:
        flagged = first_flag.get(entry.id)
        if flagged is None:
            continue
        published = _canonical_published(entry)
        rows.append(TrackRecordRow(
            technique_id=entry.id,
            paper_published=published,
            first_flagged=flagged.date().isoformat(),
            lag_days=_lag_days(published, flagged),
            ring=entry.ring.value if entry.ring else None,
            implementations=len(entry.resolved_implementations),
        ))
    return sorted(rows, key=lambda r: (r.lag_days is None, r.lag_days or 0, r.technique_id))


def _canonical_published(entry: TechniqueEntry) -> str | None:
    for paper in entry.papers:
        if paper.role == PaperRole.CANONICAL:
            return paper.published
    return None


def _lag_days(published: str | None, flagged: datetime) -> int | None:
    if not published:
        return None
    normalized = f"{published}-01" if len(published) == 7 else published
    try:
        start = datetime.fromisoformat(normalized).replace(tzinfo=UTC)
    except ValueError:
        return None
    return (flagged - start).days
```

Add the CLI command in `src/radar/cli.py` next to the other research commands:

```python
@research_app.command("track-record")
def research_track_record(
    root: Path = typer.Option(Path("."), help="Project root."),
) -> None:
    """Paper-to-radar lag per technique (predictive hit-rate needs more history)."""
    import statistics

    from radar.research_radar.history import load_technique_events
    from radar.research_radar.track_record import build_track_record

    entries = _latest_technique_entries(root)
    if entries is None:
        console.print(
            "[yellow]No research scan yet. Run [bold]radar research scan[/bold] first.[/yellow]"
        )
        return
    events = load_technique_events(root / "data" / "technique-history.jsonl")
    rows = build_track_record(entries, events)
    console.print(f"{len(rows)} technique(s) with a flag date:")
    for row in rows:
        lag = f"{row.lag_days}d" if row.lag_days is not None else "?"
        console.print(
            f"  {row.technique_id:<32} paper={row.paper_published or '?':<10} "
            f"flagged={row.first_flagged}  lag={lag:<7} "
            f"{row.ring or '-':<6} impls={row.implementations}",
            highlight=False, soft_wrap=True,
        )
    lags = [r.lag_days for r in rows if r.lag_days is not None]
    if lags:
        console.print(f"Median paper→radar lag: {int(statistics.median(lags))} days")
    console.print(
        "Note: flag-to-implementation hit-rate needs accumulated implementation "
        "history and is not computed yet."
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_track_record.py tests/test_research_cli.py -v`
Expected: PASS

- [ ] **Step 5: Lint + typecheck + commit**

```bash
uv run ruff check src/radar tests/test_track_record.py tests/test_research_cli.py && uv run mypy src/radar
git add src/radar/research_radar/track_record.py src/radar/cli.py \
  tests/test_track_record.py tests/test_research_cli.py
git commit -m "feat: radar research track-record (paper-to-radar lag)"
```

---

### Task 6: Docs + spec update + full gates

**Files:**
- Modify: `README.md`, `CHANGELOG.md`, `docs/superpowers/specs/2026-07-03-academic-research-radar-design.md`
- Test: full suite

- [ ] **Step 1: README**

Replace the discover CLI row with:

```markdown
| `radar research discover [--source all\|hf\|arxiv]` | Propose technique candidates from HF daily papers and a recent arXiv category sweep, ranked by citations/day, to `data/proposed-technique-seeds.yaml` (human-reviewed, never auto-added). |
```

Add after the `radar research show <id>` row:

```markdown
| `radar research track-record` | Paper→radar lag per technique (median + per-row; predictive hit-rate accrues with history). |
```

- [ ] **Step 2: CHANGELOG (top of Unreleased → Added)**

```markdown
- **Discovery extras + research-data hardening** — `radar research discover`
  gains an arXiv category sweep (`--source all|hf|arxiv`, keyword-gated like
  the HF source) and ranks all candidates by a deterministic citations/day
  velocity proxy (Semantic Scholar batch, best-effort); `radar research
  track-record` reports each technique's paper→radar lag with a median
  (flag-to-implementation hit-rate stays deferred until history accumulates).
  All research-run reads now go through one guarded loader, so a corrupt or
  schema-drifted research run can no longer break any dashboard page, export,
  scan, or MCP query — it degrades to "no research data" everywhere.
```

- [ ] **Step 3: Spec §9 Discovery bullet**

Update the trailing deferral sentence of the Discovery bullet to reflect reality — replace the clause listing deferred items with:

```markdown
  Shipped since: the arXiv category sweep and a citations/day velocity proxy
  on proposals (single-observation ranking — true two-observation spike
  detection would require tracking untracked papers over time), and a
  minimal track-record view (paper→radar lag). Still deferred:
  flag-to-implementation hit-rate (needs months of accumulated
  implementation history).
```

(Locate the Discovery bullet's existing deferral wording and replace only that clause; keep the rest of the bullet.)

- [ ] **Step 4: Full gates**

Run: `uv run pytest && uv run ruff check . && uv run mypy src/radar`
Expected: green, coverage ≥ 80%.

- [ ] **Step 5: Commit**

```bash
git add README.md CHANGELOG.md docs/superpowers/specs/2026-07-03-academic-research-radar-design.md
git commit -m "docs: discovery extras + hardening in README/CHANGELOG/spec"
```

---

## Self-Review Notes (already applied)

- Coverage: hardening ticket (T1, with the structural grep check), arXiv sweep (T2), velocity (T3, single-shot proxy deliberately — recorded in module docstring + spec update), --source merge (T4), track-record minimal (T5), docs/spec truth-up (T6).
- Type consistency: `discover_arxiv_candidates(seeds, client, since, limit)` matches T4's patches; `enrich_proposals_with_velocity(proposals, client, now, contact_email)` matches T3 tests and T4 call; `load_technique_entries(root)` name identical across all six swap sites; proposal schema fields shared by T2/T3 with an explicit ordering note.
- Existing-test impact called out explicitly: T4 updates the three existing discover tests' monkeypatching; T3's schema defaults keep all prior proposal constructors valid.
