# Research Sources (arXiv + HF Papers) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enhance tracked tools with arXiv paper-mention evidence (opt-in per project) and propose new tools from GitHub repos linked in Hugging Face daily papers.

**Architecture:** Mirror two existing patterns. Capability A is a new enricher (`enrichment/arxiv.py`, twin of `enrichment/hackernews.py`) wired into `enrichment/runner.py`, flowing a count + named papers through `ProjectMetrics`/`ProjectEvidence` to cards. Capability B is a new discovery module (`discovery/hf_papers.py`, twin of `discovery/github_trending.py`) wired into the `radar discover` CLI, writing to the existing `proposed-seeds.yaml` review file. No new scored category; papers never become decision cards.

**Tech Stack:** Python 3.12, pydantic v2, httpx (async), feedparser (already a dep, parses arXiv Atom), SQLite (`MetricsStore`), pytest + ruff + mypy.

## Global Constraints

- Python ≥ 3.12; all new modules start with `from __future__ import annotations`.
- No new third-party dependencies (feedparser + httpx already present).
- No API keys required for arXiv or HF daily-papers; GitHub repo lookups reuse the optional `GITHUB_TOKEN` header pattern already in the `discover` CLI.
- Every network call is best-effort: failures degrade to "no data" + a warning, never raise out of a scan (`enrichment/runner.py` `_safe()` pattern).
- Immutability: never mutate inputs; pydantic models use `model_copy(update=...)`.
- Deterministic core: no LLM in the default path.
- Keep ruff + mypy clean and coverage ≥ 80%.
- arXiv API base: `http://export.arxiv.org/api/query`. arXiv asks for ≤1 request / 3s.
- HF daily papers API: `https://huggingface.co/api/daily_papers`.

---

### Task 1: Data-model foundations (PaperRef, config fields, evidence fields)

**Files:**
- Modify: `src/radar/models.py`
- Test: `tests/test_models_papers.py` (create)

**Interfaces:**
- Produces: `PaperRef(title: str, url: str, published_at: str)` (frozen);
  `SourceConfig.paper_query: str | None = None`;
  `EnrichmentConfig.arxiv: bool = True`;
  `ProjectEvidence.papers: list[PaperRef]` and `ProjectEvidence.paper_mentions: int | None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_models_papers.py
from radar.models import EnrichmentConfig, PaperRef, ProjectEvidence, SourceConfig


def test_paper_ref_is_frozen():
    ref = PaperRef(title="FlashInfer-2", url="https://arxiv.org/abs/2506.1", published_at="2026-06-10")
    import pytest
    with pytest.raises(Exception):
        ref.title = "x"


def test_source_config_paper_query_defaults_none():
    src = SourceConfig(
        id="github-vllm", type="github_repo", project="vLLM",
        category="model_serving", url="https://github.com/vllm-project/vllm",
    )
    assert src.paper_query is None
    src2 = src.model_copy(update={"paper_query": '"vLLM"'})
    assert src2.paper_query == '"vLLM"'


def test_enrichment_config_arxiv_defaults_true():
    assert EnrichmentConfig().arxiv is True


def test_project_evidence_carries_papers_and_count():
    ev = ProjectEvidence(
        paper_mentions=3,
        papers=[PaperRef(title="P", url="https://arxiv.org/abs/1", published_at="2026-06-10")],
    )
    assert ev.paper_mentions == 3
    assert ev.papers[0].title == "P"
    assert ProjectEvidence().papers == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_models_papers.py -v`
Expected: FAIL (`ImportError: cannot import name 'PaperRef'`).

- [ ] **Step 3: Implement the model changes**

In `src/radar/models.py`, add the `PaperRef` model near `Advisory` (above `ProjectEvidence`):

```python
class PaperRef(BaseModel):
    """A research paper referencing a tracked project."""

    model_config = ConfigDict(frozen=True)

    title: str
    url: str
    published_at: str
```

Add to `SourceConfig` (after the `aliases` field):

```python
    # Optional arXiv search phrase enabling paper-mention enrichment for this
    # project. Absent → mention-tracking is OFF (keeps ambiguous names out).
    paper_query: str | None = None
```

Add to `EnrichmentConfig` (after `downloads: bool = True`):

```python
    arxiv: bool = True
```

Add to `ProjectEvidence` (after `hn_mentions`):

```python
    paper_mentions: int | None = None
    papers: list[PaperRef] = Field(default_factory=list)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_models_papers.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/radar/models.py tests/test_models_papers.py
git commit -m "feat: add PaperRef model + paper_query/arxiv/papers fields"
```

---

### Task 2: MetricsStore — `paper_mentions` column with additive migration

**Files:**
- Modify: `src/radar/storage/metrics_store.py`
- Test: `tests/test_metrics_store.py` (add cases)

**Interfaces:**
- Consumes: nothing new.
- Produces: `ProjectMetrics.paper_mentions: int | None = None`; the column is
  added to existing DBs by an additive migration in `initialize()`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_metrics_store.py — add
import sqlite3
from datetime import UTC, datetime
from radar.storage.metrics_store import MetricsStore, ProjectMetrics


