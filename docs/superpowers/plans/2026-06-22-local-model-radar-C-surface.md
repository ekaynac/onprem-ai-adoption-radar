# Local-Model Radar — Plan C: Surface Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Make the local-model radar reachable — MCP tools, report/feed surfaces, a dashboard "Models" section + catalog/per-model pages, and folding the model scan into the daily CI publish.

**Architecture:** Mirror the existing tool-radar surfaces. A `ModelQueryService` backs new MCP tools; model movers/feeds reuse the report/feed builders; the dashboard mirrors the source-health summary + per-project page patterns; CI gains a `radar models scan` step. All data already exists (Plan A/B): the latest `kind=="models"` run's `model_cards.json`, `ModelMetricsStore`, and `data/model-history.jsonl`.

**Tech Stack:** Python 3.12, pydantic v2, FastMCP, Jinja2, FastAPI, typer, pytest + ruff + mypy.

## Global Constraints

- Python ≥ 3.12; new modules begin with `from __future__ import annotations`.
- No new third-party dependencies; deterministic core, no LLM.
- Immutability (frozen models; never mutate inputs); reuse `Ring`/`HardwareTier`/existing feed builders.
- Every surface degrades gracefully when no model run exists (empty/None → "no models yet", never crash).
- ruff + mypy clean; coverage ≥ 80%. Full-gate (`ruff check src tests`, `mypy src`, `pytest -q`) before EVERY commit (not just the touched file).
- Commit on the CURRENT branch only — never create/switch branches.

## Shared helper used by C1 and C7: locating the latest model run

Both the MCP query service and the export CLI need "the latest `kind==models` run's `model_cards.json`". Implement it once in C1 and reuse:
```python
def _latest_model_cards(root: Path) -> list[dict]:
    from radar.storage.run_store import RunStore
    import json
    run_store = RunStore(root / "data" / "runs")
    for rid in reversed(run_store.list_runs()):
        if run_store.read_meta(rid).get("kind") == "models":
            path = run_store._run_dir(rid) / "model_cards.json"
            return json.loads(path.read_text(encoding="utf-8"))
    return []
```

---

### Task 1: ModelQueryService

**Files:**
- Create: `src/radar/mcp_server/model_queries.py`
- Test: `tests/test_model_queries.py`

**Interfaces:**
- Consumes: `ModelEntry` (`radar.models_radar.entities`), `ModelMetricsStore`, `load_model_events`, `momentum`/`compute_model_momentum`, `RunStore`.
- Produces: `ModelQueryService(root: Path)` with `list_models(max_memory_gb=None, hardware_tier=None, family=None, modality=None, detail="compact") -> list[dict]`, `get_model(model_id: str) -> dict | None`, `model_movers() -> list[dict]`. Module helper `_latest_model_cards(root) -> list[dict]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_model_queries.py
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from radar.mcp_server.model_queries import ModelQueryService
from radar.models_radar.entities import (
    HardwareTier, ModelEntry, Openness, Platform, QuantVariant,
)
from radar.models import Ring
from radar.storage.run_store import RunStore


def _entry(mid, tier, mem, ring, family="F"):
    return ModelEntry(
        id=mid, name=mid, family=family, params_total=8_000_000_000,
        openness=Openness.OPEN_PERMISSIVE, hardware_tier=tier, ring=ring, score=4.0,
        modality=None or __import__("radar.models_radar.entities", fromlist=["Modality"]).Modality.TEXT,
        quants=[QuantVariant(format="Q4_K_M", bits_per_weight=4.5, est_memory_gb_4k=mem,
                             platform=Platform.GENERIC, source="hf:x")],
    )


def _seed(tmp_path: Path):
    run_store = RunStore(tmp_path / "data" / "runs")
    rid = run_store.create_run()
    entries = [
        _entry("qwen3-8b", HardwareTier.LAPTOP, 8.0, Ring.ADOPT, "Qwen3"),
        _entry("qwen3-30b-a3b", HardwareTier.APPLE_HIGH_RAM, 22.0, Ring.ADOPT, "Qwen3"),
        _entry("big-405b", HardwareTier.DATACENTER, 240.0, Ring.WATCH, "Llama"),
    ]
    run_store.save_stage(rid, "model_cards", [e.model_dump(mode="json") for e in entries])
    run_store.update_meta(rid, {"kind": "models", "model_count": 3})


def test_list_models_compact_returns_all(tmp_path: Path):
    _seed(tmp_path)
    svc = ModelQueryService(tmp_path)
    rows = svc.list_models()
    assert {r["id"] for r in rows} == {"qwen3-8b", "qwen3-30b-a3b", "big-405b"}
    assert "ring" in rows[0] and "hardware_tier" in rows[0]


def test_list_models_filters_by_max_memory(tmp_path: Path):
    _seed(tmp_path)
    svc = ModelQueryService(tmp_path)
    rows = svc.list_models(max_memory_gb=24)
    ids = {r["id"] for r in rows}
    assert "big-405b" not in ids and "qwen3-8b" in ids and "qwen3-30b-a3b" in ids


def test_list_models_filters_by_tier_and_family(tmp_path: Path):
    _seed(tmp_path)
    svc = ModelQueryService(tmp_path)
    assert {r["id"] for r in svc.list_models(hardware_tier="laptop")} == {"qwen3-8b"}
    assert {r["id"] for r in svc.list_models(family="Qwen3")} == {"qwen3-8b", "qwen3-30b-a3b"}


def test_get_model_returns_full_with_quants(tmp_path: Path):
    _seed(tmp_path)
    svc = ModelQueryService(tmp_path)
    m = svc.get_model("qwen3-8b")
    assert m is not None and m["id"] == "qwen3-8b"
    assert m["quants"] and m["quants"][0]["format"] == "Q4_K_M"
    assert svc.get_model("nope") is None


def test_no_model_run_returns_empty(tmp_path: Path):
    (tmp_path / "data").mkdir(parents=True)
    svc = ModelQueryService(tmp_path)
    assert svc.list_models() == [] and svc.get_model("x") is None
```

