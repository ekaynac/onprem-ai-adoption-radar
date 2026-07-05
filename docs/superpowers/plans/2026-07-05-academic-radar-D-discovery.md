# Academic Research Radar — Plan D (Discovery + Metrics Persistence) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `radar research discover` proposes technique candidates from HF daily papers into a human-reviewed file (never auto-added), and technique citation metrics survive CI runs via a committed JSONL log (published momentum stops being perpetually "first scan").

**Architecture:** Discovery mirrors the tool/model discovery stack exactly: a proposals model + atomic YAML writer (`discovery/technique_proposals.py` ≙ `proposals.py`), a fetch-and-map module over the HF daily-papers API (`discovery/hf_technique_candidates.py` ≙ `hf_papers.py`, keyword-gated: papers whose titles match no technique keyword are dropped, not triaged — technique noise is too high for a triage fallback), and a CLI subcommand. Persistence mirrors the history-log pattern: `persist_technique_scan` dual-writes metrics rows to `data/technique-metrics.jsonl`; `run_research_scan` rehydrates an EMPTY SQLite store from that log before scoring, so a fresh CI checkout computes real citation velocity; publish.yml commits the log like the history files.

**Tech Stack:** Python 3.12, pydantic v2, httpx (in-tree), pytest + ruff + mypy. **No new dependencies.**

**Spec:** `docs/superpowers/specs/2026-07-03-academic-research-radar-design.md` §9 Discovery bullet + the §9 Surfaces "radar.db not persisted across CI runs" open item (this plan resolves it).

## Global Constraints

