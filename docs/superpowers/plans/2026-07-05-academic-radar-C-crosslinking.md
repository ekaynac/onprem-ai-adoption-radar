# Academic Research Radar — Plan C (Cross-Linking) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cross-link the three radars: tool cards gain a research-pedigree evidence line, project/model detail pages gain an "Implements research techniques" section, technique pages link back to tool/model pages, and MCP payloads carry the technique lists.

**Architecture:** One pure module (`research_radar/pedigree.py`) inverts the latest research run's `resolved_implementations` into ref→techniques indexes. Consumers thread it in three ways: the orchestrator appends a best-effort evidence note after `build_decision_cards` (immutable `model_copy`, never fails a scan); the web layer (live routes + static writer) passes `pedigree` + `technique_hrefs` context into the shared detail partials; MCP `get_project`/`get_model` append a `techniques` list. Pedigree is display/evidence only — **never a score input**.

**Tech Stack:** Python 3.12, pydantic v2, Jinja2, pytest + ruff + mypy. **No new dependencies.**

**Spec:** `docs/superpowers/specs/2026-07-03-academic-research-radar-design.md` §9 Cross-linking bullet.

## Global Constraints

- Pedigree NEVER affects scoring/rings — evidence + display only (spec §9: "never a hard score input without its own design pass").
- Everything degrades: no research run → no pedigree line/section/key, scans and pages unaffected (best-effort, mirror of enrichment).
- Key fact: `ResolvedImplementation.ref` is a **source id** for `kind=tool` (e.g. `github-vllm`) and a **model id** for `kind=model`; cards are keyed by **project name** (`source.project`); one project may have several source ids. The id→project map comes from `config.sources`.
- ruff line-length 100; python 3.12; every Python file starts with `from __future__ import annotations`; immutable updates via `model_copy` (cards are pydantic models).
- Gates: `uv run pytest` (≥80% coverage), `uv run ruff check .`, `uv run mypy src/radar`.
- Commit format `<type>: <description>`; `git add` specific paths only (unrelated modified `data/history.jsonl` must never be committed).
- Existing symbols consumed (all on main): `TechniqueEntry` (with `resolved_implementations: list[ResolvedImplementation]` — `.kind` (`ImplKind.TOOL|MODEL`), `.ref`, `.ring`), `_latest_technique_cards(root)` (`radar.mcp_server.technique_queries`), `build_slug_map` (`radar.web.slugs`), `Ring`, `SourceConfig` (`.id`, `.project`), `load_config`.

## File Structure

```
src/radar/research_radar/pedigree.py       # NEW: TechniquePedigree, PedigreeIndex, build/index/note helpers
src/radar/orchestrator.py                  # MODIFY: _attach_pedigree after build_decision_cards
src/radar/web/app.py                       # MODIFY: pedigree context on /project/{name}, /model/{id}, /technique/{id}
src/radar/web/static_site.py               # MODIFY: pedigree context threading into project/model/technique writers
src/radar/cli.py                           # MODIFY: export builds pedigree maps (has config) and threads them
src/radar/web/templates/_project_detail.html   # MODIFY: "Research techniques" section
src/radar/web/templates/_model_detail.html     # MODIFY: same section
src/radar/web/templates/_technique_detail.html # MODIFY: impl refs become links when resolvable
src/radar/mcp_server/queries.py            # MODIFY: get_project gains "techniques"
src/radar/mcp_server/model_queries.py      # MODIFY: get_model gains "techniques"
tests/test_research_radar_pedigree.py      # NEW
tests/test_orchestrator.py                 # MODIFY: pedigree evidence-line tests
tests/test_web.py, tests/test_static_site.py, tests/test_mcp_queries.py, tests/test_model_queries.py  # MODIFY
```

Out of scope: pedigree as a scoring input; citation-velocity display beyond the citation count already carried by `TechniquePedigree`; any change to `build_decision_cards`' signature (the orchestrator post-processes instead); linking impl refs that have no page (unresolvable refs render as plain text).

---

### Task 1: Pedigree index module

**Files:**
- Create: `src/radar/research_radar/pedigree.py`
- Test: `tests/test_research_radar_pedigree.py`

**Interfaces:**
- Consumes: `TechniqueEntry`, `ImplKind`, `Ring`.
- Produces (all later tasks import these exact names):
  - `TechniquePedigree` (frozen: `technique_id: str`, `name: str`, `ring: Ring | None`, `citation_count: int | None`).
  - `PedigreeIndex` (frozen: `by_tool_ref: dict[str, list[TechniquePedigree]]`, `by_model_ref: dict[str, list[TechniquePedigree]]`).
  - `build_pedigree_index(entries: list[TechniqueEntry]) -> PedigreeIndex`.
  - `pedigree_for_refs(index_map: dict[str, list[TechniquePedigree]], refs: list[str]) -> list[TechniquePedigree]` — union across refs, dedup by `technique_id`, sorted best-ring-first (adopt > pilot > watch > avoid > None) then by `technique_id`.
  - `pedigree_note(items: list[TechniquePedigree]) -> str | None` — `None` for empty; else `"Implements N tracked research technique(s) (M adopt-ring): name1, name2, name3…"` — names the top 3 (in the sorted order), trailing `…` only when more than 3, the `(M adopt-ring)` parenthetical only when M > 0, singular "technique" when N == 1.

- [ ] **Step 1: Write the failing tests**