def test_paper_mentions_round_trip(tmp_path):
    store = MetricsStore(tmp_path / "radar.db")
    store.initialize()
    store.record([ProjectMetrics(
        project="vLLM", run_id="r1", observed_at=datetime(2026, 6, 19, tzinfo=UTC),
        paper_mentions=7,
    )])
    assert store.latest("vLLM").paper_mentions == 7


def test_initialize_adds_paper_mentions_to_legacy_table(tmp_path):
    db = tmp_path / "radar.db"
    # Simulate a pre-existing table WITHOUT the new column.
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE project_metrics (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "project TEXT NOT NULL, run_id TEXT NOT NULL, observed_at TEXT NOT NULL, "
            "stars INTEGER, forks INTEGER, open_issues INTEGER, license TEXT, "
            "pushed_at TEXT, releases_in_window INTEGER NOT NULL DEFAULT 0, "
            "downloads_weekly INTEGER, hn_mentions INTEGER, advisories_open INTEGER, "
            "advisories_max_severity TEXT)"
        )
    store = MetricsStore(db)
    store.initialize()  # must add the missing column, not crash
    cols = {r[1] for r in sqlite3.connect(db).execute("PRAGMA table_info(project_metrics)")}
    assert "paper_mentions" in cols
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_metrics_store.py::test_paper_mentions_round_trip tests/test_metrics_store.py::test_initialize_adds_paper_mentions_to_legacy_table -v`
Expected: FAIL (`TypeError: unexpected keyword 'paper_mentions'` / `KeyError`).

- [ ] **Step 3: Implement the changes**

In `src/radar/storage/metrics_store.py`:

Add field to `ProjectMetrics` (after `hn_mentions`):

```python
    paper_mentions: int | None = None
```

Extend `_COLUMNS` (append the new column at the end so positional indexes for existing columns are unchanged):

```python
_COLUMNS = (
    "project, run_id, observed_at, stars, forks, open_issues, license, "
    "pushed_at, releases_in_window, downloads_weekly, hn_mentions, "
    "advisories_open, advisories_max_severity, paper_mentions"
)
```

Add the column to the `CREATE TABLE` (after `advisories_max_severity TEXT`):

```python
                    advisories_max_severity TEXT,
                    paper_mentions INTEGER
```

Add an additive migration at the end of `initialize()` (after the index creation), so legacy DBs gain the column:

```python
            cols = {row[1] for row in conn.execute("PRAGMA table_info(project_metrics)")}
            if "paper_mentions" not in cols:
                conn.execute("ALTER TABLE project_metrics ADD COLUMN paper_mentions INTEGER")
```

Add `m.paper_mentions` to the end of the `_row` tuple, add a 14th `?` to the
`INSERT ... VALUES (...)` placeholders, and add `paper_mentions=row[13]` to
`_to_metrics`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_metrics_store.py -v`
Expected: PASS (all, incl. the two new cases).

- [ ] **Step 5: Commit**

```bash
git add src/radar/storage/metrics_store.py tests/test_metrics_store.py
git commit -m "feat: persist paper_mentions in metrics store (additive migration)"
```

---

### Task 3: arXiv enrichment module

**Files:**
- Create: `src/radar/enrichment/arxiv.py`
- Test: `tests/test_enrichment_arxiv.py` (create)

**Interfaces:**
- Consumes: `PaperRef` from `radar.models`.
- Produces: `ARXIV_CATEGORIES: list[str]`; `PaperMentions(count: int, papers: list[PaperRef])`;
  `async fetch_paper_mentions(paper_query: str, client, since: datetime, max_papers: int = 5) -> PaperMentions`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_enrichment_arxiv.py
from datetime import UTC, datetime
import pytest
from radar.enrichment.arxiv import fetch_paper_mentions, ARXIV_CATEGORIES

ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
 <entry><title>Recent vLLM paper</title>
  <id>http://arxiv.org/abs/2506.0002</id>
  <published>2026-06-15T00:00:00Z</published></entry>
 <entry><title>Older vLLM paper</title>
  <id>http://arxiv.org/abs/2505.0001</id>
  <published>2026-05-01T00:00:00Z</published></entry>