- Discovery NEVER auto-adds: proposals go to `data/proposed-technique-seeds.yaml` only (gitignored, like its two sibling proposal files); a human promotes by editing `config/technique-seed.yaml`.
- Scope narrowing (deliberate, record in CHANGELOG wording): v1 discovers from HF daily papers only. arXiv category sweeps and citation-velocity-spike flagging are deferred — spikes on tracked techniques already surface via momentum/movers.
- Persistence must not change scoring semantics: rehydration only fills an EMPTY store; a warm store (local use) is never touched; identical inputs → identical rings/momentum whether the store was warm or rehydrated from the log.
- Everything degrades: HF API failure → zero proposals + warning (never a crash); missing/corrupt metrics-log lines → skipped with a warning (mirror `load_technique_events`).
- ruff line-length 100; python 3.12; `from __future__ import annotations` everywhere; no new dependencies.
- Gates: `uv run pytest` (≥80% coverage), `uv run ruff check .`, `uv run mypy src/radar`. Commit format `<type>: <description>`; `git add` specific paths only (unrelated modified `data/history.jsonl` never committed).
- Existing symbols consumed: `SeedProposal`/`write_proposals`/`load_proposals` pattern (`src/radar/discovery/proposals.py` — mirror, don't reuse: technique proposals have different fields), `load_technique_seed`, `TechniqueDomain`, `Category`, `TechniqueMetrics`/`TechniqueMetricsStore` (`storage/technique_metrics_store.py`), `persist_technique_scan`/`run_research_scan` (`research_radar/pipeline.py`), `get_with_retry`, `project_slug` (`web/slugs.py` — reuse for candidate id slugs).

## File Structure

```
src/radar/discovery/technique_proposals.py     # NEW: TechniqueProposal + write/load (atomic YAML)
src/radar/discovery/hf_technique_candidates.py # NEW: HF daily papers → keyword-gated candidates
src/radar/storage/technique_metrics_log.py     # NEW: append/load JSONL metrics log
src/radar/storage/technique_metrics_store.py   # MODIFY: + is_empty()
src/radar/research_radar/pipeline.py           # MODIFY: dual-write + rehydrate (metrics_log_path)
src/radar/cli.py                               # MODIFY: `research discover` + scan passes log path
.gitignore                                     # MODIFY: + data/proposed-technique-seeds.yaml
.github/workflows/publish.yml                  # MODIFY: commit data/technique-metrics.jsonl
README.md, CHANGELOG.md                        # MODIFY
tests/test_technique_proposals.py              # NEW
tests/test_hf_technique_candidates.py          # NEW
tests/test_research_cli.py                     # MODIFY: discover command tests
tests/test_technique_metrics_log.py            # NEW
tests/test_research_radar_pipeline.py          # MODIFY: rehydrate/dual-write tests
tests/test_publish_workflow.py                 # MODIFY
```

Out of scope: arXiv category sweep; citation-velocity-spike proposals; track-record view (spec: "later", needs accumulated history); auto-promotion of proposals (techniques stay human-gated — the catalog-autopilot precedent was for models and explicitly reversed the gate; techniques need judgment).

---

### Task 1: Technique proposals model + writer

**Files:**
- Create: `src/radar/discovery/technique_proposals.py`
- Modify: `.gitignore` (add `data/proposed-technique-seeds.yaml` after the other proposed-* lines)
- Test: `tests/test_technique_proposals.py`

**Interfaces:**
- Consumes: `TechniqueDomain`, `Category`, yaml (mirror of `discovery/proposals.py`'s atomic-write/load pattern).
- Produces: `TechniqueProposal` (`extra="forbid"`: `suggested_id: str`, `name: str`, `arxiv_id: str`, `published: str | None = None`, `upvotes: int = 0`, `suggested_domain: TechniqueDomain`, `suggested_category: Category`, `matched_keyword: str`), `write_technique_proposals(path: Path, proposals: list[TechniqueProposal]) -> None` (atomic: tmp + replace, `{"proposals": [...]}` payload, `sort_keys=False, allow_unicode=True`), `load_technique_proposals(path: Path) -> list[TechniqueProposal]` (missing file → `[]`). Tasks 2/3 import these exact names.

- [ ] **Step 1: Write the failing tests**

```python
"""Technique proposals: human-review file round-trip (mirror of proposals.py)."""

from __future__ import annotations

from pathlib import Path

from radar.discovery.technique_proposals import (
    TechniqueProposal,
    load_technique_proposals,
    write_technique_proposals,
)
from radar.models import Category
from radar.research_radar.entities import TechniqueDomain


def _proposal(suggested_id: str = "test-time-scaling") -> TechniqueProposal:
    return TechniqueProposal(
        suggested_id=suggested_id, name="Test-Time Scaling", arxiv_id="2502.12345",
        published="2025-02-18", upvotes=142, suggested_domain=TechniqueDomain.INFERENCE,
        suggested_category=Category.MODEL_SERVING, matched_keyword="inference",
    )


def test_write_and_load_round_trip(tmp_path: Path):
    path = tmp_path / "proposed-technique-seeds.yaml"

    write_technique_proposals(path, [_proposal()])
    loaded = load_technique_proposals(path)

    assert loaded == [_proposal()]
    assert not path.with_suffix(".tmp").exists()  # atomic write cleaned up


def test_load_missing_file_returns_empty(tmp_path: Path):
    assert load_technique_proposals(tmp_path / "nope.yaml") == []


def test_write_overwrites_previous_file(tmp_path: Path):
    path = tmp_path / "proposed-technique-seeds.yaml"
    write_technique_proposals(path, [_proposal("old-one")])

    write_technique_proposals(path, [_proposal("new-one")])

    assert [p.suggested_id for p in load_technique_proposals(path)] == ["new-one"]


def test_gitignore_covers_the_proposals_file():
    gitignore = Path(__file__).resolve().parents[1] / ".gitignore"

    assert "data/proposed-technique-seeds.yaml" in gitignore.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_technique_proposals.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

Create `src/radar/discovery/technique_proposals.py`:

```python
"""Candidate technique proposals — written for human review, never auto-applied.

Discovery writes suggestions to ``data/proposed-technique-seeds.yaml``. A human
reviews them and promotes the good ones by editing ``config/technique-seed.yaml``
(curating papers/implementations by hand). The radar never adds a technique to
its own seed automatically: techniques need judgment, not a download floor.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

from radar.models import Category
from radar.research_radar.entities import TechniqueDomain


class TechniqueProposal(BaseModel):
    """A discovered paper proposed as a possible new technique seed."""

    model_config = ConfigDict(extra="forbid")

    suggested_id: str
    name: str
    arxiv_id: str
    published: str | None = None
    upvotes: int = 0
    suggested_domain: TechniqueDomain
    suggested_category: Category
    matched_keyword: str


def write_technique_proposals(path: Path, proposals: list[TechniqueProposal]) -> None:
    """Write proposals to YAML (atomic). Overwrites any prior proposals file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"proposals": [p.model_dump(mode="json") for p in proposals]}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    tmp.replace(path)


def load_technique_proposals(path: Path) -> list[TechniqueProposal]:
    """Load proposals; a missing file is an empty list."""
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [TechniqueProposal.model_validate(item) for item in raw.get("proposals") or []]
```

Add to `.gitignore`, directly after the `data/proposed-model-seeds.yaml` line:

```
data/proposed-technique-seeds.yaml
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_technique_proposals.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Lint + typecheck + commit**

```bash
uv run ruff check src/radar/discovery tests/test_technique_proposals.py && uv run mypy src/radar
git add src/radar/discovery/technique_proposals.py .gitignore tests/test_technique_proposals.py
git commit -m "feat: technique proposals file (human-gated review)"
```

---

### Task 2: HF daily-papers technique candidates

**Files:**
- Create: `src/radar/discovery/hf_technique_candidates.py`
- Test: `tests/test_hf_technique_candidates.py`

**Interfaces:**
- Consumes: `TechniqueProposal` (Task 1), `TechniqueSeed` (for dedup), `project_slug` (`radar.web.slugs`), HF daily-papers API shape (`https://huggingface.co/api/daily_papers`; each item has `paper: {id: "<arxiv id>", title, upvotes, publishedAt}` — fields best-effort like `discovery/hf_papers.py`).
- Produces:
  - `KEYWORD_MAP: list[tuple[str, TechniqueDomain, Category]]` — ordered, first match on the lowercased TITLE wins. Exact entries:
    - `("quantization", INFERENCE, MODEL_SERVING)`, `("kv cache", INFERENCE, MODEL_SERVING)`, `("attention", INFERENCE, MODEL_SERVING)`, `("decoding", INFERENCE, MODEL_SERVING)`, `("inference", INFERENCE, MODEL_SERVING)`, `("serving", INFERENCE, MODEL_SERVING)`, `("distillation", INFERENCE, MODEL_SERVING)`,
    - `("fine-tun", FINE_TUNING, AI_INFRASTRUCTURE)`, `("lora", FINE_TUNING, AI_INFRASTRUCTURE)`, `("preference optimization", FINE_TUNING, AI_INFRASTRUCTURE)`, `("rlhf", FINE_TUNING, AI_INFRASTRUCTURE)`,
    - `("retrieval", RAG, AI_INFRASTRUCTURE)`, `("rag", RAG, AI_INFRASTRUCTURE)`,
    - `("agent", AGENT_ARCHITECTURE, AGENT_FRAMEWORKS)`, `("tool use", AGENT_ARCHITECTURE, AGENT_FRAMEWORKS)`, `("reasoning", AGENT_ARCHITECTURE, AGENT_FRAMEWORKS)`, `("planning", AGENT_ARCHITECTURE, AGENT_FRAMEWORKS)`,
    - `("jailbreak", SAFETY_SANDBOXING, SANDBOX_GOVERNANCE)`, `("guardrail", SAFETY_SANDBOXING, SANDBOX_GOVERNANCE)`, `("prompt injection", SAFETY_SANDBOXING, SANDBOX_GOVERNANCE)`, `("safety", SAFETY_SANDBOXING, SANDBOX_GOVERNANCE)`.
    Note "rag" is substring-matched — match against `f" {lowered_title} "` with the keyword padded (`" rag "`)? NO — keep it simple and deterministic: plain `in` substring on the lowercased title, and order "retrieval" before "rag" so most RAG papers match the safer keyword first. A false "rag" hit (e.g. "storage") is acceptable review noise: proposals are human-gated.
  - `match_keyword(title: str) -> tuple[str, TechniqueDomain, Category] | None` — first `KEYWORD_MAP` entry whose keyword is a substring of `title.lower()`; None → candidate dropped (no triage fallback — deliberate, documented in the module docstring).
  - `async discover_technique_candidates(seeds: list[TechniqueSeed], client: Any, min_upvotes: int = 10, limit: int = 20) -> list[TechniqueProposal]` — fetch daily papers (any failure → `logger.warning` + `[]`), drop items without an arxiv-style paper id or title, drop below `min_upvotes`, drop keyword non-matches, drop candidates whose `arxiv_id` already appears in any seed's papers OR whose slug id already exists as a seed id, dedup by arxiv_id, sort by upvotes desc, cap at `limit`. `suggested_id = project_slug(title)`; `published = (publishedAt or "")[:10] or None`.

- [ ] **Step 1: Write the failing tests**

```python
"""HF daily-papers → keyword-gated technique candidates."""

from __future__ import annotations

import pytest

from radar.discovery.hf_technique_candidates import (
    discover_technique_candidates,
    match_keyword,
)
from radar.models import Category
from radar.research_radar.entities import PaperLink, TechniqueDomain, TechniqueSeed


class _Response:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200
        self.headers: dict[str, str] = {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


class _Client:
    def __init__(self, payload=None, fail: bool = False):
        self._payload = payload or []
        self._fail = fail

    async def get(self, url, **kwargs):
        if self._fail:
            raise RuntimeError("HF down")
        return _Response(self._payload)


def _paper(arxiv_id: str, title: str, upvotes: int, published: str = "2026-07-01T00:00:00Z"):
    return {"paper": {"id": arxiv_id, "title": title, "upvotes": upvotes,
                      "publishedAt": published}}


def _seed(technique_id: str, arxiv_id: str) -> TechniqueSeed:
    from radar.research_radar.entities import OnPremImpact

    return TechniqueSeed(
        id=technique_id, name=technique_id, category=Category.MODEL_SERVING,
        domain=TechniqueDomain.INFERENCE, onprem_impact=OnPremImpact.REDUCES_LATENCY,
        papers=[PaperLink(arxiv_id=arxiv_id, title="t")],
    )


def test_match_keyword_first_entry_wins_and_none_drops():
    keyword, domain, category = match_keyword("Fast Speculative Decoding for LLMs")

    assert keyword == "decoding"
    assert domain == TechniqueDomain.INFERENCE
    assert category == Category.MODEL_SERVING
    assert match_keyword("A New Image Dataset") is None


@pytest.mark.asyncio
async def test_discover_filters_maps_sorts_and_caps():
    payload = [
        _paper("2507.00001", "Ultra-Fast KV Cache Compression", upvotes=90),
        _paper("2507.00002", "A Boring Dataset Paper", upvotes=500),      # no keyword → drop
        _paper("2507.00003", "Agent Planning with Memory", upvotes=40),
        _paper("2507.00004", "Tiny Inference Trick", upvotes=3),          # below floor → drop
    ]

    proposals = await discover_technique_candidates([], _Client(payload), min_upvotes=10)

    assert [p.arxiv_id for p in proposals] == ["2507.00001", "2507.00003"]  # upvotes desc
    assert proposals[0].suggested_domain == TechniqueDomain.INFERENCE
    assert proposals[0].suggested_id == "ultra-fast-kv-cache-compression"
    assert proposals[0].published == "2026-07-01"
    assert proposals[1].suggested_category == Category.AGENT_FRAMEWORKS


@pytest.mark.asyncio
async def test_discover_dedups_against_seed_papers_and_ids():
    payload = [
        _paper("2211.17192", "Even Faster Speculative Decoding", upvotes=99),  # known arxiv id
        _paper("2507.00005", "Known Slug Inference Method", upvotes=50),
    ]
    seeds = [
        _seed("spec-dec", "2211.17192"),
        _seed("known-slug-inference-method", "1111.11111"),
    ]

    proposals = await discover_technique_candidates(seeds, _Client(payload), min_upvotes=10)

    assert proposals == []


@pytest.mark.asyncio
async def test_discover_degrades_to_empty_on_api_failure():
    assert await discover_technique_candidates([], _Client(fail=True)) == []


@pytest.mark.asyncio
async def test_discover_limit_caps_output():
    payload = [_paper(f"2507.{i:05d}", f"Inference Trick {i}", upvotes=100 - i)
               for i in range(30)]

    proposals = await discover_technique_candidates([], _Client(payload), limit=5)

    assert len(proposals) == 5
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_hf_technique_candidates.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

Create `src/radar/discovery/hf_technique_candidates.py`:

```python
"""Discover candidate techniques from Hugging Face daily papers.

Keyword-gated on purpose: a daily-papers item only becomes a proposal when its
title matches a curated technique keyword. There is NO triage fallback (unlike
repo discovery) — most daily papers are model releases or benchmarks, not
adoptable techniques, so unmatched titles are dropped, not queued for triage.
Network failures degrade to "no proposals". Results are only ever written to
the review file (see technique_proposals.py) — never auto-added.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from radar.discovery.technique_proposals import TechniqueProposal
from radar.models import Category
from radar.research_radar.entities import TechniqueDomain, TechniqueSeed
from radar.web.slugs import project_slug


logger = logging.getLogger(__name__)

HF_DAILY_PAPERS_URL = "https://huggingface.co/api/daily_papers"
_ARXIV_ID_RE = re.compile(r"^\d{4}\.\d{4,5}$")

KEYWORD_MAP: list[tuple[str, TechniqueDomain, Category]] = [
    ("quantization", TechniqueDomain.INFERENCE, Category.MODEL_SERVING),
    ("kv cache", TechniqueDomain.INFERENCE, Category.MODEL_SERVING),
    ("attention", TechniqueDomain.INFERENCE, Category.MODEL_SERVING),
    ("decoding", TechniqueDomain.INFERENCE, Category.MODEL_SERVING),
    ("inference", TechniqueDomain.INFERENCE, Category.MODEL_SERVING),
    ("serving", TechniqueDomain.INFERENCE, Category.MODEL_SERVING),
    ("distillation", TechniqueDomain.INFERENCE, Category.MODEL_SERVING),
    ("fine-tun", TechniqueDomain.FINE_TUNING, Category.AI_INFRASTRUCTURE),
    ("lora", TechniqueDomain.FINE_TUNING, Category.AI_INFRASTRUCTURE),
    ("preference optimization", TechniqueDomain.FINE_TUNING, Category.AI_INFRASTRUCTURE),
    ("rlhf", TechniqueDomain.FINE_TUNING, Category.AI_INFRASTRUCTURE),
    ("retrieval", TechniqueDomain.RAG, Category.AI_INFRASTRUCTURE),
    ("rag", TechniqueDomain.RAG, Category.AI_INFRASTRUCTURE),
    ("agent", TechniqueDomain.AGENT_ARCHITECTURE, Category.AGENT_FRAMEWORKS),
    ("tool use", TechniqueDomain.AGENT_ARCHITECTURE, Category.AGENT_FRAMEWORKS),
    ("reasoning", TechniqueDomain.AGENT_ARCHITECTURE, Category.AGENT_FRAMEWORKS),
    ("planning", TechniqueDomain.AGENT_ARCHITECTURE, Category.AGENT_FRAMEWORKS),
    ("jailbreak", TechniqueDomain.SAFETY_SANDBOXING, Category.SANDBOX_GOVERNANCE),
    ("guardrail", TechniqueDomain.SAFETY_SANDBOXING, Category.SANDBOX_GOVERNANCE),
    ("prompt injection", TechniqueDomain.SAFETY_SANDBOXING, Category.SANDBOX_GOVERNANCE),
    ("safety", TechniqueDomain.SAFETY_SANDBOXING, Category.SANDBOX_GOVERNANCE),
]


def match_keyword(title: str) -> tuple[str, TechniqueDomain, Category] | None:
    """First matching KEYWORD_MAP entry for a lowercased title, else None."""
    lowered = title.lower()
    for keyword, domain, category in KEYWORD_MAP:
        if keyword in lowered:
            return keyword, domain, category
    return None


async def discover_technique_candidates(
    seeds: list[TechniqueSeed],
    client: Any,
    min_upvotes: int = 10,
    limit: int = 20,
) -> list[TechniqueProposal]:
    known_arxiv = {p.arxiv_id for s in seeds for p in s.papers}
    known_ids = {s.id for s in seeds}
    items = await _daily_papers(client)
    by_arxiv: dict[str, TechniqueProposal] = {}
    for item in items:
        paper = item.get("paper") or item
        arxiv_id = str(paper.get("id") or "")
        title = (paper.get("title") or "").strip().replace("\n", " ")
        upvotes = int(paper.get("upvotes") or 0)
        if not _ARXIV_ID_RE.match(arxiv_id) or not title:
            continue
        if upvotes < min_upvotes or arxiv_id in known_arxiv or arxiv_id in by_arxiv:
            continue
        matched = match_keyword(title)
        if matched is None:
            continue
        suggested_id = project_slug(title)
        if suggested_id in known_ids:
            continue
        keyword, domain, category = matched
        published = str(paper.get("publishedAt") or "")[:10] or None
        by_arxiv[arxiv_id] = TechniqueProposal(
            suggested_id=suggested_id, name=title, arxiv_id=arxiv_id,
            published=published, upvotes=upvotes, suggested_domain=domain,
            suggested_category=category, matched_keyword=keyword,
        )
    ranked = sorted(by_arxiv.values(), key=lambda p: p.upvotes, reverse=True)
    return ranked[:limit]


async def _daily_papers(client: Any) -> list[dict[str, Any]]:
    try:
        response = await client.get(HF_DAILY_PAPERS_URL)
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, list) else (payload.get("papers") or [])
    except Exception as exc:
        logger.warning("HF daily-papers fetch failed: %s", exc)
        return []
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_hf_technique_candidates.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Lint + typecheck + commit**

```bash
uv run ruff check src/radar/discovery tests/test_hf_technique_candidates.py && uv run mypy src/radar
git add src/radar/discovery/hf_technique_candidates.py tests/test_hf_technique_candidates.py
git commit -m "feat: HF daily-papers technique candidate discovery"
```

---

### Task 3: `radar research discover` CLI

**Files:**
- Modify: `src/radar/cli.py` (new command on the existing `research_app`)
- Test: `tests/test_research_cli.py` (append)

**Interfaces:**
- Consumes: Tasks 1–2, `load_technique_seed` (+ the packaged-seed fallback pattern already used by `research_scan` — read that command for the exact fallback lines).
- Produces: `radar research discover [--min-upvotes 10] [--limit 20] [--root .]` → loads the seed (root, falling back to the packaged `config/technique-seed.yaml`), fetches candidates with a real httpx client, writes `data/proposed-technique-seeds.yaml`, prints `"N technique candidate(s) → data/proposed-technique-seeds.yaml"` (or a no-candidates message).

- [ ] **Step 1: Write the failing tests (append to tests/test_research_cli.py)**

```python
def test_research_discover_writes_proposals(tmp_path, monkeypatch):
    from radar.discovery.technique_proposals import TechniqueProposal, load_technique_proposals
    from radar.models import Category as _Cat
    from radar.research_radar.entities import TechniqueDomain as _Dom

    async def _fake_discover(seeds, client, min_upvotes=10, limit=20):
        return [TechniqueProposal(
            suggested_id="test-time-scaling", name="Test-Time Scaling",
            arxiv_id="2502.12345", published="2025-02-18", upvotes=142,
            suggested_domain=_Dom.INFERENCE, suggested_category=_Cat.MODEL_SERVING,
            matched_keyword="inference",
        )]

    monkeypatch.setattr(
        "radar.discovery.hf_technique_candidates.discover_technique_candidates",
        _fake_discover,
    )
    runner = CliRunner()
    root = _project(tmp_path)

    result = runner.invoke(app, ["research", "discover", "--root", str(root)])

    assert result.exit_code == 0
    assert "1 technique candidate" in result.stdout
    proposals = load_technique_proposals(root / "data" / "proposed-technique-seeds.yaml")
    assert proposals[0].suggested_id == "test-time-scaling"


def test_research_discover_no_candidates_message(tmp_path, monkeypatch):
    async def _none(seeds, client, min_upvotes=10, limit=20):
        return []

    monkeypatch.setattr(
        "radar.discovery.hf_technique_candidates.discover_technique_candidates", _none,
    )
    runner = CliRunner()
    root = _project(tmp_path)

    result = runner.invoke(app, ["research", "discover", "--root", str(root)])

    assert result.exit_code == 0
    assert "No technique candidates" in result.stdout
```

NOTE for the implementer: the monkeypatch target must match how the CLI imports the function. Import it INSIDE the command body via the module (`from radar.discovery import hf_technique_candidates` then call `hf_technique_candidates.discover_technique_candidates(...)`) so `monkeypatch.setattr` on the module attribute works at call time.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_research_cli.py -v -k discover`
Expected: FAIL — `No such command 'discover'`

- [ ] **Step 3: Implement the command (in src/radar/cli.py, next to the other research commands)**

```python
@research_app.command("discover")
def research_discover(
    root: Path = typer.Option(Path("."), help="Project root."),
    min_upvotes: int = typer.Option(10, help="Minimum HF daily-papers upvotes."),
    limit: int = typer.Option(20, help="Maximum proposals to write."),
) -> None:
    """Propose technique candidates from HF daily papers (human-reviewed file)."""
    import asyncio

    import httpx

    from radar.discovery import hf_technique_candidates
    from radar.discovery.technique_proposals import write_technique_proposals
    from radar.research_radar.seed import load_technique_seed

    seed_path = root / "config" / "technique-seed.yaml"
    if not seed_path.exists():
        seed_path = Path(__file__).resolve().parents[2] / "config" / "technique-seed.yaml"
    seeds = load_technique_seed(seed_path)

    async def _run():
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            return await hf_technique_candidates.discover_technique_candidates(
                seeds, client, min_upvotes=min_upvotes, limit=limit,
            )

    proposals = asyncio.run(_run())
    if not proposals:
        console.print("No technique candidates found (or HF API unavailable).")
        return
    out_path = root / "data" / "proposed-technique-seeds.yaml"
    write_technique_proposals(out_path, proposals)
    console.print(
        f"{len(proposals)} technique candidate(s) → {out_path.relative_to(root)}"
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_research_cli.py -v`
Expected: PASS (existing + 2 new)

- [ ] **Step 5: Lint + typecheck + commit**

```bash
uv run ruff check src/radar/cli.py tests/test_research_cli.py && uv run mypy src/radar
git add src/radar/cli.py tests/test_research_cli.py
git commit -m "feat: radar research discover (HF daily-papers candidates)"
```

---

### Task 4: Technique metrics JSONL log

**Files:**
- Create: `src/radar/storage/technique_metrics_log.py`
- Modify: `src/radar/storage/technique_metrics_store.py` (add `is_empty()`)
- Test: `tests/test_technique_metrics_log.py`

**Interfaces:**
- Consumes: `TechniqueMetrics`.
- Produces: `append_metrics(path: Path, rows: list[TechniqueMetrics]) -> None` (append-only JSONL, one `model_dump(mode="json")` per line, mkdir parents, no-op on empty rows), `load_metrics(path: Path) -> list[TechniqueMetrics]` (missing file → `[]`; corrupt lines skipped with `logger.warning` — mirror `load_technique_events`), and `TechniqueMetricsStore.is_empty(self) -> bool` (True when the technique_metrics table has zero rows). Task 5 imports these exact names.

- [ ] **Step 1: Write the failing tests**

```python
"""Append-only technique metrics log (the CI-persistence backbone)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from radar.storage.technique_metrics_log import append_metrics, load_metrics
from radar.storage.technique_metrics_store import TechniqueMetrics, TechniqueMetricsStore


def _row(run: str, count: int) -> TechniqueMetrics:
    return TechniqueMetrics(
        technique_id="spec-dec", run_id=run,
        observed_at=datetime(2026, 7, 5, 10, 0, tzinfo=UTC),
        citation_count=count, citation_source="s2", resolved_impls=3, ring="adopt",
    )


def test_append_and_load_round_trip(tmp_path: Path):
    path = tmp_path / "technique-metrics.jsonl"

    append_metrics(path, [_row("run-1", 100)])
    append_metrics(path, [_row("run-2", 120)])
    append_metrics(path, [])  # no-op

    rows = load_metrics(path)
    assert [r.run_id for r in rows] == ["run-1", "run-2"]
    assert rows[1].citation_count == 120


def test_load_missing_file_returns_empty(tmp_path: Path):
    assert load_metrics(tmp_path / "nope.jsonl") == []


def test_load_skips_corrupt_lines(tmp_path: Path):
    path = tmp_path / "technique-metrics.jsonl"
    append_metrics(path, [_row("run-1", 100)])
    with path.open("a", encoding="utf-8") as handle:
        handle.write("{broken\n")

    assert len(load_metrics(path)) == 1


def test_store_is_empty_flips_after_record(tmp_path: Path):
    store = TechniqueMetricsStore(tmp_path / "radar.db")
    store.initialize()

    assert store.is_empty() is True
    store.record([_row("run-1", 100)])
    assert store.is_empty() is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_technique_metrics_log.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

Create `src/radar/storage/technique_metrics_log.py`:

```python
"""Append-only JSONL log of technique metrics (mirror of the history logs).

CI does not persist ``radar.db`` between runs, so citation velocity would
always read "first scan" on the published site. The scan appends each run's
metric rows here; the pipeline rehydrates an empty store from this log before
scoring. The file is committed back by the publish workflow like the history
logs, which makes velocity durable.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from radar.storage.technique_metrics_store import TechniqueMetrics


logger = logging.getLogger(__name__)


def append_metrics(path: Path, rows: list[TechniqueMetrics]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(r.model_dump(mode="json"), ensure_ascii=False) for r in rows]
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def load_metrics(path: Path) -> list[TechniqueMetrics]:
    if not path.exists():
        return []
    rows: list[TechniqueMetrics] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, raw in enumerate(handle, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                rows.append(TechniqueMetrics.model_validate_json(line))
            except ValueError as exc:
                logger.warning("Skipping corrupt technique-metrics line %d in %s: %s",
                               line_no, path, exc)
    return rows
```

Add to `TechniqueMetricsStore` (in `src/radar/storage/technique_metrics_store.py`):

```python
    def is_empty(self) -> bool:
        """True when no metrics have ever been recorded."""
        with sqlite3.connect(self.path) as conn:
            row = conn.execute("SELECT 1 FROM technique_metrics LIMIT 1").fetchone()
        return row is None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_technique_metrics_log.py tests/test_technique_metrics_store.py -v`
Expected: PASS (new + existing store tests)

- [ ] **Step 5: Lint + typecheck + commit**

```bash
uv run ruff check src/radar/storage tests/test_technique_metrics_log.py && uv run mypy src/radar
git add src/radar/storage/technique_metrics_log.py src/radar/storage/technique_metrics_store.py tests/test_technique_metrics_log.py
git commit -m "feat: technique metrics JSONL log + store emptiness check"
```

---

### Task 5: Pipeline dual-write + rehydration

**Files:**
- Modify: `src/radar/research_radar/pipeline.py`, `src/radar/cli.py` (`research_scan` passes the log path)
- Test: `tests/test_research_radar_pipeline.py` (append), `tests/test_research_cli.py` (append)

**Interfaces:**
- Consumes: Task 4's `append_metrics`/`load_metrics`/`is_empty`.
- Produces:
  - `persist_technique_scan(..., metrics_log_path: Path | None = None)` — after `store.record(rows)`, also `append_metrics(metrics_log_path, rows)` when the path is given.
  - `run_research_scan(..., metrics_log_path: Path | None = None)` — right after `store.initialize()` and BEFORE any `history_for` reads: `if metrics_log_path is not None and store.is_empty(): store.record(load_metrics(metrics_log_path))` (rehydrate); threads `metrics_log_path` into `persist_technique_scan`.
  - `research_scan` CLI passes `metrics_log_path=root / "data" / "technique-metrics.jsonl"`.
  - Invariant: a warm store is NEVER rehydrated (only `is_empty()`); rehydrated scoring equals warm scoring for the same inputs.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_research_radar_pipeline.py`:

```python
@pytest.mark.asyncio
async def test_rehydration_restores_velocity_after_db_loss(tmp_path):
    """Fresh DB + metrics log == warm DB: momentum sees the prior scan."""
    from radar.storage.technique_metrics_log import load_metrics
    from radar.storage.technique_metrics_store import TechniqueMetricsStore

    class _DownClient:
        async def post(self, url, **kwargs):
            raise RuntimeError("offline")

        async def get(self, url, **kwargs):
            raise RuntimeError("offline")

    seed_path = tmp_path / "technique-seed.yaml"
    seed_path.write_text(SEED_YAML, encoding="utf-8")
    log_path = tmp_path / "technique-metrics.jsonl"

    async def _scan(db_name: str):
        return await run_research_scan(
            seed_path=seed_path,
            config_path=tmp_path / "missing-config.yaml",
            db_path=tmp_path / db_name,
            model_seed_path=tmp_path / "missing-model-seed.yaml",
            model_history_path=tmp_path / "model-history.jsonl",
            history_path=tmp_path / "technique-history.jsonl",
            client=_DownClient(),
            metrics_log_path=log_path,
        )

    await _scan("radar.db")                      # scan 1: writes rows to db + log
    assert len(load_metrics(log_path)) > 0       # dual-write happened

    entries, _ = await _scan("fresh-radar.db")   # scan 2: NEW empty db, log present

    fresh_store = TechniqueMetricsStore(tmp_path / "fresh-radar.db")
    fresh_store.initialize()
    rows = fresh_store.history_for("qlora")
    assert len(rows) >= 2                        # rehydrated scan-1 row + scan-2 row


@pytest.mark.asyncio
async def test_warm_store_is_never_rehydrated(tmp_path):
    """A non-empty store ignores the log entirely (no duplicate rows)."""
    from radar.storage.technique_metrics_log import append_metrics
    from radar.storage.technique_metrics_store import (
        TechniqueMetrics,
        TechniqueMetricsStore,
    )
    from datetime import UTC as _UTC
    from datetime import datetime as _dt

    class _DownClient:
        async def post(self, url, **kwargs):
            raise RuntimeError("offline")

        async def get(self, url, **kwargs):
            raise RuntimeError("offline")

    seed_path = tmp_path / "technique-seed.yaml"
    seed_path.write_text(SEED_YAML, encoding="utf-8")
    db_path = tmp_path / "radar.db"
    store = TechniqueMetricsStore(db_path)
    store.initialize()
    store.record([TechniqueMetrics(
        technique_id="qlora", run_id="warm-run",
        observed_at=_dt(2026, 7, 1, tzinfo=_UTC), citation_count=1,
        citation_source="s2", resolved_impls=0,
    )])
    log_path = tmp_path / "technique-metrics.jsonl"
    append_metrics(log_path, [TechniqueMetrics(
        technique_id="qlora", run_id="log-only-run",
        observed_at=_dt(2026, 6, 1, tzinfo=_UTC), citation_count=99,
        citation_source="s2", resolved_impls=0,
    )])

    await run_research_scan(
        seed_path=seed_path, config_path=tmp_path / "missing-config.yaml",
        db_path=db_path, model_seed_path=tmp_path / "missing-model-seed.yaml",
        model_history_path=tmp_path / "model-history.jsonl",
        history_path=tmp_path / "technique-history.jsonl",
        client=_DownClient(), metrics_log_path=log_path,
    )

    runs = {r.run_id for r in TechniqueMetricsStore(db_path).history_for("qlora")}
    assert "log-only-run" not in runs  # warm store untouched by the log
```

Append to `tests/test_research_cli.py`:

```python
def test_research_scan_writes_metrics_log(tmp_path):
    runner = CliRunner()
    root = _project(tmp_path)

    runner.invoke(app, ["research", "scan", "--root", str(root)])

    assert (root / "data" / "technique-metrics.jsonl").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_research_radar_pipeline.py tests/test_research_cli.py -v -k "rehydr or metrics_log or warm"`
Expected: FAIL — `TypeError: run_research_scan() got an unexpected keyword argument 'metrics_log_path'`

- [ ] **Step 3: Implement**

In `src/radar/research_radar/pipeline.py`:
- Import `append_metrics, load_metrics` from `radar.storage.technique_metrics_log`.
- `persist_technique_scan` signature gains `metrics_log_path: Path | None = None`; after `store.record(rows_list)` (build the rows list into a variable first if it is currently inline), add:

```python
    if metrics_log_path is not None:
        append_metrics(metrics_log_path, rows)
```

- `run_research_scan` signature gains `metrics_log_path: Path | None = None`; right after the existing `store.initialize()`:

```python
    if metrics_log_path is not None and store.is_empty():
        rehydrated = load_metrics(metrics_log_path)
        if rehydrated:
            store.record(rehydrated)
            logger.warning(
                "Rehydrated %d technique metric rows from %s (fresh database)",
                len(rehydrated), metrics_log_path,
            )
```

(Check the module has a `logger`; add one if not, mirroring `resolve.py`.) Thread `metrics_log_path=metrics_log_path` into the `persist_technique_scan(...)` call.

In `src/radar/cli.py` `research_scan`, add to the `run_research_scan(...)` kwargs:

```python
                metrics_log_path=root / "data" / "technique-metrics.jsonl",
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_research_radar_pipeline.py tests/test_research_cli.py -v`
Expected: PASS (existing + 3 new)

- [ ] **Step 5: Lint + typecheck + commit**

```bash
uv run ruff check src/radar tests/test_research_radar_pipeline.py tests/test_research_cli.py && uv run mypy src/radar
git add src/radar/research_radar/pipeline.py src/radar/cli.py tests/test_research_radar_pipeline.py tests/test_research_cli.py
git commit -m "feat: technique metrics dual-write + rehydration (CI-durable velocity)"
```

---

### Task 6: CI wiring + docs + gates

**Files:**
- Modify: `.github/workflows/publish.yml`, `README.md`, `CHANGELOG.md`
- Test: `tests/test_publish_workflow.py` (append)

- [ ] **Step 1: Write the failing test (append to tests/test_publish_workflow.py)**

```python
def test_publish_commits_technique_metrics_log():
    text = Path(".github/workflows/publish.yml").read_text(encoding="utf-8")

    assert "data/technique-metrics.jsonl" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_publish_workflow.py -v`
Expected: FAIL on the new test

- [ ] **Step 3: Edit the workflow**

In `.github/workflows/publish.yml`'s history-commit block, after the `git add -f data/technique-history.jsonl || true` line:

```yaml
          git add -f data/technique-metrics.jsonl || true
```

- [ ] **Step 4: README + CHANGELOG**

README: in the CLI table, after the `radar research show <id>` row:

```markdown
| `radar research discover [--min-upvotes N]` | Propose technique candidates from HF daily papers to `data/proposed-technique-seeds.yaml` (human-reviewed, never auto-added). |
```

CHANGELOG: under `## [Unreleased]` → `### Added`, above the "(cross-linking)" entry:

```markdown
- **Technique discovery + durable citation velocity** — `radar research
  discover` proposes technique candidates from Hugging Face daily papers
  (keyword-gated by title, deduped against the seed, upvote floor) into
  `data/proposed-technique-seeds.yaml` for human review — techniques are never
  auto-added. Citation metrics now dual-write to an append-only
  `data/technique-metrics.jsonl` that the publish workflow commits back;
  a fresh CI checkout rehydrates its metrics store from the log, so published
  citation-velocity momentum finally survives across daily runs (arXiv
  category sweeps and velocity-spike proposals stay deferred).
```

- [ ] **Step 5: Full gates**

Run: `uv run pytest && uv run ruff check . && uv run mypy src/radar`
Expected: all green, coverage ≥ 80%.

- [ ] **Step 6: Commit**

```bash
git add .github/workflows/publish.yml tests/test_publish_workflow.py README.md CHANGELOG.md
git commit -m "ci: commit technique metrics log + discover docs"
```

---

## Self-Review Notes (already applied)

- Spec §9 Discovery coverage: HF daily papers → human-gated proposals (T1–T3); arXiv sweep, spike proposals, track-record view explicitly deferred (Out of scope + CHANGELOG wording). The §9 radar.db-persistence open item is resolved by T4–T6.
- Determinism: rehydration is gated on `is_empty()` so warm stores are untouched (tested); the log round-trips the exact `TechniqueMetrics` rows the store records.
- Type consistency: `TechniqueProposal`/`write_technique_proposals`/`load_technique_proposals` (T1) ↔ T2/T3; `append_metrics`/`load_metrics`/`is_empty` (T4) ↔ T5; `metrics_log_path` kwarg name identical across pipeline + CLI.
- The discover CLI's monkeypatch-friendly module import is called out explicitly in T3 (module attribute, not from-import).