```python
"""Pedigree index: invert technique implementations into ref → techniques."""

from __future__ import annotations

from radar.models import Category, Ring
from radar.research_radar.entities import (
    ImplKind,
    OnPremImpact,
    ResolvedImplementation,
    TechniqueDomain,
    TechniqueEntry,
)
from radar.research_radar.pedigree import (
    PedigreeIndex,
    TechniquePedigree,
    build_pedigree_index,
    pedigree_for_refs,
    pedigree_note,
)


def _impl(kind: ImplKind, ref: str, ring: Ring | None = None) -> ResolvedImplementation:
    return ResolvedImplementation(kind=kind, ref=ref, ring=ring)


def _entry(technique_id: str, name: str, ring: Ring | None,
           impls: list[ResolvedImplementation], citations: int | None = 100) -> TechniqueEntry:
    return TechniqueEntry(
        id=technique_id, name=name, category=Category.MODEL_SERVING,
        domain=TechniqueDomain.INFERENCE, onprem_impact=OnPremImpact.REDUCES_LATENCY,
        ring=ring, citation_count=citations, resolved_implementations=impls,
    )


def test_build_index_inverts_tool_and_model_refs():
    entries = [
        _entry("spec-dec", "Speculative Decoding", Ring.ADOPT, [
            _impl(ImplKind.TOOL, "github-vllm", Ring.PILOT),
            _impl(ImplKind.MODEL, "llama-3.3-70b", Ring.PILOT),
        ]),
        _entry("paged-attention", "PagedAttention", Ring.PILOT, [
            _impl(ImplKind.TOOL, "github-vllm", Ring.PILOT),
        ]),
    ]

    index = build_pedigree_index(entries)

    vllm = index.by_tool_ref["github-vllm"]
    assert {t.technique_id for t in vllm} == {"spec-dec", "paged-attention"}
    assert index.by_model_ref["llama-3.3-70b"][0].technique_id == "spec-dec"
    assert vllm[0].citation_count == 100


def test_index_carries_technique_ring_not_impl_ring():
    entries = [_entry("spec-dec", "Speculative Decoding", Ring.ADOPT,
                      [_impl(ImplKind.TOOL, "github-vllm", Ring.WATCH)])]

    index = build_pedigree_index(entries)

    assert index.by_tool_ref["github-vllm"][0].ring == Ring.ADOPT


def test_empty_entries_give_empty_index():
    index = build_pedigree_index([])

    assert index == PedigreeIndex()


def test_pedigree_for_refs_unions_dedups_and_sorts_best_ring_first():
    items_a = [
        TechniquePedigree(technique_id="watch-one", name="W", ring=Ring.WATCH, citation_count=1),
        TechniquePedigree(technique_id="adopt-one", name="A", ring=Ring.ADOPT, citation_count=2),
    ]
    items_b = [
        TechniquePedigree(technique_id="adopt-one", name="A", ring=Ring.ADOPT, citation_count=2),
        TechniquePedigree(technique_id="unringed", name="U", ring=None, citation_count=None),
    ]
    index_map = {"src-a": items_a, "src-b": items_b}

    merged = pedigree_for_refs(index_map, ["src-a", "src-b", "src-missing"])

    assert [t.technique_id for t in merged] == ["adopt-one", "watch-one", "unringed"]


def test_pedigree_note_formats_counts_and_top_three():
    items = [
        TechniquePedigree(technique_id="a", name="Alpha", ring=Ring.ADOPT, citation_count=1),
        TechniquePedigree(technique_id="b", name="Beta", ring=Ring.ADOPT, citation_count=2),
        TechniquePedigree(technique_id="c", name="Gamma", ring=Ring.PILOT, citation_count=3),
        TechniquePedigree(technique_id="d", name="Delta", ring=Ring.WATCH, citation_count=4),
    ]

    note = pedigree_note(items)

    assert note == ("Implements 4 tracked research techniques (2 adopt-ring): "
                    "Alpha, Beta, Gamma…")


def test_pedigree_note_singular_no_adopt_no_ellipsis():
    items = [TechniquePedigree(technique_id="a", name="Alpha", ring=Ring.WATCH,
                               citation_count=None)]

    assert pedigree_note(items) == "Implements 1 tracked research technique: Alpha"
    assert pedigree_note([]) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_research_radar_pedigree.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'radar.research_radar.pedigree'`

- [ ] **Step 3: Write the implementation**

Create `src/radar/research_radar/pedigree.py`:

```python
"""Research pedigree: invert technique implementations into ref → techniques.

The index answers "which techniques does this tool/model implement?" for
cards, detail pages, and MCP payloads. Display and evidence only — pedigree
is never a scoring input (spec §9).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from radar.models import Ring
from radar.research_radar.entities import ImplKind, TechniqueEntry


_RING_SORT = {Ring.ADOPT: 0, Ring.PILOT: 1, Ring.WATCH: 2, Ring.AVOID: 3, None: 4}
_NOTE_NAME_LIMIT = 3


class TechniquePedigree(BaseModel):
    """One technique as seen from an implementing tool/model."""

    model_config = ConfigDict(frozen=True)

    technique_id: str
    name: str
    ring: Ring | None = None
    citation_count: int | None = None


class PedigreeIndex(BaseModel):
    """ref → techniques, split by ref kind (tool source id vs model id)."""

    model_config = ConfigDict(frozen=True)

    by_tool_ref: dict[str, list[TechniquePedigree]] = Field(default_factory=dict)
    by_model_ref: dict[str, list[TechniquePedigree]] = Field(default_factory=dict)


def build_pedigree_index(entries: list[TechniqueEntry]) -> PedigreeIndex:
    by_tool: dict[str, list[TechniquePedigree]] = {}
    by_model: dict[str, list[TechniquePedigree]] = {}
    for entry in entries:
        pedigree = TechniquePedigree(
            technique_id=entry.id, name=entry.name, ring=entry.ring,
            citation_count=entry.citation_count,
        )
        for impl in entry.resolved_implementations:
            target = by_tool if impl.kind == ImplKind.TOOL else by_model
            target.setdefault(impl.ref, []).append(pedigree)
    return PedigreeIndex(by_tool_ref=by_tool, by_model_ref=by_model)


def pedigree_for_refs(
    index_map: dict[str, list[TechniquePedigree]], refs: list[str],
) -> list[TechniquePedigree]:
    """Union across refs, dedup by technique id, best ring first then id."""
    seen: dict[str, TechniquePedigree] = {}
    for ref in refs:
        for item in index_map.get(ref, []):
            seen.setdefault(item.technique_id, item)
    return sorted(seen.values(), key=lambda t: (_RING_SORT[t.ring], t.technique_id))


def pedigree_note(items: list[TechniquePedigree]) -> str | None:
    """Human-readable evidence line, or None when there is nothing to say."""
    if not items:
        return None
    adopt = sum(1 for t in items if t.ring == Ring.ADOPT)
    noun = "technique" if len(items) == 1 else "techniques"
    counts = f"Implements {len(items)} tracked research {noun}"
    if adopt:
        counts += f" ({adopt} adopt-ring)"
    names = ", ".join(t.name for t in items[:_NOTE_NAME_LIMIT])
    suffix = "…" if len(items) > _NOTE_NAME_LIMIT else ""
    return f"{counts}: {names}{suffix}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_research_radar_pedigree.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Lint + typecheck + commit**

```bash
uv run ruff check src/radar/research_radar tests/test_research_radar_pedigree.py && uv run mypy src/radar
git add src/radar/research_radar/pedigree.py tests/test_research_radar_pedigree.py
git commit -m "feat: research pedigree index (technique implementations inverted)"
```

---

### Task 2: Pedigree evidence line on tool cards (orchestrator)

**Files:**
- Modify: `src/radar/orchestrator.py`
- Test: `tests/test_orchestrator.py` (append)

**Interfaces:**
- Consumes: Task 1's `build_pedigree_index`, `pedigree_for_refs`, `pedigree_note`; `_latest_technique_cards` (`radar.mcp_server.technique_queries` — same import convention `web/app.py` uses); `TechniqueEntry`.
- Produces: `RadarOrchestrator._attach_pedigree(cards: list[DecisionCard], config: Config) -> list[DecisionCard]` — called in `_scan` immediately after `build_decision_cards(...)` (before quotas/overrides) so the note flows through every downstream stage. Best-effort: ANY exception → `logger.warning` + return cards unchanged; no research run → unchanged. Cards are updated immutably (`model_copy`), the note appended as the LAST `evidence_notes` line.

- [ ] **Step 1: Write the failing tests (append to tests/test_orchestrator.py)**

```python
def _seed_research_run_for_pedigree(root: Path, source_id: str) -> None:
    from radar.models import Ring as _Ring
    from radar.research_radar.entities import (
        ImplKind as _IK,
        OnPremImpact as _Imp,
        ResolvedImplementation as _RI,
        TechniqueDomain as _Dom,
        TechniqueEntry as _TE,
    )
    from radar.models import Category as _Cat
    from radar.storage.run_store import RunStore as _RS

    entry = _TE(
        id="spec-dec", name="Speculative Decoding", category=_Cat.MODEL_SERVING,
        domain=_Dom.INFERENCE, onprem_impact=_Imp.REDUCES_LATENCY, ring=_Ring.ADOPT,
        citation_count=1697,
        resolved_implementations=[_RI(kind=_IK.TOOL, ref=source_id, ring=None)],
    )
    store = _RS(root / "data" / "runs")
    run_id = store.create_run()
    store.update_meta(run_id, {"kind": "research"})
    store.save_stage(run_id, "technique_cards", [entry.model_dump(mode="json")])
    store.update_meta(run_id, {"technique_count": 1})


def test_scan_attaches_pedigree_evidence_note(tmp_path: Path):
    initialize_project(tmp_path)
    config_path = tmp_path / "data" / "config.yaml"
    config_path.write_text(
        """
version: "1.0"
sources:
  - id: mcp-docs
    type: manual
    enabled: true
    project: Model Context Protocol
    category: mcp_tooling
    url: https://modelcontextprotocol.io/docs/getting-started/intro
    tags: [mcp, protocol]
scoring:
  default_ring: watch
""",
        encoding="utf-8",
    )
    _seed_research_run_for_pedigree(tmp_path, "mcp-docs")

    result = RadarOrchestrator(root=tmp_path).scan(days=2)

    card = result.cards[0]
    assert any("Implements 1 tracked research technique" in n for n in card.evidence_notes)
    assert any("Speculative Decoding" in n for n in card.evidence_notes)


def test_scan_without_research_run_has_no_pedigree_note(tmp_path: Path):
    initialize_project(tmp_path)
    config_path = tmp_path / "data" / "config.yaml"
    config_path.write_text(
        """
version: "1.0"
sources:
  - id: mcp-docs
    type: manual
    enabled: true
    project: Model Context Protocol
    category: mcp_tooling
    url: https://modelcontextprotocol.io/docs/getting-started/intro
    tags: [mcp]
scoring:
  default_ring: watch
""",
        encoding="utf-8",
    )

    result = RadarOrchestrator(root=tmp_path).scan(days=2)

    assert not any("tracked research technique" in n
                   for n in result.cards[0].evidence_notes)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_orchestrator.py -v -k pedigree`
Expected: FAIL — the first test's assertion (no pedigree note attached)

- [ ] **Step 3: Implement `_attach_pedigree`**

In `src/radar/orchestrator.py`, right after the `cards = build_decision_cards(...)` call in `_scan`, add:

```python
        cards = self._attach_pedigree(cards, config)
```

Add the method to `RadarOrchestrator` (near the other private helpers):

```python
    def _attach_pedigree(self, cards: list[DecisionCard], config: Config) -> list[DecisionCard]:
        """Append a research-pedigree evidence line per card. Best-effort:
        no research run (or any failure) leaves the cards untouched."""
        try:
            from radar.mcp_server.technique_queries import _latest_technique_cards
            from radar.research_radar.entities import TechniqueEntry
            from radar.research_radar.pedigree import (
                build_pedigree_index,
                pedigree_for_refs,
                pedigree_note,
            )

            entries = [
                TechniqueEntry.model_validate(c) for c in _latest_technique_cards(self.root)
            ]
            if not entries:
                return cards
            index = build_pedigree_index(entries)
            ids_by_project: dict[str, list[str]] = {}
            for source in config.sources:
                ids_by_project.setdefault(source.project, []).append(source.id)
            updated: list[DecisionCard] = []
            for card in cards:
                items = pedigree_for_refs(
                    index.by_tool_ref, ids_by_project.get(card.project, [])
                )
                note = pedigree_note(items)
                if note is None:
                    updated.append(card)
                else:
                    updated.append(card.model_copy(
                        update={"evidence_notes": [*card.evidence_notes, note]}
                    ))
            return updated
        except Exception as exc:  # pedigree must never fail a scan
            logger.warning("Research pedigree unavailable: %s", exc)
            return cards
