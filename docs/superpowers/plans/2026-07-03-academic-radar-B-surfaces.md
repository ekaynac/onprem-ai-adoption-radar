# Academic Research Radar — Plan B (Surfaces) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the technique radar its surfaces: `/research` catalog + per-technique pages (dashboard and static export, with a research→production timeline), MCP tools, change feeds, daily-CI wiring, and the scan-health kind-filter fix.

**Architecture:** Mirror the local-model surface layer exactly: a kind-filtered run-store loader (`technique_queries.py` ≙ `model_queries.py`), live/static template pairs sharing a `_technique_detail.html` body (≙ `_model_detail.html`), `_write_technique_pages` inside `static_site.py` (≙ `_write_model_pages`), Atom/JSON feed renderers in `research_radar/reports.py` (≙ `models_radar/reports.py`), and an index summary partial (≙ `_models_summary.html`). The one net-new element is the timeline builder that merges paper dates with ring history.

**Tech Stack:** Python 3.12, FastAPI + Jinja2 (in-tree), FastMCP (in-tree), pytest + ruff + mypy. **No new dependencies.**

**Spec:** `docs/superpowers/specs/2026-07-03-academic-research-radar-design.md` §9 (Surfaces bullet, incl. its "known items" list).

## Global Constraints

- Deterministic, offline rendering: every surface reads persisted runs/history — no network anywhere in this plan.
- ruff line-length = 100; python 3.12; every Python file starts with `from __future__ import annotations`.
- Gates: `uv run pytest` (≥80% coverage), `uv run ruff check .`, `uv run mypy src/radar`.
- Commit format `<type>: <description>`; no attribution lines; `git add` specific paths only (the working tree may hold an unrelated modified `data/history.jsonl` that must never be committed).
- Live/static template pairs differ ONLY in nav/link targets (`/research` + `/technique/{id}` live vs `techniques.html` + `technique_<slug>.html` static) — the established models-pages convention.
- Run-kind facts: main tool scans have NO `kind` key in run meta; model scans have `kind="models"`; research scans have `kind="research"` with stage `technique_cards`. History file: `data/technique-history.jsonl`.
- Existing symbols this plan consumes (all on main today): `TechniqueEntry` (fields incl. `id,name,category,domain,papers,resolved_implementations,citation_count,score,score_breakdown,ring,warnings,superseded_by,notes,onprem_impact,open_code,peer_reviewed`), `TechniqueHistoryEvent` (`technique_id,domain,change_type,ring,previous_ring,run_id,observed_at,reasons`), `load_technique_events(path)`, `momentum_for(entries, db_path) -> dict[str, MomentumSignal]`, `MomentumSignal(technique_id,score,direction,citation_growth_pct,note)`, `build_slug_map(ids)`, `render_static_site(...)`, `create_app(root)`, `build_mcp_server(root)`.

## File Structure

```
src/radar/research_radar/reports.py        # MODIFY: + technique_events_to_feed_json/atom (+_xml_escape, _event_title)
src/radar/research_radar/timeline.py       # NEW: TimelineItem + build_technique_timeline
src/radar/mcp_server/technique_queries.py  # NEW: _latest_technique_cards + TechniqueQueryService
src/radar/mcp_server/server.py             # MODIFY: register list_techniques/get_technique/technique_movers
src/radar/web/research_summary.py          # NEW: TechniquesSummary + summarize_techniques
src/radar/web/scan_health.py               # MODIFY: + latest_tool_scan_meta (kind-filter fix)
src/radar/web/app.py                       # MODIFY: /research + /technique/{id} routes, index summary, health fix
src/radar/web/static_site.py               # MODIFY: technique params, _write_technique_pages, downloads
src/radar/cli.py                           # MODIFY: export wiring + health fix + _latest_technique_entries refactor
src/radar/web/templates/
    techniques.html static_techniques.html          # catalog table (live/static pair)
    technique.html static_technique.html            # detail shells (live/static pair)
    _technique_detail.html                          # shared detail body (incl. timeline)
    _techniques_filter_bar.html _techniques_filter_script.html _techniques_sort_script.html
    _research_summary.html                          # index banner partial
    index.html static_index.html                    # MODIFY: nav + summary include
.github/workflows/publish.yml              # MODIFY: research scan + technique-history commit
tests/test_research_radar_feeds.py         # NEW
tests/test_research_radar_timeline.py      # NEW
tests/test_technique_queries.py            # NEW
tests/test_mcp_server.py                   # MODIFY: technique tool registration
tests/test_research_summary.py             # NEW
tests/test_web.py                          # MODIFY: research routes + scan-health fix
tests/test_static_site.py                  # MODIFY: research section
tests/test_cli.py                          # MODIFY: export research assertions
tests/test_publish_workflow.py             # MODIFY: research ordering assertion
```

Out of scope: linking implementation refs to project/model pages from the technique detail (needs slug+kind routing across catalogs — a later polish); RSS variant for technique feeds (models only ship Atom+JSON; mirror that); `_FEED_LIMIT` slicing for technique feeds (models pass all events; mirror models — the shared inconsistency is a pre-existing nit); technique catalog autopilot; CI persistence of `radar.db` (decision recorded in spec §9, deferred).

---

### Task 1: Technique change-feed renderers

**Files:**
- Modify: `src/radar/research_radar/reports.py` (append)
- Test: `tests/test_research_radar_feeds.py`

**Interfaces:**
- Consumes: `TechniqueHistoryEvent`.
- Produces: `technique_events_to_feed_json(events: list[Any], site_title: str) -> dict[str, Any]` and `technique_events_to_feed_atom(events: list[Any], site_title: str, self_url: str) -> str` — Task 7 (static export) imports these exact names. Item ids are `urn:radar-technique:{technique_id}:{run_id}`; JSON items carry `tags: [domain, ring]`; both sort newest-first internally (mirror of `models_radar/reports.py:69-98`).

- [ ] **Step 1: Write the failing tests**

```python
"""Technique ring-change feeds (Atom + JSON Feed), mirror of the model feeds."""

from __future__ import annotations

from datetime import UTC, datetime

from radar.models import Ring
from radar.research_radar.entities import TechniqueDomain
from radar.research_radar.history import TechniqueHistoryEvent
from radar.research_radar.reports import (
    technique_events_to_feed_atom,
    technique_events_to_feed_json,
)
from radar.storage.history_store import ChangeType


def _event(technique_id: str, ring: Ring, at: str,
           previous: Ring | None = None) -> TechniqueHistoryEvent:
    return TechniqueHistoryEvent(
        technique_id=technique_id, domain=TechniqueDomain.INFERENCE,
        change_type=ChangeType.PROMOTED if previous else ChangeType.NEW,
        ring=ring, previous_ring=previous, run_id="run-1",
        observed_at=datetime.fromisoformat(at),
        reasons=[f"promoted to {ring.value}" if previous else f"new ({ring.value})"],
    )


OLD = _event("lora", Ring.ADOPT, "2026-07-01T10:00:00+00:00")
NEW = _event("medusa-decoding", Ring.PILOT, "2026-07-03T10:00:00+00:00", previous=Ring.WATCH)


def test_json_feed_items_newest_first_with_urn_and_tags():
    feed = technique_events_to_feed_json([OLD, NEW], site_title="Radar")

    assert feed["version"] == "https://jsonfeed.org/version/1.1"
    assert feed["title"] == "Radar — Research"
    assert [i["id"] for i in feed["items"]] == [
        "urn:radar-technique:medusa-decoding:run-1",
        "urn:radar-technique:lora:run-1",
    ]
    assert feed["items"][0]["title"] == "medusa-decoding: watch → pilot (promoted)"
    assert feed["items"][0]["tags"] == ["inference", "pilot"]


def test_atom_feed_escapes_and_carries_self_url():
    feed = technique_events_to_feed_atom([OLD], site_title="R<adar",
                                         self_url="https://x.test/changes-research.xml")

    assert '<link rel="self" href="https://x.test/changes-research.xml"/>' in feed
    assert "R&lt;adar — Research" in feed
    assert "urn:radar-technique:lora:run-1" in feed


def test_atom_feed_empty_events_still_valid():
    feed = technique_events_to_feed_atom([], site_title="Radar", self_url="changes-research.xml")

    assert feed.startswith('<?xml version="1.0"')
    assert "<updated>" in feed
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_research_radar_feeds.py -v`
Expected: FAIL — `ImportError: cannot import name 'technique_events_to_feed_atom'`

- [ ] **Step 3: Append the implementation to `src/radar/research_radar/reports.py`**

