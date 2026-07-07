# Deferred-Items Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close every actionable deferred item from the data-quality + readability reviews: sources.html onto the design system, table-wrap hygiene, keyboard-operable sorting, the run-walk dedup, and evidence-based MoE seed verification.

**Architecture:** Five independent small tasks — three template/JS, one pure refactor with a new `RunStore` helper, one data-verification task. No behavior changes except where the spec names them.

**Tech Stack:** Jinja2, vanilla JS, Python 3.12, pytest + ruff + mypy. **No new dependencies.**

**Spec:** `docs/superpowers/specs/2026-07-08-deferred-cleanup-design.md`.

## Global Constraints

- Guarded-gateway degradation behavior UNCHANGED (Task 4 extracts the walk only; every try/except shell stays where it is).
- Live/static twins byte-identical per block (Tasks 2-3 touch twins).
- Canonical live nav dict verbatim (as every live page): `{"Radar": "/", "Models": "/models", "Research": "/research", "Trending": "/trending", "Compare": "/compare", "History": "/history", "Sources": "/sources"}`.
- MoE verification is EVIDENCE-based: correct values only with proof; inconclusive → YAML comment, never a guess. HF unreachable → annotate as unverified, don't block.
- **Plan-time refinement:** the helper is `latest_run_of_kind(kind: str | None)` — `None` means "the latest run WITHOUT a `kind` key" (the main tool scan), which is what `scan_health.py:94` needs. `orchestrator.py:452` is a last-N slice with no kind filter — verified DIFFERENT pattern, NOT converted.
- ruff line-length 100 (E501 ignored); coverage ≥ 80%; gates `uv run pytest`, `uv run ruff check .`, `uv run mypy src/radar`. Use `uv run pytest -o addopts="" -q 2>&1 | tail -1` for the true count.
- Commit `<type>: <description>`; `git add` specific paths only (`data/history.jsonl` never committed).

## Verified anchors

