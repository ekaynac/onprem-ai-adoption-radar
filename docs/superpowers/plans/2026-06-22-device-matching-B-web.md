# Device Matching — Phase B: Web Surfaces Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Bring device-fit to the published dashboard — an interactive device picker that colors the Models catalog by "will it run on my machine?", and a precomputed per-model "Runs on" tier table.

**Architecture:** Phase A shipped the engine (`devices.py`, `device_fit.py`) + MCP + CLI. Phase B adds the two web surfaces, reusing those. The picker is small framework-free JS doing `usable = mem × fraction` against each row's `data-min-memory-gb` (no model data beyond per-row min memory). The per-model "Runs on" table is precomputed at export via `evaluate_fit`. Also folds in the deferred Phase-A housekeeping (verdict-branch tests).

**Tech Stack:** Python 3.12, Jinja2, FastAPI, small vanilla JS, pytest + ruff + mypy.

## Global Constraints

- Python ≥ 3.12; new modules begin with `from __future__ import annotations`.
- No new third-party dependencies; deterministic core, no LLM. Reuse `devices.py`/`device_fit.py` (don't re-derive).
- Dashboard JS stays small + framework-free (mirror `_filter_script.html`); single source of truth — usable fractions + presets injected from Python (`USABLE_FRACTION`, `DEVICE_PRESETS`), never hardcoded in JS.
- Graceful: no model run → Models page still renders (picker simply has no rows); a model with no sized quants → no `data-min-memory-gb` (treated as "unknown" by the JS).
- Back-compat: `render_static_site` with no model args unchanged; existing tool dashboard untouched.
- ruff + mypy clean; coverage ≥ 80%. Full-gate (`ruff check src tests`, `mypy src`, `pytest -q`) before EVERY commit. Commit on the CURRENT branch only.

## Reusable facts (verified)

- Catalog templates: `static_models.html` (static), `models.html` (live), both a `<table>` of model rows; per-model `_model_detail.html` (shared by `static_model.html` + `model.html`).
- Static render: `static_site.py:_write_model_pages(env, out_dir, model_entries, model_events, site_title, self_base_url)` renders `static_models.html` (ctx `models`, `slug_by_model`) + per-model `static_model.html` (ctx `model`).
- Live routes (`app.py`): `/models` → `static_models.html` (ctx `models`, `slug_by_model`); `/model/{id}` → `static_model.html` (ctx `model`); `_model_entries()` helper.
- Engine: `devices.py` → `DEVICE_PRESETS`, `USABLE_FRACTION`, `DeviceProfile`, `usable_memory_gb`; `device_fit.py` → `evaluate_fit(model, device, context_tokens=4096) -> ModelFit` (`.verdict`, `.best_quant_format`).
- True per-model min memory (for the data attribute) = min of each quant's `est_memory_gb_4k` (the existing templates' `mv[0]` is the first such value, not the min — fix to `|min` here).

---

### Task 1: Dashboard device picker

**Files:**
- Create: `src/radar/web/picker_context.py` (shared context helper)
- Create: `src/radar/web/templates/_device_picker.html`
- Modify: `src/radar/web/templates/static_models.html`, `src/radar/web/templates/models.html` (add per-row `data-min-memory-gb`, a row class, include the picker)
- Modify: `src/radar/web/static_site.py` (`_write_model_pages` passes picker context), `src/radar/web/app.py` (`/models` route passes picker context)
- Test: `tests/test_device_picker.py`

**Interfaces:**
- Consumes: `DEVICE_PRESETS`, `USABLE_FRACTION`, `usable_memory_gb` (Phase A).
- Produces: `picker_context() -> dict` = `{"device_presets": [{"id","label","total_memory_gb","kind","gpu_count","usable_gb"} …], "usable_fraction": {...}}`, injected as `device_picker` into both Models renders.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_device_picker.py
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from radar.models import Ring
from radar.models_radar.entities import HardwareTier, ModelEntry, Openness, Platform, QuantVariant
from radar.web.picker_context import picker_context
from radar.web.static_site import render_static_site