```python
def _feed_event_title(ev: Any) -> str:
    """Format a technique ring-change event as a feed title line."""
    prev = ev.previous_ring.value if ev.previous_ring else None
    if prev:
        return f"{ev.technique_id}: {prev} → {ev.ring.value} ({ev.change_type.value})"
    return f"{ev.technique_id}: {ev.change_type.value} ({ev.ring.value})"


def technique_events_to_feed_json(events: list[Any], site_title: str) -> dict[str, Any]:
    """Convert technique events to JSON Feed 1.1 format (newest-first)."""
    items = []
    for ev in sorted(events, key=lambda e: e.observed_at, reverse=True):
        items.append({
            "id": f"urn:radar-technique:{ev.technique_id}:{ev.run_id}",
            "title": _feed_event_title(ev),
            "content_text": "; ".join(ev.reasons) or _feed_event_title(ev),
            "date_published": ev.observed_at.isoformat(),
            "tags": [ev.domain.value, ev.ring.value],
        })
    return {"version": "https://jsonfeed.org/version/1.1",
            "title": f"{site_title} — Research", "items": items}


def technique_events_to_feed_atom(events: list[Any], site_title: str, self_url: str) -> str:
    """Convert technique events to an Atom feed (newest-first)."""
    rows = sorted(events, key=lambda e: e.observed_at, reverse=True)
    updated = rows[0].observed_at.isoformat() if rows else datetime.now().astimezone().isoformat()
    entries_xml = "".join(
        f"<entry><title>{_xml_escape(_feed_event_title(ev))}</title>"
        f"<id>urn:radar-technique:{ev.technique_id}:{ev.run_id}</id>"
        f"<updated>{ev.observed_at.isoformat()}</updated>"
        f"<summary>{_xml_escape('; '.join(ev.reasons) or _feed_event_title(ev))}</summary></entry>"
        for ev in rows
    )
    return (f'<?xml version="1.0" encoding="utf-8"?>'
            f'<feed xmlns="http://www.w3.org/2005/Atom">'
            f"<title>{_xml_escape(site_title)} — Research</title>"
            f'<link rel="self" href="{_xml_escape(self_url)}"/><updated>{updated}</updated>'
            f"{entries_xml}</feed>")


def _xml_escape(s: str) -> str:
    """Escape string for XML text content and attributes."""
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))
```

Ensure the imports the new code needs exist at the top of the file: `from datetime import datetime` and `from typing import Any` — check what `reports.py` already imports and add only what is missing.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_research_radar_feeds.py tests/test_research_radar_reports.py -v`
Expected: PASS (new + existing report tests)

- [ ] **Step 5: Lint + typecheck + commit**

```bash
uv run ruff check src/radar/research_radar tests/test_research_radar_feeds.py && uv run mypy src/radar
git add src/radar/research_radar/reports.py tests/test_research_radar_feeds.py
git commit -m "feat: technique ring-change feeds (Atom + JSON)"
```

---

### Task 2: Research→production timeline builder

**Files:**
- Create: `src/radar/research_radar/timeline.py`
- Test: `tests/test_research_radar_timeline.py`

**Interfaces:**
- Consumes: `TechniqueEntry` (papers with `published`/`role`/`title`), `TechniqueHistoryEvent`.
- Produces: `TimelineItem` (frozen: `date: str`, `label: str`, `kind: str` — `"paper" | "ring"`), `build_technique_timeline(entry: TechniqueEntry, events: list[TechniqueHistoryEvent]) -> list[TimelineItem]` — Tasks 6/7 pass the result to `_technique_detail.html` as `timeline`. Chronological (ISO-prefix lexicographic sort is correct for `YYYY-MM` vs `YYYY-MM-DD`); papers without a `published` date are skipped; only events for `entry.id` are included.

- [ ] **Step 1: Write the failing tests**

```python
"""Timeline: papers + ring history merged chronologically."""

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
from radar.research_radar.timeline import TimelineItem, build_technique_timeline
from radar.storage.history_store import ChangeType


def _entry(papers: list[PaperLink]) -> TechniqueEntry:
    return TechniqueEntry(
        id="speculative-decoding", name="Speculative Decoding",
        category=Category.MODEL_SERVING, domain=TechniqueDomain.INFERENCE,
        onprem_impact=OnPremImpact.REDUCES_LATENCY, papers=papers,
    )


def _ring_event(technique_id: str, at: str) -> TechniqueHistoryEvent:
    return TechniqueHistoryEvent(
        technique_id=technique_id, domain=TechniqueDomain.INFERENCE,
        change_type=ChangeType.NEW, ring=Ring.ADOPT, run_id="run-1",
        observed_at=datetime.fromisoformat(at),
    )


def test_timeline_merges_papers_and_rings_chronologically():
    papers = [
        PaperLink(arxiv_id="2211.17192", title="Fast Inference", published="2022-11"),
        PaperLink(arxiv_id="2302.01318", title="Spec Sampling",
                  role=PaperRole.FOLLOWUP, published="2023-02"),
    ]
    events = [_ring_event("speculative-decoding", "2026-07-03T10:00:00+00:00")]

    timeline = build_technique_timeline(_entry(papers), events)

    assert [i.kind for i in timeline] == ["paper", "paper", "ring"]
    assert timeline[0] == TimelineItem(
        date="2022-11", label="canonical paper: Fast Inference", kind="paper")
    assert timeline[1].label == "followup paper: Spec Sampling"
    assert timeline[2].date == "2026-07-03"
    assert "adopt" in timeline[2].label and "new" in timeline[2].label


def test_timeline_skips_undated_papers_and_other_techniques():
    papers = [PaperLink(arxiv_id="0000.00000", title="No date")]
    events = [_ring_event("some-other-technique", "2026-07-03T10:00:00+00:00")]

    timeline = build_technique_timeline(_entry(papers), events)

    assert timeline == []


def test_timeline_promotion_label_includes_previous_ring():
    event = TechniqueHistoryEvent(
        technique_id="speculative-decoding", domain=TechniqueDomain.INFERENCE,
        change_type=ChangeType.PROMOTED, ring=Ring.ADOPT, previous_ring=Ring.PILOT,
        run_id="run-2", observed_at=datetime(2026, 7, 4, 10, 0, tzinfo=UTC),
    )

    timeline = build_technique_timeline(_entry([]), [event])

    assert timeline[0].label == "pilot → adopt (promoted)"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_research_radar_timeline.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'radar.research_radar.timeline'`

- [ ] **Step 3: Write the implementation**

Create `src/radar/research_radar/timeline.py`:

```python
"""Research→production timeline: papers + ring history merged chronologically.

ISO-prefix dates ("2022-11", "2026-07-03") sort correctly with plain string
comparison, so no date parsing is needed — a deliberate simplification that
keeps the builder pure and total.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from radar.research_radar.entities import TechniqueEntry
from radar.research_radar.history import TechniqueHistoryEvent


class TimelineItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    date: str  # "YYYY-MM" or "YYYY-MM-DD"
    label: str
    kind: str  # "paper" | "ring"


def build_technique_timeline(
    entry: TechniqueEntry, events: list[TechniqueHistoryEvent],
) -> list[TimelineItem]:
    items: list[TimelineItem] = []
    for paper in entry.papers:
        if not paper.published:
            continue
        items.append(TimelineItem(
            date=paper.published,
            label=f"{paper.role.value} paper: {paper.title}",
            kind="paper",
        ))
    for event in events:
        if event.technique_id != entry.id:
            continue
        prev = f"{event.previous_ring.value} → " if event.previous_ring else ""
        items.append(TimelineItem(
            date=event.observed_at.date().isoformat(),
            label=f"{prev}{event.ring.value} ({event.change_type.value})",
            kind="ring",
        ))
    return sorted(items, key=lambda item: item.date)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_research_radar_timeline.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Lint + typecheck + commit**

```bash
uv run ruff check src/radar/research_radar tests/test_research_radar_timeline.py && uv run mypy src/radar
git add src/radar/research_radar/timeline.py tests/test_research_radar_timeline.py
git commit -m "feat: technique research-to-production timeline builder"
```

---

### Task 3: MCP technique query service

**Files:**
- Create: `src/radar/mcp_server/technique_queries.py`
- Modify: `src/radar/cli.py` (`_latest_technique_entries` delegates to the new loader)
- Test: `tests/test_technique_queries.py`

**Interfaces:**
- Consumes: `RunStore` (kind-filtered run walk — mirror `mcp_server/model_queries.py:_latest_model_cards`), `TechniqueEntry`, `load_technique_events`, `momentum_for`.
- Produces: `_latest_technique_cards(root: Path) -> list[dict[str, Any]]` (raw `technique_cards.json` dicts of the latest `kind=="research"` run; `[]` if none — Tasks 6/7 also use it) and `TechniqueQueryService(root)` with:
  - `list_techniques(ring: str | None = None, domain: str | None = None, category: str | None = None, detail: str = "compact") -> list[dict[str, Any]]` — compact row = `{id, name, domain, category, ring, score, citation_count, implementations}`; `detail="full"` = full `model_dump(mode="json")`. Filters are case-insensitive.
  - `get_technique(technique_id: str) -> dict[str, Any] | None` — full dump + `history` (this technique's events, oldest-first) + `momentum` (`{direction, score, note}`).
  - `technique_movers() -> list[dict[str, Any]]` — last 10 ring events newest-first: `{technique_id, change, ring, previous_ring, observed_at}`.

- [ ] **Step 1: Write the failing tests**

```python
"""MCP technique query service over persisted research runs."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from radar.mcp_server.technique_queries import TechniqueQueryService, _latest_technique_cards
from radar.models import Category, Ring
from radar.research_radar.entities import OnPremImpact, TechniqueDomain, TechniqueEntry
from radar.research_radar.history import TechniqueHistoryEvent, append_technique_events
from radar.storage.history_store import ChangeType
from radar.storage.run_store import RunStore