</feed>"""


class FakeResp:
    def __init__(self, text): self.text = text
    def raise_for_status(self): return None


class FakeClient:
    def __init__(self, text): self.text = text; self.params = None
    async def get(self, url, params=None, **kw):
        self.params = params
        return FakeResp(self.text)


@pytest.mark.asyncio
async def test_counts_and_caps_recent_papers():
    client = FakeClient(ATOM)
    result = await fetch_paper_mentions('"vLLM"', client, since=datetime(2026, 6, 1, tzinfo=UTC))
    # Only the 2026-06-15 entry is within the since window.
    assert result.count == 1
    assert result.papers[0].title == "Recent vLLM paper"
    assert result.papers[0].url == "http://arxiv.org/abs/2506.0002"
    # Query restricts to the AI category set.
    assert "cat:cs.AI" in client.params["search_query"]
    assert '"vLLM"' in client.params["search_query"]


@pytest.mark.asyncio
async def test_cap_limits_named_papers():
    entries = "".join(
        f'<entry><title>P{i}</title><id>http://arxiv.org/abs/2506.{i}</id>'
        f'<published>2026-06-1{i}T00:00:00Z</published></entry>' for i in range(7)
    )
    client = FakeClient(f'<feed xmlns="http://www.w3.org/2005/Atom">{entries}</feed>')
    result = await fetch_paper_mentions('"x"', client, since=datetime(2026, 6, 1, tzinfo=UTC), max_papers=5)
    assert result.count == 7
    assert len(result.papers) == 5


def test_category_set_includes_vision_and_robotics():
    assert "cs.CV" in ARXIV_CATEGORIES and "cs.RO" in ARXIV_CATEGORIES
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_enrichment_arxiv.py -v`
Expected: FAIL (`ModuleNotFoundError: radar.enrichment.arxiv`).

- [ ] **Step 3: Implement the module**

```python
# src/radar/enrichment/arxiv.py
"""arXiv paper-mention counts for tracked projects (no API key required).

Counts recent arXiv papers whose text matches a project's curated search
phrase, restricted to the AI-relevant category set, and returns the count plus
the most-recent matching papers as evidence. Mirrors the Hacker News enricher.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

import feedparser
from dateutil import parser as date_parser

from radar.models import PaperRef


ARXIV_API_URL = "http://export.arxiv.org/api/query"
# AI, ML, NLP, distributed, software-eng, vision, robotics. Module constant so
# the searched fields are easy to tune.
ARXIV_CATEGORIES = ["cs.AI", "cs.LG", "cs.CL", "cs.DC", "cs.SE", "cs.CV", "cs.RO"]


class _AsyncClient(Protocol):
    async def get(self, url: str, **kwargs: Any) -> Any: ...


@dataclass(frozen=True)
class PaperMentions:
    count: int
    papers: list[PaperRef] = field(default_factory=list)


async def fetch_paper_mentions(
    paper_query: str,
    client: _AsyncClient,
    since: datetime,
    max_papers: int = 5,
) -> PaperMentions:
    """Recent arXiv papers matching ``paper_query`` since a date."""
    cats = " OR ".join(f"cat:{c}" for c in ARXIV_CATEGORIES)
    response = await client.get(
        ARXIV_API_URL,
        params={
            "search_query": f"(all:{paper_query}) AND ({cats})",
            "sortBy": "submittedDate",
            "sortOrder": "descending",
            "start": 0,
            "max_results": 50,
        },
    )
    response.raise_for_status()
    feed = feedparser.parse(response.text)
    papers: list[PaperRef] = []
    for entry in feed.entries:
        published = _published(entry)
        if published is None or published < since:
            continue
        papers.append(
            PaperRef(
                title=(entry.get("title") or "").strip().replace("\n", " "),
                url=entry.get("id") or "",
                published_at=published.date().isoformat(),
            )
        )
    return PaperMentions(count=len(papers), papers=papers[:max_papers])


def _published(entry: Any) -> datetime | None:
    raw = entry.get("published") or entry.get("updated")
    if not raw:
        return None
    try:
        parsed = date_parser.parse(raw)
    except (ValueError, OverflowError):
        return None
    if parsed.tzinfo is None:
        from datetime import UTC
        return parsed.replace(tzinfo=UTC)
    return parsed
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_enrichment_arxiv.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/radar/enrichment/arxiv.py tests/test_enrichment_arxiv.py
git commit -m "feat: arxiv paper-mention enricher (count + named papers)"
```

---

### Task 4: Wire arXiv into the enrichment runner

**Files:**
- Modify: `src/radar/enrichment/runner.py`
- Test: `tests/test_enrichment.py` (add cases)

**Interfaces:**
- Consumes: `fetch_paper_mentions`, `PaperMentions` (Task 3); `SourceConfig.paper_query`,
  `EnrichmentConfig.arxiv`, `PaperRef` (Task 1); `ProjectMetrics.paper_mentions` (Task 2).
- Produces: `EnrichmentResult.papers: dict[str, list[PaperRef]]`; enriched rows
  carry `paper_mentions`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_enrichment.py — add (reuses existing FakeClient/FakeResponse)
import pytest
from radar.enrichment.runner import run_enrichment
from radar.models import Category, EnrichmentConfig, SourceConfig, SourceType
from radar.storage.metrics_store import ProjectMetrics
from datetime import UTC, datetime

NOW2 = datetime(2026, 6, 19, tzinfo=UTC)
SINCE2 = datetime(2026, 6, 12, tzinfo=UTC)

ARXIV_ATOM = (
    '<feed xmlns="http://www.w3.org/2005/Atom">'
    '<entry><title>vLLM speedups</title><id>http://arxiv.org/abs/2506.9</id>'
    '<published>2026-06-15T00:00:00Z</published></entry></feed>'
)


def _src(sid, project, *, paper_query=None):
    return SourceConfig(id=sid, type=SourceType.GITHUB_REPO, project=project,
                        category=Category.MODEL_SERVING,
                        url=f"https://github.com/x/{sid}", paper_query=paper_query)


@pytest.mark.asyncio
async def test_arxiv_mentions_recorded_for_queried_projects():
    cfg = EnrichmentConfig(osv=False, hackernews=False, downloads=False, arxiv=True)
    sources = [_src("github-vllm", "vLLM", paper_query='"vLLM"')]
    metrics = {"vLLM": ProjectMetrics(project="vLLM", run_id="r1", observed_at=NOW2)}
    client = FakeClient({"export.arxiv.org": ARXIV_ATOM})  # FakeResponse must expose .text
    result = await run_enrichment(cfg, sources, metrics, since=SINCE2, now=NOW2, client=client)
    assert result.metrics["vLLM"].paper_mentions == 1
    assert result.papers["vLLM"][0].title == "vLLM speedups"


@pytest.mark.asyncio
async def test_arxiv_skipped_without_paper_query():
    cfg = EnrichmentConfig(osv=False, hackernews=False, downloads=False, arxiv=True)
    sources = [_src("github-ray", "Ray")]  # no paper_query
    metrics = {"Ray": ProjectMetrics(project="Ray", run_id="r1", observed_at=NOW2)}
    client = FakeClient({})  # any arXiv call would raise AssertionError (unexpected URL)
    result = await run_enrichment(cfg, sources, metrics, since=SINCE2, now=NOW2, client=client)
    assert result.metrics["Ray"].paper_mentions is None
    assert "Ray" not in result.papers
```