```

Check the top of `orchestrator.py` for an existing module `logger`; if there is none, add `logger = logging.getLogger(__name__)` (and `import logging`) following the pattern used in `src/radar/research_radar/resolve.py`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_orchestrator.py -v`
Expected: PASS (existing + 2 new; existing tests prove no-research scans are unchanged)

- [ ] **Step 5: Lint + typecheck + commit**

```bash
uv run ruff check src/radar/orchestrator.py tests/test_orchestrator.py && uv run mypy src/radar
git add src/radar/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: research-pedigree evidence line on tool cards (best-effort)"
```

---

### Task 3: Project pages — "Implements research techniques" section

**Files:**
- Modify: `src/radar/web/templates/_project_detail.html`, `src/radar/web/app.py` (project route), `src/radar/web/static_site.py` (`render_static_site` + `_write_project_pages`), `src/radar/cli.py` (export threads the maps)
- Test: `tests/test_web.py`, `tests/test_static_site.py` (append)

**Interfaces:**
- Consumes: Task 1 helpers; `_latest_technique_cards`; `build_slug_map`; `load_config`.
- Produces:
  - `_project_detail.html` renders a new optional section from context keys `pedigree: list[TechniquePedigree] | None` and `technique_hrefs: dict[str, str]` (technique_id → href). Section heading: `Research techniques`. Each item: linked name + ` — {ring or 'unringed'}` + ` · {citation_count} citations` when known.
  - Live `/project/{name}` passes `pedigree` (from the latest research run + config id→project map) and `technique_hrefs` (`/technique/{id}`); missing research data → `pedigree=None`.
  - `render_static_site` gains `pedigree_by_project: dict[str, list[TechniquePedigree]] | None = None` and `technique_hrefs: dict[str, str] | None = None` params, threaded into `_write_project_pages`; the CLI export builds both (static hrefs `technique_<slug>.html` via `build_slug_map`) — Task 4 reuses the same params for models.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_web.py`:

```python
def _seed_pedigree_research_run(root: Path, tool_ref: str) -> None:
    from radar.models import Category as _Cat
    from radar.models import Ring as _Ring
    from radar.research_radar.entities import (
        ImplKind as _IK,
        OnPremImpact as _Imp,
        ResolvedImplementation as _RI,
        TechniqueDomain as _Dom,
        TechniqueEntry as _TE,
    )
    from radar.storage.run_store import RunStore as _RS

    entry = _TE(
        id="spec-dec", name="Speculative Decoding", category=_Cat.MODEL_SERVING,
        domain=_Dom.INFERENCE, onprem_impact=_Imp.REDUCES_LATENCY, ring=_Ring.ADOPT,
        citation_count=1697,
        resolved_implementations=[
            _RI(kind=_IK.TOOL, ref=tool_ref, ring=None),
            _RI(kind=_IK.MODEL, ref="llama-3.3-70b", ring=None),
        ],
    )
    store = _RS(root / "data" / "runs")
    run_id = store.create_run()
    store.update_meta(run_id, {"kind": "research"})
    store.save_stage(run_id, "technique_cards", [entry.model_dump(mode="json")])


def _write_pedigree_config(root: Path, source_id: str, project: str) -> None:
    (root / "data").mkdir(parents=True, exist_ok=True)
    (root / "data" / "config.yaml").write_text(
        f"""
sources:
  - id: {source_id}
    type: github_repo
    project: {project}
    category: model_serving
    url: https://github.com/vllm-project/vllm
""",
        encoding="utf-8",
    )


def test_project_page_shows_research_pedigree(tmp_path: Path):
    db = RadarDatabase(tmp_path / "data" / "radar.db")
    db.initialize()
    db.upsert_cards([_card_for_web("vLLM", Ring.ADOPT)])
    _write_pedigree_config(tmp_path, "github-vllm", "vLLM")
    _seed_pedigree_research_run(tmp_path, "github-vllm")

    text = TestClient(create_app(tmp_path)).get("/project/vLLM").text

    assert "Research techniques" in text
    assert "Speculative Decoding" in text
    assert 'href="/technique/spec-dec"' in text


def test_project_page_without_research_run_has_no_pedigree_section(tmp_path: Path):
    db = RadarDatabase(tmp_path / "data" / "radar.db")
    db.initialize()
    db.upsert_cards([_card_for_web("vLLM", Ring.ADOPT)])

    text = TestClient(create_app(tmp_path)).get("/project/vLLM").text

    assert "Research techniques" not in text
```

NOTE for the implementer: `tests/test_web.py` already has card-building helpers — find the existing helper the project-page tests use (e.g. the one behind `test_project_page_renders_full_card`) and reuse it instead of `_card_for_web` if the name differs; adjust only the helper NAME in these tests, nothing else.

Append to `tests/test_static_site.py`:

```python
def test_static_project_page_shows_pedigree_with_static_links(tmp_path):
    from radar.models import Ring
    from radar.research_radar.pedigree import TechniquePedigree

    card = _card("vLLM", Ring.ADOPT)
    pedigree_by_project = {"vLLM": [TechniquePedigree(
        technique_id="spec-dec", name="Speculative Decoding",
        ring=Ring.ADOPT, citation_count=1697,
    )]}

    render_static_site(
        [card], tmp_path / "_site", datetime(2026, 7, 5, tzinfo=UTC),
        pedigree_by_project=pedigree_by_project,
        technique_hrefs={"spec-dec": "technique_spec-dec.html"},
    )

    page = (tmp_path / "_site" / "project_vllm.html").read_text(encoding="utf-8")
    assert "Research techniques" in page
    assert 'href="technique_spec-dec.html"' in page
    assert "1697 citations" in page
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_web.py tests/test_static_site.py -v -k pedigree`
Expected: FAIL — "Research techniques" absent / `TypeError` on the new kwargs

- [ ] **Step 3: Template section**

In `src/radar/web/templates/_project_detail.html`, after the "Observed evidence" section (the block rendering `card.evidence_notes`), add:

```html
{% if pedigree %}
<h3>Research techniques</h3>
<ul>
  {% for t in pedigree %}
  <li><a href="{{ technique_hrefs[t.technique_id] }}">{{ t.name }}</a>
      — {{ t.ring.value if t.ring else 'unringed' }}
      {% if t.citation_count is not none %} · {{ t.citation_count }} citations{% endif %}</li>
  {% endfor %}