def _entry(technique_id: str, ring: Ring, domain: TechniqueDomain,
           citations: int | None = 100) -> TechniqueEntry:
    return TechniqueEntry(
        id=technique_id, name=technique_id.title(), category=Category.MODEL_SERVING,
        domain=domain, onprem_impact=OnPremImpact.REDUCES_LATENCY, ring=ring,
        citation_count=citations, score=3.5,
    )


def _seed_research_run(root: Path, entries: list[TechniqueEntry]) -> None:
    (root / "data").mkdir(parents=True, exist_ok=True)
    store = RunStore(root / "data" / "runs")
    run_id = store.create_run()
    store.save_stage(run_id, "technique_cards", [e.model_dump(mode="json") for e in entries])
    store.update_meta(run_id, {"kind": "research", "technique_count": len(entries)})


def test_latest_cards_empty_without_research_run(tmp_path):
    (tmp_path / "data").mkdir()

    assert _latest_technique_cards(tmp_path) == []


def test_list_techniques_compact_and_filters(tmp_path):
    _seed_research_run(tmp_path, [
        _entry("speculative-decoding", Ring.ADOPT, TechniqueDomain.INFERENCE),
        _entry("qlora", Ring.WATCH, TechniqueDomain.FINE_TUNING),
    ])
    svc = TechniqueQueryService(tmp_path)

    rows = svc.list_techniques()
    assert {r["id"] for r in rows} == {"speculative-decoding", "qlora"}
    assert rows[0].keys() >= {"id", "name", "domain", "ring", "score",
                              "citation_count", "implementations"}

    assert [r["id"] for r in svc.list_techniques(ring="ADOPT")] == ["speculative-decoding"]
    assert [r["id"] for r in svc.list_techniques(domain="fine_tuning")] == ["qlora"]
    assert svc.list_techniques(category="coding_agents") == []


def test_list_techniques_full_detail_dumps_everything(tmp_path):
    _seed_research_run(tmp_path, [_entry("qlora", Ring.WATCH, TechniqueDomain.FINE_TUNING)])
    svc = TechniqueQueryService(tmp_path)

    rows = svc.list_techniques(detail="full")

    assert rows[0]["onprem_impact"] == "reduces_latency"
    assert "resolved_implementations" in rows[0]


def test_get_technique_includes_history_and_momentum(tmp_path):
    _seed_research_run(tmp_path, [_entry("qlora", Ring.WATCH, TechniqueDomain.FINE_TUNING)])
    append_technique_events(tmp_path / "data" / "technique-history.jsonl", [
        TechniqueHistoryEvent(
            technique_id="qlora", domain=TechniqueDomain.FINE_TUNING,
            change_type=ChangeType.NEW, ring=Ring.WATCH, run_id="run-1",
            observed_at=datetime(2026, 7, 3, 10, 0, tzinfo=UTC),
        ),
    ])
    svc = TechniqueQueryService(tmp_path)

    payload = svc.get_technique("qlora")

    assert payload["id"] == "qlora"
    assert payload["history"][0]["change_type"] == "new"
    assert payload["momentum"]["direction"] in {"rising", "falling", "steady"}
    assert svc.get_technique("nope") is None


def test_technique_movers_newest_first_capped_at_10(tmp_path):
    (tmp_path / "data").mkdir()
    _seed_research_run(tmp_path, [])
    events = [
        TechniqueHistoryEvent(
            technique_id=f"t-{i}", domain=TechniqueDomain.INFERENCE,
            change_type=ChangeType.NEW, ring=Ring.WATCH, run_id="run-1",
            observed_at=datetime(2026, 7, 1, 10, i, tzinfo=UTC),
        )
        for i in range(12)
    ]
    append_technique_events(tmp_path / "data" / "technique-history.jsonl", events)
    svc = TechniqueQueryService(tmp_path)

    movers = svc.technique_movers()

    assert len(movers) == 10
    assert movers[0]["technique_id"] == "t-11"  # newest first
    assert movers[0]["change"] == "new"


def test_cli_research_list_still_works_after_refactor(tmp_path):
    """cli._latest_technique_entries now delegates to _latest_technique_cards."""
    from typer.testing import CliRunner

    from radar.cli import app

    _seed_research_run(tmp_path, [_entry("qlora", Ring.WATCH, TechniqueDomain.FINE_TUNING)])
    runner = CliRunner()

    result = runner.invoke(app, ["research", "list", "--root", str(tmp_path)])

    assert result.exit_code == 0
    assert "qlora" in result.stdout
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_technique_queries.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'radar.mcp_server.technique_queries'`

- [ ] **Step 3: Write the implementation**

Create `src/radar/mcp_server/technique_queries.py`:

```python
"""Query service over persisted research (technique) runs — mirror of model_queries."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from radar.research_radar.entities import TechniqueEntry
from radar.research_radar.history import load_technique_events
from radar.research_radar.pipeline import momentum_for
from radar.storage.run_store import RunStore


def _latest_technique_cards(root: Path) -> list[dict[str, Any]]:
    """Raw technique_cards.json dicts from the latest kind==research run; [] if none."""
    run_store = RunStore(Path(root) / "data" / "runs")
    for run_id in reversed(run_store.list_runs()):
        if run_store.read_meta(run_id).get("kind") == "research":
            path = run_store._run_dir(run_id) / "technique_cards.json"
            return json.loads(path.read_text(encoding="utf-8"))
    return []


class TechniqueQueryService:
    """Read-only technique queries for MCP tools (and the web/CLI loaders)."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.db_path = self.root / "data" / "radar.db"
        self.history_path = self.root / "data" / "technique-history.jsonl"

    def _entries(self) -> list[TechniqueEntry]:
        return [TechniqueEntry.model_validate(c) for c in _latest_technique_cards(self.root)]

    def list_techniques(
        self,
        ring: str | None = None,
        domain: str | None = None,
        category: str | None = None,
        detail: str = "compact",
    ) -> list[dict[str, Any]]:
        entries = self._entries()
        if ring:
            entries = [e for e in entries if e.ring and e.ring.value == ring.lower()]
        if domain:
            entries = [e for e in entries if e.domain.value == domain.lower()]
        if category:
            entries = [e for e in entries if e.category.value == category.lower()]
        if detail == "full":
            return [e.model_dump(mode="json") for e in entries]
        return [self._compact(e) for e in entries]

    def get_technique(self, technique_id: str) -> dict[str, Any] | None:
        entry = next((e for e in self._entries() if e.id == technique_id), None)
        if entry is None:
            return None
        payload = entry.model_dump(mode="json")
        payload["history"] = [
            ev.model_dump(mode="json")
            for ev in load_technique_events(self.history_path)
            if ev.technique_id == technique_id
        ]
        momentum = momentum_for([entry], self.db_path)[entry.id]
        payload["momentum"] = {
            "direction": momentum.direction, "score": momentum.score, "note": momentum.note,
        }
        return payload

    def technique_movers(self) -> list[dict[str, Any]]:
        events = load_technique_events(self.history_path)
        recent = sorted(events, key=lambda e: e.observed_at, reverse=True)[:10]
        return [{
            "technique_id": ev.technique_id,
            "change": ev.change_type.value,
            "ring": ev.ring.value,
            "previous_ring": ev.previous_ring.value if ev.previous_ring else None,
            "observed_at": ev.observed_at.isoformat(),
        } for ev in recent]

    @staticmethod
    def _compact(entry: TechniqueEntry) -> dict[str, Any]:
        return {
            "id": entry.id,
            "name": entry.name,
            "domain": entry.domain.value,
            "category": entry.category.value,
            "ring": entry.ring.value if entry.ring else None,
            "score": entry.score,
            "citation_count": entry.citation_count,
            "implementations": len(entry.resolved_implementations),
        }
```

In `src/radar/cli.py`, replace the body of `_latest_technique_entries` (keep the signature) so the run-walk lives in one place:

```python
def _latest_technique_entries(root: Path):
    from radar.mcp_server.technique_queries import _latest_technique_cards
    from radar.research_radar.entities import TechniqueEntry as _TE

    payload = _latest_technique_cards(root)
    if not payload:
        return None
    return [_TE.model_validate(item) for item in payload]
```

Note the semantic edge: the old body returned entries for the latest research run even when the stage list was empty; `_latest_technique_cards` returns `[]` both for "no research run" and "research run with zero techniques", and both now render the "No research scan yet" prompt — acceptable (a zero-technique scan is indistinguishable from no scan for display purposes).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_technique_queries.py tests/test_research_cli.py -v`
Expected: PASS (new tests + existing research CLI tests unaffected by the refactor)

- [ ] **Step 5: Lint + typecheck + commit**

