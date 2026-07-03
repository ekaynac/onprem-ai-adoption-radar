# Academic Research Radar — Plan A (Core) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build sub-project 1 of the academic research radar: a curated technique catalog with closed-loop deterministic ring decisions, citation enrichment, metrics/history persistence, and a `radar research` CLI group.

**Architecture:** New `src/radar/research_radar/` module mirroring `models_radar/`: a validated `config/technique-seed.yaml` is assembled into frozen `TechniqueEntry` objects whose implementation links resolve against the radar's *own* tool cards and model catalog (offline), enriched best-effort with citations (Semantic Scholar batch POST primary, OpenAlex batch GET fallback), then scored 1–5 on six dimensions and ring-gated. Per-scan metrics go to a new SQLite table; ring changes append to `data/technique-history.jsonl`.

**Tech Stack:** Python 3.12, pydantic v2, typer, httpx (all in-tree; **no new dependencies**), pytest + ruff + mypy.

**Spec:** `docs/superpowers/specs/2026-07-03-academic-research-radar-design.md` (approved).

## Global Constraints

- Deterministic core: identical inputs → identical rings; enrichment is best-effort and never fails a scan.
- No LLM anywhere in this plan. No new third-party dependencies. Papers With Code is NOT a source.
- ruff line-length = 100; `python_version = 3.12`; every file starts with `from __future__ import annotations`.
- Coverage ≥ 80% enforced; run gates with `uv run pytest`, `uv run ruff check .`, `uv run mypy src/radar`.
- Commit format: `<type>: <description>` (feat/fix/refactor/docs/test/chore). No attribution lines.
- All entity models are pydantic v2, frozen where the models-radar mirror is frozen; seeds use `extra="forbid"`.
- Verified live (2026-07-03): Semantic Scholar `POST /graph/v1/paper/batch?fields=citationCount,venue` with body `{"ids": ["ARXIV:2211.17192", ...]}` returns `[{"paperId", "venue", "citationCount"}, ...]` in request order (max 500 ids/call; unmatched ids → `null` entries). OpenAlex `GET /works?filter=doi:10.48550/arXiv.A|10.48550/arXiv.B&select=doi,cited_by_count,primary_location&per-page=50` returns `{"results": [...]}` (max 50 DOIs per filter; response DOIs come back lowercased, e.g. `https://doi.org/10.48550/arxiv.2211.17192`). OpenAlex citation counts differ from S2 for the same paper (34 vs 1697 observed) — velocity must only ever compare same-source counts.

## File Structure

```
src/radar/research_radar/
    __init__.py                  # empty (mirrors models_radar/__init__.py)
    entities.py                  # enums + PaperLink/ImplementationLink/TechniqueSeed/TechniqueScore/TechniqueEntry
    seed.py                      # load_technique_seed + TechniqueSeedError (dup ids, dangling superseded_by)
    resolve.py                   # ResolutionContext + closed-loop implementation-link resolution
    citations.py                 # fetch_citations: S2 batch primary, OpenAlex batch fallback
    history.py                   # TechniqueHistoryEvent + diff/append/load (mirror of models_radar/history.py)
    momentum.py                  # MomentumSignal: 1-5 score + direction from metrics rows
    scoring.py                   # six dimension ladders + score_technique + technique_ring
    pipeline.py                  # assemble → momentum → score → persist
    reports.py                   # mover lines + markdown report
src/radar/enrichment/retry.py    # MODIFY: extract _retry_loop, add post_with_retry
src/radar/storage/technique_metrics_store.py   # TechniqueMetrics + TechniqueMetricsStore
src/radar/cli.py                 # MODIFY: research_app (scan / list / show)
config/technique-seed.yaml       # starter seed (15 techniques, real arXiv ids)
tests/test_research_radar_entities_seed.py
tests/test_research_radar_resolve.py
tests/test_retry_post.py
tests/test_research_radar_citations.py
tests/test_technique_metrics_store.py
tests/test_research_radar_history.py
tests/test_research_radar_momentum.py
tests/test_research_radar_scoring.py
tests/test_research_radar_pipeline.py
tests/test_research_radar_reports.py
tests/test_research_cli.py
```