</ul>
{% endif %}
```

Also update the partial's header comment to add `pedigree (list[TechniquePedigree] | None), technique_hrefs (dict)` to the context contract.

- [ ] **Step 4: Live route wiring**

In `src/radar/web/app.py`, add a helper near `_technique_entries` (module imports: `build_pedigree_index`, `pedigree_for_refs` from `radar.research_radar.pedigree`, `load_config` from `radar.storage.config` if not already imported):

```python
    def _project_pedigree(project: str) -> list:
        """Techniques implemented by this project's sources; [] on any gap."""
        try:
            entries = _technique_entries()
            if not entries:
                return []
            config = load_config(root / "data" / "config.yaml")
            refs = [s.id for s in config.sources if s.project == project]
            return pedigree_for_refs(build_pedigree_index(entries).by_tool_ref, refs)
        except Exception:
            return []
```

In the `project_detail` route's success-path `TemplateResponse` context, add:

```python
                "pedigree": _project_pedigree(card.project) or None,
                "technique_hrefs": {t.id: f"/technique/{t.id}" for t in _technique_entries()},
```

(Compute `technique_hrefs` via a small helper if the double `_technique_entries()` call bothers the implementation — correctness first: hrefs must cover every pedigree item.)

- [ ] **Step 5: Static wiring**

In `src/radar/web/static_site.py`:
- `render_static_site` gains parameters (after `technique_events`): `pedigree_by_project: dict[str, list[TechniquePedigree]] | None = None`, `pedigree_by_model: dict[str, list[TechniquePedigree]] | None = None`, `technique_hrefs: dict[str, str] | None = None` (import `TechniquePedigree` from `radar.research_radar.pedigree`). (`pedigree_by_model` is threaded in Task 4; declare it now so the signature changes once.)
- Thread into `_write_project_pages(...)`: pass `pedigree_by_project=pedigree_by_project or {}` and `technique_hrefs=technique_hrefs or {}`; inside, per card add to the render context: `pedigree=(pedigree_by_project.get(card.project) or None), technique_hrefs=technique_hrefs`.

In `src/radar/cli.py` `export`, after the technique entries/events loading block, build the maps and thread them:

```python
    from radar.research_radar.pedigree import build_pedigree_index, pedigree_for_refs

    pedigree_by_project: dict = {}
    pedigree_by_model: dict = {}
    technique_hrefs: dict[str, str] = {}
    if technique_entries:
        technique_slugs = build_slug_map([t.id for t in technique_entries])
        technique_hrefs = {tid: f"technique_{slug}.html" for tid, slug in technique_slugs.items()}
        pedigree_index = build_pedigree_index(technique_entries)
        export_config = load_config(root / "data" / "config.yaml")
        ids_by_project: dict[str, list[str]] = {}
        for source in export_config.sources:
            ids_by_project.setdefault(source.project, []).append(source.id)
        pedigree_by_project = {
            project: items for project, ids in ids_by_project.items()
            if (items := pedigree_for_refs(pedigree_index.by_tool_ref, ids))
        }
        pedigree_by_model = {
            ref: items for ref in pedigree_index.by_model_ref
            if (items := pedigree_for_refs(pedigree_index.by_model_ref, [ref]))
        }
```

and add to the `render_static_site(...)` call: `pedigree_by_project=pedigree_by_project or None, pedigree_by_model=pedigree_by_model or None, technique_hrefs=technique_hrefs or None`. (`build_slug_map` and `load_config` may already be imported in `cli.py` — check before adding imports.)

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_web.py tests/test_static_site.py tests/test_cli.py -v`
Expected: PASS (new + existing)

- [ ] **Step 7: Lint + typecheck + commit**

```bash
uv run ruff check src/radar tests/test_web.py tests/test_static_site.py && uv run mypy src/radar
git add src/radar/web/templates/_project_detail.html src/radar/web/app.py src/radar/web/static_site.py \
  src/radar/cli.py tests/test_web.py tests/test_static_site.py
git commit -m "feat: research-techniques section on project pages (live + static)"
```

---

### Task 4: Model pages — same section

**Files:**
- Modify: `src/radar/web/templates/_model_detail.html`, `src/radar/web/app.py` (model route), `src/radar/web/static_site.py` (`_write_model_pages`)
- Test: `tests/test_web.py`, `tests/test_static_site.py` (append)

**Interfaces:**
- Consumes: Task 1 helpers; Task 3's `pedigree_by_model`/`technique_hrefs` params (already declared on `render_static_site`).
- Produces: `_model_detail.html` renders the same optional section from `pedigree` + `technique_hrefs`; live `/model/{model_id}` passes `pedigree` from `by_model_ref[model.id]`; `_write_model_pages` gains `pedigree_by_model: dict | None = None` + `technique_hrefs: dict | None = None` parameters and threads per-entry context.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_web.py`:

```python
def test_model_page_shows_research_pedigree(tmp_path: Path):
    _seed_models(tmp_path)  # reuse the existing models seeding helper in this file
    _seed_pedigree_research_run(tmp_path, "github-vllm")  # spec-dec also refs llama-3.3-70b

    # The seeded technique's model ref must match a seeded model id: re-seed the
    # research run pointing at the id the models helper creates.
    from radar.storage.run_store import RunStore as _RS

    store = _RS(tmp_path / "data" / "runs")
    model_ids = [m["id"] for m in __import__("json").loads(
        (store._run_dir(next(r for r in store.list_runs()
                             if store.read_meta(r).get("kind") == "models"))
         / "model_cards.json").read_text(encoding="utf-8"))]
    target = model_ids[0]
    _seed_pedigree_research_run_for_model(tmp_path, target)

    text = TestClient(create_app(tmp_path)).get(f"/model/{target}").text

    assert "Research techniques" in text
    assert "Speculative Decoding" in text