```bash
uv run ruff check src/radar/mcp_server src/radar/cli.py tests/test_technique_queries.py && uv run mypy src/radar
git add src/radar/mcp_server/technique_queries.py src/radar/cli.py tests/test_technique_queries.py
git commit -m "feat: MCP technique query service (list/get/movers)"
```

---

### Task 4: MCP server registration

**Files:**
- Modify: `src/radar/mcp_server/server.py`
- Test: `tests/test_mcp_server.py` (append)

**Interfaces:**
- Consumes: `TechniqueQueryService` (Task 3).
- Produces: MCP tools `list_techniques`, `get_technique`, `technique_movers` registered on the server built by `build_mcp_server(root)`.

- [ ] **Step 1: Write the failing tests (append to tests/test_mcp_server.py)**

```python
def _seed_techniques(root: Path) -> None:
    from radar.models import Category, Ring
    from radar.research_radar.entities import OnPremImpact, TechniqueDomain, TechniqueEntry
    from radar.storage.run_store import RunStore

    (root / "data").mkdir(parents=True, exist_ok=True)
    entry = TechniqueEntry(
        id="speculative-decoding", name="Speculative Decoding",
        category=Category.MODEL_SERVING, domain=TechniqueDomain.INFERENCE,
        onprem_impact=OnPremImpact.REDUCES_LATENCY, ring=Ring.ADOPT, score=4.3,
        citation_count=1697,
    )
    store = RunStore(root / "data" / "runs")
    run_id = store.create_run()
    store.save_stage(run_id, "technique_cards", [entry.model_dump(mode="json")])
    store.update_meta(run_id, {"kind": "research", "technique_count": 1})


def test_server_registers_technique_tools(tmp_path: Path):
    _seed_techniques(tmp_path)
    server = build_mcp_server(tmp_path)

    names = {t.name for t in asyncio.run(server.list_tools())}

    assert {"list_techniques", "get_technique", "technique_movers"} <= names


def test_list_techniques_tool_returns_compact_rows(tmp_path: Path):
    _seed_techniques(tmp_path)
    server = build_mcp_server(tmp_path)

    result = asyncio.run(server.call_tool("list_techniques", {"ring": "adopt"}))
    payload = result[1].get("result", result[1])

    assert any(item["id"] == "speculative-decoding" for item in payload)


def test_get_technique_tool_full_payload(tmp_path: Path):
    _seed_techniques(tmp_path)
    server = build_mcp_server(tmp_path)

    result = asyncio.run(server.call_tool("get_technique",
                                          {"technique_id": "speculative-decoding"}))
    payload = result[1].get("result", result[1])

    assert payload["citation_count"] == 1697
    assert "momentum" in payload
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_mcp_server.py -v -k technique`
Expected: FAIL — `AssertionError` (tool names missing)

- [ ] **Step 3: Register the tools**

In `src/radar/mcp_server/server.py`, inside `build_mcp_server` next to the model tools: instantiate the service alongside the existing ones (`techniques = TechniqueQueryService(root)`, import at top: `from radar.mcp_server.technique_queries import TechniqueQueryService`) and add:

```python
    @mcp.tool()
    def list_techniques(
        ring: str | None = None,
        domain: str | None = None,
        category: str | None = None,
        detail: str = "compact",
    ) -> list[dict]:
        """Research techniques with rings (compact rows; detail='full' for everything)."""
        return techniques.list_techniques(ring=ring, domain=domain,
                                          category=category, detail=detail)

    @mcp.tool()
    def get_technique(technique_id: str) -> dict | None:
        """One technique: score breakdown, papers, implementations, history, momentum."""
        return techniques.get_technique(technique_id)

    @mcp.tool()
    def technique_movers() -> list[dict]:
        """Recent technique ring changes, newest first."""
        return techniques.technique_movers()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_mcp_server.py -v`
Expected: PASS (existing + 3 new)

- [ ] **Step 5: Lint + typecheck + commit**

```bash
uv run ruff check src/radar/mcp_server tests/test_mcp_server.py && uv run mypy src/radar
git add src/radar/mcp_server/server.py tests/test_mcp_server.py
git commit -m "feat: MCP tools list_techniques/get_technique/technique_movers"
```

---

### Task 5: Index research summary

**Files:**
- Create: `src/radar/web/research_summary.py`
- Create: `src/radar/web/templates/_research_summary.html`
- Test: `tests/test_research_summary.py`

**Interfaces:**
- Consumes: `TechniqueEntry`.
- Produces: `TechniquesSummary` (frozen: `total: int`, `by_ring: dict[str, int]`, `by_domain: dict[str, int]`, property `has_techniques: bool`, property `one_line: str`), `summarize_techniques(entries: Iterable[TechniqueEntry]) -> TechniquesSummary` — Tasks 6/7 pass it to the index templates as `techniques_summary` (+ `research_href`). Mirror of `web/models_summary.py`.

- [ ] **Step 1: Write the failing tests**

```python
"""Index banner summary of the technique catalog (mirror of models_summary)."""

from __future__ import annotations

from radar.models import Category, Ring
from radar.research_radar.entities import OnPremImpact, TechniqueDomain, TechniqueEntry
from radar.web.research_summary import TechniquesSummary, summarize_techniques


def _entry(technique_id: str, ring: Ring | None, domain: TechniqueDomain) -> TechniqueEntry:
    return TechniqueEntry(
        id=technique_id, name=technique_id, category=Category.MODEL_SERVING,
        domain=domain, onprem_impact=OnPremImpact.REDUCES_LATENCY, ring=ring,
    )


def test_summarize_counts_rings_and_domains():
    summary = summarize_techniques([
        _entry("a", Ring.ADOPT, TechniqueDomain.INFERENCE),
        _entry("b", Ring.PILOT, TechniqueDomain.INFERENCE),
        _entry("c", Ring.WATCH, TechniqueDomain.RAG),
        _entry("d", None, TechniqueDomain.RAG),
    ])

    assert summary.total == 4
    assert summary.by_ring == {"adopt": 1, "pilot": 1, "watch": 1}
    assert summary.by_domain == {"inference": 2, "rag": 2}
    assert summary.has_techniques is True
    assert "4 techniques" in summary.one_line


def test_empty_summary_has_no_techniques():
    summary = summarize_techniques([])

    assert summary == TechniquesSummary()
    assert summary.has_techniques is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_research_summary.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

Create `src/radar/web/research_summary.py`:

```python
"""Immutable display summary of the technique catalog (mirror of models_summary)."""

from __future__ import annotations

from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict, Field

from radar.research_radar.entities import TechniqueEntry


class TechniquesSummary(BaseModel):
    """Immutable, display-ready summary of the technique catalog."""

    model_config = ConfigDict(frozen=True)

    total: int = 0
    by_ring: dict[str, int] = Field(default_factory=dict)
    by_domain: dict[str, int] = Field(default_factory=dict)

    @property
    def has_techniques(self) -> bool:
        return self.total > 0

    @property
    def one_line(self) -> str:
        adopt = self.by_ring.get("adopt", 0)
        pilot = self.by_ring.get("pilot", 0)
        return f"Research: {self.total} techniques — {adopt} adopt · {pilot} pilot"


def summarize_techniques(entries: Iterable[TechniqueEntry]) -> TechniquesSummary:
    total = 0
    by_ring: dict[str, int] = {}
    by_domain: dict[str, int] = {}
    for entry in entries:
        total += 1
        if entry.ring is not None:
            by_ring[entry.ring.value] = by_ring.get(entry.ring.value, 0) + 1
        by_domain[entry.domain.value] = by_domain.get(entry.domain.value, 0) + 1
    return TechniquesSummary(total=total, by_ring=by_ring, by_domain=by_domain)