- [ ] **Step 2: Run test → fails** (`pytest tests/test_model_queries.py -v` → `ModuleNotFoundError`).

- [ ] **Step 3: Implement**

```python
# src/radar/mcp_server/model_queries.py
"""Query service backing the model-radar MCP tools (read-only over run state)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from radar.models_radar.entities import HardwareTier, ModelEntry
from radar.models_radar.memory import minimum_viable_quant
from radar.models_radar.momentum import compute_model_momentum
from radar.models_radar.history import load_model_events
from radar.storage.model_metrics_store import ModelMetricsStore
from radar.storage.run_store import RunStore


def _latest_model_cards(root: Path) -> list[dict[str, Any]]:
    """Raw model_cards.json dicts from the latest kind==models run; [] if none."""
    runs_dir = root / "data" / "runs"
    if not runs_dir.exists():
        return []
    run_store = RunStore(runs_dir)
    for rid in reversed(run_store.list_runs()):
        if run_store.read_meta(rid).get("kind") == "models":
            path = run_store._run_dir(rid) / "model_cards.json"
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8"))
    return []


class ModelQueryService:
    """Transport-agnostic queries over the latest model scan."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.db_path = self.root / "data" / "radar.db"
        self.history_path = self.root / "data" / "model-history.jsonl"

    def _entries(self) -> list[ModelEntry]:
        return [ModelEntry.model_validate(c) for c in _latest_model_cards(self.root)]

    def list_models(
        self,
        max_memory_gb: float | None = None,
        hardware_tier: str | None = None,
        family: str | None = None,
        modality: str | None = None,
        detail: str = "compact",
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for entry in self._entries():
            if hardware_tier and entry.hardware_tier.value != hardware_tier:
                continue
            if family and entry.family.lower() != family.lower():
                continue
            if modality and entry.modality.value != modality:
                continue
            if max_memory_gb is not None:
                mv = minimum_viable_quant(entry.quants)
                if mv is None or mv.est_memory_gb_4k is None or mv.est_memory_gb_4k > max_memory_gb:
                    continue
            rows.append(_model_compact(entry) if detail == "compact" else _model_full(entry))
        return rows

    def get_model(self, model_id: str) -> dict[str, Any] | None:
        entry = next((e for e in self._entries() if e.id == model_id), None)
        if entry is None:
            return None
        data = _model_full(entry)
        store = ModelMetricsStore(self.db_path)
        store.initialize()
        events = [e for e in load_model_events(self.history_path) if e.model_id == model_id]
        data["history"] = [
            {"change_type": e.change_type.value, "ring": e.ring.value,
             "previous_ring": e.previous_ring.value if e.previous_ring else None,
             "observed_at": e.observed_at.isoformat()}
            for e in events
        ]
        mom = compute_model_momentum(model_id, store.history_for(model_id), events)
        data["momentum"] = {"direction": mom.direction,
                            "downloads_growth_pct": mom.downloads_growth_pct}
        return data

    def model_movers(self) -> list[dict[str, Any]]:
        store = ModelMetricsStore(self.db_path)
        store.initialize()
        all_events = load_model_events(self.history_path)
        by_model: dict[str, list] = {}
        for ev in all_events:
            by_model.setdefault(ev.model_id, []).append(ev)
        movers: list[dict[str, Any]] = []
        for entry in self._entries():
            mom = compute_model_momentum(
                entry.id, store.history_for(entry.id), by_model.get(entry.id, []))
            if mom.direction != "steady":
                movers.append({"id": entry.id, "direction": mom.direction,
                               "downloads_growth_pct": mom.downloads_growth_pct,
                               "note": mom.note})
        return movers


def _model_compact(entry: ModelEntry) -> dict[str, Any]:
    mv = minimum_viable_quant(entry.quants)
    return {
        "id": entry.id, "name": entry.name, "family": entry.family,
        "ring": entry.ring.value if entry.ring else None,
        "hardware_tier": entry.hardware_tier.value,
        "min_memory_gb": mv.est_memory_gb_4k if mv else None,
        "params_total": entry.params_total, "modality": entry.modality.value,
    }


def _model_full(entry: ModelEntry) -> dict[str, Any]:
    data = entry.model_dump(mode="json")
    mv = minimum_viable_quant(entry.quants)
    data["min_memory_gb"] = mv.est_memory_gb_4k if mv else None
    return data
```