```

NOTE for the implementer: the above sketches intent but is convoluted — implement it the straightforward way: read `tests/test_web.py`'s existing `_seed_models` helper to learn the first seeded model id (it is a literal in the helper, e.g. `qwen3-8b`), then write the test plainly:

```python
def _seed_pedigree_research_run_for_model(root: Path, model_ref: str) -> None:
    # same body as _seed_pedigree_research_run but with kind=ImplKind.MODEL, ref=model_ref

def test_model_page_shows_research_pedigree(tmp_path: Path):
    _seed_models(tmp_path)
    _seed_pedigree_research_run_for_model(tmp_path, "qwen3-8b")  # ← the helper's real first id

    text = TestClient(create_app(tmp_path)).get("/model/qwen3-8b").text

    assert "Research techniques" in text
    assert "Speculative Decoding" in text
    assert 'href="/technique/spec-dec"' in text
```

Append to `tests/test_static_site.py`:

```python
def test_static_model_page_shows_pedigree(tmp_path):
    from radar.models import Ring
    from radar.research_radar.pedigree import TechniquePedigree

    entry = _model_entry()  # reuse this file's existing ModelEntry helper (adjust name if it differs)
    render_static_site(
        [], tmp_path / "_site", datetime(2026, 7, 5, tzinfo=UTC),
        model_entries=[entry],
        pedigree_by_model={entry.id: [TechniquePedigree(
            technique_id="spec-dec", name="Speculative Decoding",
            ring=Ring.ADOPT, citation_count=1697,
        )]},
        technique_hrefs={"spec-dec": "technique_spec-dec.html"},
    )

    page_name = next(p.name for p in (tmp_path / "_site").iterdir()
                     if p.name.startswith("model_"))
    page = (tmp_path / "_site" / page_name).read_text(encoding="utf-8")
    assert "Research techniques" in page
    assert 'href="technique_spec-dec.html"' in page
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_web.py tests/test_static_site.py -v -k "model and pedigree"`
Expected: FAIL — section absent

- [ ] **Step 3: Implement**

`src/radar/web/templates/_model_detail.html` — append at the end (after the "Runs on" block):

```html
{% if pedigree %}
<h3>Research techniques</h3>
<ul>
  {% for t in pedigree %}
  <li><a href="{{ technique_hrefs[t.technique_id] }}">{{ t.name }}</a>
      — {{ t.ring.value if t.ring else 'unringed' }}
      {% if t.citation_count is not none %} · {{ t.citation_count }} citations{% endif %}</li>
  {% endfor %}
</ul>
{% endif %}
```

`src/radar/web/app.py` — in `model_detail`, add a `_model_pedigree(model_id)` helper mirroring `_project_pedigree` but over `by_model_ref` with `refs=[model_id]`, and extend the context: `"pedigree": _model_pedigree(model_id) or None, "technique_hrefs": {...}` (same href builder as Task 3 — extract a shared `_technique_hrefs()` closure now that two routes need it, and use it in BOTH the project and model routes).

`src/radar/web/static_site.py` — `_write_model_pages` gains `pedigree_by_model: dict[str, list[TechniquePedigree]] | None = None, technique_hrefs: dict[str, str] | None = None` params; the call site passes them from `render_static_site`'s params; per-entry render context gains `pedigree=(pedigree_by_model or {}).get(entry.id) or None, technique_hrefs=technique_hrefs or {}`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_web.py tests/test_static_site.py -v`
Expected: PASS

- [ ] **Step 5: Lint + typecheck + commit**

```bash
uv run ruff check src/radar tests/test_web.py tests/test_static_site.py && uv run mypy src/radar
git add src/radar/web/templates/_model_detail.html src/radar/web/app.py src/radar/web/static_site.py \
  tests/test_web.py tests/test_static_site.py
git commit -m "feat: research-techniques section on model pages (live + static)"
```

---

### Task 5: Technique pages link back to tool/model pages

**Files:**
- Modify: `src/radar/web/templates/_technique_detail.html`, `src/radar/web/app.py` (technique route), `src/radar/web/static_site.py` (`_write_technique_pages`), `src/radar/cli.py` (export builds impl hrefs)
- Test: `tests/test_web.py`, `tests/test_static_site.py` (append)

**Interfaces:**
- Consumes: `load_config` (id→project), `build_slug_map` (project + model slugs), existing route/writer contexts.
- Produces: `_technique_detail.html`'s implementations list renders `impl.ref` as a link when `impl.ref in impl_hrefs`, plain text otherwise; context key `impl_hrefs: dict[str, str]` (ref → href). Live hrefs: tool ref → `/project/{project name}` (via config id→project; URL-quote the name with Jinja's default escaping — pass the href prebuilt), model ref → `/model/{ref}`. Static hrefs: tool ref → `project_<slug>.html` ONLY when that project has a card in this export (slug map from cards), model ref → `model_<slug>.html` ONLY when the model is in this export's entries. Unresolvable refs stay plain text.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_web.py`:

```python
def test_technique_page_links_implementations(tmp_path: Path):
    db = RadarDatabase(tmp_path / "data" / "radar.db")
    db.initialize()
    db.upsert_cards([_card_for_web("vLLM", Ring.ADOPT)])  # reuse the existing card helper name
    _write_pedigree_config(tmp_path, "github-vllm", "vLLM")
    _seed_pedigree_research_run(tmp_path, "github-vllm")

    text = TestClient(create_app(tmp_path)).get("/technique/spec-dec").text

    assert 'href="/project/vLLM"' in text          # tool impl linked
    assert 'href="/model/llama-3.3-70b"' in text   # model impl linked


def test_technique_page_unresolvable_impl_stays_plain(tmp_path: Path):
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    _seed_pedigree_research_run(tmp_path, "github-gone")  # no config → no id→project map

    text = TestClient(create_app(tmp_path)).get("/technique/spec-dec").text

    assert "github-gone" in text
    assert 'href="/project/' not in text
```

Append to `tests/test_static_site.py`:

```python
def test_static_technique_page_links_impls_only_when_targets_exist(tmp_path):
    entry = _technique_entry()  # existing helper: spec-dec with papers; extend if needed
    entry = entry.model_copy(update={"resolved_implementations": [
        __import__("radar.research_radar.entities", fromlist=["ResolvedImplementation"])
        .ResolvedImplementation(kind=__import__(
            "radar.research_radar.entities", fromlist=["ImplKind"]).ImplKind.TOOL,
            ref="github-vllm", ring=None),
    ]})

    render_static_site(
        [], tmp_path / "_site", datetime(2026, 7, 5, tzinfo=UTC),
        technique_entries=[entry],
        impl_hrefs={"github-vllm": "project_vllm.html"},
    )

    page = (tmp_path / "_site" / "technique_speculative-decoding.html").read_text(
        encoding="utf-8")
    assert 'href="project_vllm.html"' in page
```

NOTE for the implementer: the dunder-`__import__` contortions above are sketches — write them as plain top-of-function imports in the real test (`from radar.research_radar.entities import ImplKind, ResolvedImplementation`).

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_web.py tests/test_static_site.py -v -k "technique and (impl or links)"`
Expected: FAIL — no hrefs / `TypeError` on `impl_hrefs`

- [ ] **Step 3: Implement**

`_technique_detail.html` — replace the implementations `<li>` line with:

```html
  <li>[{{ impl.kind.value }}]
      {% if impl.ref in impl_hrefs %}<a href="{{ impl_hrefs[impl.ref] }}">{{ impl.ref }}</a>
      {% else %}{{ impl.ref }}{% endif %}
      — {{ impl.ring.value if impl.ring else 'unringed' }}
      {% if impl.note %}· {{ impl.note }}{% endif %}</li>
```

(Keep the em-dash separator consistent with the current template's format; `impl_hrefs` must default safely — add `{% set impl_hrefs = impl_hrefs | default({}) %}` at the top of the partial so existing callers without the key keep working.)

`src/radar/web/app.py` — in `technique_detail`, build and pass `impl_hrefs`:

```python
        impl_hrefs: dict[str, str] = {}
        try:
            config = load_config(root / "data" / "config.yaml")
            project_by_id = {s.id: s.project for s in config.sources}
        except Exception:
            project_by_id = {}
        model_ids = {m.id for m in _model_entries()}
        for impl in entry.resolved_implementations:
            if impl.kind.value == "tool" and impl.ref in project_by_id:
                impl_hrefs[impl.ref] = f"/project/{project_by_id[impl.ref]}"
            elif impl.kind.value == "model" and impl.ref in model_ids:
                impl_hrefs[impl.ref] = f"/model/{impl.ref}"
```

(Import `ImplKind` and compare `impl.kind == ImplKind.TOOL` instead of `.value` string comparison if the import is already available — prefer the enum.) Add `"impl_hrefs": impl_hrefs` to the context.

`src/radar/web/static_site.py` — `render_static_site` gains `impl_hrefs: dict[str, str] | None = None`; `_write_technique_pages` gains and threads it into each `static_technique.html` render context (`impl_hrefs=impl_hrefs or {}`).

`src/radar/cli.py` export — build static impl hrefs next to the pedigree maps (inside the same `if technique_entries:` block; `slug_by_project` for cards is already computed in the export flow — reuse it; model slugs via `build_slug_map([m.id for m in model_entries])`, matching `_write_model_pages`' filenames):

```python
        impl_hrefs: dict[str, str] = {}
        project_by_id = {s.id: s.project for s in export_config.sources}
        card_slugs = build_slug_map([c.project for c in cards])
        model_slugs = build_slug_map([m.id for m in model_entries]) if model_entries else {}
        for technique in technique_entries:
            for impl in technique.resolved_implementations:
                if impl.ref in impl_hrefs:
                    continue
                if impl.kind.value == "tool":
                    project = project_by_id.get(impl.ref)
                    if project in card_slugs:
                        impl_hrefs[impl.ref] = f"project_{card_slugs[project]}.html"
                elif impl.ref in model_slugs:
                    impl_hrefs[impl.ref] = f"model_{model_slugs[impl.ref]}.html"
```

and pass `impl_hrefs=impl_hrefs or None` to `render_static_site`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_web.py tests/test_static_site.py tests/test_cli.py -v`
Expected: PASS

- [ ] **Step 5: Lint + typecheck + commit**

```bash
uv run ruff check src/radar tests/test_web.py tests/test_static_site.py && uv run mypy src/radar
git add src/radar/web/templates/_technique_detail.html src/radar/web/app.py \
  src/radar/web/static_site.py src/radar/cli.py tests/test_web.py tests/test_static_site.py
git commit -m "feat: technique pages link implementations to project/model pages"
```

---

### Task 6: MCP payloads + docs + gates

**Files:**
- Modify: `src/radar/mcp_server/queries.py` (`get_project`), `src/radar/mcp_server/model_queries.py` (`get_model`), `README.md`, `CHANGELOG.md`
- Test: `tests/test_mcp_queries.py`, `tests/test_model_queries.py` (append)