```

Create `src/radar/web/templates/_research_summary.html`:

```html
{# Research summary. Context: techniques_summary (TechniquesSummary) | None. #}
{% if techniques_summary and techniques_summary.has_techniques %}
<div class="scan-health">
  <details>
    <summary>🎓 {{ techniques_summary.one_line }}</summary>
    <ul>
      {% for ring, n in techniques_summary.by_ring.items() %}<li>{{ ring }}: {{ n }}</li>{% endfor %}
      {% for domain, n in techniques_summary.by_domain.items() %}<li>{{ domain }}: {{ n }}</li>{% endfor %}
    </ul>
    <p><a href="{{ research_href|default('techniques.html') }}">Browse research →</a></p>
  </details>
</div>
{% endif %}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_research_summary.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Lint + typecheck + commit**

```bash
uv run ruff check src/radar/web tests/test_research_summary.py && uv run mypy src/radar
git add src/radar/web/research_summary.py src/radar/web/templates/_research_summary.html tests/test_research_summary.py
git commit -m "feat: index research summary (module + partial)"
```

---

### Task 6: Live dashboard — research templates + routes

**Files:**
- Create: `src/radar/web/templates/techniques.html`, `technique.html`, `_technique_detail.html`, `_techniques_filter_bar.html`, `_techniques_filter_script.html`, `_techniques_sort_script.html`
- Modify: `src/radar/web/templates/index.html` (nav + summary include), `src/radar/web/app.py` (routes + index context)
- Test: `tests/test_web.py` (append)

**Interfaces:**
- Consumes: `_latest_technique_cards` (Task 3), `build_technique_timeline` (Task 2), `summarize_techniques` (Task 5), `load_technique_events`, `build_slug_map`.
- Produces: routes `GET /research` (renders `techniques.html` with `{techniques, slug_by_technique}`) and `GET /technique/{technique_id}` (renders `technique.html` with `{technique, timeline}`; unknown id → 404). Index context gains `techniques_summary` + `research_href="/research"`; index nav gains `"Research": "/research"`. Templates carry `id="techniques-table"`, rows carry `data-technique/-domain/-ring/-category/-impls/-citations`, no-matches row id `techniques-no-matches` — Task 7's static pair must match these exactly.

- [ ] **Step 1: Write the failing tests (append to tests/test_web.py)**

```python
def _seed_techniques_run(root: Path) -> None:
    from radar.models import Category as _Cat
    from radar.models import Ring as _Ring
    from radar.research_radar.entities import (
        OnPremImpact as _Imp,
        PaperLink as _PL,
        TechniqueDomain as _Dom,
        TechniqueEntry as _TE,
    )
    from radar.storage.run_store import RunStore as _RS

    (root / "data").mkdir(parents=True, exist_ok=True)
    entry = _TE(
        id="speculative-decoding", name="Speculative Decoding",
        category=_Cat.MODEL_SERVING, domain=_Dom.INFERENCE,
        onprem_impact=_Imp.REDUCES_LATENCY, ring=_Ring.ADOPT, score=4.3,
        citation_count=1697,
        papers=[_PL(arxiv_id="2211.17192", title="Fast Inference", published="2022-11")],
    )
    store = _RS(root / "data" / "runs")
    run_id = store.create_run()
    store.save_stage(run_id, "technique_cards", [entry.model_dump(mode="json")])
    store.update_meta(run_id, {"kind": "research", "technique_count": 1})


def test_research_route_lists_techniques(tmp_path):
    _seed_techniques_run(tmp_path)
    client = TestClient(create_app(tmp_path))

    r = client.get("/research")

    assert r.status_code == 200
    assert "Speculative Decoding" in r.text
    assert "inference" in r.text
    assert 'href="/technique/speculative-decoding"' in r.text


def test_research_route_empty_without_scan(tmp_path):
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    client = TestClient(create_app(tmp_path))

    r = client.get("/research")

    assert r.status_code == 200
    assert "No research scan yet" in r.text


def test_technique_detail_route_shows_timeline_and_papers(tmp_path):
    _seed_techniques_run(tmp_path)
    client = TestClient(create_app(tmp_path))

    r = client.get("/technique/speculative-decoding")

    assert r.status_code == 200
    assert "2211.17192" in r.text
    assert "canonical paper" in r.text
    assert 'href="/research"' in r.text  # live back-link, not techniques.html


def test_technique_detail_unknown_returns_404(tmp_path):
    _seed_techniques_run(tmp_path)
    client = TestClient(create_app(tmp_path))

    assert client.get("/technique/nope").status_code == 404


def test_index_shows_research_summary_and_nav(tmp_path):
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    _seed_techniques_run(tmp_path)
    client = TestClient(create_app(tmp_path))

    r = client.get("/")

    assert "Research: 1 techniques" in r.text
    assert 'href="/research"' in r.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_web.py -v -k "research or technique"`
Expected: FAIL — 404 on `/research` (route missing)

- [ ] **Step 3: Create the templates**

`src/radar/web/templates/techniques.html`:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Research · Techniques</title>
    <link rel="icon" type="image/png" href="{{ asset_base }}static/brand/favicon.png" />
    {% include "_base_styles.html" %}
  </head>
  <body>
    {% set page_title = "Research Techniques" %}
    {% set tagline = "Research with rings — scored by which tracked tools already run it, plus citations." %}
    {% set nav = {"Radar": "/", "Models": "/models", "History": "/history"} %}
    {% include "_hero.html" %}
    <main class="container">
      {% if not techniques %}<p>No research scan yet.</p>{% endif %}
      {% include "_techniques_filter_bar.html" %}
      <table id="techniques-table">
        <thead>
          <tr>
            <th data-key="technique" data-type="str" onclick="techniquesSort(this)">Technique</th>
            <th data-key="domain" data-type="str" onclick="techniquesSort(this)">Domain</th>
            <th data-key="ring" data-type="str" onclick="techniquesSort(this)">Ring</th>
            <th data-key="category" data-type="str" onclick="techniquesSort(this)">Category</th>
            <th data-key="impls" data-type="num" onclick="techniquesSort(this)">Impls</th>
            <th data-key="citations" data-type="num" onclick="techniquesSort(this)">Citations</th>
          </tr>
        </thead>
        <tbody>
          {% for t in techniques %}
          <tr data-technique="{{ t.name }}" data-domain="{{ t.domain.value }}"
              data-ring="{{ t.ring.value if t.ring else '' }}" data-category="{{ t.category.value }}"
              data-impls="{{ t.resolved_implementations | length }}"
              data-citations="{{ t.citation_count or 0 }}">
            <td><a href="/technique/{{ t.id }}">{{ t.name }}</a></td>
            <td>{{ t.domain.value }}</td>
            <td>{{ t.ring.value if t.ring else '-' }}</td>
            <td>{{ t.category.value }}</td>
            <td>{{ t.resolved_implementations | length }}</td>
            <td>{{ t.citation_count if t.citation_count is not none else '?' }}</td>
          </tr>
          {% endfor %}
          <tr id="techniques-no-matches" style="display:none;"><td colspan="6">No techniques match.</td></tr>
        </tbody>
      </table>
      {% include "_techniques_filter_script.html" %}
      {% include "_techniques_sort_script.html" %}
    </main>
    {% include "_footer.html" %}
  </body>
</html>
```

`src/radar/web/templates/_techniques_filter_bar.html`:

```html
{# Client-side filter for #techniques-table. Context: techniques. Progressive enhancement. #}
<div class="filter-bar">
  <input id="tfilter-text" type="text" placeholder="Search techniques…"
         oninput="techniquesFilter()" aria-label="Search techniques">
  <select id="tfilter-domain" onchange="techniquesFilter()" aria-label="Filter by domain">
    <option value="">All domains</option>
    {% for d in techniques | map(attribute='domain.value') | unique | sort %}
    <option value="{{ d }}">{{ d }}</option>
    {% endfor %}
  </select>
  <select id="tfilter-ring" onchange="techniquesFilter()" aria-label="Filter by ring">
    <option value="">Any ring</option>
    {% for r in techniques | selectattr('ring') | map(attribute='ring.value') | unique | sort %}
    <option value="{{ r }}">{{ r }}</option>
    {% endfor %}
  </select>
  <select id="tfilter-category" onchange="techniquesFilter()" aria-label="Filter by category">
    <option value="">Any category</option>
    {% for c in techniques | map(attribute='category.value') | unique | sort %}
    <option value="{{ c }}">{{ c }}</option>
    {% endfor %}
  </select>
</div>
```

`src/radar/web/templates/_techniques_filter_script.html`:

```html
{# Dependency-free filter for #techniques-table. Matches on data-* attributes. #}
<script>
  function techniquesFilter() {
    var text = (document.getElementById('tfilter-text').value || '').toLowerCase();
    var domain = document.getElementById('tfilter-domain').value || '';
    var ring = document.getElementById('tfilter-ring').value || '';
    var cat = document.getElementById('tfilter-category').value || '';
    var rows = document.querySelectorAll('#techniques-table tbody tr[data-technique]');
    var shown = 0;
    rows.forEach(function (row) {
      var hay = (row.getAttribute('data-technique') + ' ' +
                 row.getAttribute('data-domain')).toLowerCase();
      var ok = (!text || hay.indexOf(text) !== -1)
        && (!domain || row.getAttribute('data-domain') === domain)
        && (!ring || row.getAttribute('data-ring') === ring)
        && (!cat || row.getAttribute('data-category') === cat);
      row.style.display = ok ? '' : 'none';
      if (ok) shown++;
    });
    var none = document.getElementById('techniques-no-matches');
    if (none) none.style.display = shown ? 'none' : '';
  }
</script>
```

`src/radar/web/templates/_techniques_sort_script.html`:

```html
{# Dependency-free click-to-sort for #techniques-table (mirror of _models_sort_script). #}
<style>
  #techniques-table th[data-key] { cursor: pointer; user-select: none; white-space: nowrap; }
  #techniques-table th[data-key][data-dir="asc"]::after { content: " \25B2"; font-size: .75em; }
  #techniques-table th[data-key][data-dir="desc"]::after { content: " \25BC"; font-size: .75em; }
</style>
<script>
  function techniquesSort(th) {
    var key = th.getAttribute('data-key');
    var type = th.getAttribute('data-type');
    var dir = th.getAttribute('data-dir') === 'asc' ? 'desc' : 'asc';
    var table = th.closest('table');
    var tbody = table.querySelector('tbody');
    table.querySelectorAll('th[data-key]').forEach(function (h) { h.removeAttribute('data-dir'); });
    th.setAttribute('data-dir', dir);
    var rows = Array.prototype.slice.call(tbody.querySelectorAll('tr[data-technique]'));
    rows.sort(function (a, b) {
      var av = a.getAttribute('data-' + key) || '';
      var bv = b.getAttribute('data-' + key) || '';
      var cmp = type === 'num'
        ? (parseFloat(av) || 0) - (parseFloat(bv) || 0)
        : av.toLowerCase().localeCompare(bv.toLowerCase());
      return dir === 'asc' ? cmp : -cmp;
    });
    rows.forEach(function (r) { tbody.appendChild(r); });
    var none = document.getElementById('techniques-no-matches');
    if (none) tbody.appendChild(none);
  }
</script>
```

`src/radar/web/templates/_technique_detail.html`:

```html
{# Shared technique-detail body. Context: technique (TechniqueEntry), timeline (list[TimelineItem]). #}
<h2>{{ technique.name }} <small>{{ technique.domain.value }}</small></h2>
<p>Ring: <strong>{{ technique.ring.value if technique.ring else '-' }}</strong>
   · Category: {{ technique.category.value }}
   · On-prem impact: {{ technique.onprem_impact.value }}
   {% if technique.citation_count is not none %} · Citations: {{ technique.citation_count }}{% endif %}
   {% if technique.superseded_by %} · Superseded by: <strong>{{ technique.superseded_by }}</strong>{% endif %}</p>
{% if technique.notes %}<p>{{ technique.notes }}</p>{% endif %}
{% if technique.score_breakdown %}
<table>
  <thead><tr><th>Breadth</th><th>Maturity</th><th>Validation</th><th>Reproducibility</th>
             <th>Momentum</th><th>On-prem</th><th>Avg</th></tr></thead>
  <tbody><tr>
    <td>{{ technique.score_breakdown.implementation_breadth }}</td>
    <td>{{ technique.score_breakdown.implementation_maturity }}</td>
    <td>{{ technique.score_breakdown.validation }}</td>
    <td>{{ technique.score_breakdown.reproducibility }}</td>
    <td>{{ technique.score_breakdown.momentum }}</td>
    <td>{{ technique.score_breakdown.onprem_impact }}</td>
    <td><strong>{{ technique.score_breakdown.average }}</strong></td>
  </tr></tbody>
</table>
{% endif %}
{% if technique.papers %}
<h3>Papers</h3>
<ul>
  {% for p in technique.papers %}
  <li>[{{ p.role.value }}] <a href="https://arxiv.org/abs/{{ p.arxiv_id }}">{{ p.title }}</a>
      {% if p.published %}({{ p.published }}){% endif %}</li>
  {% endfor %}
</ul>
{% endif %}
{% if technique.resolved_implementations %}
<h3>Implementations</h3>
<ul>
  {% for impl in technique.resolved_implementations %}
  <li>[{{ impl.kind.value }}] {{ impl.ref }} — {{ impl.ring.value if impl.ring else 'unringed' }}
      {% if impl.note %}· {{ impl.note }}{% endif %}</li>
  {% endfor %}
</ul>
{% endif %}
{% if timeline %}
<h3>Research → production timeline</h3>
<ul>
  {% for item in timeline %}
  <li><strong>{{ item.date }}</strong> — {{ item.label }}</li>
  {% endfor %}
</ul>
{% endif %}
{% for warning in technique.warnings %}
<p class="warning">⚠ {{ warning }}</p>
{% endfor %}
```

`src/radar/web/templates/technique.html`:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{{ technique.name }} · Research</title>
    <link rel="icon" type="image/png" href="{{ asset_base }}static/brand/favicon.png" />
    {% include "_base_styles.html" %}
  </head>
  <body>
    {% set page_title = technique.name %}
    {% set tagline = technique.domain.value %}
    {% set nav = {"Research": "/research", "Radar": "/"} %}
    {% include "_hero.html" %}
    <main class="container">
      {% include "_technique_detail.html" %}
    </main>
    {% include "_footer.html" %}
  </body>
</html>
```

- [ ] **Step 4: Wire the routes and index**

In `src/radar/web/app.py`:

Add imports: `from radar.mcp_server.technique_queries import _latest_technique_cards`, `from radar.research_radar.entities import TechniqueEntry`, `from radar.research_radar.history import load_technique_events`, `from radar.research_radar.timeline import build_technique_timeline`, `from radar.web.research_summary import summarize_techniques`.

Add a loader helper next to `_model_entries`:

```python
    def _technique_entries() -> list[TechniqueEntry]:
        """Load technique entries from the latest research run; empty list if none."""
        return [TechniqueEntry.model_validate(c) for c in _latest_technique_cards(root)]
```

Extend the index context (inside the existing `index()` return dict):

```python
                "techniques_summary": summarize_techniques(_technique_entries()),
                "research_href": "/research",
```

Add the routes next to the models routes:

```python
    @app.get("/research", response_class=HTMLResponse)
    def research_page(request: Request):
        entries = _technique_entries()
        return TEMPLATES.TemplateResponse(
            request, "techniques.html", {"techniques": entries}
        )

    @app.get("/technique/{technique_id}", response_class=HTMLResponse)
    def technique_detail(request: Request, technique_id: str):
        entry = next((e for e in _technique_entries() if e.id == technique_id), None)
        if entry is None:
            return HTMLResponse("Technique not found", status_code=404)
        events = load_technique_events(root / "data" / "technique-history.jsonl")
        return TEMPLATES.TemplateResponse(
            request, "technique.html",
            {"technique": entry, "timeline": build_technique_timeline(entry, events)},
        )
```

In `src/radar/web/templates/index.html`: add `"Research": "/research"` to the `nav` dict (after `"Models": "/models"`), and add `{% include "_research_summary.html" %}` immediately after the `{% include "_models_summary.html" %}` line.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_web.py -v`
Expected: PASS (existing + 5 new)

- [ ] **Step 6: Lint + typecheck + commit**

```bash
uv run ruff check src/radar/web tests/test_web.py && uv run mypy src/radar
git add src/radar/web/templates/techniques.html src/radar/web/templates/technique.html \
  src/radar/web/templates/_technique_detail.html src/radar/web/templates/_techniques_filter_bar.html \
  src/radar/web/templates/_techniques_filter_script.html src/radar/web/templates/_techniques_sort_script.html \
  src/radar/web/templates/index.html src/radar/web/app.py tests/test_web.py
git commit -m "feat: /research and /technique dashboard pages + index summary"
```

---

### Task 7: Static export — research pages, feeds, downloads

**Files:**
- Create: `src/radar/web/templates/static_techniques.html`, `static_technique.html`
- Modify: `src/radar/web/static_site.py`, `src/radar/web/templates/static_index.html`, `src/radar/cli.py` (export command)
- Test: `tests/test_static_site.py` (append), `tests/test_cli.py` (append)

**Interfaces:**
- Consumes: Tasks 1–6 (`technique_events_to_feed_atom/json`, `build_technique_timeline`, `_latest_technique_cards`, `summarize_techniques`, live-template markup).
- Produces: `render_static_site(..., technique_entries: list[TechniqueEntry] | None = None, technique_events: list[TechniqueHistoryEvent] | None = None)`; `_write_technique_pages(env, out_dir, technique_entries, technique_events, site_title, self_base_url, generated_at)` writing `techniques.html`, `technique_<slug>.html`, `changes-research.xml`, `changes-research.json`; index downloads gain `"Technique History (JSONL)": "technique-history.jsonl"` (when the file was copied into the site); static index gains the research summary + `"Research": "techniques.html"` nav; `radar export` loads entries/events, copies `data/technique-history.jsonl` into the site, and threads both params.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_static_site.py`:

```python
def _technique_entry():
    from radar.models import Category, Ring
    from radar.research_radar.entities import (
        OnPremImpact,
        PaperLink,
        TechniqueDomain,
        TechniqueEntry,
    )

    return TechniqueEntry(
        id="speculative-decoding", name="Speculative Decoding",
        category=Category.MODEL_SERVING, domain=TechniqueDomain.INFERENCE,
        onprem_impact=OnPremImpact.REDUCES_LATENCY, ring=Ring.ADOPT, score=4.3,
        citation_count=1697,
        papers=[PaperLink(arxiv_id="2211.17192", title="Fast Inference", published="2022-11")],
    )


def _technique_event():
    from datetime import UTC, datetime

    from radar.models import Ring
    from radar.research_radar.entities import TechniqueDomain
    from radar.research_radar.history import TechniqueHistoryEvent
    from radar.storage.history_store import ChangeType

    return TechniqueHistoryEvent(
        technique_id="speculative-decoding", domain=TechniqueDomain.INFERENCE,
        change_type=ChangeType.NEW, ring=Ring.ADOPT, run_id="run-1",
        observed_at=datetime(2026, 7, 3, 10, 0, tzinfo=UTC),
    )


def test_static_site_renders_research_section(tmp_path):
    render_static_site(
        [], tmp_path / "_site", datetime(2026, 7, 3, tzinfo=UTC),
        technique_entries=[_technique_entry()], technique_events=[_technique_event()],
    )
    site = tmp_path / "_site"

    techniques_html = (site / "techniques.html").read_text(encoding="utf-8")
    assert "Speculative Decoding" in techniques_html
    assert 'href="technique_speculative-decoding.html"' in techniques_html
    detail_html = (site / "technique_speculative-decoding.html").read_text(encoding="utf-8")
    assert "2211.17192" in detail_html
    assert "canonical paper" in detail_html  # timeline rendered
    assert 'href="techniques.html"' in detail_html  # static back-link
    assert (site / "changes-research.xml").exists()
    assert "urn:radar-technique:speculative-decoding" in (
        site / "changes-research.json").read_text(encoding="utf-8")
    index_html = (site / "index.html").read_text(encoding="utf-8")
    assert "Research: 1 techniques" in index_html
    assert 'href="techniques.html"' in index_html


def test_static_site_backcompat_without_techniques(tmp_path):
    render_static_site([], tmp_path / "_site", datetime(2026, 7, 3, tzinfo=UTC))
    site = tmp_path / "_site"

    assert not (site / "techniques.html").exists()
    assert not (site / "changes-research.xml").exists()
    assert (site / "index.html").exists()
```

Append to `tests/test_cli.py`:

```python
def test_export_includes_research_pages_after_research_scan(tmp_path):
    from radar.models import Category, Ring
    from radar.research_radar.entities import OnPremImpact, TechniqueDomain, TechniqueEntry
    from radar.research_radar.history import TechniqueHistoryEvent, append_technique_events
    from radar.storage.history_store import ChangeType
    from radar.storage.run_store import RunStore
    from datetime import UTC, datetime

    runner = CliRunner()
    runner.invoke(app, ["init", "--root", str(tmp_path)])
    entry = TechniqueEntry(
        id="qlora", name="QLoRA", category=Category.AI_INFRASTRUCTURE,
        domain=TechniqueDomain.FINE_TUNING, onprem_impact=OnPremImpact.REDUCES_MEMORY,
        ring=Ring.WATCH,
    )
    store = RunStore(tmp_path / "data" / "runs")
    run_id = store.create_run()
    store.save_stage(run_id, "technique_cards", [entry.model_dump(mode="json")])
    store.update_meta(run_id, {"kind": "research", "technique_count": 1})
    append_technique_events(tmp_path / "data" / "technique-history.jsonl", [
        TechniqueHistoryEvent(
            technique_id="qlora", domain=TechniqueDomain.FINE_TUNING,
            change_type=ChangeType.NEW, ring=Ring.WATCH, run_id=run_id,
            observed_at=datetime(2026, 7, 3, 10, 0, tzinfo=UTC),
        ),
    ])

    result = runner.invoke(app, ["export", "--root", str(tmp_path),
                                 "--out", str(tmp_path / "_site")])

    assert result.exit_code == 0
    assert (tmp_path / "_site" / "techniques.html").exists()
    assert (tmp_path / "_site" / "technique-history.jsonl").exists()
    assert "Technique History (JSONL)" in (
        tmp_path / "_site" / "index.html").read_text(encoding="utf-8")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_static_site.py tests/test_cli.py -v -k "research or technique"`
Expected: FAIL — `TypeError: render_static_site() got an unexpected keyword argument 'technique_entries'`

- [ ] **Step 3: Create the static template pair**

`src/radar/web/templates/static_techniques.html` — copy the committed file `src/radar/web/templates/techniques.html` (it exists in the repo by this task) byte-for-byte, then change ONLY:
- `{% set nav = {"Radar": "index.html", "Models": "models.html", "History": "history.html"} %}`
- the row link: `<td><a href="technique_{{ slug_by_technique[t.id] }}.html">{{ t.name }}</a></td>`
- add `generated_at=generated_at` support: the hero already renders `generated_at` if set — pass it through the render context (no template change needed beyond the two lines above).

`src/radar/web/templates/static_technique.html` — copy the committed file `src/radar/web/templates/technique.html` byte-for-byte, then change ONLY:
- `{% set nav = {"Research": "techniques.html", "Radar": "index.html"} %}`

- [ ] **Step 4: Wire static_site.py**

In `src/radar/web/static_site.py`:

Add imports:

```python
from radar.research_radar.entities import TechniqueEntry
from radar.research_radar.history import TechniqueHistoryEvent
from radar.research_radar.reports import (
    technique_events_to_feed_atom,
    technique_events_to_feed_json,
)
from radar.research_radar.timeline import build_technique_timeline
from radar.web.research_summary import summarize_techniques
```

Extend `render_static_site`'s signature (after `model_events`):

```python
    technique_entries: list[TechniqueEntry] | None = None,
    technique_events: list[TechniqueHistoryEvent] | None = None,
```

Inside, mirror the model wiring:

```python
    technique_history_available = (out_dir / "technique-history.jsonl").exists()
```

Add to the `downloads` dict:

```python
        "Technique History (JSONL)": "technique-history.jsonl" if technique_history_available else None,
```

Next to `models_summary = ...`:

```python
    techniques_summary = summarize_techniques(technique_entries) if technique_entries else None
```

Pass `techniques_summary=techniques_summary` into the `static_index.html` render context (next to `models_summary`).

Next to the `_write_model_pages` call:

```python
    if technique_entries:
        _write_technique_pages(
            env, out_dir, technique_entries, technique_events or [],
            site_title, self_base_url, stamp,
        )
```

Add the writer (mirror of `_write_model_pages`):

```python
def _write_technique_pages(
    env: Environment,
    out_dir: Path,
    technique_entries: list[TechniqueEntry],
    technique_events: list[TechniqueHistoryEvent],
    site_title: str,
    self_base_url: str,
    generated_at: str = "",
) -> None:
    """Render techniques.html, per-technique pages, and research feed files."""
    slug_by_technique = build_slug_map([t.id for t in technique_entries])

    (out_dir / "techniques.html").write_text(
        env.get_template("static_techniques.html").render(
            techniques=technique_entries,
            slug_by_technique=slug_by_technique,
            generated_at=generated_at,
        ),
        encoding="utf-8",
    )

    technique_template = env.get_template("static_technique.html")
    for entry in technique_entries:
        (out_dir / f"technique_{slug_by_technique[entry.id]}.html").write_text(
            technique_template.render(
                technique=entry,
                timeline=build_technique_timeline(entry, technique_events),
                generated_at=generated_at,
            ),
            encoding="utf-8",
        )

    if technique_events:
        self_url = (
            f"{self_base_url.rstrip('/')}/changes-research.xml"
            if self_base_url
            else "changes-research.xml"
        )
        (out_dir / "changes-research.xml").write_text(
            technique_events_to_feed_atom(technique_events, site_title=site_title,
                                          self_url=self_url),
            encoding="utf-8",
        )
        (out_dir / "changes-research.json").write_text(
            json.dumps(technique_events_to_feed_json(technique_events, site_title=site_title),
                       indent=2),
            encoding="utf-8",
        )
```

In `src/radar/web/templates/static_index.html`: add `"Research": "techniques.html"` to the nav dict (after `"Models": "models.html"`) and `{% include "_research_summary.html" %}` right after the `_models_summary.html` include (the partial's `research_href` default is already `techniques.html`).

- [ ] **Step 5: Wire the export CLI**

In `src/radar/cli.py` `export` command, next to the model loading block:

```python
    from radar.mcp_server.technique_queries import _latest_technique_cards
    from radar.research_radar.entities import TechniqueEntry
    from radar.research_radar.history import load_technique_events as _load_tech_events

    technique_entries = [TechniqueEntry.model_validate(c) for c in _latest_technique_cards(root)]
    technique_events = _load_tech_events(root / "data" / "technique-history.jsonl")

    technique_history_src = root / "data" / "technique-history.jsonl"
    if technique_history_src.exists():
        shutil.copy2(technique_history_src, out / "technique-history.jsonl")
```

(The `out.mkdir(parents=True, exist_ok=True)` already happens just above for the model copy — keep the technique copy after it.) Then thread both into the `render_static_site(...)` call:

```python
        technique_entries=technique_entries or None,
        technique_events=technique_events or None,
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_static_site.py tests/test_cli.py tests/test_web.py -v`
Expected: PASS (new + existing; back-compat test proves no-techniques exports unchanged)

- [ ] **Step 7: Lint + typecheck + commit**

```bash
uv run ruff check src/radar tests/test_static_site.py tests/test_cli.py && uv run mypy src/radar
git add src/radar/web/templates/static_techniques.html src/radar/web/templates/static_technique.html \
  src/radar/web/templates/static_index.html src/radar/web/static_site.py src/radar/cli.py \
  tests/test_static_site.py tests/test_cli.py
git commit -m "feat: static export research pages, feeds, and history download"
```

---

### Task 8: Scan-health kind filter (bug fix)

**Files:**
- Modify: `src/radar/web/scan_health.py`, `src/radar/web/app.py` (index), `src/radar/cli.py` (export)
- Test: `tests/test_web.py` (append), `tests/test_cli.py` (append)

**Interfaces:**
- Consumes: `RunStore.list_runs()` / `read_meta()` (main tool scans have NO `kind` key in meta).
- Produces: `latest_tool_scan_meta(run_store: Any) -> dict[str, Any]` in `scan_health.py` — used by `app.py` `index()` (replacing `run_store.read_meta(run_ids[-1])`) and `cli.py` `export` (replacing the same pattern for `latest_scan_meta`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_web.py`:

```python
def test_scan_health_survives_a_later_research_run(tmp_path):
    """A models/research scan after the tool scan must not blank scan health."""
    from radar.storage.run_store import RunStore as _RS

    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    store = _RS(tmp_path / "data" / "runs")
    tool_run = store.create_run()
    store.update_meta(tool_run, {"collector_warnings": ["github: rate limited"]})
    research_run = store.create_run()
    store.update_meta(research_run, {"kind": "research", "technique_count": 0})

    client = TestClient(create_app(tmp_path))
    r = client.get("/")

    assert "rate limited" in r.text
```

Append to `tests/test_cli.py`:

```python
def test_export_scan_health_ignores_research_runs(tmp_path):
    from radar.storage.run_store import RunStore

    runner = CliRunner()
    runner.invoke(app, ["init", "--root", str(tmp_path)])
    store = RunStore(tmp_path / "data" / "runs")
    tool_run = store.create_run()
    store.update_meta(tool_run, {"collector_warnings": ["github: rate limited"]})
    research_run = store.create_run()
    store.update_meta(research_run, {"kind": "research", "technique_count": 0})

    result = runner.invoke(app, ["export", "--root", str(tmp_path),
                                 "--out", str(tmp_path / "_site")])

    assert result.exit_code == 0
    assert "rate limited" in (tmp_path / "_site" / "index.html").read_text(encoding="utf-8")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_web.py::test_scan_health_survives_a_later_research_run tests/test_cli.py::test_export_scan_health_ignores_research_runs -v`
Expected: FAIL — "rate limited" absent (the research run's empty meta wins)

- [ ] **Step 3: Implement the helper and swap both call sites**

Append to `src/radar/web/scan_health.py`:

```python
def latest_tool_scan_meta(run_store: Any) -> dict[str, Any]:
    """Meta of the most recent MAIN tool-scan run.

    Model and research scans stamp a ``kind`` into their run meta; the main
    tool scan does not. Without this filter, a later ``radar models scan`` or
    ``radar research scan`` silently blanks the dashboard's scan-health panel.
    """
    for run_id in reversed(run_store.list_runs()):
        meta = run_store.read_meta(run_id)
        if "kind" not in meta:
            return meta
    return {}
```

In `src/radar/web/app.py` `index()` replace:

```python
        run_ids = run_store.list_runs()
        meta = run_store.read_meta(run_ids[-1]) if run_ids else {}
```

with:

```python
        meta = latest_tool_scan_meta(run_store)
```

(and import `latest_tool_scan_meta` from `radar.web.scan_health` alongside `summarize_meta`).

In `src/radar/cli.py` `export` replace:

```python
    run_ids = orchestrator.run_store.list_runs()
    latest_scan_meta = orchestrator.run_store.read_meta(run_ids[-1]) if run_ids else {}
```

with:

```python
    from radar.web.scan_health import latest_tool_scan_meta

    latest_scan_meta = latest_tool_scan_meta(orchestrator.run_store)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_web.py tests/test_cli.py -v`
Expected: PASS (new + all existing scan-health/export tests)

- [ ] **Step 5: Lint + typecheck + commit**

```bash
uv run ruff check src/radar tests/test_web.py tests/test_cli.py && uv run mypy src/radar
git add src/radar/web/scan_health.py src/radar/web/app.py src/radar/cli.py tests/test_web.py tests/test_cli.py
git commit -m "fix: scan-health panel reads the latest tool scan, not any run kind"
```

---

### Task 9: CI wiring (publish.yml)

**Files:**
- Modify: `.github/workflows/publish.yml`
- Test: `tests/test_publish_workflow.py` (append)

**Interfaces:**
- Consumes: the existing workflow steps (models scan at the "Scan" step; history commit block with `git add -f`).
- Produces: `uv run radar research scan --root .` runs after `radar models scan` and before `radar export`; `data/technique-history.jsonl` is force-added in the history-commit block.

- [ ] **Step 1: Write the failing test (append to tests/test_publish_workflow.py)**

```python
def test_publish_runs_research_scan_before_export_and_commits_technique_history():
    text = Path(".github/workflows/publish.yml").read_text(encoding="utf-8")

    research_idx = text.index("radar research scan")
    export_idx = text.index("radar export")
    models_idx = text.index("radar models scan")

    assert models_idx < research_idx < export_idx
    assert "data/technique-history.jsonl" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_publish_workflow.py -v`
Expected: FAIL — `ValueError: substring not found`

- [ ] **Step 3: Edit the workflow**

In `.github/workflows/publish.yml`, in the Scan step, add after the `uv run radar models scan --root .` line:

```yaml
          uv run radar research scan --root .
```

In the history-commit block, after `git add -f data/model-history.jsonl || true`:

```yaml
          git add -f data/technique-history.jsonl || true
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_publish_workflow.py -v`
Expected: PASS (both ordering tests)

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/publish.yml tests/test_publish_workflow.py
git commit -m "ci: research scan in daily publish + technique history commit"
```

---

### Task 10: README + CHANGELOG + full gates

**Files:**
- Modify: `README.md`, `CHANGELOG.md`
- Test: the full suite

- [ ] **Step 1: Update README**

In the Highlights research bullet (added in Plan A), extend it to mention the surfaces — replace:

```markdown
- 🎓 **Research technique radar** — curated academic techniques (speculative decoding, PagedAttention, LoRA, ReAct…) get their own deterministic rings, scored by *which tracked tools already implement them* plus citation evidence — research verdicts move when tool verdicts move.
```

with:

```markdown
- 🎓 **Research technique radar** — curated academic techniques (speculative decoding, PagedAttention, LoRA, ReAct…) get their own deterministic rings, scored by *which tracked tools already implement them* plus citation evidence — research verdicts move when tool verdicts move. Browsable at `/research` (dashboard + static site) with per-technique pages showing a research→production timeline, queryable over MCP (`list_techniques`/`get_technique`/`technique_movers`), and published as Atom/JSON change feeds.
```

- [ ] **Step 2: Update CHANGELOG**

Insert under `## [Unreleased]` → `### Added`, above the "Academic research radar (core)" entry:

```markdown
- **Academic research radar (surfaces)** — the technique radar is now visible
  everywhere the models radar is: a `/research` catalog page + per-technique
  pages (with a research→production timeline merging paper dates and ring
  history) on both the live dashboard and the static site, a Research summary
  on the index, MCP tools (`list_techniques`, `get_technique`,
  `technique_movers`), Atom/JSON research change feeds
  (`changes-research.xml`/`.json`), a Technique History (JSONL) download, and
  a daily `radar research scan` in the publish workflow. Also fixes the
  scan-health panel to read the latest *tool* scan instead of the latest run
  of any kind.
```

- [ ] **Step 3: Run the full gate suite**

Run: `uv run pytest && uv run ruff check . && uv run mypy src/radar`
Expected: all tests pass, coverage ≥ 80%, ruff and mypy clean. Fix anything failing (implementation, not tests, unless a test is genuinely wrong).

- [ ] **Step 4: Commit**

```bash
git add README.md CHANGELOG.md
git commit -m "docs: research surfaces in README + CHANGELOG"
```

---

## Self-Review Notes (already applied)

- Spec §9 Surfaces coverage: catalog+detail pages (T6/T7), timeline (T2, rendered T6/T7), MCP (T3/T4), change feeds (T1, written T7), CI wiring + technique-history commit (T9), scan-health kind filter (T8). The §9 "radar.db not persisted in CI" item is a recorded deferral (spec-level decision), not a task.
- Deliberate scope notes recorded under File Structure: no impl→page links, no RSS variant, no `_FEED_LIMIT` slicing for technique feeds (all mirror the models precedent), no technique autopilot.
- Type consistency: `technique_events_to_feed_atom/json` (T1) consumed in T7; `build_technique_timeline` (T2) consumed in T6 (route) and T7 (writer); `_latest_technique_cards` (T3) consumed in T6 and T7 and by the refactored CLI helper; `summarize_techniques`/`techniques_summary`/`research_href` names match between T5's partial and T6/T7 contexts; table id `techniques-table`, row attr `data-technique`, no-matches id `techniques-no-matches` consistent across bar/scripts/templates.
- The `_seed_techniques_run` helper in T6's tests and `_seed_research_run` in T3's tests intentionally duplicate the run-seeding pattern per test file (matching how `test_mcp_server.py`'s `_seed_models` stands alone today).