Out of scope for this plan (per spec): web/MCP surfaces, tool/model-card cross-linking, discovery, and the expansion of the seed from 16 → 60–100 techniques (that is a separate curation session with user review, like the model seed's 8 → 33 expansion).

---

### Task 1: Schema layer — entities + seed loader

**Files:**
- Create: `src/radar/research_radar/__init__.py` (empty file)
- Create: `src/radar/research_radar/entities.py`
- Create: `src/radar/research_radar/seed.py`
- Test: `tests/test_research_radar_entities_seed.py`

**Interfaces:**
- Consumes: `radar.models.Category`, `radar.models.Ring` (existing).
- Produces: `TechniqueDomain`, `PaperRole`, `OnPremImpact`, `ImplKind`, `PaperLink`, `ImplementationLink`, `ResolvedImplementation`, `TechniqueSeed`, `TechniqueScore`, `TechniqueEntry`, `TechniqueSeedError`, `load_technique_seed(path: Path) -> list[TechniqueSeed]`. Every later task imports from these two modules.

- [ ] **Step 1: Write the failing tests**

```python
"""Schema layer: entities + technique-seed loader."""

from pathlib import Path

import pytest

from radar.models import Category, Ring
from radar.research_radar.entities import (
    ImplementationLink,
    ImplKind,
    OnPremImpact,
    PaperLink,
    ResolvedImplementation,
    TechniqueDomain,
    TechniqueEntry,
    TechniqueScore,
    TechniqueSeed,
)
from radar.research_radar.seed import TechniqueSeedError, load_technique_seed


VALID_SEED = """
techniques:
  - id: speculative-decoding
    name: Speculative Decoding
    category: model_serving
    domain: inference
    aliases: ["speculative sampling"]
    papers:
      - arxiv_id: "2211.17192"
        title: "Fast Inference from Transformers via Speculative Decoding"
    implementations:
      - kind: tool
        ref: github-vllm
      - kind: model
        ref: llama-3.3-70b
    open_code: true
    onprem_impact: reduces_latency
"""


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "technique-seed.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_load_valid_seed(tmp_path):
    seeds = load_technique_seed(_write(tmp_path, VALID_SEED))

    assert len(seeds) == 1
    seed = seeds[0]
    assert seed.id == "speculative-decoding"
    assert seed.category == Category.MODEL_SERVING
    assert seed.domain == TechniqueDomain.INFERENCE
    assert seed.papers[0].arxiv_id == "2211.17192"
    assert seed.papers[0].role.value == "canonical"  # default
    assert seed.implementations[0] == ImplementationLink(kind=ImplKind.TOOL, ref="github-vllm")
    assert seed.onprem_impact == OnPremImpact.REDUCES_LATENCY
    assert seed.enabled is True
    assert seed.superseded_by is None


def test_missing_file_raises(tmp_path):
    with pytest.raises(TechniqueSeedError, match="not found"):
        load_technique_seed(tmp_path / "nope.yaml")


def test_invalid_yaml_raises(tmp_path):
    with pytest.raises(TechniqueSeedError, match="Invalid YAML"):
        load_technique_seed(_write(tmp_path, "techniques: [::"))


def test_unknown_field_rejected(tmp_path):
    bad = VALID_SEED + "    stars: 100\n"
    with pytest.raises(TechniqueSeedError, match="validation failed"):
        load_technique_seed(_write(tmp_path, bad))


def test_duplicate_ids_rejected(tmp_path):
    dup = VALID_SEED + VALID_SEED.replace("techniques:\n", "")
    with pytest.raises(TechniqueSeedError, match="[Dd]uplicate"):
        load_technique_seed(_write(tmp_path, dup))


def test_dangling_superseded_by_rejected(tmp_path):
    bad = VALID_SEED + "    superseded_by: not-a-technique\n"
    with pytest.raises(TechniqueSeedError, match="superseded_by"):
        load_technique_seed(_write(tmp_path, bad))


def test_superseded_by_resolving_to_seeded_id_is_accepted(tmp_path):
    two = VALID_SEED + """
  - id: medusa
    name: Medusa
    category: model_serving
    domain: inference
    onprem_impact: reduces_latency
    superseded_by: speculative-decoding
"""
    seeds = load_technique_seed(_write(tmp_path, two))

    assert seeds[1].superseded_by == "speculative-decoding"


def test_technique_entry_is_frozen_with_optional_enrichment():
    entry = TechniqueEntry(
        id="lora",
        name="LoRA",
        category=Category.AI_INFRASTRUCTURE,
        domain=TechniqueDomain.FINE_TUNING,
        onprem_impact=OnPremImpact.REDUCES_MEMORY,
    )

    assert entry.citation_count is None
    assert entry.ring is None
    assert entry.warnings == []
    with pytest.raises(Exception):
        entry.name = "changed"  # type: ignore[misc]


def test_technique_score_bounds():
    with pytest.raises(Exception):
        TechniqueScore(
            implementation_breadth=0, implementation_maturity=1, validation=1,
            reproducibility=1, momentum=1, onprem_impact=1, average=1.0,
        )


def test_resolved_implementation_carries_ring():
    resolved = ResolvedImplementation(kind=ImplKind.TOOL, ref="github-vllm", ring=Ring.ADOPT)

    assert resolved.ring == Ring.ADOPT


def test_paper_link_rejects_unknown_fields():
    with pytest.raises(Exception):
        PaperLink(arxiv_id="1", title="t", doi="nope")  # type: ignore[call-arg]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_research_radar_entities_seed.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'radar.research_radar'`

- [ ] **Step 3: Write the implementation**

Create empty `src/radar/research_radar/__init__.py`.

Create `src/radar/research_radar/entities.py`:

```python
"""Entities for the academic research radar (techniques, not papers)."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from radar.models import Category, Ring


class TechniqueDomain(str, Enum):
    """Research-native grouping, orthogonal to the radar Category."""

    INFERENCE = "inference"
    FINE_TUNING = "fine_tuning"
    RAG = "rag"
    AGENT_ARCHITECTURE = "agent_architecture"
    SAFETY_SANDBOXING = "safety_sandboxing"
    ORCHESTRATION = "orchestration"
    EMBODIED = "embodied"


class PaperRole(str, Enum):
    CANONICAL = "canonical"
    FOLLOWUP = "followup"
    SURVEY = "survey"


class OnPremImpact(str, Enum):
    """What adopting the technique buys an on-prem deployment."""

    REDUCES_MEMORY = "reduces_memory"
    REDUCES_LATENCY = "reduces_latency"
    ENABLES_SCALE = "enables_scale"
    IMPROVES_SAFETY = "improves_safety"
    IMPROVES_QUALITY = "improves_quality"


class ImplKind(str, Enum):
    TOOL = "tool"    # ref = a source id in data/config.yaml
    MODEL = "model"  # ref = a model id in config/model-seed.yaml


class PaperLink(BaseModel):
    """A paper attached to a technique (papers are attributes, never entities)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    arxiv_id: str
    title: str
    role: PaperRole = PaperRole.CANONICAL
    published: str | None = None  # ISO "YYYY-MM"


class ImplementationLink(BaseModel):
    """A typed link into the radar's own tool/model catalogs."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: ImplKind
    ref: str
    note: str | None = None


class ResolvedImplementation(BaseModel):
    """An implementation link resolved against the catalogs at assembly time."""

    model_config = ConfigDict(frozen=True)

    kind: ImplKind
    ref: str
    ring: Ring | None = None  # referenced entity's current ring (None = no ring yet)
    note: str | None = None


class TechniqueSeed(BaseModel):
    """A curated technique entry (config/technique-seed.yaml)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    category: Category
    domain: TechniqueDomain
    aliases: list[str] = Field(default_factory=list)
    papers: list[PaperLink] = Field(default_factory=list)
    implementations: list[ImplementationLink] = Field(default_factory=list)
    open_code: bool = False
    onprem_impact: OnPremImpact
    superseded_by: str | None = None
    enabled: bool = True
    notes: str | None = None


class TechniqueScore(BaseModel):
    """Deterministic technique-adoption score dimensions (1-5)."""

    model_config = ConfigDict(frozen=True)

    implementation_breadth: int = Field(ge=1, le=5)
    implementation_maturity: int = Field(ge=1, le=5)
    validation: int = Field(ge=1, le=5)
    reproducibility: int = Field(ge=1, le=5)
    momentum: int = Field(ge=1, le=5)
    onprem_impact: int = Field(ge=1, le=5)
    average: float


class TechniqueEntry(BaseModel):
    """A tracked technique with resolved evidence and (after scoring) a ring."""

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    category: Category
    domain: TechniqueDomain
    aliases: list[str] = Field(default_factory=list)
    papers: list[PaperLink] = Field(default_factory=list)
    resolved_implementations: list[ResolvedImplementation] = Field(default_factory=list)
    open_code: bool = False
    onprem_impact: OnPremImpact
    superseded_by: str | None = None
    notes: str | None = None
    citation_count: int | None = None
    citation_source: str | None = None  # "s2" | "openalex" (velocity is same-source only)
    peer_reviewed: bool | None = None
    score: float | None = None
    score_breakdown: TechniqueScore | None = None
    ring: Ring | None = None
    warnings: list[str] = Field(default_factory=list)
```

Create `src/radar/research_radar/seed.py`:

```python
"""Load the technique seed (config/technique-seed.yaml). Fails loud before network."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from radar.research_radar.entities import TechniqueSeed


class TechniqueSeedError(ValueError):
    """Raised when the technique seed cannot be loaded."""


def load_technique_seed(path: Path) -> list[TechniqueSeed]:
    try:
        contents = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise TechniqueSeedError(f"Technique seed not found: {path}") from exc
    try:
        raw = yaml.safe_load(contents) or {}
    except yaml.YAMLError as exc:
        raise TechniqueSeedError(f"Invalid YAML in {path}: {exc}") from exc
    try:
        seeds = [TechniqueSeed.model_validate(item) for item in raw.get("techniques") or []]
    except ValidationError as exc:
        raise TechniqueSeedError(f"Technique seed validation failed for {path}: {exc}") from exc
    _check_ids(seeds, path)
    return seeds


def _check_ids(seeds: list[TechniqueSeed], path: Path) -> None:
    """Unique ids; every superseded_by must reference a seeded id."""
    ids = [s.id for s in seeds]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise TechniqueSeedError(f"Duplicate technique ids in {path}: {', '.join(duplicates)}")
    known = set(ids)
    for seed in seeds:
        if seed.superseded_by is not None and seed.superseded_by not in known:
            raise TechniqueSeedError(
                f"{path}: {seed.id} has superseded_by={seed.superseded_by!r},"
                " which is not a seeded technique id"
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_research_radar_entities_seed.py -v`
Expected: PASS (11 tests)

- [ ] **Step 5: Lint + typecheck**

Run: `uv run ruff check src/radar/research_radar tests/test_research_radar_entities_seed.py && uv run mypy src/radar`
Expected: clean

- [ ] **Step 6: Commit**

```bash
git add src/radar/research_radar/ tests/test_research_radar_entities_seed.py
git commit -m "feat: research-radar entities + technique-seed loader"
```

---

### Task 2: Closed-loop resolution of implementation links

**Files:**
- Create: `src/radar/research_radar/resolve.py`
- Test: `tests/test_research_radar_resolve.py`

**Interfaces:**
- Consumes: `ImplementationLink`, `ImplKind`, `ResolvedImplementation` (Task 1); existing `radar.storage.config.load_config`, `radar.storage.database.RadarDatabase` (`.initialize()`, `.list_cards()` → `DecisionCard` with `.project`/`.ring`), `radar.models_radar.seed.load_model_seed`, `radar.models_radar.history.load_model_events` (oldest-first; last event per model wins).
- Produces: `ResolutionContext` (fields `tool_rings: dict[str, Ring | None]`, `model_rings: dict[str, Ring | None]`, `warnings: list[str]`), `build_resolution_context(config_path: Path, db_path: Path, model_seed_path: Path, model_history_path: Path) -> ResolutionContext`, `resolve_implementations(links: list[ImplementationLink], context: ResolutionContext) -> tuple[list[ResolvedImplementation], list[str]]`.

The resolution chain for tools: source id → source.project (config.yaml) → DecisionCard by project → ring. For models: model id ∈ model seed; ring = last `technique`-independent event in `model-history.jsonl` (mirror of `models_radar.pipeline._latest_rings`). A missing config/db/seed degrades to an empty map + a context warning — a research scan must work before the tool radar has ever run.

- [ ] **Step 1: Write the failing tests**

```python
"""Closed-loop resolution: implementation links → current rings from own catalogs."""

from pathlib import Path

from radar.models import Ring
from radar.research_radar.entities import ImplementationLink, ImplKind
from radar.research_radar.resolve import (
    ResolutionContext,
    build_resolution_context,
    resolve_implementations,
)


def _context(**kwargs) -> ResolutionContext:
    defaults = {"tool_rings": {}, "model_rings": {}, "warnings": []}
    defaults.update(kwargs)
    return ResolutionContext(**defaults)


def test_tool_link_resolves_with_ring():
    context = _context(tool_rings={"github-vllm": Ring.ADOPT})

    resolved, warnings = resolve_implementations(
        [ImplementationLink(kind=ImplKind.TOOL, ref="github-vllm")], context
    )

    assert warnings == []
    assert resolved[0].ring == Ring.ADOPT
    assert resolved[0].kind == ImplKind.TOOL


def test_model_link_resolves_with_ring():
    context = _context(model_rings={"llama-3.3-70b": Ring.PILOT})

    resolved, warnings = resolve_implementations(
        [ImplementationLink(kind=ImplKind.MODEL, ref="llama-3.3-70b")], context
    )

    assert resolved[0].ring == Ring.PILOT


def test_known_entity_without_ring_resolves_as_unringed():
    context = _context(tool_rings={"github-new-tool": None})

    resolved, warnings = resolve_implementations(
        [ImplementationLink(kind=ImplKind.TOOL, ref="github-new-tool")], context
    )

    assert warnings == []
    assert resolved[0].ring is None


def test_dangling_ref_warns_and_drops():
    resolved, warnings = resolve_implementations(
        [ImplementationLink(kind=ImplKind.TOOL, ref="github-removed")], _context()
    )

    assert resolved == []
    assert "github-removed" in warnings[0]


def test_build_context_from_real_stores(tmp_path):
    from radar.storage.database import RadarDatabase
    from radar.models import Category, DecisionCard

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
sources:
  - id: github-vllm
    type: github_repo
    project: vLLM
    category: model_serving
    url: https://github.com/vllm-project/vllm
""",
        encoding="utf-8",
    )
    db = RadarDatabase(tmp_path / "radar.db")
    db.initialize()
    db.upsert_cards([DecisionCard(
        project="vLLM", category=Category.MODEL_SERVING, ring=Ring.ADOPT,
        summary="s", workflow_fit={}, risk_level="low",
    )])
    model_seed = tmp_path / "model-seed.yaml"
    model_seed.write_text(
        "models:\n  - id: llama-3.3-70b\n    name: Llama 3.3 70B\n    family: llama\n",
        encoding="utf-8",
    )

    context = build_resolution_context(
        config_path, tmp_path / "radar.db", model_seed, tmp_path / "model-history.jsonl"
    )

    assert context.tool_rings == {"github-vllm": Ring.ADOPT}
    assert context.model_rings == {"llama-3.3-70b": None}  # seeded, never ringed


def test_build_context_degrades_when_stores_missing(tmp_path):
    context = build_resolution_context(
        tmp_path / "no-config.yaml", tmp_path / "no.db",
        tmp_path / "no-model-seed.yaml", tmp_path / "no-history.jsonl",
    )

    assert context.tool_rings == {}
    assert context.model_rings == {}
    assert len(context.warnings) == 2  # config unavailable + model seed unavailable
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_research_radar_resolve.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'radar.research_radar.resolve'`

- [ ] **Step 3: Write the implementation**

Create `src/radar/research_radar/resolve.py`:

```python
"""Resolve technique implementation links against the radar's own catalogs.

The closed loop: tool refs map source id → project (config.yaml) → the
project's latest DecisionCard ring; model refs map model id → the last ring
event in model-history.jsonl. Everything is offline. Missing stores degrade
to empty maps + a warning so a research scan works before any tool scan.
"""

from __future__ import annotations

import logging
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from radar.models import Ring
from radar.models_radar.history import load_model_events
from radar.models_radar.seed import ModelSeedError, load_model_seed
from radar.research_radar.entities import (
    ImplementationLink,
    ImplKind,
    ResolvedImplementation,
)
from radar.storage.config import load_config
from radar.storage.database import RadarDatabase


logger = logging.getLogger(__name__)


class ResolutionContext(BaseModel):
    """Current rings per known tool source id and model id (None = unringed)."""

    model_config = ConfigDict(frozen=True)

    tool_rings: dict[str, Ring | None] = Field(default_factory=dict)
    model_rings: dict[str, Ring | None] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


def build_resolution_context(
    config_path: Path,
    db_path: Path,
    model_seed_path: Path,
    model_history_path: Path,
) -> ResolutionContext:
    warnings: list[str] = []
    tool_rings = _tool_rings(config_path, db_path, warnings)
    model_rings = _model_rings(model_seed_path, model_history_path, warnings)
    return ResolutionContext(tool_rings=tool_rings, model_rings=model_rings, warnings=warnings)


def resolve_implementations(
    links: list[ImplementationLink],
    context: ResolutionContext,
) -> tuple[list[ResolvedImplementation], list[str]]:
    """(resolved links with current rings, warnings for dangling refs)."""
    resolved: list[ResolvedImplementation] = []
    warnings: list[str] = []
    for link in links:
        known = context.tool_rings if link.kind == ImplKind.TOOL else context.model_rings
        if link.ref not in known:
            warnings.append(f"implementation ref not found ({link.kind.value}): {link.ref}")
            continue
        resolved.append(ResolvedImplementation(
            kind=link.kind, ref=link.ref, ring=known[link.ref], note=link.note,
        ))
    return resolved, warnings


def _tool_rings(config_path: Path, db_path: Path, warnings: list[str]) -> dict[str, Ring | None]:
    try:
        config = load_config(config_path)
    except Exception as exc:
        warnings.append(f"tool catalog unavailable ({config_path}): {exc}")
        return {}
    ring_by_project: dict[str, Ring] = {}
    try:
        database = RadarDatabase(db_path)
        database.initialize()
        ring_by_project = {card.project: card.ring for card in database.list_cards()}
    except Exception as exc:  # cards are optional: sources still resolve as unringed
        logger.warning("Decision cards unavailable (%s): %s", db_path, exc)
    return {source.id: ring_by_project.get(source.project) for source in config.sources}


def _model_rings(
    model_seed_path: Path, model_history_path: Path, warnings: list[str],
) -> dict[str, Ring | None]:
    try:
        seeds = load_model_seed(model_seed_path)
    except ModelSeedError as exc:
        warnings.append(f"model catalog unavailable ({model_seed_path}): {exc}")
        return {}
    latest: dict[str, Ring] = {}
    for event in load_model_events(model_history_path):  # oldest-first → last wins
        latest[event.model_id] = event.ring
    return {seed.id: latest.get(seed.id) for seed in seeds}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_research_radar_resolve.py -v`
Expected: PASS (6 tests). If `DecisionCard` requires more mandatory fields than the test provides, check `src/radar/models.py:328` and add the minimal missing fields to the test's card, not to the implementation.

- [ ] **Step 5: Lint + typecheck + commit**

```bash
uv run ruff check src/radar/research_radar tests/test_research_radar_resolve.py && uv run mypy src/radar
git add src/radar/research_radar/resolve.py tests/test_research_radar_resolve.py
git commit -m "feat: closed-loop implementation-link resolution for research radar"
```

---

### Task 3: POST support in the shared retry helper

**Files:**
- Modify: `src/radar/enrichment/retry.py`
- Test: `tests/test_retry_post.py`

**Interfaces:**
- Consumes: existing `get_with_retry` internals (`MAX_RETRIES`, `RETRYABLE_STATUS`, `_retry_delay`).
- Produces: `post_with_retry(client, url, *, label="request", **kwargs) -> Any` with identical retry semantics; `get_with_retry`'s public signature and behavior unchanged (existing tests must keep passing).

The Semantic Scholar batch endpoint is POST-only; the retry loop is extracted into a private `_retry_loop(send, label)` taking a zero-arg async callable, and both public helpers delegate to it.

- [ ] **Step 1: Write the failing tests**

```python
"""post_with_retry: same 429/5xx semantics as get_with_retry, for POST endpoints."""

import pytest

from radar.enrichment.retry import get_with_retry, post_with_retry


class _Response:
    def __init__(self, status_code: int = 200):
        self.status_code = status_code
        self.headers: dict[str, str] = {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _Client:
    def __init__(self, statuses: list[int]):
        self._statuses = statuses
        self.post_calls: list[tuple[str, dict]] = []

    async def post(self, url: str, **kwargs):
        self.post_calls.append((url, kwargs))
        return _Response(self._statuses.pop(0))

    async def get(self, url: str, **kwargs):
        return _Response(self._statuses.pop(0))


@pytest.mark.asyncio
async def test_post_retries_429_then_succeeds(monkeypatch):
    import asyncio

    async def _no_sleep(_):
        return None

    monkeypatch.setattr(asyncio, "sleep", _no_sleep)
    client = _Client([429, 200])

    response = await post_with_retry(client, "https://api.test/batch", json={"ids": []})

    assert response.status_code == 200
    assert len(client.post_calls) == 2
    assert client.post_calls[0][1] == {"json": {"ids": []}}


@pytest.mark.asyncio
async def test_post_raises_after_exhausting_retries(monkeypatch):
    import asyncio

    async def _no_sleep(_):
        return None

    monkeypatch.setattr(asyncio, "sleep", _no_sleep)
    client = _Client([503, 503, 503, 503])

    with pytest.raises(RuntimeError, match="HTTP 503"):
        await post_with_retry(client, "https://api.test/batch")


@pytest.mark.asyncio
async def test_get_with_retry_still_works():
    client = _Client([200])

    response = await get_with_retry(client, "https://api.test/x")

    assert response.status_code == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_retry_post.py -v`
Expected: FAIL — `ImportError: cannot import name 'post_with_retry'`

- [ ] **Step 3: Refactor retry.py**

In `src/radar/enrichment/retry.py`, replace the body of `get_with_retry` with a delegation and add the shared loop + `post_with_retry`. The `_AsyncClient` protocol gains a `post` method with a default-raising stub is NOT needed — use two protocols to keep old callers passing fakes that only implement `get`:

```python
class _AsyncGetClient(Protocol):
    async def get(self, url: str, **kwargs: Any) -> Any: ...


class _AsyncPostClient(Protocol):
    async def post(self, url: str, **kwargs: Any) -> Any: ...


async def get_with_retry(
    client: _AsyncGetClient,
    url: str,
    *,
    label: str = "request",
    **kwargs: Any,
) -> Any:
    """GET ``url`` (passing ``kwargs`` through), retrying 429/5xx before raising."""
    return await _retry_loop(lambda: client.get(url, **kwargs), label)


async def post_with_retry(
    client: _AsyncPostClient,
    url: str,
    *,
    label: str = "request",
    **kwargs: Any,
) -> Any:
    """POST ``url`` (passing ``kwargs`` through), retrying 429/5xx before raising."""
    return await _retry_loop(lambda: client.post(url, **kwargs), label)


async def _retry_loop(send: Callable[[], Awaitable[Any]], label: str) -> Any:
    for attempt in range(MAX_RETRIES + 1):
        response = await send()
        status = getattr(response, "status_code", 200)
        if status not in RETRYABLE_STATUS or attempt == MAX_RETRIES:
            response.raise_for_status()
            return response
        delay = _retry_delay(response, attempt)
        logger.warning(
            "%s returned HTTP %s; retry %d/%d in %.1fs",
            label, status, attempt + 1, MAX_RETRIES, delay,
        )
        await asyncio.sleep(delay)
    raise RuntimeError("retry loop exited without a response")
```

Keep the module docstring, constants, and `_retry_delay` exactly as they are; add `from collections.abc import Awaitable, Callable` to the imports; delete the old `_AsyncClient` protocol (replaced by the two above).

- [ ] **Step 4: Run the new tests AND the existing retry consumers' tests**

Run: `uv run pytest tests/test_retry_post.py tests/test_enrichment.py tests/test_enrichment_arxiv.py -v`
Expected: all PASS (behavior of `get_with_retry` unchanged)

- [ ] **Step 5: Lint + typecheck + commit**

```bash
uv run ruff check src/radar/enrichment tests/test_retry_post.py && uv run mypy src/radar
git add src/radar/enrichment/retry.py tests/test_retry_post.py
git commit -m "refactor: extract retry loop, add post_with_retry for batch APIs"
```

---

### Task 4: Citation enrichment (Semantic Scholar batch → OpenAlex fallback)

**Files:**
- Create: `src/radar/research_radar/citations.py`
- Test: `tests/test_research_radar_citations.py`

**Interfaces:**
- Consumes: `get_with_retry`, `post_with_retry` (Task 3).
- Produces: `CitationRecord` (frozen: `arxiv_id: str`, `citation_count: int`, `venue: str | None`, `peer_reviewed: bool`, `source: str`), `fetch_citations(arxiv_ids: list[str], client: Any, contact_email: str | None = None) -> dict[str, CitationRecord]`. Total failure of both APIs returns `{}` — the caller treats missing ids as "no fresh data".

- [ ] **Step 1: Write the failing tests**

```python
"""Citation enrichment: S2 batch primary, OpenAlex batch fallback, {} on total failure."""

import pytest

from radar.research_radar.citations import (
    OPENALEX_WORKS_URL,
    S2_BATCH_URL,
    CitationRecord,
    fetch_citations,
)


class _Response:
    def __init__(self, payload, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code
        self.headers: dict[str, str] = {}

    def json(self):
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _Client:
    """Programmable fake: maps (method, url-prefix) to a queue of responses."""

    def __init__(self, post_responses=None, get_responses=None):
        self._post = list(post_responses or [])
        self._get = list(get_responses or [])
        self.post_urls: list[str] = []
        self.get_urls: list[str] = []
        self.post_bodies: list[dict] = []
        self.get_params: list[dict] = []

    async def post(self, url: str, **kwargs):
        self.post_urls.append(url)
        self.post_bodies.append(kwargs.get("json") or {})
        if not self._post:
            raise RuntimeError("connection failed")
        return self._post.pop(0)

    async def get(self, url: str, **kwargs):
        self.get_urls.append(url)
        self.get_params.append(kwargs.get("params") or {})
        if not self._get:
            raise RuntimeError("connection failed")
        return self._get.pop(0)


S2_OK = _Response([
    {"paperId": "abc", "venue": "International Conference on Machine Learning",
     "citationCount": 1697},
    None,  # unmatched id comes back as null
    {"paperId": "def", "venue": "", "citationCount": 12},
])


@pytest.mark.asyncio
async def test_s2_batch_happy_path_maps_by_request_order():
    client = _Client(post_responses=[S2_OK])

    records = await fetch_citations(["2211.17192", "9999.00000", "2305.14314"], client)

    assert client.post_urls == [S2_BATCH_URL]
    assert client.post_bodies[0] == {
        "ids": ["ARXIV:2211.17192", "ARXIV:9999.00000", "ARXIV:2305.14314"]
    }
    assert records["2211.17192"] == CitationRecord(
        arxiv_id="2211.17192", citation_count=1697,
        venue="International Conference on Machine Learning",
        peer_reviewed=True, source="s2",
    )
    assert "9999.00000" not in records  # null entry skipped
    assert records["2305.14314"].peer_reviewed is False  # empty venue = preprint


@pytest.mark.asyncio
async def test_s2_venue_arxiv_is_not_peer_reviewed():
    client = _Client(post_responses=[_Response([
        {"paperId": "x", "venue": "arXiv.org", "citationCount": 40},
    ])])

    records = await fetch_citations(["2305.18290"], client)

    assert records["2305.18290"].peer_reviewed is False


OPENALEX_OK = _Response({"results": [
    {"doi": "https://doi.org/10.48550/arxiv.2211.17192", "cited_by_count": 34,
     "primary_location": {"source": {"display_name": "arXiv (Cornell University)"}}},
]})


@pytest.mark.asyncio
async def test_openalex_fallback_when_s2_fails():
    client = _Client(post_responses=[], get_responses=[OPENALEX_OK])

    records = await fetch_citations(["2211.17192"], client)

    assert client.get_urls == [OPENALEX_WORKS_URL]
    assert "doi:10.48550/arXiv.2211.17192" in client.get_params[0]["filter"]
    record = records["2211.17192"]
    assert record.citation_count == 34
    assert record.source == "openalex"
    assert record.peer_reviewed is False  # arXiv repository = preprint


@pytest.mark.asyncio
async def test_openalex_mailto_forwarded():
    client = _Client(post_responses=[], get_responses=[OPENALEX_OK])

    await fetch_citations(["2211.17192"], client, contact_email="radar@mega.com.tr")

    assert client.get_params[0]["mailto"] == "radar@mega.com.tr"


@pytest.mark.asyncio
async def test_both_apis_down_returns_empty():
    client = _Client(post_responses=[], get_responses=[])

    records = await fetch_citations(["2211.17192"], client)

    assert records == {}


@pytest.mark.asyncio
async def test_empty_input_makes_no_requests():
    client = _Client()

    records = await fetch_citations([], client)

    assert records == {}
    assert client.post_urls == []
    assert client.get_urls == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_research_radar_citations.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'radar.research_radar.citations'`

- [ ] **Step 3: Write the implementation**

Create `src/radar/research_radar/citations.py`:

```python
"""Citation counts + venue per arXiv id. Best-effort; a scan never fails here.

Primary: Semantic Scholar Graph batch endpoint (POST, up to 500 ids/call,
keyless). Fallback: OpenAlex works filtered by arXiv DOI (GET, up to 50 DOIs
per piped filter, keyless; ``mailto`` joins the polite pool). The two count
citations differently, so every record carries its ``source`` and velocity is
only ever computed between same-source counts (see momentum.py).
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, ConfigDict

from radar.enrichment.retry import get_with_retry, post_with_retry


logger = logging.getLogger(__name__)

S2_BATCH_URL = "https://api.semanticscholar.org/graph/v1/paper/batch"
S2_FIELDS = "citationCount,venue"
S2_BATCH_SIZE = 500
OPENALEX_WORKS_URL = "https://api.openalex.org/works"
OPENALEX_BATCH_SIZE = 50


class CitationRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    arxiv_id: str
    citation_count: int
    venue: str | None = None
    peer_reviewed: bool = False
    source: str  # "s2" | "openalex"


async def fetch_citations(
    arxiv_ids: list[str],
    client: Any,
    contact_email: str | None = None,
) -> dict[str, CitationRecord]:
    """Citation record per arXiv id; ids the APIs don't know are simply absent."""
    if not arxiv_ids:
        return {}
    try:
        return await _from_semantic_scholar(arxiv_ids, client)
    except Exception as exc:
        logger.warning("Semantic Scholar citations failed, trying OpenAlex: %s", exc)
    try:
        return await _from_openalex(arxiv_ids, client, contact_email)
    except Exception as exc:
        logger.warning("OpenAlex citations failed too: %s", exc)
        return {}


def _is_peer_reviewed(venue: str | None) -> bool:
    """Deterministic rule from the spec: a non-arXiv venue means peer-reviewed."""
    return bool(venue) and "arxiv" not in (venue or "").lower()


async def _from_semantic_scholar(
    arxiv_ids: list[str], client: Any,
) -> dict[str, CitationRecord]:
    records: dict[str, CitationRecord] = {}
    for start in range(0, len(arxiv_ids), S2_BATCH_SIZE):
        chunk = arxiv_ids[start:start + S2_BATCH_SIZE]
        response = await post_with_retry(
            client,
            S2_BATCH_URL,
            label="semantic-scholar",
            params={"fields": S2_FIELDS},
            json={"ids": [f"ARXIV:{arxiv_id}" for arxiv_id in chunk]},
        )
        payload = response.json()
        for arxiv_id, item in zip(chunk, payload, strict=False):
            if not isinstance(item, dict):
                continue  # unmatched ids come back as null
            venue = (item.get("venue") or "").strip() or None
            records[arxiv_id] = CitationRecord(
                arxiv_id=arxiv_id,
                citation_count=int(item.get("citationCount") or 0),
                venue=venue,
                peer_reviewed=_is_peer_reviewed(venue),
                source="s2",
            )
    return records


async def _from_openalex(
    arxiv_ids: list[str], client: Any, contact_email: str | None,
) -> dict[str, CitationRecord]:
    records: dict[str, CitationRecord] = {}
    for start in range(0, len(arxiv_ids), OPENALEX_BATCH_SIZE):
        chunk = arxiv_ids[start:start + OPENALEX_BATCH_SIZE]
        dois = "|".join(f"doi:10.48550/arXiv.{arxiv_id}" for arxiv_id in chunk)
        params: dict[str, str] = {
            "filter": dois,
            "select": "doi,cited_by_count,primary_location",
            "per-page": str(OPENALEX_BATCH_SIZE),
        }
        if contact_email:
            params["mailto"] = contact_email
        response = await get_with_retry(
            client, OPENALEX_WORKS_URL, label="openalex", params=params,
        )
        for item in response.json().get("results") or []:
            arxiv_id = _arxiv_id_from_doi(str(item.get("doi") or ""))
            if arxiv_id is None:
                continue
            source = (item.get("primary_location") or {}).get("source") or {}
            venue = (source.get("display_name") or "").strip() or None
            records[arxiv_id] = CitationRecord(
                arxiv_id=arxiv_id,
                citation_count=int(item.get("cited_by_count") or 0),
                venue=venue,
                peer_reviewed=_is_peer_reviewed(venue),
                source="openalex",
            )
    return records


def _arxiv_id_from_doi(doi: str) -> str | None:
    """'https://doi.org/10.48550/arxiv.2211.17192' → '2211.17192' (case-insensitive)."""
    marker = "10.48550/arxiv."
    lowered = doi.lower()
    if marker not in lowered:
        return None
    return doi[lowered.index(marker) + len(marker):] or None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_research_radar_citations.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Lint + typecheck + commit**

```bash
uv run ruff check src/radar/research_radar tests/test_research_radar_citations.py && uv run mypy src/radar
git add src/radar/research_radar/citations.py tests/test_research_radar_citations.py
git commit -m "feat: citation enrichment (S2 batch primary, OpenAlex fallback)"
```

---

### Task 5: Technique metrics store

**Files:**
- Create: `src/radar/storage/technique_metrics_store.py`
- Test: `tests/test_technique_metrics_store.py`

**Interfaces:**
- Consumes: nothing new (sqlite3, pydantic).
- Produces: `TechniqueMetrics` (fields `technique_id: str`, `run_id: str`, `observed_at: datetime`, `citation_count: int | None`, `citation_source: str | None`, `resolved_impls: int | None`, `ring: str | None`) and `TechniqueMetricsStore(path)` with `initialize()`, `record(metrics: list[TechniqueMetrics])`, `latest(technique_id, exclude_run=None) -> TechniqueMetrics | None`, `history_for(technique_id, limit=50) -> list[TechniqueMetrics]` (oldest-first). Direct mirror of `src/radar/storage/model_metrics_store.py`.

- [ ] **Step 1: Write the failing tests**

```python
"""SQLite store of per-scan technique metrics (mirror of model_metrics_store)."""

from datetime import datetime

from radar.storage.technique_metrics_store import TechniqueMetrics, TechniqueMetricsStore


def _metric(run: str, count: int | None, source: str | None = "s2",
            impls: int = 2, at: str = "2026-07-03T10:00:00+00:00") -> TechniqueMetrics:
    return TechniqueMetrics(
        technique_id="speculative-decoding", run_id=run,
        observed_at=datetime.fromisoformat(at),
        citation_count=count, citation_source=source, resolved_impls=impls, ring="adopt",
    )


def test_record_and_history_roundtrip_oldest_first(tmp_path):
    store = TechniqueMetricsStore(tmp_path / "radar.db")
    store.initialize()
    store.record([_metric("run-1", 100, at="2026-07-01T10:00:00+00:00")])
    store.record([_metric("run-2", 120, at="2026-07-02T10:00:00+00:00")])

    rows = store.history_for("speculative-decoding")

    assert [r.run_id for r in rows] == ["run-1", "run-2"]
    assert rows[1].citation_count == 120
    assert rows[1].citation_source == "s2"
    assert rows[1].resolved_impls == 2


def test_latest_excludes_run(tmp_path):
    store = TechniqueMetricsStore(tmp_path / "radar.db")
    store.initialize()
    store.record([_metric("run-1", 100, at="2026-07-01T10:00:00+00:00")])
    store.record([_metric("run-2", 120, at="2026-07-02T10:00:00+00:00")])

    assert store.latest("speculative-decoding").run_id == "run-2"
    assert store.latest("speculative-decoding", exclude_run="run-2").run_id == "run-1"
    assert store.latest("unknown-technique") is None


def test_record_empty_list_is_noop(tmp_path):
    store = TechniqueMetricsStore(tmp_path / "radar.db")
    store.initialize()

    store.record([])

    assert store.history_for("speculative-decoding") == []


def test_nullable_fields_roundtrip(tmp_path):
    store = TechniqueMetricsStore(tmp_path / "radar.db")
    store.initialize()
    store.record([_metric("run-1", None, source=None)])

    row = store.latest("speculative-decoding")

    assert row.citation_count is None
    assert row.citation_source is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_technique_metrics_store.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

Create `src/radar/storage/technique_metrics_store.py`:

```python
"""SQLite store of per-scan technique metrics (mirror of model_metrics_store.py)."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel


class TechniqueMetrics(BaseModel):
    technique_id: str
    run_id: str
    observed_at: datetime
    citation_count: int | None = None
    citation_source: str | None = None  # "s2" | "openalex" — velocity is same-source only
    resolved_impls: int | None = None
    ring: str | None = None


_COLUMNS = (
    "technique_id, run_id, observed_at, citation_count, citation_source, "
    "resolved_impls, ring"
)


class TechniqueMetricsStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def initialize(self) -> None:
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS technique_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    technique_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    citation_count INTEGER,
                    citation_source TEXT,
                    resolved_impls INTEGER,
                    ring TEXT
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_technique_metrics_technique "
                "ON technique_metrics(technique_id, observed_at)"
            )

    def record(self, metrics: list[TechniqueMetrics]) -> None:
        if not metrics:
            return
        with sqlite3.connect(self.path) as conn:
            conn.executemany(
                f"INSERT INTO technique_metrics({_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?)",
                [self._row(m) for m in metrics],
            )

    def latest(
        self, technique_id: str, exclude_run: str | None = None,
    ) -> TechniqueMetrics | None:
        query = f"SELECT {_COLUMNS} FROM technique_metrics WHERE technique_id = ?"
        params: list[str] = [technique_id]
        if exclude_run is not None:
            query += " AND run_id != ?"
            params.append(exclude_run)
        query += " ORDER BY observed_at DESC, id DESC LIMIT 1"
        with sqlite3.connect(self.path) as conn:
            row = conn.execute(query, params).fetchone()
        return self._to_metrics(row) if row else None

    def history_for(self, technique_id: str, limit: int = 50) -> list[TechniqueMetrics]:
        with sqlite3.connect(self.path) as conn:
            rows = conn.execute(
                f"SELECT {_COLUMNS} FROM technique_metrics WHERE technique_id = ? "
                "ORDER BY observed_at DESC, id DESC LIMIT ?",
                (technique_id, limit),
            ).fetchall()
        return [self._to_metrics(r) for r in reversed(rows)]

    @staticmethod
    def _row(m: TechniqueMetrics) -> tuple:
        return (m.technique_id, m.run_id, m.observed_at.isoformat(), m.citation_count,
                m.citation_source, m.resolved_impls, m.ring)

    @staticmethod
    def _to_metrics(row: tuple) -> TechniqueMetrics:
        return TechniqueMetrics(
            technique_id=row[0], run_id=row[1],
            observed_at=datetime.fromisoformat(row[2]),
            citation_count=row[3], citation_source=row[4],
            resolved_impls=row[5], ring=row[6],
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_technique_metrics_store.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Lint + typecheck + commit**

```bash
uv run ruff check src/radar/storage tests/test_technique_metrics_store.py && uv run mypy src/radar
git add src/radar/storage/technique_metrics_store.py tests/test_technique_metrics_store.py
git commit -m "feat: technique metrics store"
```

---

### Task 6: Technique ring history (JSONL)

**Files:**
- Create: `src/radar/research_radar/history.py`
- Test: `tests/test_research_radar_history.py`

**Interfaces:**
- Consumes: `TechniqueEntry`, `TechniqueDomain` (Task 1); existing `radar.storage.history_store.ChangeType` (`NEW`/`PROMOTED`/`DEMOTED`), `Ring`.
- Produces: `TechniqueHistoryEvent` (fields `technique_id`, `domain: TechniqueDomain`, `change_type: ChangeType`, `ring: Ring`, `previous_ring: Ring | None`, `run_id: str`, `observed_at: datetime`, `reasons: list[str]`), `diff_technique_rings(entries, previous_rings: dict[str, Ring], run_id, observed_at) -> list[TechniqueHistoryEvent]`, `append_technique_events(path, events)`, `load_technique_events(path) -> list[TechniqueHistoryEvent]` (oldest-first, corrupt lines skipped with a warning). Direct mirror of `src/radar/models_radar/history.py`.

- [ ] **Step 1: Write the failing tests**

```python
"""Technique ring-change events + append-only JSONL log."""

from datetime import UTC, datetime

from radar.models import Category, Ring
from radar.research_radar.entities import OnPremImpact, TechniqueDomain, TechniqueEntry
from radar.research_radar.history import (
    TechniqueHistoryEvent,
    append_technique_events,
    diff_technique_rings,
    load_technique_events,
)
from radar.storage.history_store import ChangeType


NOW = datetime(2026, 7, 3, 10, 0, tzinfo=UTC)


def _entry(technique_id: str, ring: Ring | None) -> TechniqueEntry:
    return TechniqueEntry(
        id=technique_id, name=technique_id, category=Category.MODEL_SERVING,
        domain=TechniqueDomain.INFERENCE, onprem_impact=OnPremImpact.REDUCES_LATENCY,
        ring=ring,
    )


def test_new_promoted_demoted_and_unchanged():
    entries = [
        _entry("brand-new", Ring.WATCH),
        _entry("promoted", Ring.ADOPT),
        _entry("demoted", Ring.WATCH),
        _entry("unchanged", Ring.PILOT),
        _entry("unringed", None),
    ]
    previous = {"promoted": Ring.PILOT, "demoted": Ring.PILOT, "unchanged": Ring.PILOT}

    events = diff_technique_rings(entries, previous, "run-1", NOW)

    by_id = {e.technique_id: e for e in events}
    assert set(by_id) == {"brand-new", "promoted", "demoted"}
    assert by_id["brand-new"].change_type == ChangeType.NEW
    assert by_id["promoted"].change_type == ChangeType.PROMOTED
    assert by_id["promoted"].previous_ring == Ring.PILOT
    assert by_id["demoted"].change_type == ChangeType.DEMOTED


def test_append_and_load_roundtrip(tmp_path):
    path = tmp_path / "technique-history.jsonl"
    events = diff_technique_rings([_entry("lora", Ring.ADOPT)], {}, "run-1", NOW)
    append_technique_events(path, events)
    append_technique_events(path, [])  # no-op, must not create noise

    loaded = load_technique_events(path)

    assert len(loaded) == 1
    assert loaded[0].technique_id == "lora"
    assert loaded[0].domain == TechniqueDomain.INFERENCE  # domain round-trips
    assert loaded[0].ring == Ring.ADOPT


def test_load_skips_corrupt_lines(tmp_path):
    path = tmp_path / "technique-history.jsonl"
    append_technique_events(
        path, diff_technique_rings([_entry("lora", Ring.ADOPT)], {}, "run-1", NOW)
    )
    with path.open("a", encoding="utf-8") as handle:
        handle.write("{not json}\n")

    assert len(load_technique_events(path)) == 1


def test_load_missing_file_returns_empty(tmp_path):
    assert load_technique_events(tmp_path / "nope.jsonl") == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_research_radar_history.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

Create `src/radar/research_radar/history.py`:

```python
"""Technique ring-change events + append-only JSONL log (mirror of models_radar)."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field

from radar.models import Ring
from radar.research_radar.entities import TechniqueDomain, TechniqueEntry
from radar.storage.history_store import ChangeType


logger = logging.getLogger(__name__)

_RING_ORDER = {Ring.AVOID: 0, Ring.WATCH: 1, Ring.PILOT: 2, Ring.ADOPT: 3}


class TechniqueHistoryEvent(BaseModel):
    technique_id: str
    domain: TechniqueDomain
    change_type: ChangeType
    ring: Ring
    previous_ring: Ring | None = None
    run_id: str
    observed_at: datetime
    reasons: list[str] = Field(default_factory=list)


def diff_technique_rings(
    entries: list[TechniqueEntry],
    previous_rings: dict[str, Ring],
    run_id: str,
    observed_at: datetime,
) -> list[TechniqueHistoryEvent]:
    """Emit new/promoted/demoted events. Unchanged rings emit nothing."""
    events: list[TechniqueHistoryEvent] = []
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
        events.append(TechniqueHistoryEvent(
            technique_id=entry.id, domain=entry.domain, change_type=change,
            ring=entry.ring, previous_ring=prev, run_id=run_id, observed_at=observed_at,
            reasons=[f"{change.value} to {entry.ring.value}"],
        ))
    return events


def append_technique_events(path: Path, events: list[TechniqueHistoryEvent]) -> None:
    if not events:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(e.model_dump(mode="json"), ensure_ascii=False) for e in events]
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def load_technique_events(path: Path) -> list[TechniqueHistoryEvent]:
    if not path.exists():
        return []
    events: list[TechniqueHistoryEvent] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, raw in enumerate(handle, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                events.append(TechniqueHistoryEvent.model_validate_json(line))
            except ValueError as exc:
                logger.warning("Skipping corrupt technique-history line %d in %s: %s",
                               line_no, path, exc)
    return events
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_research_radar_history.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Lint + typecheck + commit**

```bash
uv run ruff check src/radar/research_radar tests/test_research_radar_history.py && uv run mypy src/radar
git add src/radar/research_radar/history.py tests/test_research_radar_history.py
git commit -m "feat: technique ring history (append-only JSONL)"
```

---

### Task 7: Momentum signal

**Files:**
- Create: `src/radar/research_radar/momentum.py`
- Test: `tests/test_research_radar_momentum.py`

**Interfaces:**
- Consumes: `TechniqueMetrics` (Task 5).
- Produces: `MomentumSignal` (frozen: `technique_id: str`, `score: int` (1–5), `direction: str` ("rising"|"falling"|"steady"), `citation_growth_pct: float | None`, `note: str`), `momentum_signal(technique_id: str, previous_rows: list[TechniqueMetrics], citation_count: int | None, citation_source: str | None, impl_count: int) -> MomentumSignal`, constant `CITATION_RISING_PCT = 10.0`.

Ladder from the spec (defaults; constants tunable): new resolved impl since last scan → 5; citation velocity ≥ `CITATION_RISING_PCT` → 4; steady → 3; velocity negative → 2; velocity negative AND a previously-resolved impl gone → 1. Velocity compares the current count against the most recent *same-source* row only (S2 and OpenAlex counts are not comparable — verified live, 1697 vs 34 for the same paper). Impl delta compares against the most recent row of any source. First scan (no rows) → steady 3.

- [ ] **Step 1: Write the failing tests**

```python
"""Momentum: 1-5 score + direction from technique metric history."""

from datetime import UTC, datetime

from radar.research_radar.momentum import CITATION_RISING_PCT, MomentumSignal, momentum_signal
from radar.storage.technique_metrics_store import TechniqueMetrics


def _row(count: int | None, source: str | None = "s2", impls: int = 2,
         at: str = "2026-07-01T10:00:00+00:00") -> TechniqueMetrics:
    return TechniqueMetrics(
        technique_id="t", run_id="r", observed_at=datetime.fromisoformat(at),
        citation_count=count, citation_source=source, resolved_impls=impls,
    )


def test_first_scan_is_steady_3():
    signal = momentum_signal("t", [], citation_count=100, citation_source="s2", impl_count=2)

    assert signal == MomentumSignal(technique_id="t", score=3, direction="steady",
                                    citation_growth_pct=None, note=signal.note)


def test_new_implementation_scores_5():
    signal = momentum_signal("t", [_row(100, impls=2)], 100, "s2", impl_count=3)

    assert signal.score == 5
    assert signal.direction == "rising"
    assert "implementation" in signal.note


def test_citation_velocity_above_threshold_scores_4():
    signal = momentum_signal("t", [_row(100)], citation_count=115, citation_source="s2",
                             impl_count=2)

    assert signal.score == 4
    assert signal.direction == "rising"
    assert signal.citation_growth_pct == 15.0


def test_flat_citations_steady_3():
    signal = momentum_signal("t", [_row(100)], 104, "s2", impl_count=2)

    assert signal.score == 3
    assert signal.direction == "steady"


def test_negative_velocity_scores_2():
    signal = momentum_signal("t", [_row(100)], 90, "s2", impl_count=2)

    assert signal.score == 2
    assert signal.direction == "falling"


def test_negative_velocity_and_lost_impl_scores_1():
    signal = momentum_signal("t", [_row(100, impls=3)], 90, "s2", impl_count=2)

    assert signal.score == 1
    assert signal.direction == "falling"


def test_velocity_ignores_rows_from_other_source():
    # Last s2 row was 100; an openalex row in between must not poison the comparison.
    rows = [_row(100, "s2", at="2026-07-01T10:00:00+00:00"),
            _row(34, "openalex", at="2026-07-02T10:00:00+00:00")]

    signal = momentum_signal("t", rows, 115, "s2", impl_count=2)

    assert signal.citation_growth_pct == 15.0
    assert signal.score == 4


def test_no_same_source_history_means_no_velocity():
    signal = momentum_signal("t", [_row(34, "openalex")], 1697, "s2", impl_count=2)

    assert signal.citation_growth_pct is None
    assert signal.score == 3


def test_missing_current_citations_still_uses_impl_delta():
    signal = momentum_signal("t", [_row(100, impls=2)], None, None, impl_count=3)

    assert signal.score == 5
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_research_radar_momentum.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

Create `src/radar/research_radar/momentum.py`:

```python
"""Technique momentum: 1-5 score + direction from metric history.

Velocity only compares same-source citation counts (S2 vs OpenAlex counts
differ wildly for the same paper), while implementation deltas compare
against the most recent row of any source.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from radar.storage.technique_metrics_store import TechniqueMetrics


CITATION_RISING_PCT = 10.0


class MomentumSignal(BaseModel):
    model_config = ConfigDict(frozen=True)

    technique_id: str
    score: int  # 1-5, feeds TechniqueScore.momentum
    direction: str  # rising | falling | steady
    citation_growth_pct: float | None = None
    note: str = ""


def momentum_signal(
    technique_id: str,
    previous_rows: list[TechniqueMetrics],
    citation_count: int | None,
    citation_source: str | None,
    impl_count: int,
) -> MomentumSignal:
    """Rows are oldest-first and exclude the current scan (compute before persist)."""
    growth = _citation_growth_pct(previous_rows, citation_count, citation_source)
    impl_delta = _impl_delta(previous_rows, impl_count)
    if impl_delta is not None and impl_delta > 0:
        return MomentumSignal(
            technique_id=technique_id, score=5, direction="rising",
            citation_growth_pct=growth,
            note=f"+{impl_delta} tracked implementation(s) since last scan.",
        )
    if growth is not None and growth < 0:
        lost = impl_delta is not None and impl_delta < 0
        return MomentumSignal(
            technique_id=technique_id, score=1 if lost else 2, direction="falling",
            citation_growth_pct=growth,
            note="Citations falling" + (" and an implementation dropped." if lost else "."),
        )
    if growth is not None and growth >= CITATION_RISING_PCT:
        return MomentumSignal(
            technique_id=technique_id, score=4, direction="rising",
            citation_growth_pct=growth,
            note=f"Citations {growth:+.1f}% since last comparable scan.",
        )
    return MomentumSignal(technique_id=technique_id, score=3, direction="steady",
                          citation_growth_pct=growth)


def _citation_growth_pct(
    rows: list[TechniqueMetrics], current: int | None, source: str | None,
) -> float | None:
    if current is None or source is None:
        return None
    for row in reversed(rows):  # most recent same-source row wins
        if row.citation_source == source and row.citation_count:
            return round((current - row.citation_count) / row.citation_count * 100, 1)
    return None


def _impl_delta(rows: list[TechniqueMetrics], current: int) -> int | None:
    for row in reversed(rows):
        if row.resolved_impls is not None:
            return current - row.resolved_impls
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_research_radar_momentum.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Lint + typecheck + commit**

```bash
uv run ruff check src/radar/research_radar tests/test_research_radar_momentum.py && uv run mypy src/radar
git add src/radar/research_radar/momentum.py tests/test_research_radar_momentum.py
git commit -m "feat: technique momentum signal (same-source citation velocity)"
```

---

### Task 8: Scoring + ring gate

**Files:**
- Create: `src/radar/research_radar/scoring.py`
- Test: `tests/test_research_radar_scoring.py`

**Interfaces:**
- Consumes: `TechniqueEntry`, `TechniqueScore`, `OnPremImpact`, `ResolvedImplementation`, `ImplKind` (Task 1), `MomentumSignal` (Task 7), `Ring`.
- Produces: `score_technique(entry: TechniqueEntry, momentum: MomentumSignal) -> TechniqueScore`, `technique_ring(score: TechniqueScore, resolved_count: int) -> Ring`. Module constants: `CITATIONS_HIGH = 500`, `CITATIONS_MID = 100`, `CITATIONS_LOW = 25`, `_IMPACT_SCORE`.

Ladders from the spec:
- breadth: 0→1, 1→2, 2→3, 3–4→4, ≥5→5 (resolved implementations only).
- maturity over resolved rings: ≥2 adopt→5, 1 adopt→4, best is pilot→3, any watch→2, none/unringed→1 (avoid-ring impls count as unringed — an avoided tool is not evidence of maturity).
- validation: `superseded_by` set → 1; `citation_count is None` → 2; peer-reviewed and ≥500 → 5; ≥100 → 4; ≥25 or peer-reviewed → 3; else 2.
- reproducibility: open_code and ≥1 resolved TOOL impl → 5; open_code only → 4; tool impl only → 3; neither → 1.
- momentum: `momentum.score` (Task 7).
- onprem_impact: reduces_memory 5, reduces_latency 5, enables_scale 4, improves_safety 4, improves_quality 3.
- ring: avg < 2.0 → AVOID; resolved_count == 0 → WATCH (cap; checked after AVOID so AVOID stays reachable); avg ≥ 4.0 and maturity ≥ 4 → ADOPT; avg ≥ 3.0 → PILOT; else WATCH.

- [ ] **Step 1: Write the failing tests**

```python
"""Six scoring ladders + the technique ring gate, boundary by boundary."""

import pytest

from radar.models import Category, Ring
from radar.research_radar.entities import (
    ImplKind,
    OnPremImpact,
    ResolvedImplementation,
    TechniqueDomain,
    TechniqueEntry,
    TechniqueScore,
)
from radar.research_radar.momentum import MomentumSignal
from radar.research_radar.scoring import score_technique, technique_ring


def _impl(ring: Ring | None, kind: ImplKind = ImplKind.TOOL, ref: str = "x"):
    return ResolvedImplementation(kind=kind, ref=ref, ring=ring)


def _entry(impls=(), citations=None, peer_reviewed=None, open_code=False,
           superseded=None, impact=OnPremImpact.IMPROVES_QUALITY) -> TechniqueEntry:
    return TechniqueEntry(
        id="t", name="t", category=Category.MODEL_SERVING,
        domain=TechniqueDomain.INFERENCE, onprem_impact=impact,
        resolved_implementations=list(impls), citation_count=citations,
        peer_reviewed=peer_reviewed, open_code=open_code, superseded_by=superseded,
    )


def _steady() -> MomentumSignal:
    return MomentumSignal(technique_id="t", score=3, direction="steady")


@pytest.mark.parametrize(("impl_count", "expected"), [(0, 1), (1, 2), (2, 3), (3, 4),
                                                      (4, 4), (5, 5), (7, 5)])
def test_breadth_ladder(impl_count, expected):
    impls = [_impl(Ring.WATCH, ref=f"tool-{i}") for i in range(impl_count)]

    score = score_technique(_entry(impls=impls), _steady())

    assert score.implementation_breadth == expected


def test_maturity_two_adopts_is_5():
    impls = [_impl(Ring.ADOPT, ref="a"), _impl(Ring.ADOPT, ref="b")]
    assert score_technique(_entry(impls=impls), _steady()).implementation_maturity == 5


def test_maturity_one_adopt_is_4():
    impls = [_impl(Ring.ADOPT), _impl(Ring.WATCH, ref="w")]
    assert score_technique(_entry(impls=impls), _steady()).implementation_maturity == 4


def test_maturity_best_pilot_is_3():
    assert score_technique(_entry(impls=[_impl(Ring.PILOT)]), _steady()).implementation_maturity == 3


def test_maturity_watch_only_is_2():
    assert score_technique(_entry(impls=[_impl(Ring.WATCH)]), _steady()).implementation_maturity == 2


def test_maturity_unringed_or_avoid_is_1():
    assert score_technique(_entry(impls=[_impl(None)]), _steady()).implementation_maturity == 1
    assert score_technique(_entry(impls=[_impl(Ring.AVOID)]), _steady()).implementation_maturity == 1


def test_maturity_no_impls_is_1():
    assert score_technique(_entry(), _steady()).implementation_maturity == 1


@pytest.mark.parametrize(("citations", "peer_reviewed", "expected"), [
    (600, True, 5),   # peer-reviewed + >=500
    (600, False, 4),  # >=100 but not peer-reviewed → falls to the >=100 rung
    (150, False, 4),
    (30, False, 3),   # >=25
    (10, True, 3),    # peer-reviewed rescues low counts
    (10, False, 2),
    (None, None, 2),  # unknown → neutral
])
def test_validation_ladder(citations, peer_reviewed, expected):
    score = score_technique(_entry(citations=citations, peer_reviewed=peer_reviewed), _steady())

    assert score.validation == expected


def test_validation_superseded_forces_1():
    entry = _entry(citations=10_000, peer_reviewed=True, superseded="newer-technique")

    assert score_technique(entry, _steady()).validation == 1


def test_reproducibility_ladder():
    tool = [_impl(Ring.ADOPT)]
    model_only = [_impl(Ring.ADOPT, kind=ImplKind.MODEL)]
    assert score_technique(_entry(open_code=True, impls=tool), _steady()).reproducibility == 5
    assert score_technique(_entry(open_code=True), _steady()).reproducibility == 4
    assert score_technique(_entry(open_code=True, impls=model_only), _steady()).reproducibility == 4
    assert score_technique(_entry(impls=tool), _steady()).reproducibility == 3
    assert score_technique(_entry(), _steady()).reproducibility == 1


def test_onprem_impact_mapping():
    assert score_technique(_entry(impact=OnPremImpact.REDUCES_MEMORY), _steady()).onprem_impact == 5
    assert score_technique(_entry(impact=OnPremImpact.REDUCES_LATENCY), _steady()).onprem_impact == 5
    assert score_technique(_entry(impact=OnPremImpact.ENABLES_SCALE), _steady()).onprem_impact == 4
    assert score_technique(_entry(impact=OnPremImpact.IMPROVES_SAFETY), _steady()).onprem_impact == 4
    assert score_technique(_entry(impact=OnPremImpact.IMPROVES_QUALITY), _steady()).onprem_impact == 3


def test_momentum_flows_through_and_average_rounds():
    momentum = MomentumSignal(technique_id="t", score=5, direction="rising")

    score = score_technique(_entry(), momentum)

    assert score.momentum == 5
    expected = round((1 + 1 + 2 + 1 + 5 + 3) / 6, 2)
    assert score.average == expected


def _score(avg: float, maturity: int = 3) -> TechniqueScore:
    return TechniqueScore(
        implementation_breadth=3, implementation_maturity=maturity, validation=3,
        reproducibility=3, momentum=3, onprem_impact=3, average=avg,
    )


def test_ring_no_impls_caps_at_watch_even_with_high_average():
    assert technique_ring(_score(4.8, maturity=5), resolved_count=0) == Ring.WATCH


def test_ring_avoid_stays_reachable_below_the_cap():
    assert technique_ring(_score(1.5), resolved_count=0) == Ring.AVOID


def test_ring_adopt_needs_average_and_maturity():
    assert technique_ring(_score(4.2, maturity=4), resolved_count=3) == Ring.ADOPT
    assert technique_ring(_score(4.2, maturity=3), resolved_count=3) == Ring.PILOT


def test_ring_pilot_and_watch_thresholds():
    assert technique_ring(_score(3.0), resolved_count=2) == Ring.PILOT
    assert technique_ring(_score(2.9), resolved_count=2) == Ring.WATCH
    assert technique_ring(_score(1.9), resolved_count=2) == Ring.AVOID
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_research_radar_scoring.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

Create `src/radar/research_radar/scoring.py`:

```python
"""Deterministic technique scoring + ring gate.

The two implementation dimensions are the closed loop: they read the rings
the radar's *own* tool and model scans produced, so research verdicts move
when tool verdicts move. No network anywhere in this module.
"""

from __future__ import annotations

from radar.models import Ring
from radar.research_radar.entities import (
    ImplKind,
    OnPremImpact,
    ResolvedImplementation,
    TechniqueEntry,
    TechniqueScore,
)
from radar.research_radar.momentum import MomentumSignal


CITATIONS_HIGH = 500
CITATIONS_MID = 100
CITATIONS_LOW = 25

_IMPACT_SCORE = {
    OnPremImpact.REDUCES_MEMORY: 5,
    OnPremImpact.REDUCES_LATENCY: 5,
    OnPremImpact.ENABLES_SCALE: 4,
    OnPremImpact.IMPROVES_SAFETY: 4,
    OnPremImpact.IMPROVES_QUALITY: 3,
}


def score_technique(entry: TechniqueEntry, momentum: MomentumSignal) -> TechniqueScore:
    impls = entry.resolved_implementations
    breadth = _breadth(len(impls))
    maturity = _maturity(impls)
    validation = _validation(entry)
    reproducibility = _reproducibility(entry)
    impact = _IMPACT_SCORE[entry.onprem_impact]
    average = round(
        (breadth + maturity + validation + reproducibility + momentum.score + impact) / 6, 2
    )
    return TechniqueScore(
        implementation_breadth=breadth, implementation_maturity=maturity,
        validation=validation, reproducibility=reproducibility,
        momentum=momentum.score, onprem_impact=impact, average=average,
    )


def technique_ring(score: TechniqueScore, resolved_count: int) -> Ring:
    """Absolute gates. The zero-implementation cap comes after AVOID on purpose:
    you cannot adopt what you cannot run on-prem, but AVOID stays reachable."""
    if score.average < 2.0:
        return Ring.AVOID
    if resolved_count == 0:
        return Ring.WATCH
    if score.average >= 4.0 and score.implementation_maturity >= 4:
        return Ring.ADOPT
    if score.average >= 3.0:
        return Ring.PILOT
    return Ring.WATCH


def _breadth(count: int) -> int:
    if count >= 5:
        return 5
    if count >= 3:
        return 4
    return count + 1  # 0→1, 1→2, 2→3


def _maturity(impls: list[ResolvedImplementation]) -> int:
    """Avoid-ring implementations count as unringed: not evidence of maturity."""
    rings = [i.ring for i in impls if i.ring is not None and i.ring != Ring.AVOID]
    adopts = sum(1 for r in rings if r == Ring.ADOPT)
    if adopts >= 2:
        return 5
    if adopts == 1:
        return 4
    if Ring.PILOT in rings:
        return 3
    if Ring.WATCH in rings:
        return 2
    return 1


def _validation(entry: TechniqueEntry) -> int:
    if entry.superseded_by is not None:
        return 1
    count = entry.citation_count
    if count is None:
        return 2  # unknown → neutral; the entry carries a "citations unknown" warning
    peer_reviewed = bool(entry.peer_reviewed)
    if peer_reviewed and count >= CITATIONS_HIGH:
        return 5
    if count >= CITATIONS_MID:
        return 4
    if count >= CITATIONS_LOW or peer_reviewed:
        return 3
    return 2


def _reproducibility(entry: TechniqueEntry) -> int:
    has_tool_impl = any(
        i.kind == ImplKind.TOOL for i in entry.resolved_implementations
    )
    if entry.open_code and has_tool_impl:
        return 5
    if entry.open_code:
        return 4
    if has_tool_impl:
        return 3
    return 1
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_research_radar_scoring.py -v`
Expected: PASS (all parametrized boundaries)

- [ ] **Step 5: Lint + typecheck + commit**

```bash
uv run ruff check src/radar/research_radar tests/test_research_radar_scoring.py && uv run mypy src/radar
git add src/radar/research_radar/scoring.py tests/test_research_radar_scoring.py
git commit -m "feat: technique scoring ladders + ring gate (closed-loop maturity)"
```

---

### Task 9: Pipeline (assemble → momentum → score → persist)

**Files:**
- Create: `src/radar/research_radar/pipeline.py`
- Test: `tests/test_research_radar_pipeline.py`

**Interfaces:**
- Consumes: everything from Tasks 1–8.
- Produces:
  - `assemble_entries(seeds: list[TechniqueSeed], context: ResolutionContext, citations: dict[str, CitationRecord], store: TechniqueMetricsStore) -> list[TechniqueEntry]` — resolves impls, applies fresh citations (a technique's count = max over its papers, `peer_reviewed` = any), falls back to last-known store values with a warning, warns "citations unknown" when neither exists. Disabled seeds are skipped. Sorted by id.
  - `score_technique_entries(entries: list[TechniqueEntry], store: TechniqueMetricsStore) -> list[TechniqueEntry]` — computes momentum per entry from `store.history_for(id)` (pre-persist!), returns new entries with score/breakdown/ring (immutable `model_copy`).
  - `persist_technique_scan(entries, run_id: str, observed_at: datetime, db_path: Path, history_path: Path) -> list[TechniqueHistoryEvent]` — diff vs `_latest_rings(history_path)`, append events, record metrics rows.
  - `momentum_for(entries: list[TechniqueEntry], db_path: Path) -> dict[str, MomentumSignal]` — post-hoc momentum for CLI display (uses `history_for` which then includes the current scan; direction only, mirrors `models_radar.pipeline.momentum_for`).
  - `run_research_scan(seed_path, config_path, db_path, model_seed_path, model_history_path, history_path, client, contact_email=None) -> tuple[list[TechniqueEntry], list[TechniqueHistoryEvent]]` — the full async flow; only `load_technique_seed` may raise.

- [ ] **Step 1: Write the failing tests**

```python
"""Pipeline integration: assemble → momentum → score → persist, offline determinism."""

from datetime import UTC, datetime

import pytest

from radar.models import Ring
from radar.research_radar.citations import CitationRecord
from radar.research_radar.entities import TechniqueSeed
from radar.research_radar.pipeline import (
    assemble_entries,
    persist_technique_scan,
    run_research_scan,
    score_technique_entries,
)
from radar.research_radar.resolve import ResolutionContext
from radar.storage.technique_metrics_store import TechniqueMetricsStore


NOW = datetime(2026, 7, 3, 10, 0, tzinfo=UTC)

SEED_YAML = """
techniques:
  - id: speculative-decoding
    name: Speculative Decoding
    category: model_serving
    domain: inference
    papers:
      - arxiv_id: "2211.17192"
        title: "Fast Inference from Transformers via Speculative Decoding"
    implementations:
      - kind: tool
        ref: github-vllm
      - kind: tool
        ref: github-llama-cpp
      - kind: tool
        ref: github-gone-tool
    open_code: true
    onprem_impact: reduces_latency
  - id: qlora
    name: QLoRA
    category: ai_infrastructure
    domain: fine_tuning
    papers:
      - arxiv_id: "2305.14314"
        title: "QLoRA"
    open_code: true
    onprem_impact: reduces_memory
  - id: disabled-one
    name: Disabled
    category: model_serving
    domain: inference
    onprem_impact: reduces_latency
    enabled: false
"""


def _seeds() -> list[TechniqueSeed]:
    import yaml

    raw = yaml.safe_load(SEED_YAML)
    return [TechniqueSeed.model_validate(item) for item in raw["techniques"]]


def _context() -> ResolutionContext:
    return ResolutionContext(
        tool_rings={"github-vllm": Ring.ADOPT, "github-llama-cpp": Ring.ADOPT},
        model_rings={},
    )


def _citations() -> dict[str, CitationRecord]:
    return {"2211.17192": CitationRecord(
        arxiv_id="2211.17192", citation_count=1697, venue="ICML",
        peer_reviewed=True, source="s2",
    )}


def test_assemble_resolves_warns_and_skips_disabled(tmp_path):
    store = TechniqueMetricsStore(tmp_path / "radar.db")
    store.initialize()

    entries = assemble_entries(_seeds(), _context(), _citations(), store)

    assert [e.id for e in entries] == ["qlora", "speculative-decoding"]  # sorted, no disabled
    spec = entries[1]
    assert len(spec.resolved_implementations) == 2  # gone-tool dropped
    assert any("github-gone-tool" in w for w in spec.warnings)
    assert spec.citation_count == 1697
    assert spec.peer_reviewed is True
    qlora = entries[0]
    assert qlora.citation_count is None
    assert any("citations unknown" in w for w in qlora.warnings)


def test_assemble_falls_back_to_last_known_citations(tmp_path):
    from radar.storage.technique_metrics_store import TechniqueMetrics

    store = TechniqueMetricsStore(tmp_path / "radar.db")
    store.initialize()
    store.record([TechniqueMetrics(
        technique_id="qlora", run_id="run-0", observed_at=NOW,
        citation_count=800, citation_source="s2", resolved_impls=0,
    )])

    entries = assemble_entries(_seeds(), _context(), {}, store)

    qlora = [e for e in entries if e.id == "qlora"][0]
    assert qlora.citation_count == 800
    assert qlora.citation_source == "s2"
    assert any("last-known" in w for w in qlora.warnings)


def test_score_and_ring_closed_loop(tmp_path):
    store = TechniqueMetricsStore(tmp_path / "radar.db")
    store.initialize()
    entries = assemble_entries(_seeds(), _context(), _citations(), store)

    scored = score_technique_entries(entries, store)

    by_id = {e.id: e for e in scored}
    # Two adopt-ring impls + peer-reviewed 1697 citations + open code → ADOPT.
    spec = by_id["speculative-decoding"]
    assert spec.score_breakdown.implementation_maturity == 5
    assert spec.score_breakdown.validation == 5
    assert spec.ring == Ring.ADOPT
    # No resolved implementations → capped at WATCH despite open code.
    assert by_id["qlora"].ring == Ring.WATCH


def test_persist_appends_history_and_metrics_once(tmp_path):
    db = tmp_path / "radar.db"
    history = tmp_path / "technique-history.jsonl"
    store = TechniqueMetricsStore(db)
    store.initialize()
    entries = score_technique_entries(
        assemble_entries(_seeds(), _context(), _citations(), store), store
    )

    events_first = persist_technique_scan(entries, "run-1", NOW, db, history)
    events_second = persist_technique_scan(entries, "run-2", NOW, db, history)

    assert {e.technique_id for e in events_first} == {"speculative-decoding", "qlora"}
    assert events_second == []  # unchanged rings emit nothing
    assert len(store.history_for("speculative-decoding")) == 2


@pytest.mark.asyncio
async def test_run_research_scan_offline_is_deterministic(tmp_path):
    """Both citation APIs down → warnings, neutral validation, same rings twice."""

    class _DownClient:
        async def post(self, url, **kwargs):
            raise RuntimeError("offline")

        async def get(self, url, **kwargs):
            raise RuntimeError("offline")

    seed_path = tmp_path / "technique-seed.yaml"
    seed_path.write_text(SEED_YAML, encoding="utf-8")

    async def _scan():
        return await run_research_scan(
            seed_path=seed_path,
            config_path=tmp_path / "missing-config.yaml",
            db_path=tmp_path / "radar.db",
            model_seed_path=tmp_path / "missing-model-seed.yaml",
            model_history_path=tmp_path / "model-history.jsonl",
            history_path=tmp_path / "technique-history.jsonl",
            client=_DownClient(),
        )

    entries_a, events_a = await _scan()
    entries_b, events_b = await _scan()

    assert [e.ring for e in entries_a] == [e.ring for e in entries_b]
    # config missing → vllm/llama-cpp unresolved → spec-decoding also capped at WATCH
    assert all(e.ring == Ring.WATCH for e in entries_a)
    assert events_b == []  # second scan: nothing changed
    assert all(any("citations unknown" in w for w in e.warnings) for e in entries_a)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_research_radar_pipeline.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

Create `src/radar/research_radar/pipeline.py`:

```python
"""Technique decision pipeline: assemble → momentum → score → persist."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from radar.models import Ring
from radar.research_radar.citations import CitationRecord, fetch_citations
from radar.research_radar.entities import TechniqueEntry, TechniqueSeed
from radar.research_radar.history import (
    TechniqueHistoryEvent,
    append_technique_events,
    diff_technique_rings,
    load_technique_events,
)
from radar.research_radar.momentum import MomentumSignal, momentum_signal
from radar.research_radar.resolve import (
    ResolutionContext,
    build_resolution_context,
    resolve_implementations,
)
from radar.research_radar.scoring import score_technique, technique_ring
from radar.research_radar.seed import load_technique_seed
from radar.storage.technique_metrics_store import TechniqueMetrics, TechniqueMetricsStore


def assemble_entries(
    seeds: list[TechniqueSeed],
    context: ResolutionContext,
    citations: dict[str, CitationRecord],
    store: TechniqueMetricsStore,
) -> list[TechniqueEntry]:
    """Pre-score entries: resolved impls + citations (fresh, else last-known)."""
    entries: list[TechniqueEntry] = []
    for seed in seeds:
        if not seed.enabled:
            continue
        resolved, warnings = resolve_implementations(seed.implementations, context)
        count, source, peer_reviewed, citation_warnings = _citation_fields(
            seed, citations, store
        )
        entries.append(TechniqueEntry(
            id=seed.id, name=seed.name, category=seed.category, domain=seed.domain,
            aliases=seed.aliases, papers=seed.papers,
            resolved_implementations=resolved, open_code=seed.open_code,
            onprem_impact=seed.onprem_impact, superseded_by=seed.superseded_by,
            notes=seed.notes, citation_count=count, citation_source=source,
            peer_reviewed=peer_reviewed, warnings=warnings + citation_warnings,
        ))
    return sorted(entries, key=lambda e: e.id)


def score_technique_entries(
    entries: list[TechniqueEntry], store: TechniqueMetricsStore,
) -> list[TechniqueEntry]:
    """New entries with score/breakdown/ring. Momentum reads the store PRE-persist."""
    scored: list[TechniqueEntry] = []
    for entry in entries:
        momentum = momentum_signal(
            entry.id, store.history_for(entry.id), entry.citation_count,
            entry.citation_source, len(entry.resolved_implementations),
        )
        breakdown = score_technique(entry, momentum)
        ring = technique_ring(breakdown, len(entry.resolved_implementations))
        scored.append(entry.model_copy(update={
            "score": breakdown.average, "score_breakdown": breakdown, "ring": ring,
        }))
    return scored


def persist_technique_scan(
    entries: list[TechniqueEntry],
    run_id: str,
    observed_at: datetime,
    db_path: Path,
    history_path: Path,
) -> list[TechniqueHistoryEvent]:
    """Diff rings vs the log, append new events, record per-scan metrics."""
    previous = _latest_rings(history_path)
    events = diff_technique_rings(entries, previous, run_id, observed_at)
    append_technique_events(history_path, events)
    store = TechniqueMetricsStore(db_path)
    store.initialize()
    store.record([TechniqueMetrics(
        technique_id=entry.id, run_id=run_id, observed_at=observed_at,
        citation_count=entry.citation_count, citation_source=entry.citation_source,
        resolved_impls=len(entry.resolved_implementations),
        ring=(entry.ring.value if entry.ring else None),
    ) for entry in entries])
    return events


def momentum_for(
    entries: list[TechniqueEntry], db_path: Path,
) -> dict[str, MomentumSignal]:
    """Post-hoc momentum for display (history here includes the current scan)."""
    store = TechniqueMetricsStore(db_path)
    store.initialize()
    result: dict[str, MomentumSignal] = {}
    for entry in entries:
        rows = store.history_for(entry.id)
        result[entry.id] = momentum_signal(
            entry.id, rows[:-1], entry.citation_count, entry.citation_source,
            len(entry.resolved_implementations),
        )
    return result


async def run_research_scan(
    seed_path: Path,
    config_path: Path,
    db_path: Path,
    model_seed_path: Path,
    model_history_path: Path,
    history_path: Path,
    client: Any,
    contact_email: str | None = None,
    run_id: str | None = None,
) -> tuple[list[TechniqueEntry], list[TechniqueHistoryEvent]]:
    """Full scan. Only the seed load may raise; everything else degrades."""
    seeds = load_technique_seed(seed_path)  # fails loud before any network
    context = build_resolution_context(
        config_path, db_path, model_seed_path, model_history_path
    )
    arxiv_ids = sorted({
        paper.arxiv_id for seed in seeds if seed.enabled for paper in seed.papers
    })
    citations = await fetch_citations(arxiv_ids, client, contact_email)
    store = TechniqueMetricsStore(db_path)
    store.initialize()
    entries = assemble_entries(seeds, context, citations, store)
    entries = score_technique_entries(entries, store)
    observed_at = datetime.now(UTC)
    resolved_run_id = run_id or observed_at.strftime("research-%Y%m%d-%H%M%S")
    events = persist_technique_scan(
        entries, resolved_run_id, observed_at, db_path, history_path,
    )
    return entries, events


def _latest_rings(history_path: Path) -> dict[str, Ring]:
    rings: dict[str, Ring] = {}
    for event in load_technique_events(history_path):  # oldest-first → last wins
        rings[event.technique_id] = event.ring
    return rings


def _citation_fields(
    seed: TechniqueSeed,
    citations: dict[str, CitationRecord],
    store: TechniqueMetricsStore,
) -> tuple[int | None, str | None, bool | None, list[str]]:
    """(count, source, peer_reviewed, warnings): fresh max-over-papers, else last-known."""
    fresh = [citations[p.arxiv_id] for p in seed.papers if p.arxiv_id in citations]
    if fresh:
        best = max(fresh, key=lambda r: r.citation_count)
        return (best.citation_count, best.source,
                any(r.peer_reviewed for r in fresh), [])
    last = store.latest(seed.id)
    if last is not None and last.citation_count is not None:
        return (last.citation_count, last.citation_source, None,
                ["citations: using last-known value (APIs unavailable)"])
    if seed.papers:
        return None, None, None, ["citations unknown (never fetched)"]
    return None, None, None, ["citations unknown (no papers seeded)"]
```

The optional `run_id` parameter exists because the CLI (Task 11) passes its own `RunStore` run id; the timestamp form is the library-use fallback.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_research_radar_pipeline.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Lint + typecheck + commit**

```bash
uv run ruff check src/radar/research_radar tests/test_research_radar_pipeline.py && uv run mypy src/radar
git add src/radar/research_radar/pipeline.py tests/test_research_radar_pipeline.py
git commit -m "feat: research scan pipeline (assemble, score, persist, degrade offline)"
```

---

### Task 10: Starter technique seed (15 techniques, verified arXiv ids)

**Files:**
- Create: `config/technique-seed.yaml`
- Test: add to `tests/test_research_radar_entities_seed.py`

**Interfaces:**
- Consumes: `load_technique_seed` (Task 1); packaged `config/seed-sources.yaml` source ids and `config/model-seed.yaml` model ids (implementation refs below use only ids that exist there today: `github-vllm`, `github-sglang`, `github-llama-cpp`, `github-tensorrt-llm`, `github-lmdeploy`, `github-langgraph`, `github-crewai`, `github-agno`, `github-autogen`, `github-pydantic-ai`, `qwen3-30b-a3b`).
- Produces: the packaged starter seed the CLI falls back to.

- [ ] **Step 1: Write the failing test (append to tests/test_research_radar_entities_seed.py)**

```python
def test_packaged_starter_seed_loads_and_is_coherent():
    packaged = Path(__file__).resolve().parents[1] / "config" / "technique-seed.yaml"

    seeds = load_technique_seed(packaged)

    assert len(seeds) >= 15
    assert len({s.id for s in seeds}) == len(seeds)
    domains = {s.domain for s in seeds}
    assert TechniqueDomain.INFERENCE in domains
    assert TechniqueDomain.FINE_TUNING in domains
    assert TechniqueDomain.AGENT_ARCHITECTURE in domains
    assert TechniqueDomain.RAG in domains
    # every technique with papers has exactly one canonical paper
    for seed in seeds:
        if seed.papers:
            assert sum(1 for p in seed.papers if p.role.value == "canonical") == 1
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_research_radar_entities_seed.py::test_packaged_starter_seed_loads_and_is_coherent -v`
Expected: FAIL — `TechniqueSeedError: Technique seed not found`

- [ ] **Step 3: Create `config/technique-seed.yaml`**

```yaml
# Starter technique seed — curated evidence-linked research techniques.
# implementations[].ref must be a source id (kind: tool) from
# config/seed-sources.yaml / data/config.yaml, or a model id (kind: model)
# from config/model-seed.yaml. Expansion to 60-100 techniques is a separate
# curated pass (spec §8).
techniques:
  - id: speculative-decoding
    name: Speculative Decoding
    category: model_serving
    domain: inference
    aliases: ["speculative sampling", "draft model decoding"]
    papers:
      - arxiv_id: "2211.17192"
        title: "Fast Inference from Transformers via Speculative Decoding"
        published: "2022-11"
      - arxiv_id: "2302.01318"
        title: "Accelerating Large Language Model Decoding with Speculative Sampling"
        role: followup
        published: "2023-02"
    implementations:
      - kind: tool
        ref: github-vllm
      - kind: tool
        ref: github-sglang
      - kind: tool
        ref: github-llama-cpp
      - kind: tool
        ref: github-tensorrt-llm
    open_code: true
    onprem_impact: reduces_latency

  - id: paged-attention
    name: PagedAttention
    category: model_serving
    domain: inference
    aliases: ["paged KV cache"]
    papers:
      - arxiv_id: "2309.06180"
        title: "Efficient Memory Management for Large Language Model Serving with PagedAttention"
        published: "2023-09"
    implementations:
      - kind: tool
        ref: github-vllm
      - kind: tool
        ref: github-tensorrt-llm
      - kind: tool
        ref: github-lmdeploy
    open_code: true
    onprem_impact: reduces_memory

  - id: flash-attention
    name: FlashAttention
    category: model_serving
    domain: inference
    papers:
      - arxiv_id: "2205.14135"
        title: "FlashAttention: Fast and Memory-Efficient Exact Attention with IO-Awareness"
        published: "2022-05"
      - arxiv_id: "2307.08691"
        title: "FlashAttention-2: Faster Attention with Better Parallelism and Work Partitioning"
        role: followup
        published: "2023-07"
    implementations:
      - kind: tool
        ref: github-vllm
      - kind: tool
        ref: github-sglang
      - kind: tool
        ref: github-tensorrt-llm
    open_code: true
    onprem_impact: reduces_latency

  - id: mixture-of-experts
    name: Mixture of Experts (sparse routing)
    category: model_serving
    domain: inference
    aliases: ["MoE", "sparse expert models"]
    papers:
      - arxiv_id: "2101.03961"
        title: "Switch Transformers: Scaling to Trillion Parameter Models"
        published: "2021-01"
      - arxiv_id: "2401.04088"
        title: "Mixtral of Experts"
        role: followup
        published: "2024-01"
    implementations:
      - kind: tool
        ref: github-vllm
      - kind: model
        ref: qwen3-30b-a3b
    open_code: true
    onprem_impact: enables_scale

  - id: medusa-decoding
    name: Medusa (multi-head decoding)
    category: model_serving
    domain: inference
    papers:
      - arxiv_id: "2401.10774"
        title: "Medusa: Simple LLM Inference Acceleration Framework with Multiple Decoding Heads"
        published: "2024-01"
    implementations:
      - kind: tool
        ref: github-tensorrt-llm
    open_code: true
    onprem_impact: reduces_latency

  - id: structured-generation
    name: Structured / Constrained Generation
    category: model_serving
    domain: inference
    aliases: ["guided decoding", "grammar-constrained decoding"]
    papers:
      - arxiv_id: "2307.09702"
        title: "Efficient Guided Generation for Large Language Models"
        published: "2023-07"
    implementations:
      - kind: tool
        ref: github-sglang
      - kind: tool
        ref: github-vllm
    open_code: true
    onprem_impact: improves_safety

  - id: gptq
    name: GPTQ Quantization
    category: model_serving
    domain: inference
    papers:
      - arxiv_id: "2210.17323"
        title: "GPTQ: Accurate Post-Training Quantization for Generative Pre-trained Transformers"
        published: "2022-10"
    implementations:
      - kind: tool
        ref: github-vllm
    open_code: true
    onprem_impact: reduces_memory

  - id: awq
    name: AWQ (Activation-aware Weight Quantization)
    category: model_serving
    domain: inference
    papers:
      - arxiv_id: "2306.00978"
        title: "AWQ: Activation-aware Weight Quantization for LLM Compression and Acceleration"
        published: "2023-06"
    implementations:
      - kind: tool
        ref: github-vllm
      - kind: tool
        ref: github-lmdeploy
    open_code: true
    onprem_impact: reduces_memory

  - id: lora
    name: LoRA (Low-Rank Adaptation)
    category: ai_infrastructure
    domain: fine_tuning
    papers:
      - arxiv_id: "2106.09685"
        title: "LoRA: Low-Rank Adaptation of Large Language Models"
        published: "2021-06"
    implementations:
      - kind: tool
        ref: github-vllm
      - kind: tool
        ref: github-llama-cpp
    open_code: true
    onprem_impact: reduces_memory

  - id: qlora
    name: QLoRA (Quantized LoRA fine-tuning)
    category: ai_infrastructure
    domain: fine_tuning
    papers:
      - arxiv_id: "2305.14314"
        title: "QLoRA: Efficient Finetuning of Quantized LLMs"
        published: "2023-05"
    open_code: true
    onprem_impact: reduces_memory
    notes: "No tracked implementation yet — WATCH by construction until one lands."

  - id: dpo
    name: DPO (Direct Preference Optimization)
    category: ai_infrastructure
    domain: fine_tuning
    papers:
      - arxiv_id: "2305.18290"
        title: "Direct Preference Optimization: Your Language Model is Secretly a Reward Model"
        published: "2023-05"
    open_code: true
    onprem_impact: improves_quality
    notes: "No tracked implementation yet — WATCH by construction until one lands."

  - id: react
    name: ReAct (Reason + Act)
    category: agent_frameworks
    domain: agent_architecture
    papers:
      - arxiv_id: "2210.03629"
        title: "ReAct: Synergizing Reasoning and Acting in Language Models"
        published: "2022-10"
    implementations:
      - kind: tool
        ref: github-langgraph
      - kind: tool
        ref: github-crewai
      - kind: tool
        ref: github-agno
    open_code: true
    onprem_impact: improves_quality

  - id: reflexion
    name: Reflexion (self-reflection loops)
    category: agent_frameworks
    domain: agent_architecture
    papers:
      - arxiv_id: "2303.11366"
        title: "Reflexion: Language Agents with Verbal Reinforcement Learning"
        published: "2023-03"
    implementations:
      - kind: tool
        ref: github-langgraph
    open_code: true
    onprem_impact: improves_quality

  - id: llm-tool-use
    name: LLM Tool Use / Function Calling
    category: agent_frameworks
    domain: agent_architecture
    aliases: ["function calling", "tool calling"]
    papers:
      - arxiv_id: "2302.04761"
        title: "Toolformer: Language Models Can Teach Themselves to Use Tools"
        published: "2023-02"
    implementations:
      - kind: tool
        ref: github-langgraph
      - kind: tool
        ref: github-pydantic-ai
      - kind: tool
        ref: github-autogen
    open_code: false
    onprem_impact: improves_quality
    notes: "Canonical paper has no official public code; adoption evidence is the impls."

  - id: rag
    name: Retrieval-Augmented Generation
    category: ai_infrastructure
    domain: rag
    aliases: ["RAG"]
    papers:
      - arxiv_id: "2005.11401"
        title: "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks"
        published: "2020-05"
    implementations:
      - kind: tool
        ref: github-langgraph
      - kind: tool
        ref: github-crewai
    open_code: true
    onprem_impact: improves_quality
```

- [ ] **Step 4: Verify every arXiv id resolves (one live batch call)**

Run:

```bash
curl -s -X POST "https://api.semanticscholar.org/graph/v1/paper/batch?fields=title,citationCount" \
  -H "Content-Type: application/json" \
  -d '{"ids":["ARXIV:2211.17192","ARXIV:2302.01318","ARXIV:2309.06180","ARXIV:2205.14135","ARXIV:2307.08691","ARXIV:2101.03961","ARXIV:2401.04088","ARXIV:2401.10774","ARXIV:2307.09702","ARXIV:2210.17323","ARXIV:2306.00978","ARXIV:2106.09685","ARXIV:2305.14314","ARXIV:2305.18290","ARXIV:2210.03629","ARXIV:2303.11366","ARXIV:2302.04761","ARXIV:2005.11401"]}' \
  | python3 -c "import json,sys; data=json.load(sys.stdin); nulls=[i for i,d in enumerate(data) if not d]; print('nulls at positions:', nulls); [print(d['title'][:70], d['citationCount']) for d in data if d]"
```

Expected: `nulls at positions: []` and 18 titles that match the seed's titles. If any position is null or a title clearly mismatches, fix that seed entry's `arxiv_id`/`title` before continuing (do NOT ship an unverified id).

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/test_research_radar_entities_seed.py -v`
Expected: PASS (the new test and all Task 1 tests)

- [ ] **Step 6: Commit**

```bash
git add config/technique-seed.yaml tests/test_research_radar_entities_seed.py
git commit -m "feat: starter technique seed (15 techniques, verified arXiv ids)"
```

---

### Task 11: Reports + CLI (`radar research scan | list | show`)

**Files:**
- Create: `src/radar/research_radar/reports.py`
- Modify: `src/radar/cli.py` (add `research_app` after the `models_app` block at `src/radar/cli.py:30-31`)
- Test: `tests/test_research_radar_reports.py`, `tests/test_research_cli.py`

**Interfaces:**
- Consumes: `TechniqueEntry`, `TechniqueHistoryEvent`, `MomentumSignal`, `momentum_for`, `run_research_scan`, `load_technique_events`; existing `RunStore` (`create_run`, `save_stage`, `update_meta`, `read_meta`, `list_runs`, `_run_dir`), `console` from cli.py.
- Produces: `build_technique_mover_lines(events: list[TechniqueHistoryEvent], momentums: list[MomentumSignal]) -> list[str]`, `render_technique_report(entries: list[TechniqueEntry], mover_lines: list[str], title: str) -> str`; CLI commands `research scan`, `research list [--ring/--domain/--category]`, `research show <id>`.

- [ ] **Step 1: Write the failing report tests (tests/test_research_radar_reports.py)**

```python
"""Mover lines + markdown report for techniques."""

from datetime import UTC, datetime

from radar.models import Category, Ring
from radar.research_radar.entities import OnPremImpact, TechniqueDomain, TechniqueEntry
from radar.research_radar.history import TechniqueHistoryEvent
from radar.research_radar.momentum import MomentumSignal
from radar.research_radar.reports import build_technique_mover_lines, render_technique_report
from radar.storage.history_store import ChangeType


NOW = datetime(2026, 7, 3, 10, 0, tzinfo=UTC)


def _event(technique_id: str, change: ChangeType, ring: Ring,
           previous: Ring | None = None) -> TechniqueHistoryEvent:
    return TechniqueHistoryEvent(
        technique_id=technique_id, domain=TechniqueDomain.INFERENCE, change_type=change,
        ring=ring, previous_ring=previous, run_id="run-1", observed_at=NOW,
    )


def _entry(technique_id: str, ring: Ring) -> TechniqueEntry:
    return TechniqueEntry(
        id=technique_id, name=technique_id.title(), category=Category.MODEL_SERVING,
        domain=TechniqueDomain.INFERENCE, onprem_impact=OnPremImpact.REDUCES_LATENCY,
        ring=ring, citation_count=100,
    )


def test_mover_lines_ring_changes_then_rising():
    events = [
        _event("medusa-decoding", ChangeType.PROMOTED, Ring.PILOT, Ring.WATCH),
        _event("qlora", ChangeType.NEW, Ring.WATCH),
    ]
    momentums = [
        MomentumSignal(technique_id="lora", score=4, direction="rising",
                       citation_growth_pct=12.0),
        MomentumSignal(technique_id="medusa-decoding", score=5, direction="rising"),
        MomentumSignal(technique_id="rag", score=3, direction="steady"),
    ]

    lines = build_technique_mover_lines(events, momentums)

    assert lines[0] == "medusa-decoding: watch → pilot (promoted)"
    assert lines[1] == "qlora: new on the radar (watch)"
    assert any(line.startswith("lora: rising") for line in lines)
    assert not any("medusa-decoding: rising" in line for line in lines)  # no double-report
    assert not any("rag" in line for line in lines)


def test_render_report_contains_movers_and_rings():
    entries = [_entry("speculative-decoding", Ring.ADOPT), _entry("qlora", Ring.WATCH)]

    markdown = render_technique_report(entries, ["qlora: new on the radar (watch)"],
                                       "Research Radar")

    assert "# Research Radar" in markdown
    assert "## Movers" in markdown
    assert "`adopt`" in markdown
    assert "Speculative-Decoding" in markdown or "speculative-decoding" in markdown
```

- [ ] **Step 2: Write the failing CLI tests (tests/test_research_cli.py)**

```python
"""CLI: radar research scan / list / show against a temp project root."""

from pathlib import Path

from typer.testing import CliRunner

from radar.cli import app


SEED = """
techniques:
  - id: qlora
    name: QLoRA
    category: ai_infrastructure
    domain: fine_tuning
    papers:
      - arxiv_id: "0000.00000"
        title: "QLoRA"
    open_code: true
    onprem_impact: reduces_memory
"""
# arxiv_id 0000.00000 does not exist: with OR without network the citation
# lookup finds nothing, so the "citations unknown" path is deterministic.


def _project(tmp_path: Path) -> Path:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "technique-seed.yaml").write_text(SEED, encoding="utf-8")
    (tmp_path / "data").mkdir()
    return tmp_path


def test_research_scan_offline_writes_run_and_history(tmp_path):
    runner = CliRunner()

    result = runner.invoke(app, ["research", "scan", "--root", str(_project(tmp_path))])

    assert result.exit_code == 0
    assert "1 technique" in result.stdout
    assert (tmp_path / "data" / "technique-history.jsonl").exists()
    runs = list((tmp_path / "data" / "runs").iterdir())
    assert len(runs) == 1
    assert (runs[0] / "technique_cards.json").exists()


def test_research_list_shows_ring_and_domain(tmp_path):
    runner = CliRunner()
    root = _project(tmp_path)
    runner.invoke(app, ["research", "scan", "--root", str(root)])

    result = runner.invoke(app, ["research", "list", "--root", str(root)])

    assert result.exit_code == 0
    assert "qlora" in result.stdout
    assert "watch" in result.stdout
    assert "fine_tuning" in result.stdout


def test_research_list_filters_by_ring(tmp_path):
    runner = CliRunner()
    root = _project(tmp_path)
    runner.invoke(app, ["research", "scan", "--root", str(root)])

    result = runner.invoke(app, ["research", "list", "--root", str(root),
                                 "--ring", "adopt"])

    assert result.exit_code == 0
    assert "qlora" not in result.stdout


def test_research_list_without_scan_prompts_for_scan(tmp_path):
    runner = CliRunner()

    result = runner.invoke(app, ["research", "list", "--root", str(_project(tmp_path))])

    assert result.exit_code == 0
    assert "radar research scan" in result.stdout


def test_research_show_prints_breakdown_and_warnings(tmp_path):
    runner = CliRunner()
    root = _project(tmp_path)
    runner.invoke(app, ["research", "scan", "--root", str(root)])

    result = runner.invoke(app, ["research", "show", "qlora", "--root", str(root)])

    assert result.exit_code == 0
    assert "QLoRA" in result.stdout
    assert "watch" in result.stdout
    assert "0000.00000" in result.stdout
    assert "citations unknown" in result.stdout


def test_research_show_unknown_id_fails(tmp_path):
    runner = CliRunner()
    root = _project(tmp_path)
    runner.invoke(app, ["research", "scan", "--root", str(root)])

    result = runner.invoke(app, ["research", "show", "nope", "--root", str(root)])

    assert result.exit_code == 1
```

Note: `research scan` degrades network failure to warnings (Task 9), so these tests pass with or without network access; the nonexistent arXiv id in SEED keeps the "citations unknown" assertion deterministic either way.

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_research_radar_reports.py tests/test_research_cli.py -v`
Expected: FAIL — `ModuleNotFoundError` / `No such command 'research'`

- [ ] **Step 4: Write reports.py**

Create `src/radar/research_radar/reports.py`:

```python
"""Render technique movers + report sections (mirror of models_radar/reports.py)."""

from __future__ import annotations

from radar.research_radar.entities import TechniqueEntry
from radar.research_radar.history import TechniqueHistoryEvent
from radar.research_radar.momentum import MomentumSignal
from radar.storage.history_store import ChangeType


MAX_TRENDING = 3


def build_technique_mover_lines(
    events: list[TechniqueHistoryEvent], momentums: list[MomentumSignal],
) -> list[str]:
    """Ring changes first, then up to MAX_TRENDING rising techniques not already shown."""
    lines: list[str] = []
    moved: set[str] = set()
    for ev in events:
        prev = ev.previous_ring.value if ev.previous_ring else "?"
        if ev.change_type == ChangeType.PROMOTED:
            lines.append(f"{ev.technique_id}: {prev} → {ev.ring.value} (promoted)")
            moved.add(ev.technique_id)
        elif ev.change_type == ChangeType.DEMOTED:
            lines.append(f"{ev.technique_id}: {prev} → {ev.ring.value} (demoted)")
            moved.add(ev.technique_id)
        elif ev.change_type == ChangeType.NEW:
            lines.append(f"{ev.technique_id}: new on the radar ({ev.ring.value})")
            moved.add(ev.technique_id)
    rising = sorted(
        (m for m in momentums if m.direction == "rising" and m.technique_id not in moved),
        key=lambda m: m.citation_growth_pct or 0.0, reverse=True,
    )
    for momentum in rising[:MAX_TRENDING]:
        pct = (f" citations {momentum.citation_growth_pct:+.1f}%"
               if momentum.citation_growth_pct is not None else "")
        lines.append(f"{momentum.technique_id}: rising —{pct} {momentum.note}".rstrip())
    return lines


def render_technique_report(
    entries: list[TechniqueEntry], mover_lines: list[str], title: str,
) -> str:
    out = [f"# {title}", ""]
    if mover_lines:
        out.append("## Movers")
        out += [f"- {line}" for line in mover_lines]
        out.append("")
    out.append("## Techniques")
    for entry in sorted(entries, key=lambda e: (e.domain.value, e.id)):
        ring = entry.ring.value if entry.ring else "-"
        impls = len(entry.resolved_implementations)
        citations = entry.citation_count if entry.citation_count is not None else "?"
        out.append(
            f"- **{entry.name}** ({entry.domain.value}) · `{ring}` · "
            f"{impls} impl(s) · {citations} citations"
        )
    out.append("")
    return "\n".join(out)
```

- [ ] **Step 5: Wire the CLI**

In `src/radar/cli.py`, after the `models_app` registration (`src/radar/cli.py:30-31`), add:

```python
research_app = typer.Typer(help="Academic research radar (techniques).", no_args_is_help=True)
app.add_typer(research_app, name="research")
```

Then add the three commands next to the models commands (imports local to each command, mirroring `models_scan`/`models_list`):

```python
@research_app.command("scan")
def research_scan(root: Path = typer.Option(Path("."), help="Project root.")) -> None:
    """Score seeded techniques against the radar's own catalogs + citations."""
    import asyncio
    import os

    import httpx

    from radar.research_radar.pipeline import momentum_for, run_research_scan
    from radar.research_radar.reports import build_technique_mover_lines, render_technique_report
    from radar.storage.run_store import RunStore

    seed_path = root / "config" / "technique-seed.yaml"
    if not seed_path.exists():
        seed_path = Path(__file__).resolve().parents[2] / "config" / "technique-seed.yaml"
    model_seed_path = root / "config" / "model-seed.yaml"
    if not model_seed_path.exists():
        model_seed_path = Path(__file__).resolve().parents[2] / "config" / "model-seed.yaml"

    run_store = RunStore(root / "data" / "runs")
    run_id = run_store.create_run()

    async def _run():
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            return await run_research_scan(
                seed_path=seed_path,
                config_path=root / "data" / "config.yaml",
                db_path=root / "data" / "radar.db",
                model_seed_path=model_seed_path,
                model_history_path=root / "data" / "model-history.jsonl",
                history_path=root / "data" / "technique-history.jsonl",
                client=client,
                contact_email=os.environ.get("RADAR_CONTACT_EMAIL"),
                run_id=run_id,
            )

    entries, events = asyncio.run(_run())
    momentums = momentum_for(entries, root / "data" / "radar.db")
    report = render_technique_report(
        entries, build_technique_mover_lines(events, list(momentums.values())),
        "Academic Research Radar",
    )
    run_store.save_stage(run_id, "technique_cards", [e.model_dump(mode="json") for e in entries])
    run_store.save_report(run_id, report)
    run_store.update_meta(run_id, {"kind": "research", "technique_count": len(entries)})
    warned = sum(1 for e in entries if e.warnings)
    suffix = f" ({warned} with warnings)" if warned else ""
    console.print(f"Scanned {len(entries)} technique(s) → run {run_id}{suffix}")


@research_app.command("list")
def research_list(
    root: Path = typer.Option(Path("."), help="Project root."),
    ring: str = typer.Option("", help="Filter by ring: adopt|pilot|watch|avoid."),
    domain: str = typer.Option("", help="Filter by domain, e.g. inference."),
    category: str = typer.Option("", help="Filter by radar category."),
) -> None:
    """List techniques from the latest research scan."""
    entries = _latest_technique_entries(root)
    if entries is None:
        console.print(
            "[yellow]No research scan yet. Run [bold]radar research scan[/bold] first.[/yellow]"
        )
        return
    if ring:
        entries = [e for e in entries if e.ring and e.ring.value == ring.lower()]
    if domain:
        entries = [e for e in entries if e.domain.value == domain.lower()]
    if category:
        entries = [e for e in entries if e.category.value == category.lower()]
    console.print(f"{len(entries)} technique(s):")
    for e in entries:
        ring_label = e.ring.value if e.ring else "-"
        citations = str(e.citation_count) if e.citation_count is not None else "?"
        console.print(
            f"  {e.id:<26} {ring_label:<7} {e.domain.value:<18} "
            f"impls={len(e.resolved_implementations):<3} citations={citations}",
            highlight=False, soft_wrap=True,
        )


@research_app.command("show")
def research_show(
    technique_id: str = typer.Argument(..., help="Technique id, e.g. speculative-decoding."),
    root: Path = typer.Option(Path("."), help="Project root."),
) -> None:
    """One technique: score breakdown, papers, implementations, ring history."""
    from radar.research_radar.history import load_technique_events

    entries = _latest_technique_entries(root)
    if entries is None:
        console.print(
            "[yellow]No research scan yet. Run [bold]radar research scan[/bold] first.[/yellow]"
        )
        return
    matches = [e for e in entries if e.id == technique_id]
    if not matches:
        console.print(f"[red]Unknown technique id:[/red] {technique_id}")
        raise typer.Exit(code=1)
    entry = matches[0]
    ring = entry.ring.value if entry.ring else "-"
    console.print(f"[bold]{entry.name}[/bold] ({entry.domain.value}) · ring: {ring}")
    if entry.score_breakdown is not None:
        b = entry.score_breakdown
        console.print(
            f"  breadth={b.implementation_breadth} maturity={b.implementation_maturity} "
            f"validation={b.validation} reproducibility={b.reproducibility} "
            f"momentum={b.momentum} onprem={b.onprem_impact} avg={b.average}"
        )
    for paper in entry.papers:
        console.print(f"  paper [{paper.role.value}] {paper.arxiv_id}: {paper.title}")
    for impl in entry.resolved_implementations:
        impl_ring = impl.ring.value if impl.ring else "unringed"
        console.print(f"  impl [{impl.kind.value}] {impl.ref} ({impl_ring})")
    for warning in entry.warnings:
        console.print(f"  [yellow]warning:[/yellow] {warning}")
    events = [e for e in load_technique_events(root / "data" / "technique-history.jsonl")
              if e.technique_id == technique_id]
    for event in events:
        console.print(
            f"  {event.observed_at.date()} {event.change_type.value} → {event.ring.value}"
        )


def _latest_technique_entries(root: Path):
    import json as _json

    from radar.research_radar.entities import TechniqueEntry as _TE
    from radar.storage.run_store import RunStore

    run_store = RunStore(root / "data" / "runs")
    for rid in reversed(run_store.list_runs()):
        if run_store.read_meta(rid).get("kind") == "research":
            cards_path = run_store._run_dir(rid) / "technique_cards.json"
            payload = _json.loads(cards_path.read_text(encoding="utf-8"))
            return [_TE.model_validate(item) for item in payload]
    return None
```

- [ ] **Step 6: Run all new tests**

Run: `uv run pytest tests/test_research_radar_reports.py tests/test_research_cli.py -v`
Expected: PASS

- [ ] **Step 7: Lint + typecheck + commit**

```bash
uv run ruff check src/radar tests/test_research_radar_reports.py tests/test_research_cli.py && uv run mypy src/radar
git add src/radar/research_radar/reports.py src/radar/cli.py tests/test_research_radar_reports.py tests/test_research_cli.py
git commit -m "feat: radar research CLI (scan/list/show) + technique report"
```

---

### Task 12: README + full gates

**Files:**
- Modify: `README.md` (CLI table + a Highlights bullet)
- Test: the full suite

- [ ] **Step 1: Update README**

In the CLI table (after the `radar seed list` row), add:

```markdown
| `radar research scan` | Score seeded research techniques: closed-loop vs the radar's own tool/model rings + citations (Semantic Scholar/OpenAlex, best-effort). |
| `radar research list [--ring R] [--domain D]` | List techniques from the latest research scan. |
| `radar research show <id>` | One technique: score breakdown, papers, implementations, ring history. |
```

In Highlights (after the "Fun lane" bullet), add:

```markdown
- 🎓 **Research technique radar** — curated academic techniques (speculative decoding, PagedAttention, LoRA, ReAct…) get their own deterministic rings, scored by *which tracked tools already implement them* plus citation evidence — research verdicts move when tool verdicts move.
```

- [ ] **Step 2: Run the full gate suite**

Run: `uv run pytest && uv run ruff check . && uv run mypy src/radar`
Expected: all tests pass, coverage ≥ 80%, ruff and mypy clean. Fix anything that fails before committing (implementation, not tests, unless a test is genuinely wrong).

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: README for the research technique radar CLI"
```

---

## Self-Review Notes (already applied)

- Spec §1–§7 map to Tasks 1–11; spec §8's 60–100-technique expansion and §9's sub-projects 2–4 are explicitly out of scope (recorded under File Structure).
- The spec's scan-health integration (§4 step 7) is covered by per-entry `warnings` + the scan summary line ("N with warnings") — full scan-health-store integration belongs to sub-project 2's surfaces and is intentionally not wired here.
- Type consistency verified: `MomentumSignal.score` feeds `TechniqueScore.momentum`; `resolve_implementations` returns `(list[ResolvedImplementation], list[str])` everywhere it is consumed (Tasks 2, 9); `run_research_scan` carries `run_id` (added in Task 9, consumed in Task 11).
- Determinism: the only nondeterministic input (network) degrades to last-known/neutral values; the Task 9 integration test asserts same-rings-twice offline.