Note the test's `_entry` helper imports `Modality` awkwardly; the implementer should simplify the test helper to `from radar.models_radar.entities import Modality` at top and set `modality=Modality.TEXT`. Keep assertions identical.

- [ ] **Step 4: Run test → pass**, then full gate.
- [ ] **Step 5: Commit** `git add src/radar/mcp_server/model_queries.py tests/test_model_queries.py && git commit -m "feat(models): ModelQueryService for MCP (list/get/movers + filters)"`

---

### Task 2: MCP tools (list_models, get_model, model_movers)

**Files:**
- Modify: `src/radar/mcp_server/server.py`
- Test: `tests/test_mcp_server.py` (add)

**Interfaces:**
- Consumes: `ModelQueryService` (C1).
- Produces: three new registered MCP tools delegating to a `ModelQueryService(root)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_mcp_server.py — add
import asyncio
from pathlib import Path
from radar.mcp_server.server import build_mcp_server
from radar.storage.run_store import RunStore


def _seed_models(tmp_path: Path):
    from radar.models_radar.entities import (
        HardwareTier, Modality, ModelEntry, Openness, Platform, QuantVariant)
    from radar.models import Ring
    rs = RunStore(tmp_path / "data" / "runs")
    rid = rs.create_run()
    e = ModelEntry(id="qwen3-8b", name="Qwen3 8B", family="Qwen3", params_total=8_000_000_000,
                   openness=Openness.OPEN_PERMISSIVE, hardware_tier=HardwareTier.LAPTOP,
                   ring=Ring.ADOPT, score=4.0, modality=Modality.TEXT,
                   quants=[QuantVariant(format="Q4_K_M", bits_per_weight=4.5,
                                        est_memory_gb_4k=8.0, platform=Platform.GENERIC, source="hf:x")])
    rs.save_stage(rid, "model_cards", [e.model_dump(mode="json")])
    rs.update_meta(rid, {"kind": "models", "model_count": 1})


def test_server_registers_model_tools(tmp_path: Path):
    _seed_models(tmp_path)
    server = build_mcp_server(tmp_path)
    names = {t.name for t in asyncio.run(server.list_tools())}
    assert {"list_models", "get_model", "model_movers"} <= names


def test_list_models_tool_filters_by_memory(tmp_path: Path):
    _seed_models(tmp_path)
    server = build_mcp_server(tmp_path)
    result = asyncio.run(server.call_tool("list_models", {"max_memory_gb": 24}))
    payload = result[1].get("result", result[1])
    assert any(item["id"] == "qwen3-8b" for item in payload)
```

- [ ] **Step 2: Run → fails** (tools not registered).

- [ ] **Step 3: Implement** — in `build_mcp_server`, add a `ModelQueryService` and three tools mirroring the existing `@mcp.tool()` style:

```python
# add import at top
from radar.mcp_server.model_queries import ModelQueryService
```
```python
# inside build_mcp_server, after `service = RadarQueryService(root)`:
    models = ModelQueryService(root)

    @mcp.tool()
    def list_models(
        max_memory_gb: float | None = None,
        hardware_tier: str | None = None,
        family: str | None = None,
        modality: str | None = None,
        detail: str = "compact",
    ) -> list[dict]:
        """List tracked local models, optionally filtered by fit/family/modality."""
        return models.list_models(max_memory_gb, hardware_tier, family, modality, detail)

    @mcp.tool()
    def get_model(model_id: str) -> dict | None:
        """Full spec + quant table + ring + recent history/momentum for one model."""
        return models.get_model(model_id)

    @mcp.tool()
    def model_movers() -> list[dict]:
        """Models trending up/down (ring changes or download growth)."""
        return models.model_movers()
```

- [ ] **Step 4: Run → pass**, full gate. **Step 5: Commit** `feat(models): MCP list_models/get_model/model_movers tools`.

---

### Task 3: Model mover lines (report)

**Files:**
- Create: `src/radar/models_radar/reports.py`
- Test: `tests/test_models_radar_reports.py`

**Interfaces:**
- Consumes: `ModelHistoryEvent` (`models_radar.history`), `ModelMomentum` (`models_radar.momentum`), `ChangeType`.
- Produces: `build_model_mover_lines(events: list[ModelHistoryEvent], momentums: list[ModelMomentum]) -> list[str]`. Constant `MAX_TRENDING = 3`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_models_radar_reports.py
from __future__ import annotations

from datetime import UTC, datetime

from radar.models import Ring
from radar.models_radar.history import ModelHistoryEvent
from radar.models_radar.momentum import ModelMomentum
from radar.models_radar.reports import build_model_mover_lines
from radar.storage.history_store import ChangeType

NOW = datetime(2026, 6, 22, tzinfo=UTC)


def _ev(mid, ct, ring, prev=None):
    return ModelHistoryEvent(model_id=mid, family="F", change_type=ct, ring=ring,
                             previous_ring=prev, run_id="r", observed_at=NOW)