- `src/radar/web/templates/sources.html` (143 lines): bespoke `<style>` lines 7-83; body = `← Dashboard` link, `<h1>Signal Sources</h1>`, a 5-col sources table (uses `.mono`, `.disabled` row class), `<h2>Add a source</h2>`, `{% if error %}<p class="error">`, a POST form with 6 `<label>`-wrapped controls (two carry `class="full"`) + submit button. Route: GET+POST `/sources` in `app.py` (find it; context passes `sources`, `types`, `categories`, `error`).
- `_base_styles.html` already provides: `.error`, `.filter-bar` (+ label/button rules), `.table-wrap`, `.mono` — VERIFY `.mono` exists there (grep; if it's defined only in a page style, add `.mono { font-family: ui-monospace, monospace; }` to base styles). `.disabled` row styling was bespoke — carry it as one small rule if used (`tr.disabled { opacity: 0.55; }` matching the old look — read the old rule first).
- Wrap-hygiene sites: `trending.html` + `static_trending.html` first table block (h2 inside the div); `_project_detail.html` "Score breakdown" h2 + "On-prem rubric" h2 + `on_prem_fit` paragraph; `_model_detail.html` "Runs on" h3. All other 22 sites wrap tightly.
- Sort scripts: `_models_sort_script.html` defines `function modelsSort(th)` (headers carry inline `onclick="modelsSort(this)"`, `data-key`, `aria-sort="none"`); `_techniques_sort_script.html` mirrors with `techniquesSort`. Scripts are included after the tables (bottom of page), so a direct `querySelectorAll` wiring loop runs against existing DOM.
- Walk sites + shapes:
  - `cli.py:522` (models_list): find latest `kind == "models"` run id.
  - `cli.py:1555` (`_research_snapshot_status`): latest `kind == "research"` run id (then reads meta again for the stamp — keep that).
  - `web/scan_health.py:94`: latest run WITHOUT a `kind` key → returns that meta.
  - `mcp_server/model_queries.py:27`: latest `kind == "models"` → reads `model_cards.json` from `_run_dir`.
  - `mcp_server/technique_queries.py:25` (`_latest_technique_cards`): latest `kind == "research"` → reads `technique_cards.json`.
  - `orchestrator.py:452`: NOT converted (different pattern).
- `RunStore` (`src/radar/storage/run_store.py`): dataclass; `read_meta(run_id)` at line 103, `list_runs(include_replays=False)` at 113. Add the new method after `read_meta`.
- The 3 MoE seeds (`config/model-seed.yaml`): `hf-qwen3-6-35b-a3b-nvfp4` → `nvidia/Qwen3.6-35B-A3B-NVFP4` / 18683860336; `hf-gemma-4-26b-a4b-nvfp4` → `nvidia/Gemma-4-26B-A4B-NVFP4` / 14386941232; `hf-qwen3-6-27b-nvfp4` → `nvidia/Qwen3.6-27B-NVFP4` / 18164649200.
- `_MOE_TOKEN` in `src/radar/discovery/model_promotion.py` (near `plausible_params`).

## File Structure

```
src/radar/web/templates/sources.html            # T1: design-system conversion
CHANGELOG.md                                     # T1 restore + T5 entry
src/radar/web/templates/{trending,static_trending}.html _project_detail.html _model_detail.html  # T2
src/radar/web/templates/{models,static_models,techniques,static_techniques}.html + both sort scripts  # T3
src/radar/storage/run_store.py + cli.py web/scan_health.py mcp_server/{model,technique}_queries.py  # T4
config/model-seed.yaml src/radar/discovery/model_promotion.py README.md  # T5
tests/test_web.py test_static_site.py test_run_store.py (locate real name) ...  # per task
```

---

### Task 1: sources.html design-system conversion (+ CHANGELOG restore)

**Files:**
- Modify: `src/radar/web/templates/sources.html`, `src/radar/web/templates/_base_styles.html` (only if `.mono`/`.disabled` rules are missing), `CHANGELOG.md`
- Test: `tests/test_web.py` (append; find the existing /sources tests — `grep -n "sources" tests/test_web.py`)

**Interfaces:**
- Consumes: `_base_styles.html`, `_hero.html` (needs `page_title`, `tagline`, `nav`, `asset_base`, optional `generated_at`), `_footer.html`, `.filter-bar`, `.table-wrap`, `.error` — all existing.

- [ ] **Step 1: Write the failing tests** (append to tests/test_web.py, reusing the existing /sources fixture plumbing):

```python
def test_sources_page_on_design_system(tmp_path):
    client = TestClient(create_app(tmp_path))
    r = client.get("/sources")
    assert r.status_code == 200
    assert 'class="hero"' in r.text and "--hero-bg" in r.text     # shared styles + hero
    assert '<div class="table-wrap">' in r.text
    assert 'class="filter-bar"' in r.text                          # form styled
    assert "#f9fafb" not in r.text                                 # bespoke style gone
    for label in ("Radar", "Models", "Research", "Trending", "Compare", "History", "Sources"):
        assert f">{label}</a>" in r.text
```

Also extend the TF4-era live-nav test's path list with "/sources" if it exists. Keep the existing POST-route tests untouched (they pin behavior).

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_web.py -k sources -v` → new test FAILS.

- [ ] **Step 3: Convert the template.** Rebuild `sources.html` on the converted `compare.html` skeleton (read it): keep `<!doctype…>` head shape with `{% include "_base_styles.html" %}`, `{% set nav = {…canonical live dict…} %}`, `_hero` with `page_title="Signal Sources"`, `tagline="Seed sources the radar scans — review and add."`, then `<main class="container">`: the sources table wrapped in `.table-wrap` (keep `.mono` cells + `.disabled` row class), the `<h2>Add a source</h2>` + `{% if error %}<p class="error">…` + the form with `class="filter-bar"` (labels/controls/names/ids/action/method UNCHANGED; keep the `class="full"` labels — they're harmless), `_footer` include. Check `.mono` exists in `_base_styles.html`; if not add `.mono { font-family: ui-monospace, monospace; }`; port `tr.disabled` as one rule matching the old opacity/strike look (read the old bespoke rule first).

- [ ] **Step 4: CHANGELOG.** In the readability entry (or this pass's new entry), restore the claim: sources now renders the canonical 7-item nav / shared design system (reword the earlier correction honestly — it was true-after-this-pass).

- [ ] **Step 5: Run tests** — `uv run pytest tests/test_web.py -q` → PASS (incl. existing POST tests).

- [ ] **Step 6: Lint + commit**

```bash
uv run ruff check tests/ && uv run mypy src/radar
git add src/radar/web/templates/sources.html src/radar/web/templates/_base_styles.html \
  CHANGELOG.md tests/test_web.py
git commit -m "feat: sources page adopts the shared design system"
```

---

### Task 2: table-wrap hygiene (4 sites)

**Files:**
- Modify: `src/radar/web/templates/trending.html`, `static_trending.html`, `_project_detail.html`, `_model_detail.html`
- Test: `tests/test_base_styles.py` (append a template-hygiene pin) + `tests/test_static_site.py`

**Interfaces:** none new — markup reshuffle only.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_base_styles.py` (it already reads template files):

```python
def test_no_headings_inside_table_wrap():
    import re
    from pathlib import Path
    for tpl in Path("src/radar/web/templates").glob("*.html"):
        text = tpl.read_text(encoding="utf-8")
        # between a wrap-open and its <table>, no heading/paragraph may appear
        for m in re.finditer(r'<div class="table-wrap">(.*?)<table', text, re.S):
            inner = m.group(1)
            assert not re.search(r"<h[1-4]|<p[ >]", inner), f"{tpl.name}: heading/paragraph inside table-wrap"
```

Append to `tests/test_static_site.py`:

```python
def test_export_emits_no_empty_table_wrap(tmp_path):
    render_static_site([], tmp_path / "_site", datetime(2026, 7, 8, tzinfo=UTC))
    for page in (tmp_path / "_site").glob("*.html"):
        text = page.read_text(encoding="utf-8")
        assert '<div class="table-wrap"></div>' not in text.replace("\n", "").replace(" ", ""), page.name
```

(The empty-div check normalizes whitespace; adjust the normalization so it catches `<div class="table-wrap">\n    </div>` too — e.g. regex `r'<div class="table-wrap">\s*</div>'`.)

- [ ] **Step 2: Run to verify failure** — the hygiene test names the 4 offending templates.

- [ ] **Step 3: Fix the 4 sites.** In each: move the heading (and `_project_detail`'s `on_prem_fit` paragraph) ABOVE the `<div class="table-wrap">`, and move any `{% if %}` that guards the WHOLE block outside the div so no empty div renders when false. trending.html + static_trending.html stay byte-identical per block.

- [ ] **Step 4: Run tests** — hygiene + static + web suites → PASS.

- [ ] **Step 5: Lint + commit**

```bash
git add src/radar/web/templates/ tests/test_base_styles.py tests/test_static_site.py
git commit -m "fix: headings and guards moved outside table-wrap divs"
```

---

### Task 3: keyboard-operable sortable headers

**Files:**
- Modify: `models.html`, `static_models.html`, `techniques.html`, `static_techniques.html` (markup), `_models_sort_script.html`, `_techniques_sort_script.html` (keydown wiring)
- Test: `tests/test_web.py` (append)

**Interfaces:** none new.

- [ ] **Step 1: Write the failing test**

```python
def test_sortable_headers_keyboard_operable(tmp_path):
    client = TestClient(create_app(tmp_path))
    for path in ("/models", "/research"):
        text = client.get(path).text
        # every sortable header is focusable + announced as a button
        assert text.count('tabindex="0"') >= 1
        assert text.count('data-key') - text.count('th[data-key]') == \
               text.count('role="button"') or 'role="button"' in text
        assert "keydown" in text                    # the JS wiring shipped
```

(Tighten the count assertion to the real header counts once read: models has 9 sortable th, techniques 6 — assert `text.count('role="button"') == 9` on /models and `== 6` on /research, matching `aria-sort="none"` counts.)

- [ ] **Step 2: Run to verify failure.**

- [ ] **Step 3: Implement.** Markup: every sortable `<th … data-key=…>` in the 4 templates gains `tabindex="0" role="button"` (twins identical). Scripts: at the bottom of each sort script's `<script>` block, add the wiring loop (models version shown; techniques mirrors with its table id + function):

```js
  document.querySelectorAll('#models-table th[data-key]').forEach(function (h) {
    h.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); modelsSort(h); }
    });
  });
```

- [ ] **Step 4: Run tests** — web + static suites → PASS.

- [ ] **Step 5: Lint + commit**

```bash
git add src/radar/web/templates/ tests/test_web.py
git commit -m "feat: sortable headers operable by keyboard"
```

---

### Task 4: `RunStore.latest_run_of_kind` dedup

**Files:**
- Modify: `src/radar/storage/run_store.py`, `src/radar/cli.py` (2 sites), `src/radar/web/scan_health.py`, `src/radar/mcp_server/model_queries.py`, `src/radar/mcp_server/technique_queries.py`
- Test: the RunStore test file (`grep -rl "RunStore" tests/ | head`) — append unit tests

**Interfaces:**
- Produces: `RunStore.latest_run_of_kind(kind: str | None) -> str | None` — walks `reversed(self.list_runs())`; `kind` a string → first run whose meta `.get("kind") == kind`; `kind is None` → first run whose meta has NO `"kind"` key (the main tool scan); no match → `None`.

- [ ] **Step 1: Write the failing unit tests** (mirror the RunStore test file's fixtures):

```python
def test_latest_run_of_kind_matches_latest(tmp_path):
    store = RunStore(tmp_path)
    a = store.create_run(); store.update_meta(a, {"kind": "models"})
    b = store.create_run(); store.update_meta(b, {"kind": "models"})
    c = store.create_run(); store.update_meta(c, {"kind": "research"})
    assert store.latest_run_of_kind("models") == b       # latest models, not a; not c
    assert store.latest_run_of_kind("research") == c
    assert store.latest_run_of_kind("trending") is None


def test_latest_run_of_kind_none_means_kindless(tmp_path):
    store = RunStore(tmp_path)
    tool = store.create_run()                            # main scan: no kind key
    m = store.create_run(); store.update_meta(m, {"kind": "models"})
    assert store.latest_run_of_kind(None) == tool


def test_latest_run_of_kind_empty_store(tmp_path):
    assert RunStore(tmp_path).latest_run_of_kind("models") is None
```

(Adapt `create_run`/meta plumbing to the real fixtures — run ids may need to be distinct/ordered; check how `list_runs` orders them.)

- [ ] **Step 2: Run to verify failure** — AttributeError.

- [ ] **Step 3: Implement** in `run_store.py` (after `read_meta`):

```python
    def latest_run_of_kind(self, kind: str | None) -> str | None:
        """Newest run id whose meta ``kind`` matches; ``None`` kind = runs without one."""
        for run_id in reversed(self.list_runs()):
            meta = self.read_meta(run_id)
            if (kind is None and "kind" not in meta) or meta.get("kind") == kind:
                return run_id
        return None
```

CAREFUL: that condition mis-matches when `kind is None` and meta HAS a kind of None-value — write it explicitly:

```python
    def latest_run_of_kind(self, kind: str | None) -> str | None:
        """Newest run id whose meta ``kind`` matches; ``None`` = runs without a kind key."""
        for run_id in reversed(self.list_runs()):
            meta = self.read_meta(run_id)
            if kind is None:
                if "kind" not in meta:
                    return run_id
            elif meta.get("kind") == kind:
                return run_id
        return None
```

- [ ] **Step 4: Convert the five walk sites** (each keeps its own guards/stage reads; behavior identical):
- `cli.py:522` → `model_run = run_store.latest_run_of_kind("models")`
- `cli.py:1555` → `latest = run_store.latest_run_of_kind("research")`; if not None, `meta = run_store.read_meta(latest)` for the stamp (keep the surrounding try/except and the `latest_run_id = "none"` default exactly).
- `scan_health.py:94` → `run_id = run_store.latest_run_of_kind(None)`; `return run_store.read_meta(run_id) if run_id else {}`.
- `model_queries.py:27` → `rid = run_store.latest_run_of_kind("models")`; keep the `_run_dir`/exists/json reads.
- `technique_queries.py:25` → same with `"research"` + `technique_cards.json`.
- `orchestrator.py:452`: LEAVE (different pattern — last-N slice).

- [ ] **Step 5: Run tests** — the RunStore file + `uv run pytest -q` FULL suite (the gateways' existing tests pin degradation behavior) → green.

- [ ] **Step 6: Lint + commit**

```bash
uv run ruff check src/radar tests/ && uv run mypy src/radar
git add src/radar/storage/run_store.py src/radar/cli.py src/radar/web/scan_health.py \
  src/radar/mcp_server/model_queries.py src/radar/mcp_server/technique_queries.py tests/
git commit -m "refactor: latest_run_of_kind helper replaces five run-walk loops"
```

---

### Task 5: MoE seed verification + won't-fix comment + docs + gates

**Files:**
- Modify: `config/model-seed.yaml` (comments and/or corrected values), `src/radar/discovery/model_promotion.py` (one comment), `CHANGELOG.md`, `README.md`
- Test: existing seed/fit suites pin the outcome.

- [ ] **Step 1: Gather evidence.** For each of the 3 repos (`nvidia/Qwen3.6-35B-A3B-NVFP4`, `nvidia/Gemma-4-26B-A4B-NVFP4`, `nvidia/Qwen3.6-27B-NVFP4`): `curl -s https://huggingface.co/api/models/<repo>` and read `safetensors.parameters` / `safetensors.total`; ALSO search for the base (unquantized) repos (`https://huggingface.co/api/models?search=Qwen3.6-35B-A3B` etc.) and fetch their totals. Record every number in your report. (Set a UA header if 429s occur; if the API is unreachable, mark unverified and go to the annotate path.)

- [ ] **Step 2: Decide per seed, with evidence.**
- Base repo total found AND materially different from the seed value AND the NVFP4 number is a packing artifact → correct `params_total` to the base total (memory math wants REAL parameter count, not packed).
- NVFP4 total ≈ seed value and no contradicting base evidence → keep, annotate: `# params_total = NVFP4 checkpoint total per HF API (verified 2026-07-08); nominal <N>B`.
- Unreachable/inconclusive → keep, annotate: `# params_total unverified vs base model (HF API unavailable 2026-07-08)`.

- [ ] **Step 3: Won't-fix comment.** Above `_MOE_TOKEN` in `model_promotion.py`:

```python
# Deliberately does NOT match A<N>B active-param suffixes (e.g. "…-A3B"): the guard
# fails toward less data, and treating the active count as nominal would keep
# mis-scraped totals — the worse failure. See 2026-07-08 deferred-cleanup spec.
```

- [ ] **Step 4: Docs.** CHANGELOG Unreleased: one entry for the pass (sources on the design system; table-wrap hygiene; keyboard sorting; latest_run_of_kind dedup; MoE seeds verified/annotated; A3B bypass documented). README badge to the exact full-gate count.

- [ ] **Step 5: Full gates** — `uv run pytest && uv run ruff check . && uv run mypy src/radar` green; seed loads (`uv run pytest -k seed -q`); if values changed, fit tests still pass.

- [ ] **Step 6: Commit**

```bash
git add config/model-seed.yaml src/radar/discovery/model_promotion.py CHANGELOG.md README.md
git commit -m "chore: verify MoE seed params against HF; document A3B guard intent; docs"
```

---

## Self-Review Notes (already applied)

- Spec coverage: item 1→T1 (incl. CHANGELOG restore), 2→T2, 3→T3, 4→T4 (with the `kind: str | None` refinement + orchestrator exclusion), 5→T5 (evidence rules verbatim); won't-fix comment→T5; clock nit + `{% if url %}` guard documented in the spec only (no code task, per spec).
- T4's helper condition written explicitly (the compact boolean had a None-value-kind bug — called out and corrected in the plan itself).
- Guarded behavior: every converted site keeps its own try/except + defaults; the helper never raises on missing meta (read_meta's own behavior — verify it returns {} or raises and mirror the walk's current handling; if read_meta can raise on a corrupt meta, the helper inherits the caller's existing guards, same as the inline walks did).
- Twins: T2 (trending pair) + T3 (models/techniques pairs) restate the rule.
- No new deps; sources conversion is live-only (no static twin created).