def test_picker_context_has_presets_and_fractions():
    ctx = picker_context()
    assert ctx["usable_fraction"]["gpu"] == 0.85
    ids = {d["id"] for d in ctx["device_presets"]}
    assert "rtx-4090-24gb" in ids
    a = next(d for d in ctx["device_presets"] if d["id"] == "rtx-4090-24gb")
    assert a["usable_gb"] == 20.4 and a["kind"] == "gpu"


def test_static_models_page_has_picker_and_row_data(tmp_path: Path):
    m = ModelEntry(id="qwen3-8b", name="Qwen3 8B", family="Qwen3", ring=Ring.ADOPT,
                   hardware_tier=HardwareTier.LAPTOP, openness=Openness.OPEN_PERMISSIVE,
                   quants=[QuantVariant(format="Q4_K_M", bits_per_weight=4.5, est_memory_gb_4k=8.4,
                                        platform=Platform.GENERIC, source="x"),
                           QuantVariant(format="Q8_0", bits_per_weight=8.0, est_memory_gb_4k=12.0,
                                        platform=Platform.GENERIC, source="x")])
    render_static_site([], tmp_path / "_site", datetime(2026, 6, 22, tzinfo=UTC), model_entries=[m])
    html = (tmp_path / "_site" / "models.html").read_text(encoding="utf-8")
    assert 'id="device-select"' in html
    assert 'data-min-memory-gb="8.4"' in html   # min across quants, not first
    assert "RADAR_USABLE_FRACTION" in html and "rtx-4090-24gb" in html
```

- [ ] **Step 2: Run test → fails** (`ModuleNotFoundError` / missing markup).

- [ ] **Step 3: Implement the context helper**

```python
# src/radar/web/picker_context.py
"""Shared template context for the dashboard device picker (single source of truth)."""

from __future__ import annotations

from typing import Any

from radar.models_radar.devices import DEVICE_PRESETS, USABLE_FRACTION, usable_memory_gb


def picker_context() -> dict[str, Any]:
    """Presets + usable fractions for the Models-page device picker."""
    return {
        "device_presets": [
            {"id": key, "label": d.name, "total_memory_gb": d.total_memory_gb,
             "kind": d.kind, "gpu_count": d.gpu_count, "usable_gb": usable_memory_gb(d)}
            for key, d in DEVICE_PRESETS.items()
        ],
        "usable_fraction": dict(USABLE_FRACTION),
    }