def test_ring_changes_first_then_trending():
    events = [_ev("a", ChangeType.PROMOTED, Ring.ADOPT, Ring.PILOT),
              _ev("b", ChangeType.NEW, Ring.PILOT)]
    moms = [ModelMomentum(model_id="c", direction="rising", downloads_growth_pct=12.0,
                          note="Downloads +12.0%"),
            ModelMomentum(model_id="a", direction="rising", downloads_growth_pct=5.0)]
    lines = build_model_mover_lines(events, moms)
    assert any("a:" in l and "promoted" in l for l in lines)
    assert any("b:" in l and "new" in l for l in lines)
    # c trends; a already shown as a ring move → not repeated in trending
    assert any("c:" in l and "rising" in l for l in lines)
    assert sum(1 for l in lines if l.startswith("a:")) == 1


def test_empty_inputs_yield_no_lines():
    assert build_model_mover_lines([], []) == []
```

- [ ] **Step 2: Run → fails.**

- [ ] **Step 3: Implement** (mirror `reports/movers.py`):

```python
# src/radar/models_radar/reports.py
"""Render model movers + report sections from model history/momentum."""

from __future__ import annotations

from radar.models_radar.history import ModelHistoryEvent
from radar.models_radar.momentum import ModelMomentum
from radar.storage.history_store import ChangeType


MAX_TRENDING = 3


def build_model_mover_lines(
    events: list[ModelHistoryEvent], momentums: list[ModelMomentum],
) -> list[str]:
    """Ring changes first, then up to MAX_TRENDING rising models not already shown."""
    lines: list[str] = []
    moved: set[str] = set()
    for ev in events:
        if ev.change_type == ChangeType.PROMOTED:
            lines.append(f"{ev.model_id}: {ev.previous_ring.value if ev.previous_ring else '?'} "
                         f"→ {ev.ring.value} (promoted)")
            moved.add(ev.model_id)
        elif ev.change_type == ChangeType.DEMOTED:
            lines.append(f"{ev.model_id}: {ev.previous_ring.value if ev.previous_ring else '?'} "
                         f"→ {ev.ring.value} (demoted)")
            moved.add(ev.model_id)
        elif ev.change_type == ChangeType.NEW:
            lines.append(f"{ev.model_id}: new on the radar ({ev.ring.value})")
            moved.add(ev.model_id)
    rising = sorted(
        (m for m in momentums if m.direction == "rising" and m.model_id not in moved),
        key=lambda m: m.downloads_growth_pct or 0.0, reverse=True,
    )
    for m in rising[:MAX_TRENDING]:
        pct = f" downloads {m.downloads_growth_pct:+.1f}%" if m.downloads_growth_pct is not None else ""
        lines.append(f"{m.model_id}: rising —{pct} across recent scans".replace("— ", "— "))
    return lines
```

- [ ] **Step 4: Run → pass**, full gate. **Step 5: Commit** `feat(models): model mover lines`.

---

### Task 4: Model markdown report + model change-feeds

**Files:**
- Modify: `src/radar/models_radar/reports.py` (add)
- Test: `tests/test_models_radar_reports.py` (add)

**Interfaces:**
- Consumes: `ModelEntry`, `ModelHistoryEvent`, `reports/feeds.py` builders.
- Produces: `render_model_report(entries: list[ModelEntry], mover_lines: list[str], title: str) -> str`; `model_events_to_feed_json(events, site_title) -> dict`; `model_events_to_feed_atom(events, site_title, self_url) -> str`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_models_radar_reports.py — add
from radar.models_radar.entities import HardwareTier, ModelEntry, Openness
from radar.models import Ring
from radar.models_radar.reports import (
    model_events_to_feed_atom, model_events_to_feed_json, render_model_report,
)


def test_render_model_report_has_sections():
    e = ModelEntry(id="qwen3-8b", name="Qwen3 8B", family="Qwen3", ring=Ring.ADOPT,
                   hardware_tier=HardwareTier.LAPTOP, openness=Openness.OPEN_PERMISSIVE)
    md = render_model_report([e], ["qwen3-8b: rising"], "Model Radar")
    assert "# Model Radar" in md and "## Movers" in md and "qwen3-8b" in md
    assert "laptop" in md


def test_model_feeds_build_from_events():
    ev = _ev("qwen3-8b", ChangeType.NEW, Ring.ADOPT)
    j = model_events_to_feed_json([ev], "Model Radar")
    assert j["items"] and "qwen3-8b" in j["items"][0]["title"]
    x = model_events_to_feed_atom([ev], "Model Radar", "https://example/changes-models.xml")
    assert "<feed" in x and "qwen3-8b" in x
```

- [ ] **Step 2: Run → fails.**

- [ ] **Step 3: Implement** — append to `reports.py`. For the feeds, adapt each `ModelHistoryEvent` to the `ProjectHistoryEvent`-shaped dict the existing `feeds.py` builders consume; since `feeds.py` functions take typed `ProjectHistoryEvent`, build small local renderers instead (do NOT import tool feeds to avoid coupling). Keep them tiny:

```python
# append to src/radar/models_radar/reports.py
from datetime import datetime
from typing import Any

from radar.models import Ring
from radar.models_radar.entities import ModelEntry


def render_model_report(entries: list[ModelEntry], mover_lines: list[str], title: str) -> str:
    out = [f"# {title}", ""]
    if mover_lines:
        out.append("## Movers")
        out += [f"- {line}" for line in mover_lines]
        out.append("")
    out.append("## Models")
    for e in sorted(entries, key=lambda m: (m.hardware_tier.value, m.id)):
        ring = e.ring.value if e.ring else "-"
        out.append(f"- **{e.name}** ({e.family}) · `{ring}` · {e.hardware_tier.value}"
                   + (f" · {e.license}" if e.license else ""))
    out.append("")
    return "\n".join(out)


def _event_title(ev: Any) -> str:
    prev = ev.previous_ring.value if ev.previous_ring else None
    if prev:
        return f"{ev.model_id}: {prev} → {ev.ring.value} ({ev.change_type.value})"
    return f"{ev.model_id}: {ev.change_type.value} ({ev.ring.value})"


def model_events_to_feed_json(events: list[Any], site_title: str) -> dict[str, Any]:
    items = []
    for ev in sorted(events, key=lambda e: e.observed_at, reverse=True):
        items.append({
            "id": f"urn:radar-model:{ev.model_id}:{ev.run_id}",
            "title": _event_title(ev),
            "content_text": "; ".join(ev.reasons) or _event_title(ev),
            "date_published": ev.observed_at.isoformat(),
            "tags": [ev.family, ev.ring.value],
        })
    return {"version": "https://jsonfeed.org/version/1.1", "title": f"{site_title} — Models",
            "items": items}


def model_events_to_feed_atom(events: list[Any], site_title: str, self_url: str) -> str:
    rows = sorted(events, key=lambda e: e.observed_at, reverse=True)
    updated = rows[0].observed_at.isoformat() if rows else datetime.now().astimezone().isoformat()
    entries_xml = "".join(
        f"<entry><title>{_xml_escape(_event_title(ev))}</title>"
        f"<id>urn:radar-model:{ev.model_id}:{ev.run_id}</id>"
        f"<updated>{ev.observed_at.isoformat()}</updated>"
        f"<summary>{_xml_escape('; '.join(ev.reasons) or _event_title(ev))}</summary></entry>"
        for ev in rows
    )
    return (f'<?xml version="1.0" encoding="utf-8"?>'
            f'<feed xmlns="http://www.w3.org/2005/Atom"><title>{_xml_escape(site_title)} — Models</title>'
            f'<link rel="self" href="{_xml_escape(self_url)}"/><updated>{updated}</updated>'
            f'{entries_xml}</feed>')


def _xml_escape(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))
```

- [ ] **Step 4: Run → pass**, full gate. **Step 5: Commit** `feat(models): model markdown report + change feeds`.

---

### Task 5: Dashboard "Models" summary

**Files:**
- Create: `src/radar/web/models_summary.py`
- Create: `src/radar/web/templates/_models_summary.html`
- Modify: `src/radar/web/templates/index.html`, `src/radar/web/templates/static_index.html` (add the include)
- Test: `tests/test_models_summary.py`

**Interfaces:**
- Consumes: `ModelEntry`.
- Produces: frozen `ModelsSummary` (`total:int`, `by_ring:dict[str,int]`, `by_tier:dict[str,int]`, `has_models:bool`, `one_line:str`); `summarize_models(entries: list[ModelEntry]) -> ModelsSummary`.

- [ ] **Step 1: Write the failing test** (mirror `tests/test_source_health_view.py`):

```python
# tests/test_models_summary.py
from __future__ import annotations

from radar.models import Ring
from radar.models_radar.entities import HardwareTier, ModelEntry, Openness
from radar.web.models_summary import summarize_models


def _e(mid, ring, tier):
    return ModelEntry(id=mid, name=mid, family="F", ring=ring, hardware_tier=tier,
                      openness=Openness.OPEN_PERMISSIVE)


def test_empty_is_no_models():
    s = summarize_models([])
    assert s.total == 0 and not s.has_models and "no models" in s.one_line.lower()


def test_counts_by_ring_and_tier():
    s = summarize_models([_e("a", Ring.ADOPT, HardwareTier.LAPTOP),
                          _e("b", Ring.ADOPT, HardwareTier.APPLE_HIGH_RAM),
                          _e("c", Ring.PILOT, HardwareTier.LAPTOP)])
    assert s.total == 3 and s.has_models
    assert s.by_ring["adopt"] == 2 and s.by_ring["pilot"] == 1
    assert s.by_tier["laptop"] == 2 and s.by_tier["apple_high_ram"] == 1
```

- [ ] **Step 2: Run → fails.**

- [ ] **Step 3: Implement**

```python
# src/radar/web/models_summary.py
"""Immutable display summary of the model catalog (mirror of source_health)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict, Field

from radar.models_radar.entities import ModelEntry


class ModelsSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    total: int = 0
    by_ring: dict[str, int] = Field(default_factory=dict)
    by_tier: dict[str, int] = Field(default_factory=dict)

    @property
    def has_models(self) -> bool:
        return self.total > 0

    @property
    def one_line(self) -> str:
        if not self.total:
            return "Models: no models scanned yet."
        adopt = self.by_ring.get("adopt", 0)
        return f"Models: {self.total} tracked, {adopt} adopt-ready."


def summarize_models(entries: Iterable[ModelEntry]) -> ModelsSummary:
    items = list(entries)
    by_ring = Counter(e.ring.value for e in items if e.ring)
    by_tier = Counter(e.hardware_tier.value for e in items)
    return ModelsSummary(total=len(items), by_ring=dict(by_ring), by_tier=dict(by_tier))
```