**Interfaces:**
- Consumes: Task 1 helpers, `_latest_technique_cards`, `load_config`.
- Produces: `get_project(project)` payload gains `"techniques": [{"id", "name", "ring", "citation_count"}, ...]` (empty list when no research data; best-effort try/except → `[]`); `get_model(model_id)` payload gains the same key from `by_model_ref`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_mcp_queries.py` (reuse this file's existing seeding helpers for cards; seed the research run with the same `RunStore` pattern as elsewhere):

```python
def test_get_project_includes_techniques(tmp_path):
    _seed_cards(tmp_path)  # reuse/adjust to the file's existing card-seeding helper
    _seed_pedigree_research_run(tmp_path)  # write helper: technique spec-dec → tool ref
    # whose source id maps to the seeded card's project via a data/config.yaml
    svc = RadarQueryService(tmp_path)

    payload = svc.get_project("vLLM")

    assert payload["techniques"] == [{
        "id": "spec-dec", "name": "Speculative Decoding",
        "ring": "adopt", "citation_count": 1697,
    }]


def test_get_project_without_research_run_has_empty_techniques(tmp_path):
    _seed_cards(tmp_path)
    svc = RadarQueryService(tmp_path)

    assert svc.get_project("vLLM")["techniques"] == []
```

Append to `tests/test_model_queries.py`:

```python
def test_get_model_includes_techniques(tmp_path: Path):
    _seed(tmp_path)  # existing models seeding helper in this file
    # seed a research run whose technique has kind=model, ref=<first seeded model id>
    _seed_model_pedigree_run(tmp_path, "qwen3-8b")  # adjust ref to the helper's real id
    svc = ModelQueryService(tmp_path)

    payload = svc.get_model("qwen3-8b")

    assert payload["techniques"][0]["id"] == "spec-dec"
    assert payload["techniques"][0]["ring"] == "adopt"


def test_get_model_without_research_run_has_empty_techniques(tmp_path: Path):
    _seed(tmp_path)
    svc = ModelQueryService(tmp_path)

    assert svc.get_model("qwen3-8b")["techniques"] == []
```

(Write the two research-run seeding helpers in each test file following the established `RunStore` + `technique_cards` + `kind="research"` pattern used in `tests/test_technique_queries.py`; the mcp_queries variant also writes a minimal `data/config.yaml` mapping the tool source id to the card's project.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_mcp_queries.py tests/test_model_queries.py -v -k techniques`
Expected: FAIL — `KeyError: 'techniques'`

- [ ] **Step 3: Implement**

`src/radar/mcp_server/queries.py` — in `get_project`, after `detail["history"] = ...`, add:

```python
        detail["techniques"] = self._project_techniques(card.project)
```

and the helper on `RadarQueryService`:

```python
    def _project_techniques(self, project: str) -> list[dict[str, Any]]:
        """Techniques implemented by this project's sources (best-effort, [] on any gap)."""
        try:
            from radar.mcp_server.technique_queries import _latest_technique_cards
            from radar.research_radar.entities import TechniqueEntry
            from radar.research_radar.pedigree import build_pedigree_index, pedigree_for_refs
            from radar.storage.config import load_config

            entries = [TechniqueEntry.model_validate(c)
                       for c in _latest_technique_cards(self.root)]
            if not entries:
                return []
            config = load_config(self.root / "data" / "config.yaml")
            refs = [s.id for s in config.sources if s.project == project]
            items = pedigree_for_refs(build_pedigree_index(entries).by_tool_ref, refs)
            return [{"id": t.technique_id, "name": t.name,
                     "ring": t.ring.value if t.ring else None,
                     "citation_count": t.citation_count} for t in items]
        except Exception:
            return []
```

(Confirm `RadarQueryService` stores `self.root`; if it only stores db/history paths, add `self.root = Path(root)` in `__init__` following `ModelQueryService`.)

`src/radar/mcp_server/model_queries.py` — in `get_model`, after the momentum/history enrichment, add `payload["techniques"] = self._model_techniques(model_id)` with the analogous helper over `by_model_ref` and `refs=[model_id]` (no config needed).

- [ ] **Step 4: README + CHANGELOG**

README: in the 🎓 research Highlights bullet, append one sentence:

```markdown
 Tool and model pages cross-link back: each shows the research techniques it implements, and tool cards carry an "Implements N tracked research techniques" evidence line.
```

CHANGELOG: under `## [Unreleased]` → `### Added`, above the "(surfaces)" entry:

```markdown
- **Research pedigree cross-linking** — the three radars now reference each
  other: tool decision cards carry an "Implements N tracked research
  techniques" evidence line (best-effort, never affects scoring), project and
  model pages show the techniques they implement (with rings + citations,
  linked to the technique pages), technique pages link implementations back to
  project/model pages, and MCP `get_project`/`get_model` payloads gain a
  `techniques` list.
```

- [ ] **Step 5: Full gates**

Run: `uv run pytest && uv run ruff check . && uv run mypy src/radar`
Expected: all green, coverage ≥ 80%.

- [ ] **Step 6: Commit**

```bash
git add src/radar/mcp_server/queries.py src/radar/mcp_server/model_queries.py \
  tests/test_mcp_queries.py tests/test_model_queries.py README.md CHANGELOG.md
git commit -m "feat: techniques in MCP get_project/get_model + pedigree docs"
```

---

## Self-Review Notes (already applied)

- Spec §9 cross-linking coverage: evidence line (T2), project/model page sections with rings+citations (T3/T4), technique→tool/model back-links (T5), MCP (T6). "Citation velocity" is represented by the citation count on each pedigree item — full velocity display would need the metrics store on the read path; deliberately out of scope (recorded under File Structure).
- Pedigree never touches scoring: `_attach_pedigree` runs AFTER `build_decision_cards` and only appends to `evidence_notes`.
- Type consistency: `TechniquePedigree`/`pedigree_for_refs`/`pedigree_note`/`build_pedigree_index` names match across T1→T2/T3/T4/T6; `pedigree`/`technique_hrefs`/`impl_hrefs` context keys match template ↔ route ↔ writer ↔ CLI.
- Tests that reference existing helpers by guessed names carry explicit implementer notes to reuse the file's real helpers — the assertions, not the helper names, are the contract.