Note: extend the existing `FakeResponse` in `tests/test_enrichment.py` to also
expose a `.text` attribute (set it from the routed payload when the value is a
`str`), so the arXiv Atom string is returned by `.text` while JSON routes keep
using `.json()`.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_enrichment.py::test_arxiv_mentions_recorded_for_queried_projects -v`
Expected: FAIL (`AttributeError: 'EnrichmentResult' has no attribute 'papers'`).

- [ ] **Step 3: Implement the wiring**

In `src/radar/enrichment/runner.py`:

Add imports:

```python
from radar.enrichment.arxiv import fetch_paper_mentions
from radar.models import Advisory, EnrichmentConfig, PackageRef, PaperRef, SourceConfig
```

Add `papers` to the result dataclass:

```python
@dataclass(frozen=True)
class EnrichmentResult:
    metrics: dict[str, ProjectMetrics]
    advisories: dict[str, list[Advisory]] = field(default_factory=dict)
    papers: dict[str, list[PaperRef]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
```

In `run_enrichment`, add a paper-query map next to `packages`:

```python
    packages = _packages_by_project(sources)
    paper_queries = _paper_queries_by_project(sources)
    papers: dict[str, list[PaperRef]] = {}
```

Inside the per-project loop, after the downloads block, add:

```python
        paper_query = paper_queries.get(project)
        if config.arxiv and paper_query:
            mentions = await _safe(
                fetch_paper_mentions(paper_query, client, since=since),
                f"arxiv:{project}",
                warnings,
            )
            if mentions is not None:
                updates["paper_mentions"] = mentions.count
                if mentions.papers:
                    papers[project] = mentions.papers
```

Add `papers=papers` to the returned `EnrichmentResult(...)`, and add the helper:

```python
def _paper_queries_by_project(sources: list[SourceConfig]) -> dict[str, str]:
    return {
        source.project: source.paper_query
        for source in sources
        if source.enabled and source.paper_query
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_enrichment.py -v`
Expected: PASS (existing + 2 new).

- [ ] **Step 5: Commit**

```bash
git add src/radar/enrichment/runner.py tests/test_enrichment.py
git commit -m "feat: wire arxiv mentions into enrichment runner (opt-in per project)"
```

---

### Task 5: Evidence — carry papers/paper_mentions and render the note; pass through orchestrator

**Files:**
- Modify: `src/radar/pipeline/evidence.py`
- Modify: `src/radar/orchestrator.py`
- Test: `tests/test_evidence.py` (add cases)

**Interfaces:**
- Consumes: `EnrichmentResult.papers` (Task 4), `ProjectEvidence.papers/paper_mentions` (Task 1).
- Produces: `build_evidence(..., papers: list[PaperRef] | None = None)`; `evidence_notes`
  renders a paper line.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_evidence.py — add
from datetime import UTC, datetime
from radar.models import PaperRef
from radar.pipeline.evidence import build_evidence, evidence_notes
from radar.storage.metrics_store import ProjectMetrics

NOW = datetime(2026, 6, 19, tzinfo=UTC)


def test_build_evidence_carries_papers_and_count():
    cur = ProjectMetrics(project="vLLM", run_id="r1", observed_at=NOW, paper_mentions=2)
    papers = [PaperRef(title="FlashInfer-2", url="https://arxiv.org/abs/2506.1", published_at="2026-06-15")]
    ev = build_evidence(cur, None, now=NOW, papers=papers)
    assert ev.paper_mentions == 2
    assert ev.papers[0].title == "FlashInfer-2"


def test_evidence_notes_renders_paper_line():
    cur = ProjectMetrics(project="vLLM", run_id="r1", observed_at=NOW, paper_mentions=2)
    papers = [PaperRef(title="FlashInfer-2", url="https://arxiv.org/abs/2506.1", published_at="2026-06-15")]
    notes = evidence_notes(build_evidence(cur, None, now=NOW, papers=papers))
    assert any("2 recent papers" in n and "FlashInfer-2" in n for n in notes)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_evidence.py::test_build_evidence_carries_papers_and_count -v`
Expected: FAIL (`TypeError: build_evidence() got an unexpected keyword 'papers'`).

- [ ] **Step 3: Implement**

In `src/radar/pipeline/evidence.py`:

Update import: `from radar.models import Advisory, PaperRef, ProjectEvidence, Signal`.

Change `build_evidence` signature and the early-return + final return:

```python
def build_evidence(
    current: ProjectMetrics | None,
    previous: ProjectMetrics | None,
    now: datetime,
    advisories: list[Advisory] | None = None,
    papers: list[PaperRef] | None = None,
) -> ProjectEvidence:
    if current is None:
        return ProjectEvidence(advisories=advisories or [], papers=papers or [])
    ...
    return ProjectEvidence(
        ...,  # all existing fields unchanged
        hn_mentions=current.hn_mentions,
        paper_mentions=current.paper_mentions,
        papers=papers or [],
        license=current.license,
        license_changed_from=license_changed_from,
    )
```

Add the note in `evidence_notes`, after the `hn_mentions` block:

```python
    if evidence.paper_mentions and evidence.papers:
        titles = ", ".join(f"{p.title} ({p.url})" for p in evidence.papers)
        notes.append(f"Cited in {evidence.paper_mentions} recent papers: {titles}.")
    elif evidence.paper_mentions:
        notes.append(f"Cited in {evidence.paper_mentions} recent papers.")
```

In `src/radar/orchestrator.py`, capture papers from enrichment and pass them
into `build_evidence`. After `advisories = dict(enrichment.advisories)` add:

```python
            papers = dict(enrichment.papers)
```

Initialize `papers: dict[str, list] = {}` alongside `advisories: dict[str, list] = {}`
(the no-enrichment path), and add `papers=papers.get(project)` to **both**
`build_evidence(...)` call sites (the enriched path ~line 285 and the
no-metrics fallback ~line 391).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_evidence.py tests/test_orchestrator.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/radar/pipeline/evidence.py src/radar/orchestrator.py tests/test_evidence.py
git commit -m "feat: carry paper evidence through build_evidence + render note"
```

---

### Task 6: Cards — add named-paper URLs to the evidence link set

**Files:**
- Modify: `src/radar/pipeline/cards.py`
- Test: `tests/test_cards.py` (add case)

**Interfaces:**
- Consumes: `ProjectEvidence.papers` (Task 1).
- Produces: paper URLs included in `DecisionCard.evidence`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cards.py — add. Build cards with an evidence_by_project entry whose
# .papers contains a PaperRef, and assert its URL lands in the card's evidence.
# Mirror the existing card-construction test setup in this file for inputs.
def test_paper_urls_appear_in_card_evidence(...):
    # ... construct scored items for one project as existing tests do ...
    evidence_by_project = {"vLLM": ProjectEvidence(
        paper_mentions=1,
        papers=[PaperRef(title="P", url="https://arxiv.org/abs/2506.1", published_at="2026-06-15")],
    )}
    cards = build_decision_cards(..., evidence_by_project=evidence_by_project)
    card = next(c for c in cards if c.project == "vLLM")
    assert "https://arxiv.org/abs/2506.1" in card.evidence
```

(Use the same `build_decision_cards` invocation and scored-item fixtures the
existing `tests/test_cards.py` cases use; only the `evidence_by_project` arg and
the assertion are new.)

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cards.py::test_paper_urls_appear_in_card_evidence -v`
Expected: FAIL (paper URL absent from `card.evidence`).

- [ ] **Step 3: Implement**

In `src/radar/pipeline/cards.py`, replace the `evidence=` line in the
`DecisionCard(...)` construction:

```python
                evidence=sorted(
                    {str(item.signal.url) for item in items}
                    | {
                        p.url
                        for p in (
                            evidence_for_project.papers if evidence_for_project else []
                        )
                    }
                ),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cards.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/radar/pipeline/cards.py tests/test_cards.py
git commit -m "feat: surface paper links in decision-card evidence"
```

---

### Task 7: HF Papers discovery module

**Files:**
- Create: `src/radar/discovery/hf_papers.py`
- Test: `tests/test_discovery_hf_papers.py` (create)

**Interfaces:**
- Consumes: `SeedProposal` (`radar.discovery.proposals`), `Category`, `SourceConfig`,
  `project_slug` (`radar.web.slugs`), `_tracked_repos` logic.
- Produces: `HF_DAILY_PAPERS_URL`; `map_category(tags: list[str]) -> tuple[Category, bool]`;
  `async discover_from_hf_papers(tracked_sources, client, min_stars=500, headers=None) -> list[SeedProposal]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_discovery_hf_papers.py
import pytest
from radar.discovery.hf_papers import discover_from_hf_papers, map_category
from radar.models import Category, SourceConfig, SourceType


class FakeResp:
    def __init__(self, payload): self._p = payload
    def raise_for_status(self): return None
    def json(self): return self._p


class FakeClient:
    """Routes daily_papers JSON + per-repo GitHub lookups by URL substring."""
    def __init__(self, routes): self.routes = routes
    async def get(self, url, **kw):
        for frag, payload in self.routes.items():
            if frag in url:
                return FakeResp(payload)
        raise AssertionError(f"unexpected URL {url}")


DAILY = [
    {"paper": {"title": "Fast serving", "githubRepo": "https://github.com/acme/fastserve",
               "tags": ["model-serving"]}},
    {"paper": {"title": "No repo paper", "tags": ["nlp"]}},               # skipped: no repo
    {"paper": {"title": "Tracked already", "githubRepo": "https://github.com/vllm-project/vllm"}},
]
REPO = {"stargazers_count": 1200, "description": "fast", "topics": ["llm", "serving"],
        "full_name": "acme/fastserve", "name": "fastserve", "html_url": "https://github.com/acme/fastserve"}


def _tracked():
    return [SourceConfig(id="github-vllm", type=SourceType.GITHUB_REPO, project="vLLM",
                         category=Category.MODEL_SERVING, url="https://github.com/vllm-project/vllm")]


@pytest.mark.asyncio
async def test_proposes_repo_linked_paper_above_floor():
    client = FakeClient({"daily_papers": DAILY, "api.github.com/repos": REPO})
    proposals = await discover_from_hf_papers(_tracked(), client, min_stars=500)
    assert [p.suggested_id for p in proposals] == ["github-fastserve"]
    assert proposals[0].stars == 1200
    assert proposals[0].category == Category.MODEL_SERVING


@pytest.mark.asyncio
async def test_below_floor_is_dropped():
    low = dict(REPO, stargazers_count=10)
    client = FakeClient({"daily_papers": DAILY, "api.github.com/repos": low})
    assert await discover_from_hf_papers(_tracked(), client, min_stars=500) == []


def test_map_category_falls_back_to_triage():
    cat, triage = map_category(["totally-unknown-topic"])
    assert triage is True
    cat2, triage2 = map_category(["mcp-server"])
    assert cat2 == Category.MCP_TOOLING and triage2 is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_discovery_hf_papers.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement the module**

```python
# src/radar/discovery/hf_papers.py
"""Discover candidate tools from GitHub repos linked in HF daily papers.

Pulls the Hugging Face daily-papers feed, resolves each paper's linked GitHub
repo, drops repos already tracked or below the star floor, best-effort maps the
paper's tags to a radar category (flagging needs-triage when unsure), and
returns proposals. Network failures degrade to "no proposals". Results are only
ever written to the review file (see proposals.py) — never auto-added.
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urlparse

from radar.discovery.proposals import SeedProposal
from radar.models import Category, SourceConfig
from radar.web.slugs import project_slug


logger = logging.getLogger(__name__)

HF_DAILY_PAPERS_URL = "https://huggingface.co/api/daily_papers"
GITHUB_REPO_URL = "https://api.github.com/repos/{full_name}"
_GITHUB_RE = re.compile(r"github\.com/([^/\s]+)/([^/\s#?]+)")

# Tag/topic keyword → category. First match wins; no match → triage fallback.
_CATEGORY_KEYWORDS: dict[str, Category] = {
    "coding": Category.CODING_AGENTS,
    "mcp": Category.MCP_TOOLING,
    "model-context-protocol": Category.MCP_TOOLING,
    "sandbox": Category.SANDBOX_GOVERNANCE,
    "agent-framework": Category.AGENT_FRAMEWORKS,
    "agent": Category.GENERAL_AGENTS,
    "serving": Category.MODEL_SERVING,
    "inference": Category.MODEL_SERVING,
    "infrastructure": Category.AI_INFRASTRUCTURE,
    "robot": Category.PHYSICAL_AI_INFRASTRUCTURE,
    "embodied": Category.PHYSICAL_AI_INFRASTRUCTURE,
}
_TRIAGE_FALLBACK = Category.MODEL_SERVING


def map_category(tags: list[str]) -> tuple[Category, bool]:
    """Best-effort (category, needs_triage). Unmatched → fallback + triage=True."""
    for tag in tags:
        low = tag.lower()
        for keyword, category in _CATEGORY_KEYWORDS.items():
            if keyword in low:
                return category, False
    return _TRIAGE_FALLBACK, True


async def discover_from_hf_papers(
    tracked_sources: list[SourceConfig],
    client: Any,
    min_stars: int = 500,
    headers: dict[str, str] | None = None,
) -> list[SeedProposal]:
    tracked = _tracked_repos(tracked_sources)
    items = await _daily_papers(client)
    by_url: dict[str, SeedProposal] = {}
    for item in items:
        paper = item.get("paper") or item
        full_name = _github_full_name(paper)
        if not full_name or full_name.lower() in tracked:
            continue
        repo = await _repo(client, full_name, headers)
        stars = int((repo or {}).get("stargazers_count") or 0)
        if repo is None or stars < min_stars:
            continue
        category, triage = map_category(
            list(paper.get("tags") or []) + list(repo.get("topics") or [])
        )
        name = repo.get("name") or full_name.split("/")[-1]
        url = repo.get("html_url") or f"https://github.com/{full_name}"
        if url in by_url:
            continue
        tags = list(repo.get("topics") or [])[:5]
        if triage:
            tags = ["needs-triage", *tags][:5]
        by_url[url] = SeedProposal(
            project=name,
            category=category,
            url=url,
            stars=stars,
            description=(repo.get("description") or "")[:200],
            suggested_id=f"github-{project_slug(name)}",
            suggested_tags=tags,
        )
    return sorted(by_url.values(), key=lambda p: p.stars, reverse=True)


async def _daily_papers(client: Any) -> list[dict[str, Any]]:
    try:
        response = await client.get(HF_DAILY_PAPERS_URL)
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, list) else (payload.get("papers") or [])
    except Exception as exc:
        logger.warning("HF daily-papers fetch failed: %s", exc)
        return []


async def _repo(client: Any, full_name: str, headers: dict[str, str] | None) -> dict[str, Any] | None:
    try:
        response = await client.get(
            GITHUB_REPO_URL.format(full_name=full_name), headers=headers or {}
        )
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        logger.warning("GitHub repo lookup failed (%s): %s", full_name, exc)
        return None


def _github_full_name(paper: dict[str, Any]) -> str | None:
    candidate = paper.get("githubRepo") or paper.get("github") or ""
    if not candidate:
        for value in paper.values():
            if isinstance(value, str) and "github.com/" in value:
                candidate = value
                break
    match = _GITHUB_RE.search(str(candidate))
    if not match:
        return None
    owner, repo = match.group(1), match.group(2)
    return f"{owner}/{repo.removesuffix('.git')}"


def _tracked_repos(sources: list[SourceConfig]) -> set[str]:
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

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_discovery_hf_papers.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/radar/discovery/hf_papers.py tests/test_discovery_hf_papers.py
git commit -m "feat: HF daily-papers discovery (repo-linked candidates, star floor)"
```

---

### Task 8: Wire HF Papers discovery into the `discover` CLI

**Files:**
- Modify: `src/radar/cli.py` (the `discover` command, ~lines 230-286)
- Test: `tests/test_cli.py` (add case)

**Interfaces:**
- Consumes: `discover_from_hf_papers` (Task 7), existing `discover_trending` + `write_proposals`.
- Produces: `proposed-seeds.yaml` containing both GitHub-trending and HF-papers candidates (deduped by URL).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli.py — add. Run `radar discover` in a tmp project with a monkey-
# patched discover_from_hf_papers returning one proposal, and assert it lands in
# proposed-seeds.yaml alongside trending results. Patch both discovery functions
# to avoid live network (mirror how other CLI tests stub network calls).
def test_discover_includes_hf_papers(tmp_path, monkeypatch):
    from radar.discovery.proposals import SeedProposal, load_proposals
    from radar.models import Category
    runner = CliRunner()
    runner.invoke(app, ["init", "--root", str(tmp_path)])

    async def fake_trending(*a, **k): return []
    async def fake_hf(*a, **k):
        return [SeedProposal(project="fastserve", category=Category.MODEL_SERVING,
                             url="https://github.com/acme/fastserve", stars=1200,
                             suggested_id="github-fastserve")]
    monkeypatch.setattr("radar.discovery.github_trending.discover_trending", fake_trending)
    monkeypatch.setattr("radar.discovery.hf_papers.discover_from_hf_papers", fake_hf)

    result = runner.invoke(app, ["discover", "--root", str(tmp_path)])
    assert result.exit_code == 0, result.stdout
    proposals = load_proposals(tmp_path / "data" / "proposed-seeds.yaml")
    assert any(p.suggested_id == "github-fastserve" for p in proposals)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli.py::test_discover_includes_hf_papers -v`
Expected: FAIL (HF proposal absent).

- [ ] **Step 3: Implement**

In `src/radar/cli.py` `discover` command, add the import next to the others:

```python
    from radar.discovery.hf_papers import discover_from_hf_papers
```

Replace the body of `_run()` so it merges both sources (dedupe by URL, GitHub-trending wins on tie):

```python
    async def _run():
        async with httpx.AsyncClient(timeout=30.0) as client:
            trending = await discover_trending(
                config.sources, client, categories=categories,
                min_stars=min_stars, since_days=since_days, headers=_headers(),
            )
            hf = await discover_from_hf_papers(
                config.sources, client, min_stars=min_stars, headers=_headers(),
            )
            merged: dict[str, Any] = {p.url: p for p in hf}
            for proposal in trending:  # trending overrides HF on URL collision
                merged[proposal.url] = proposal
            return sorted(merged.values(), key=lambda p: p.stars, reverse=True)
```

Add `from typing import Any` to the function's local imports if not already in
scope at module top (it is imported at module level in `cli.py`; otherwise add
it). No other changes to the command.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cli.py::test_discover_includes_hf_papers -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/radar/cli.py tests/test_cli.py
git commit -m "feat: discover CLI also proposes HF daily-papers candidates"
```

---

### Task 9: Seed `paper_query` for distinctively-named tools

**Files:**
- Modify: `config/seed-sources.yaml`
- Test: `tests/test_seed_config.py` (add case)

**Interfaces:**
- Consumes: `SourceConfig.paper_query` (Task 1).
- Produces: curated `paper_query` values in the bundled seed.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_seed_config.py — add
import yaml
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]


def test_seed_has_paper_queries_for_distinctive_tools():
    raw = yaml.safe_load((_REPO_ROOT / "config" / "seed-sources.yaml").read_text())
    by_id = {s["id"]: s for s in raw["sources"]}
    # Distinctively-named, high-value tools get a curated query.
    for sid in ("github-vllm", "github-sglang", "github-llama-cpp"):
        assert by_id[sid].get("paper_query"), f"{sid} missing paper_query"
    # Ambiguous names stay off until curated.
    assert by_id["github-ray"].get("paper_query") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_seed_config.py::test_seed_has_paper_queries_for_distinctive_tools -v`
Expected: FAIL (`paper_query` absent).

- [ ] **Step 3: Implement**

In `config/seed-sources.yaml`, add a `paper_query:` line to the distinctively-named
serving/framework tools. Use the exact-id check above plus other safe names.
Examples (add the line under each matching source, keeping existing fields):

```yaml
  - id: github-vllm
    # ...existing fields...
    paper_query: '"vLLM"'
  - id: github-sglang
    paper_query: '"SGLang"'
  - id: github-llama-cpp
    paper_query: '"llama.cpp"'
  - id: github-tensorrt-llm
    paper_query: '"TensorRT-LLM"'
  - id: github-lmdeploy
    paper_query: '"LMDeploy"'
  - id: github-kserve
    paper_query: '"KServe"'
  - id: github-triton-inference-server
    paper_query: '"Triton Inference Server"'
```

Leave ambiguous names (Ray, Continue, Goose, Crush, Cua, garak, Suna) WITHOUT a
`paper_query`. Confirm each id exists in the file before editing; only add the
field, never reorder existing keys.

- [ ] **Step 4: Run test, then refresh the active config**

Run: `pytest tests/test_seed_config.py -v`
Expected: PASS.

Run: `radar init --force --root .` then
`python -c "from pathlib import Path; from radar.storage.config import load_config; c=load_config(Path('data/config.yaml')); print(sum(1 for s in c.sources if s.paper_query))"`
Expected: prints the count of queried sources (≥ 7), and the active config still loads.

- [ ] **Step 5: Commit**

```bash
git add config/seed-sources.yaml tests/test_seed_config.py
git commit -m "feat: seed paper_query for distinctively-named tracked tools"
```

---

### Task 10: Full-suite gate + live smoke + merge

**Files:** none (verification only).

- [ ] **Step 1: Run all gates**

Run: `ruff check src tests && mypy src && pytest -q`
Expected: ruff clean, mypy clean, all tests pass.

- [ ] **Step 2: Live smoke — arXiv (no key)**

Run a short script invoking `fetch_paper_mentions('"vLLM"', httpx.AsyncClient(), since=14d-ago)`.
Expected: non-zero count with real paper titles + arxiv.org URLs. If arXiv is
unreachable, note it — the scan path degrades gracefully regardless.

- [ ] **Step 3: Live smoke — HF Papers discovery**

Run: `radar discover --root . --min-stars 500` (set `GITHUB_TOKEN` for the repo lookups).
Expected: `data/proposed-seeds.yaml` gains repo-linked candidates not already tracked; `needs-triage` tag present on uncategorized ones.

- [ ] **Step 4: Merge to main (no-ff) and delete the branch**

```bash
git checkout main
git merge --no-ff feature/research-sources -m "Merge feature/research-sources: arXiv mentions + HF Papers discovery"
git branch -d feature/research-sources
```

---

## Self-Review

**Spec coverage:** A (arXiv mentions, opt-in `paper_query`, count + ≤5 named papers, cs.* incl. CV/RO, momentum-eligible metric, evidence + card links) → Tasks 1,2,3,4,5,6,9. B (HF papers → repo-linked proposals, star floor, category + needs-triage, review file) → Tasks 7,8. Error handling (best-effort, warnings) → Tasks 3,4,7. Testing → every task. No spec requirement left unmapped.

**Placeholder scan:** Task 6's test references the existing `build_decision_cards` fixture setup rather than repeating ~40 lines of card scaffolding — the implementer reuses the sibling cases in the same file; the new arg + assertion are shown in full. All code steps include complete code.

**Type consistency:** `PaperRef(title,url,published_at)` and `PaperMentions(count,papers)` are used identically across Tasks 1,3,4,5,6. `fetch_paper_mentions(paper_query, client, since, max_papers)` signature matches between Task 3 and its caller in Task 4. `EnrichmentResult.papers: dict[str,list[PaperRef]]` matches between Tasks 4 and 5. `discover_from_hf_papers(tracked_sources, client, min_stars, headers)` matches between Tasks 7 and 8. `paper_mentions` column index (row[13]) is consistent in Task 2.