- [ ] **Step 4: Create the partial** `src/radar/web/templates/_models_summary.html` (native `<details>`, no JS — mirror `_source_health.html`):

```html
{# Models summary. Context: models_summary (ModelsSummary) | None. #}
{% if models_summary and models_summary.has_models %}
<div class="scan-health">
  <details>
    <summary>🧠 {{ models_summary.one_line }}</summary>
    <ul>
      {% for ring, n in models_summary.by_ring.items() %}<li>{{ ring }}: {{ n }}</li>{% endfor %}
      {% for tier, n in models_summary.by_tier.items() %}<li>{{ tier }}: {{ n }}</li>{% endfor %}
    </ul>
    <p><a href="models.html">Browse models →</a></p>
  </details>
</div>
{% endif %}
```

Add `{% include "_models_summary.html" %}` to both `index.html` and `static_index.html` immediately after the existing `{% include "_source_health.html" %}` line. (In `index.html` the models link should be `/models`; keep `models.html` for static — pass an `asset_base`-aware href OR keep `models.html` since the live route also serves it; simplest: use `{{ asset_base }}models.html` — but the live app uses absolute `/`. To avoid divergence, hardcode `models.html` in the static include and rely on the live app adding its own link in C6's `/models` nav. Keep this partial static-only-safe: use `models.html`.)

- [ ] **Step 5: Run test + render check + commit**

Run `pytest tests/test_models_summary.py -v` → pass; full gate. Commit `feat(models): dashboard Models summary partial`.

---

### Task 6: Models catalog page + per-model pages (static) + live routes

**Files:**
- Create: `src/radar/web/templates/static_models.html`, `src/radar/web/templates/_model_detail.html`, `src/radar/web/templates/static_model.html`, `src/radar/web/templates/models.html`, `src/radar/web/templates/model.html`
- Modify: `src/radar/web/app.py` (routes `/models`, `/model/{model_id}`)
- Test: `tests/test_static_site.py` (extended in C7) + a focused live-route test in `tests/test_web.py`

**Interfaces:**
- Consumes: `ModelEntry`, `summarize_models`, slug helpers.
- Produces: templates rendering a catalog table + per-model detail; live routes returning them.

Because the static render wiring is C7, C6 delivers the templates + live routes and a live-route test. The templates take `models` (list[ModelEntry]) and `slug_by_model` (dict[str,str]).

- [ ] **Step 1: Write the failing test** (live routes):

```python
# tests/test_web.py — add
from fastapi.testclient import TestClient
from pathlib import Path
from radar.web.app import create_app
from radar.storage.run_store import RunStore


def _seed_models(root: Path):
    from radar.models_radar.entities import (
        HardwareTier, Modality, ModelEntry, Openness, Platform, QuantVariant)
    from radar.models import Ring
    rs = RunStore(root / "data" / "runs")
    rid = rs.create_run()
    e = ModelEntry(id="qwen3-8b", name="Qwen3 8B", family="Qwen3", params_total=8_000_000_000,
                   openness=Openness.OPEN_PERMISSIVE, hardware_tier=HardwareTier.LAPTOP,
                   ring=Ring.ADOPT, score=4.0, modality=Modality.TEXT,
                   quants=[QuantVariant(format="Q4_K_M", bits_per_weight=4.5,
                                        est_memory_gb_4k=8.0, platform=Platform.GENERIC, source="hf:x")])
    rs.save_stage(rid, "model_cards", [e.model_dump(mode="json")])
    rs.update_meta(rid, {"kind": "models", "model_count": 1})


def test_models_route_lists_models(tmp_path):
    (tmp_path / "data").mkdir(parents=True)
    _seed_models(tmp_path)
    client = TestClient(create_app(tmp_path))
    r = client.get("/models")
    assert r.status_code == 200 and "qwen3-8b" in r.text and "laptop" in r.text


def test_model_detail_route(tmp_path):
    (tmp_path / "data").mkdir(parents=True)
    _seed_models(tmp_path)
    client = TestClient(create_app(tmp_path))
    r = client.get("/model/qwen3-8b")
    assert r.status_code == 200 and "Q4_K_M" in r.text


def test_models_route_empty_when_no_scan(tmp_path):
    (tmp_path / "data").mkdir(parents=True)
    client = TestClient(create_app(tmp_path))
    assert client.get("/models").status_code == 200  # renders "no models yet", no crash
```

- [ ] **Step 2: Run → fails** (no routes).

- [ ] **Step 3: Implement templates.** `_model_detail.html` (shared core), `model.html`/`static_model.html` (wrap it), `models.html`/`static_models.html` (catalog). Keep them small and mirror `_project_detail.html` styling classes. Catalog body:

```html
{# _model_detail.html — Context: model (ModelEntry) #}
<h2>{{ model.name }} <small>{{ model.family }}</small></h2>
<p>Ring: <strong>{{ model.ring.value if model.ring else '-' }}</strong> ·
   Hardware: <strong>{{ model.hardware_tier.value }}</strong> ·
   Modality: {{ model.modality.value }}{% if model.license %} · License: {{ model.license }}{% endif %}</p>
<p>Params: {{ model.params_total or '?' }}{% if model.params_active %} (active {{ model.params_active }}){% endif %}
   {% if model.context_length %} · Context: {{ model.context_length }}{% endif %}</p>
<table><thead><tr><th>Quant</th><th>Bits</th><th>Mem @4K</th><th>Mem @32K</th><th>Platform</th></tr></thead>
<tbody>
{% for q in model.quants %}<tr><td>{{ q.format }}</td><td>{{ q.bits_per_weight }}</td>
<td>{{ '%.1f'|format(q.est_memory_gb_4k) if q.est_memory_gb_4k else '?' }} GB</td>
<td>{{ '%.1f'|format(q.est_memory_gb_32k) if q.est_memory_gb_32k else '?' }} GB</td>
<td>{{ q.platform.value }}</td></tr>{% endfor %}
</tbody></table>
```
```html
{# static_models.html — Context: models (list[ModelEntry]), slug_by_model #}
<!doctype html><html><head><meta charset="utf-8"><title>Models</title></head><body>
<h1>Local Models</h1>
{% if not models %}<p>No models scanned yet.</p>{% endif %}
<table><thead><tr><th>Model</th><th>Ring</th><th>Tier</th><th>Min mem</th><th>Family</th></tr></thead><tbody>
{% for m in models %}<tr>
<td><a href="model_{{ slug_by_model[m.id] }}.html">{{ m.name }}</a></td>
<td>{{ m.ring.value if m.ring else '-' }}</td><td>{{ m.hardware_tier.value }}</td>
<td>{% set mv = m.quants|selectattr('est_memory_gb_4k')|list %}{{ '%.1f GB'|format(mv[0].est_memory_gb_4k) if mv else '?' }}</td>
<td>{{ m.family }}</td></tr>{% endfor %}
</tbody></table></body></html>
```
`static_model.html` wraps `_model_detail.html` in a minimal html doc. `models.html`/`model.html` (live) can `{% extends %}` or simply reuse the same bodies via include with the live nav — to keep it simple, make `models.html` and `static_models.html` identical content (the live route renders `static_models.html` too). Likewise `model.html` renders `_model_detail.html`.

In `app.py`, add routes (mirror the existing index/source-health wiring; reuse `ModelQueryService` or load entries directly):

```python
from radar.web.models_summary import summarize_models
from radar.mcp_server.model_queries import _latest_model_cards
from radar.models_radar.entities import ModelEntry
from radar.web.slugs import build_slug_map

def _model_entries() -> list[ModelEntry]:
    return [ModelEntry.model_validate(c) for c in _latest_model_cards(root)]

@app.get("/models", response_class=HTMLResponse)
def models_page(request: Request):
    entries = _model_entries()
    slug_by_model = build_slug_map([e.id for e in entries])
    return TEMPLATES.TemplateResponse(request, "static_models.html",
                                      {"models": entries, "slug_by_model": slug_by_model})

@app.get("/model/{model_id}", response_class=HTMLResponse)
def model_detail(request: Request, model_id: str):
    entry = next((e for e in _model_entries() if e.id == model_id), None)
    if entry is None:
        return HTMLResponse("Model not found", status_code=404)
    return TEMPLATES.TemplateResponse(request, "static_model.html", {"model": entry})
```

Also pass `models_summary=summarize_models(_model_entries())` into the index route's context (so the C5 partial shows on the live index).

- [ ] **Step 4: Run → pass**, full gate. **Step 5: Commit** `feat(models): models catalog + per-model pages + live routes`.

---

### Task 7: Static export wiring

**Files:**
- Modify: `src/radar/web/static_site.py` (params + render), `src/radar/cli.py` (`export`)
- Test: `tests/test_static_site.py` (add)

**Interfaces:**
- Consumes: `summarize_models`, model report/feed builders (C3/C4), `_latest_model_cards`, `ModelMetricsStore`, `load_model_events`.
- Produces: `render_static_site(..., model_entries: list[ModelEntry] | None = None, model_events: list | None = None)` writing `models.html`, `model_<slug>.html` pages, `changes-models.xml/json`, the index Models summary, and copying `model-history.jsonl` into downloads.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_static_site.py — add
def test_static_site_renders_models_section(tmp_path):
    from radar.models_radar.entities import HardwareTier, ModelEntry, Openness, QuantVariant, Platform
    from radar.models import Ring
    from radar.web.static_site import render_static_site
    from datetime import UTC, datetime
    e = ModelEntry(id="qwen3-8b", name="Qwen3 8B", family="Qwen3", ring=Ring.ADOPT,
                   hardware_tier=HardwareTier.LAPTOP, openness=Openness.OPEN_PERMISSIVE,
                   quants=[QuantVariant(format="Q4_K_M", bits_per_weight=4.5,
                                        est_memory_gb_4k=8.0, platform=Platform.GENERIC, source="x")])
    render_static_site([], tmp_path / "_site", datetime(2026, 6, 22, tzinfo=UTC),
                       model_entries=[e])
    site = tmp_path / "_site"
    assert (site / "models.html").exists()
    assert "qwen3-8b" in (site / "models.html").read_text(encoding="utf-8")
    assert (site / "model_qwen3-8b.html").exists()


def test_static_site_models_backcompat_without_models(tmp_path):
    from radar.web.static_site import render_static_site
    from datetime import UTC, datetime
    render_static_site([], tmp_path / "_site", datetime(2026, 6, 22, tzinfo=UTC))
    assert (tmp_path / "_site" / "index.html").exists()  # no crash, no models
```

- [ ] **Step 2: Run → fails.**

- [ ] **Step 3: Implement** in `static_site.py`: add `model_entries`/`model_events` params (default None→[]); compute `summarize_models(model_entries)` and pass `models_summary` into the `static_index.html` render; write `models.html` (static_models template with `slug_by_model = build_slug_map([m.id for m in model_entries])`), a `model_<slug>.html` per entry (static_model template), and `changes-models.xml/json` via the C4 builders when `model_events`. Add the model history download to the `downloads` dict. Guard everything on `if model_entries:`. In `cli.py export`, load `model_entries = [ModelEntry.model_validate(c) for c in _latest_model_cards(root)]`, `model_events = load_model_events(root/"data"/"model-history.jsonl")`, and pass them; copy `data/model-history.jsonl` into the site if present.

- [ ] **Step 4: Run → pass**, full gate. **Step 5: Commit** `feat(models): export Models page, per-model pages, model feeds`.

---

### Task 8: Daily-scan + publish integration

**Files:**
- Modify: `.github/workflows/publish.yml`
- Test: `tests/test_publish_workflow.py` (create — a text assertion on the YAML)

**Interfaces:** none (CI config).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_publish_workflow.py
from __future__ import annotations
from pathlib import Path


def test_publish_runs_model_scan_before_export_and_commits_model_history():
    yml = Path(".github/workflows/publish.yml").read_text(encoding="utf-8")
    assert "radar models scan" in yml
    i_models = yml.index("radar models scan")
    i_export = yml.index("radar export")
    assert i_models < i_export, "model scan must run before export"
    assert "data/model-history.jsonl" in yml
```

- [ ] **Step 2: Run → fails.**

- [ ] **Step 3: Implement** — in `publish.yml`, add `uv run radar models scan --root .` on the line immediately after the existing `uv run radar scan --root . --days 7` step, and add `git add -f data/model-history.jsonl || true` alongside the existing `git add -f data/history.jsonl` in the commit step. Keep the existing steps unchanged.

- [ ] **Step 4: Run → pass**, full gate. **Step 5: Commit** `ci: run model scan in daily publish + commit model history`.

---

### Task 9: Full-gate + live smoke + final review + merge

**Files:** none.

- [ ] **Step 1: Gates** — `ruff check src tests && mypy src && pytest -q` green.
- [ ] **Step 2: Live smoke** — `radar models scan --root .`; then `radar export --root . --out /tmp/site-c` → assert `/tmp/site-c/models.html` lists models with tiers + quant tables, `model_<slug>.html` pages exist, `changes-models.xml`/`.json` present, `index.html` shows the Models summary. Build the MCP server on `.`: `list_models(max_memory_gb=24)` excludes datacenter-tier models; `get_model("qwen3-30b-a3b")` returns a quant table + ring + momentum. Confirm `radar export` ran without a model run still works (back-compat).
- [ ] **Step 3: Final whole-branch review** (most-capable model) over the branch base..HEAD package.
- [ ] **Step 4: Merge** to main `--no-ff`, delete branch, integrate `origin`, push.

```bash
git checkout main && git merge --no-ff feature/local-model-radar-c \
  -m "Merge feature/local-model-radar-c (Plan C): model-radar surface (MCP, reports/feeds, dashboard, CI)"
git branch -d feature/local-model-radar-c
```

---

## Self-Review

**Spec coverage (Plan C scope):** §6 MCP tools → C1/C2; §6 reports/feeds → C3/C4; §6 dashboard Models section + per-model pages → C5/C6/C7; §7 daily-scan integration → C8. §5 discovery (HF-trending model proposals) is NOT in this plan — note: deferred, mention to user (the spec listed it under Plan C; it's the one §-item omitted here to keep C focused on surfacing what exists; can be a small follow-up C10 or fold into the hardware sub-project intake). **FLAG at execution: confirm whether discovery is wanted in Plan C or deferred.**

**Placeholder scan:** Each code step has complete code; template tasks include the full template bodies. The C1 test has an awkward `Modality` import the implementer is told to simplify — concrete instruction, not a placeholder.

**Type consistency:** `_latest_model_cards(root)->list[dict]` defined in C1, reused in C6/C7. `ModelQueryService` methods (C1) consumed by C2 tools. `build_model_mover_lines`/`render_model_report`/`model_events_to_feed_*` (C3/C4) consumed by C7. `summarize_models->ModelsSummary` (C5) consumed by C6/C7. `ModelEntry.model_validate` round-trip used consistently. `RunStore` meta `kind=="models"` filter consistent with Plan A/B.