```

- [ ] **Step 4: Create the picker partial** `src/radar/web/templates/_device_picker.html` (framework-free; injects presets + fractions as JSON, then the fit script). Context: `device_picker` (the dict above).

```html
{# Device picker. Context: device_picker = {device_presets, usable_fraction}. #}
{% if device_picker %}
<div class="device-picker" style="margin:1rem 0;">
  <label>Will it run on
    <select id="device-select">
      <option value="">— pick a device —</option>
      {% for d in device_picker.device_presets %}
      <option value="{{ d.id }}" data-usable="{{ d.usable_gb }}">{{ d.label }} (~{{ '%.0f'|format(d.usable_gb) }} GB usable)</option>
      {% endfor %}
      <option value="__custom__">Custom…</option>
    </select>
  </label>
  <span id="device-custom" style="display:none;">
    <input id="device-mem" type="number" min="1" step="1" placeholder="GB" style="width:5rem;">
    <select id="device-kind"><option value="gpu">GPU</option><option value="apple">Apple</option><option value="cpu">CPU</option></select>
    <input id="device-gpus" type="number" min="1" step="1" value="1" style="width:3.5rem;" title="GPU count">
  </span>
  <span id="device-usable" style="margin-left:.5rem;color:#666;"></span>
</div>
<script>
window.RADAR_USABLE_FRACTION = {{ device_picker.usable_fraction | tojson }};
window.RADAR_DEVICE_PRESETS = {{ device_picker.device_presets | tojson }};
(function () {
  var sel = document.getElementById("device-select");
  var custom = document.getElementById("device-custom");
  var usableLabel = document.getElementById("device-usable");
  if (!sel) return;
  function usableGb() {
    if (sel.value === "__custom__") {
      var mem = parseFloat(document.getElementById("device-mem").value) || 0;
      var kind = document.getElementById("device-kind").value;
      var gpus = parseInt(document.getElementById("device-gpus").value) || 1;
      return mem * (window.RADAR_USABLE_FRACTION[kind] || 0.85) * gpus;
    }
    var preset = window.RADAR_DEVICE_PRESETS.find(function (d) { return d.id === sel.value; });
    return preset ? preset.usable_gb : 0;
  }
  function apply() {
    custom.style.display = sel.value === "__custom__" ? "" : "none";
    var usable = usableGb();
    usableLabel.textContent = usable ? "~" + usable.toFixed(1) + " GB usable" : "";
    document.querySelectorAll("tr[data-min-memory-gb]").forEach(function (row) {
      var min = parseFloat(row.getAttribute("data-min-memory-gb"));
      row.classList.remove("fit-yes", "fit-tight", "fit-no");
      if (!usable || isNaN(min)) return;
      if (min <= usable * 0.95) row.classList.add("fit-yes");
      else if (min <= usable) row.classList.add("fit-tight");
      else row.classList.add("fit-no");
    });
  }
  sel.addEventListener("change", apply);
  ["device-mem", "device-kind", "device-gpus"].forEach(function (id) {
    var el = document.getElementById(id); if (el) el.addEventListener("input", apply);
  });
})();
</script>
<style>
tr.fit-yes td:first-child { box-shadow: inset 3px 0 0 #2e7d32; }
tr.fit-tight td:first-child { box-shadow: inset 3px 0 0 #f9a825; }
tr.fit-no { opacity: .5; }
</style>
{% endif %}
```

- [ ] **Step 5: Wire the catalog templates.** In BOTH `static_models.html` and `models.html`: add `{% include "_device_picker.html" %}` just above the `<table>`; give each model `<tr>` a `data-min-memory-gb` from the min of its quant 4K estimates, and use that same min for the "Min mem" cell. Replace the existing `{% set mv = … %}` cell with:

```html
{% set mems = m.quants | selectattr('est_memory_gb_4k') | map(attribute='est_memory_gb_4k') | list %}
<tr{% if mems %} data-min-memory-gb="{{ mems | min }}"{% endif %}>
  ... existing cells ...
  <td>{{ '%.1f GB'|format(mems | min) if mems else '?' }}</td>
  ...
</tr>
```
(Apply the same `mems`/`data-min-memory-gb`/`mems|min` change to both files. `static_models.html` is a bare doc — its rows must still carry the attribute + the picker include + a minimal `<style>`; the partial supplies its own styles, so just add the include.)

Then thread `device_picker=picker_context()` into the render context: in `static_site.py:_write_model_pages` add it to the `static_models.html` render call; in `app.py` `/models` route add it to the `TemplateResponse` context.

- [ ] **Step 6: Run test → pass**, full gate. **Step 7: Commit** `feat(models): dashboard device picker (fit coloring by chosen device)`.

---

### Task 2: Per-model "Runs on" tier table

**Files:**
- Modify: `src/radar/models_radar/devices.py` (add `COMMON_DEVICE_TIERS`)
- Modify: `src/radar/web/templates/_model_detail.html` (render the table)
- Modify: `src/radar/web/static_site.py` (per-model render passes `fit_by_tier`), `src/radar/web/app.py` (`/model/{id}` route passes `fit_by_tier`)
- Test: `tests/test_static_site.py` (add) + `tests/test_web.py` (add)

**Interfaces:**
- Consumes: `DEVICE_PRESETS`, `evaluate_fit` (Phase A).
- Produces: `COMMON_DEVICE_TIERS: list[str]` (preset ids); a shared `fit_by_tier(model) -> list[dict]` helper (in `web/picker_context.py`) returning `[{"device","verdict","best_quant"} …]` over the tiers; passed as `fit_by_tier` into `_model_detail.html`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_static_site.py — add
def test_model_page_has_runs_on_table(tmp_path):
    from datetime import UTC, datetime
    from radar.models import Ring
    from radar.models_radar.entities import HardwareTier, ModelEntry, Openness, Platform, QuantVariant
    from radar.web.static_site import render_static_site
    m = ModelEntry(id="qwen3-8b", name="Qwen3 8B", family="Qwen3", params_total=8_000_000_000,
                   ring=Ring.ADOPT, hardware_tier=HardwareTier.LAPTOP, openness=Openness.OPEN_PERMISSIVE,
                   quants=[QuantVariant(format="Q4_K_M", bits_per_weight=4.5, est_memory_gb_4k=8.4,
                                        platform=Platform.GENERIC, source="x")])
    render_static_site([], tmp_path / "_site", datetime(2026, 6, 22, tzinfo=UTC), model_entries=[m])
    page = (tmp_path / "_site" / "model_qwen3-8b.html").read_text(encoding="utf-8")
    assert "Runs on" in page
    assert "RTX 4090 (24GB)" in page  # one of the COMMON_DEVICE_TIERS
```
```python
# tests/test_picker_context (or test_static_site) — add a unit test for the helper
def test_fit_by_tier_returns_verdicts():
    from radar.models_radar.entities import HardwareTier, ModelEntry, Platform, QuantVariant
    from radar.web.picker_context import fit_by_tier
    m = ModelEntry(id="x", name="x", family="F", params_total=8_000_000_000,
                   quants=[QuantVariant(format="Q4_K_M", bits_per_weight=4.5, est_memory_gb_4k=8.4,
                                        platform=Platform.GENERIC, source="x")])
    rows = fit_by_tier(m)
    assert rows and {"device", "verdict", "best_quant"} <= set(rows[0])
    assert any(r["verdict"] == "fits" for r in rows)
```

- [ ] **Step 2: Run test → fails.**

- [ ] **Step 3: Implement** — `COMMON_DEVICE_TIERS` in `devices.py` (subset of presets spanning the range):

```python
COMMON_DEVICE_TIERS = [
    "rtx-4060-8gb", "rtx-4080-16gb", "rtx-4090-24gb",
    "rtx-6000-ada-48gb", "a100-80gb", "mac-64gb",
]
```
`fit_by_tier` in `web/picker_context.py`:
```python
from radar.models_radar.device_fit import evaluate_fit
from radar.models_radar.devices import COMMON_DEVICE_TIERS, DEVICE_PRESETS
from radar.models_radar.entities import ModelEntry


def fit_by_tier(model: ModelEntry) -> list[dict[str, Any]]:
    """Largest-fitting quant per common device tier (for the per-model page)."""
    rows: list[dict[str, Any]] = []
    for key in COMMON_DEVICE_TIERS:
        dev = DEVICE_PRESETS[key]
        fit = evaluate_fit(model, dev)
        rows.append({"device": dev.name, "verdict": fit.verdict,
                     "best_quant": fit.best_quant_format or "-"})
    return rows
```
Append a "Runs on" section to `_model_detail.html` (context gains `fit_by_tier`):
```html
{% if fit_by_tier %}
<h3>Runs on</h3>
<table><thead><tr><th>Device</th><th>Fit</th><th>Largest quant that fits</th></tr></thead><tbody>
{% for r in fit_by_tier %}<tr><td>{{ r.device }}</td><td>{{ r.verdict }}</td><td>{{ r.best_quant }}</td></tr>{% endfor %}
</tbody></table>
{% endif %}
```
Pass `fit_by_tier=fit_by_tier(entry)` in `static_site.py`'s per-model render loop and in `app.py`'s `/model/{id}` route. (Import the helper; guard `if model_entries`/entry exists as today.)

- [ ] **Step 4: Run tests → pass**, full gate. **Step 5: Commit** `feat(models): per-model "Runs on" device-tier table`.

---

### Task 3: Phase-A housekeeping + gate + live smoke + final review + merge

**Files:**
- Modify: `tests/test_device_fit.py` (add the two missing verdict-branch tests)
- Modify: `src/radar/models_radar/device_fit.py` (docstring wording tweak only, if warranted)

- [ ] **Step 1: Add the deferred verdict-branch tests** (Phase-A review flagged `fits_tight`/`fits_quantized` as untested):

```python
# tests/test_device_fit.py — add
def test_fits_tight_when_best_above_95pct():
    # usable 20.4 (24GB GPU); make the only quant land between 95% and 100%
    m = _model("q", 36_000_000_000, [("Q4_K_M", 4.5)])  # ~24.3GB? tune so 19.4–20.4
    # choose params so weights-only ≈ 19.8GB: 36e9*4.5/8/1e9*1.2 = 24.3 → too big; use 28e9 → ~18.9 (fits, not tight)
    # Use explicit est via QuantVariant to control memory precisely:
    from radar.models_radar.entities import ModelEntry, Platform, QuantVariant
    m = ModelEntry(id="q", name="q", family="F",
                   quants=[QuantVariant(format="Q4_K_M", bits_per_weight=4.5,
                                        est_memory_gb_4k=20.0, platform=Platform.GENERIC, source="x")])
    from radar.models_radar.devices import DeviceProfile
    fit = evaluate_fit(m, DeviceProfile(name="g", kind="gpu", total_memory_gb=24))  # usable 20.4
    assert fit.verdict == "fits_tight"  # 20.0 ≤ 20.4 but > 0.95*20.4=19.38


def test_fits_quantized_when_only_subq4_fits():
    from radar.models_radar.entities import ModelEntry, Platform, QuantVariant
    # only a sub-Q4 (3.4 bits) quant is small enough to fit
    m = ModelEntry(id="q", name="q", family="F", quants=[
        QuantVariant(format="Q3_K", bits_per_weight=3.4, est_memory_gb_4k=10.0, platform=Platform.GENERIC, source="x"),
        QuantVariant(format="Q8_0", bits_per_weight=8.0, est_memory_gb_4k=30.0, platform=Platform.GENERIC, source="x"),
    ])
    from radar.models_radar.devices import DeviceProfile
    fit = evaluate_fit(m, DeviceProfile(name="g", kind="gpu", total_memory_gb=16))  # usable 13.6
    assert fit.verdict == "fits_quantized" and fit.best_quant_format == "Q3_K"
```
(Note: these construct `ModelEntry` with explicit `est_memory_gb_4k` and NO `params_total`, so the estimator returns None and the stored value is used — gives precise control over the verdict boundary. The implementer should keep only the explicit-`QuantVariant` versions, dropping the `_model(...)` sketch lines.)

- [ ] **Step 2: Gates** — `ruff check src tests && mypy src && pytest -q` green.
- [ ] **Step 3: Live smoke** — `radar models scan --root .` then `radar export --root . --out /tmp/site-db`:
  - open `/tmp/site-db/models.html` → confirm the `#device-select` + `RADAR_USABLE_FRACTION` script + per-row `data-min-memory-gb` are present;
  - open a `model_*.html` → confirm the "Runs on" table with the 6 tiers + verdicts.
  - Start the live app (or `TestClient`) → `/models` carries the picker; `/model/qwen3-8b` carries the table.
- [ ] **Step 4: Final whole-branch review** (most-capable model) over branch base..HEAD.
- [ ] **Step 5: Merge** to main `--no-ff`, delete branch, integrate `origin`, push.

```bash
git checkout main && git merge --no-ff feature/device-matching-b \
  -m "Merge feature/device-matching-b (Phase B): dashboard device picker + per-model Runs-on table"
git branch -d feature/device-matching-b
```

---

## Self-Review

**Spec coverage (Phase B):** dashboard device picker (live + static, JS coloring by chosen device, presets+custom) → Task 1; per-model "Runs on" tier table (precomputed, static) → Task 2; deferred Phase-A housekeeping (fits_tight/fits_quantized tests) → Task 3. Single source of truth: usable fractions + presets injected from `USABLE_FRACTION`/`DEVICE_PRESETS` (no JS hardcoding).

**Placeholder scan:** Full template/JS/Python code given. Task 3's test sketch explicitly tells the implementer to keep the explicit-`QuantVariant` versions and drop the `_model(...)` sketch lines — a concrete instruction, not a placeholder.

**Type consistency:** `picker_context()` (Task 1) + `fit_by_tier(model)` (Task 2) both in `web/picker_context.py`, consumed by `static_site.py` + `app.py`. `device_picker` context dict shape (`device_presets`/`usable_fraction`) matches the partial's usage. `COMMON_DEVICE_TIERS` (Task 2, in devices.py) keys exist in `DEVICE_PRESETS`. Reuses `evaluate_fit(model, device)->ModelFit` (`.verdict`,`.best_quant_format`) and `usable_memory_gb` from Phase A unchanged. Per-row `data-min-memory-gb` = `mems|min` consistently in both catalog templates.
