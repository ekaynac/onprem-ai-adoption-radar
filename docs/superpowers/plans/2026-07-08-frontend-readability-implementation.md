# Frontend Readability Pass Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all 18 frontend-readability audit findings — WCAG contrast (hero + dark-mode status colors), responsive tables, signal badges, legend/nav consistency, and compare.html design parity.

**Architecture:** One shared-stylesheet task establishes tokens + rules; four template tasks consume them (tables, badges, nav/legend, compare parity); one closing task adds sort a11y + docs. All pure template/CSS — no Python logic changes, no new failure surface.

**Tech Stack:** Jinja2 templates, inlined CSS (`_base_styles.html`), pytest render tests. **No new dependencies.**

**Spec:** `docs/superpowers/specs/2026-07-08-frontend-readability-design.md`. Evidence: `.superpowers/sdd/fe-findings.md` (finding #s below).

## Global Constraints

- Live/static template twins stay byte-identical per block (established rule). Shared partials (`_model_detail.html`, `_technique_detail.html`, `_hero.html`, `_legend.html`) are included by BOTH surfaces — one edit covers both; verify with grep before assuming.
- `--hero-bg: #005F85` both themes; `#009FDA` (`--blue`) itself unchanged. `--watch: #8C6200` / `--avoid: #B93025` light; `--watch: #D9A519` / `--avoid: #E5534B` dark.
- **No new hues:** positive badges (`.fit-yes`, `.risk-low`) reuse the `.ring-adopt` blue trio; caution reuses the `.ring-watch` colors (via `--watch`); negative reuses `.ring-avoid` (via `--avoid`). (Plan-time refinement of the spec's "green" parenthetical — the site's positive semantic is adopt-blue; staying in the brand palette.)
- **Canonical nav (plan-time refinement):** the hero brand lockup does NOT link home, so the nav gains a leading "Radar" item — 7 labels, identical per surface:
  - Live: `{"Radar": "/", "Models": "/models", "Research": "/research", "Trending": "/trending", "Compare": "/compare", "History": "/history", "Sources": "/sources"}`
  - Static: `{"Radar": "index.html", "Models": "models.html", "Research": "techniques.html", "Trending": "trending.html", "Compare": "compare.html", "History": "history.html", "Changes feed": "changes.xml"}` (no static sources page exists; "Changes feed" is static's 7th, as static_index already has)
  - `digests/` subdir pages are OUT of scope (relative-path complexity, not in the audit).
- Daily-publish invariant untouched (templates only; export must stay green).
- ruff line-length 100 (E501 ignored); coverage ≥ 80%; gates `uv run pytest`, `uv run ruff check .`, `uv run mypy src/radar`.
- Commit `<type>: <description>`; `git add` specific paths only (`data/history.jsonl` never committed).

## Verified anchors (all in `src/radar/web/templates/`)

- `_base_styles.html`: `:root` vars at ~line 26 (`--blue: #009FDA; --blue-dark: #0082B3; --blue-darker: #005F85; ... --muted: #6B7280`), dark block ~line 35; `.hero` line 56-58 (`background: var(--blue)`); `.tagline` line 72 (`rgba(255,255,255,0.82)`), `.generated` line 74 (`0.7`); `th` line 101 (`font-size: 0.72rem`); ring pills lines 113-116 (`.ring-watch`/`.ring-avoid` hardcode `#8C6200`/`#B93025`); `.stat-watch .num`/`.stat-avoid .num` lines 92-93, `.stat-avoid::before` line 87 hardcode them too (grep `#8C6200\|#B93025` for the full list incl. `.scan-health summary`, `.pinned-note`). NOTE: `.stat .num` / `.stat-watch .num` exist — the NEW `.num` table class must not collide: scope it as `td.num, th.num`.
- Nav: each page template sets `{% set nav = {...} %}` consumed by `_hero.html`'s `hero-nav` loop. Current dicts are inconsistent subsets (models.html has 3, static_history has "Changes feed", detail pages 2).
- `_model_detail.html:20`: `<td>{{ r.verdict }}</td>` (raw enum); shared by `model.html` + `static_model.html`.
- `index.html` line ~47-48: trend arrow `<td title="{{ card.trend }}">…↑↓→…</td>` and risk `<td>{{ card.risk_level }}</td>`; twin `static_index.html`.
- `techniques.html` line ~37: `<td>{{ t.ring.value if t.ring else '-' }}</td>`; `models.html` line ~43 has the ring-pill pattern to copy; twins `static_techniques.html`/`static_models.html`.
- `trending.html` + `static_trending.html`: 4 tables each, each with a blank `<th></th>` status column.
- `_legend.html`: three `<h4>` columns (Rings / Backed by / Trend); included only by `index.html` + `static_index.html`.
- `static_compare.html`: bespoke `<style>` at line 7 (`body { font-family: system-ui … color: #1f2937 … }`), no `_base_styles`/`_hero`/`_footer`; `static_history.html` is the proven conversion example.
- Sort scripts `_models_sort_script.html`/`_techniques_sort_script.html`: zero `aria-sort` today.
- Table sites (26): index 1, models 1, techniques 1, trending 4, history 1, compare 1, `_model_detail` 2, `_technique_detail` 1, `_project_detail` 4, static_index 2, static_models 1, static_techniques 1, static_trending 4, static_history 1, static_compare 1.

## File Structure

```
src/radar/web/templates/_base_styles.html      # T1: all tokens + rules + badge classes
src/radar/web/templates/{index,models,techniques,trending,history,compare}.html + static twins,
  _model_detail.html _technique_detail.html _project_detail.html   # T2 wraps/num/units, T3 badges
src/radar/web/templates/{all page templates}   # T4: canonical nav; _legend.html + catalog includes
src/radar/web/templates/static_compare.html    # T5: design-system conversion
src/radar/web/templates/_models_sort_script.html _techniques_sort_script.html  # T6: aria-sort
tests/test_base_styles.py                       # NEW (T1): string pins on the stylesheet
tests/test_web.py tests/test_static_site.py     # T2-T5: render tests
README.md CHANGELOG.md                          # T6
```

---

### Task 1: Shared stylesheet — tokens, rules, badge classes (findings #1 #2 #9 #10 #13 #14 #16 + classes for #3 #5 #7 #11)

**Files:**
- Modify: `src/radar/web/templates/_base_styles.html`
- Test: Create `tests/test_base_styles.py`

**Interfaces:**
- Produces (consumed by T2-T5): CSS classes `.table-wrap`, `td.num/th.num`, `.trend-up/.trend-down/.trend-flat`, `.risk-low/.risk-medium/.risk-high`, `.fit-yes/.fit-tight/.fit-no`, `.warning`; tokens `--hero-bg`, `--watch`, `--avoid` (with dark overrides).

- [ ] **Step 1: Write the failing string-pin tests**

```python
"""Pins on the shared stylesheet (_base_styles.html) — readability pass."""

from __future__ import annotations

import re
from pathlib import Path

STYLES = Path("src/radar/web/templates/_base_styles.html").read_text(encoding="utf-8")


def test_hero_uses_dedicated_dark_brand_shade():
    assert "--hero-bg: #005F85" in STYLES
    assert re.search(r"\.hero \{[^}]*background: var\(--hero-bg\)", STYLES)


def test_watch_avoid_tokens_with_dark_overrides():
    assert STYLES.count("--watch:") == 2 and STYLES.count("--avoid:") == 2  # :root + dark
    assert "--watch: #D9A519" in STYLES and "--avoid: #E5534B" in STYLES    # dark values


def test_no_hardcoded_status_hex_outside_token_definitions():
    # every former #8C6200/#B93025 usage now goes through var(--watch)/var(--avoid)
    body = STYLES.split("@media", 1)[0] + STYLES.split("}", 1)[-1]
    for hexcode in ("#8C6200", "#B93025"):
        uses = [ln for ln in STYLES.splitlines() if hexcode in ln and "--watch" not in ln
                and "--avoid" not in ln]
        assert uses == [], f"{hexcode} still hardcoded: {uses}"


def test_new_rules_present():
    assert re.search(r"(^|\s)h3 \{", STYLES)                      # heading tier (#10)
    assert "main p { max-width: 70ch" in STYLES                    # measure (#13)
    assert ".table-wrap { overflow-x: auto" in STYLES              # responsive (#3)
    assert re.search(r"td\.num, th\.num \{[^}]*tabular-nums", STYLES)  # numeric (#9)
    assert ".warning { color: var(--avoid)" in STYLES              # (#14)
    assert "font-size: 0.75rem" in STYLES and "font-size: 0.72rem" not in STYLES  # th (#16)


def test_signal_badge_classes_present():
    for cls in (".trend-up", ".trend-down", ".trend-flat",
                ".risk-low", ".risk-medium", ".risk-high",
                ".fit-yes", ".fit-tight", ".fit-no"):
        assert cls in STYLES, f"missing {cls}"


def test_tagline_and_generated_contrast_raised():
    assert "rgba(255,255,255,0.82)" not in STYLES and "rgba(255,255,255,0.7)" not in STYLES
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_base_styles.py -v` → FAILs.

- [ ] **Step 3: Implement in `_base_styles.html`:**

1. `:root`: add `--hero-bg: #005F85; --watch: #8C6200; --avoid: #B93025;` — dark block: add `--hero-bg: #005F85; --watch: #D9A519; --avoid: #E5534B;`.
2. `.hero`: `background: var(--hero-bg);`. `.tagline` → `rgba(255,255,255,0.95)`; `.generated` → `rgba(255,255,255,0.9)`.
3. Replace every hardcoded `#8C6200` → `var(--watch)` and `#B93025` → `var(--avoid)` (grep both; includes `.stat-watch .num`, `.stat-avoid .num`, `.stat-avoid::before`, `.ring-watch`, `.ring-avoid`, `.scan-health summary`, `.pinned-note`, and any others found).
4. `th` `font-size: 0.72rem` → `0.75rem`.
5. Append the new rules (near the table styles):

```css
  h3 { margin: 1.5rem 0 0.4rem; font-size: 1.05rem; font-weight: 700; letter-spacing: -0.01em; }
  main p { max-width: 70ch; }
  .warning { color: var(--avoid); font-weight: 600; }
  .table-wrap { overflow-x: auto; }
  td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
  .trend-up { color: var(--blue-dark); font-weight: 700; }
  .trend-down { color: var(--avoid); font-weight: 700; }
  .trend-flat { color: var(--muted); }
  .risk-low { background: rgba(0,159,218,0.12); color: var(--blue-dark); border-color: rgba(0,159,218,0.35); }
  .risk-medium { background: rgba(200,145,0,0.12); color: var(--watch); border-color: rgba(200,145,0,0.35); }
  .risk-high { background: rgba(185,48,37,0.10); color: var(--avoid); border-color: rgba(185,48,37,0.30); }
  .fit-yes { background: rgba(0,159,218,0.12); color: var(--blue-dark); border-color: rgba(0,159,218,0.35); }
  .fit-tight { background: rgba(200,145,0,0.12); color: var(--watch); border-color: rgba(200,145,0,0.35); }
  .fit-no { background: rgba(185,48,37,0.10); color: var(--avoid); border-color: rgba(185,48,37,0.30); }
```

`.risk-*`/`.fit-*` are pill-shaped: check how `.ring-pill` gets its shape (padding/border-radius/border) — if shape lives on `.ring-pill` itself, T3's markup will use `class="ring-pill risk-low"` etc.; confirm and note in the report which composition you chose (the classes above supply only colors, matching the `.ring-*` pattern).

- [ ] **Step 4: Run tests** — `uv run pytest tests/test_base_styles.py tests/test_web.py tests/test_static_site.py -q` → PASS (no template consumes the new classes yet; existing renders unaffected).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check tests/test_base_styles.py && uv run mypy src/radar
git add src/radar/web/templates/_base_styles.html tests/test_base_styles.py
git commit -m "feat: readability tokens + rules in shared stylesheet (hero, dark status, tables)"
```

---

### Task 2: Responsive table wrap + numeric alignment + unit headers (findings #3 #9 #18)

**Files:**
- Modify (all in `src/radar/web/templates/`): `index.html`, `models.html`, `techniques.html`, `trending.html`, `history.html`, `compare.html`, `_model_detail.html`, `_technique_detail.html`, `_project_detail.html`, `static_index.html`, `static_models.html`, `static_techniques.html`, `static_trending.html`, `static_history.html` (static_compare is T5)
- Test: `tests/test_web.py`, `tests/test_static_site.py` (append)

**Interfaces:**
- Consumes: `.table-wrap`, `td.num/th.num` (T1).
- Produces: every `<table>` in the listed templates wrapped in `<div class="table-wrap">…</div>`; numeric columns in models/techniques/trending (+ twins) carry `class="num"` on `<th>` and `<td>`; numeric headers name units.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_web.py` (adapt fixtures from the existing catalog-page tests):

```python
def test_catalog_tables_are_scroll_wrapped(tmp_path):
    client = TestClient(create_app(tmp_path))
    for path in ("/", "/models", "/research", "/trending"):
        r = client.get(path)
        assert r.status_code == 200
        assert ('<table' not in r.text) or ('<div class="table-wrap">' in r.text), path
```

Append to `tests/test_static_site.py`:

```python
def test_static_tables_are_scroll_wrapped(tmp_path):
    render_static_site([], tmp_path / "_site", datetime(2026, 7, 8, tzinfo=UTC))
    for page in (tmp_path / "_site").glob("*.html"):
        text = page.read_text(encoding="utf-8")
        if "<table" in text and page.name != "compare.html":   # compare converts in T5
            assert '<div class="table-wrap">' in text, page.name
```

(If existing fixtures render pages without tables, the guard `'<table' not in text` keeps them green. Add one assertion that models.html output contains `class="num"` and a unit header, e.g. `"Min mem (GB)"` — read the current header names first and pick real ones.)

- [ ] **Step 2: Run to verify failure** — wrapped-div assertions fail.

- [ ] **Step 3: Implement.** In each listed template, wrap each `<table>…</table>` with `<div class="table-wrap">` / `</div>` (26 sites minus static_compare; keep indentation consistent). In `models.html`/`static_models.html`, `techniques.html`/`static_techniques.html`, `trending.html`/`static_trending.html`: add `class="num"` to numeric `<th>` + `<td>` (models: Params, Context, Min mem; techniques: Impls, Citations; trending: Stars, Velocity, Downloads/Upvotes columns, Citations). Unit headers (#18): `Context` → `Context (tokens)`, `Min mem` → `Min mem (GB)`, `Velocity/day` → `Velocity (stars/day)` where currently unlabeled — check each header's current text and only add units where missing/ambiguous. Twins byte-identical per block.

- [ ] **Step 4: Run tests** — `uv run pytest tests/test_web.py tests/test_static_site.py -q` → PASS.

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check tests/ && uv run mypy src/radar
git add src/radar/web/templates/ tests/test_web.py tests/test_static_site.py
git commit -m "feat: responsive table wrappers + numeric alignment + unit headers"
```

---

### Task 3: Signal badges (findings #4 #5 #7 #11 #12)

**Files:**
- Modify: `techniques.html` + `static_techniques.html` (ring-pill), `_model_detail.html` (fit verdict — shared partial), `index.html` + `static_index.html` (trend spans + risk badge), `trending.html` + `static_trending.html` (Status headers), `_legend.html` (Risk column)
- Test: `tests/test_web.py`, `tests/test_static_site.py` (append)

**Interfaces:**
- Consumes: `.trend-*`, `.risk-*`, `.fit-*` (T1); the existing `ring-pill ring-{value}` pattern from `models.html`.
- Produces: no raw `wont_fit`/`fits_tight` text anywhere; ring pills on the techniques catalog; colored trend spans; risk badges + legend entry; `<th>Status</th>` ×4 per trending template.

- [ ] **Step 1: Write the failing tests** (append; adapt fixture plumbing from neighboring tests):

```python
def test_techniques_catalog_renders_ring_pill(tmp_path):
    # seed a research run with one ringed technique (reuse _seed_techniques_run)
    r = TestClient(create_app(tmp_path)).get("/research")
    assert 'class="ring-pill ring-' in r.text


def test_model_fit_verdict_humanized(tmp_path):
    # seed a model whose fit table contains a wont_fit row (reuse the model-detail fixture)
    r = TestClient(create_app(tmp_path)).get("/model/<seeded-id>")
    assert "wont_fit" not in r.text and "fits_tight" not in r.text
    assert "Won't fit" in r.text or "Fits" in r.text


def test_index_trend_and_risk_badges(tmp_path):
    r = TestClient(create_app(tmp_path)).get("/")
    assert 'class="trend-' in r.text          # ↑/→/↓ wrapped
    assert 'risk-' in r.text                   # risk badge class


def test_trending_status_headers(tmp_path):
    r = TestClient(create_app(tmp_path)).get("/trending")
    assert r.text.count("<th>Status</th>") >= 4
    assert "<th></th>" not in r.text
```

(+ static-twin equivalents in test_static_site.py where fixtures exist; the contracts are the asserts.)

- [ ] **Step 2: Run to verify failure.**

- [ ] **Step 3: Implement:**

- `techniques.html` + `static_techniques.html` ring cell → `<td>{% if t.ring %}<span class="ring-pill ring-{{ t.ring.value }}">{{ t.ring.value }}</span>{% else %}-{% endif %}</td>` (byte-copy of models.html's pattern).
- `_model_detail.html:20` verdict cell →

```html
<td>{% if r.verdict == "fits" %}<span class="ring-pill fit-yes">Fits</span>{% elif r.verdict == "fits_tight" %}<span class="ring-pill fit-tight">Fits (tight)</span>{% else %}<span class="ring-pill fit-no">Won't fit</span>{% endif %}</td>
```

(Verify the actual verdict values first — grep the fit-report builder for the enum values; adjust the elif chain to the real set.)
- `index.html` + `static_index.html` trend cell → `<td title="{{ card.trend }}">{% if card.trend == 'rising' %}<span class="trend-up">↑</span>{% elif card.trend == 'falling' %}<span class="trend-down">↓</span>{% else %}<span class="trend-flat">→</span>{% endif %}</td>`; risk cell → `<td><span class="ring-pill risk-{{ card.risk_level }}">{{ card.risk_level }}</span></td>`.
- `trending.html` + `static_trending.html`: all four blank `<th></th>` → `<th>Status</th>`.
- `_legend.html`: add a fourth column mirroring the existing `<h4>` blocks: `<h4>Risk</h4>` with low/medium/high pills using `.ring-pill risk-*`.

- [ ] **Step 4: Run tests** — the web + static suites → PASS.

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check tests/ && uv run mypy src/radar
git add src/radar/web/templates/ tests/test_web.py tests/test_static_site.py
git commit -m "feat: signal badges — ring pills, humanized fit verdicts, trend/risk, Status headers"
```

---

### Task 4: Canonical nav + legend on catalogs (findings #6 #8 #15)

**Files:**
- Modify (nav dicts): live `index.html`, `models.html`, `techniques.html`, `trending.html`, `history.html`, `compare.html`, `model.html`, `technique.html`, `project.html`; static `static_index.html`, `static_models.html`, `static_techniques.html`, `static_trending.html`, `static_history.html`, `static_model.html`, `static_technique.html`, `static_project.html` (static_compare in T5; `digest.html` OUT of scope)
- Modify (legend): `models.html`, `techniques.html`, `static_models.html`, `static_techniques.html`
- Test: `tests/test_web.py`, `tests/test_static_site.py` (append)

**Interfaces:**
- Consumes: `_hero.html`'s `nav` dict contract; `_legend.html`.
- Produces: every listed live template sets the SAME live dict; every listed static template the SAME static dict (Global Constraints block has both verbatim). `project.html`/`static_project.html` currently use a `links.*` indirection — replace with the canonical dict (live absolute paths work from any URL; static project pages are root-level so root file hrefs work — VERIFY by checking where the export writes project pages before replacing, and keep `links.*` if any static page is NOT root-level).

- [ ] **Step 1: Write the failing tests**

```python
LIVE_NAV = ["Radar", "Models", "Research", "Trending", "Compare", "History", "Sources"]

def test_nav_identical_across_live_pages(tmp_path):
    client = TestClient(create_app(tmp_path))
    for path in ("/", "/models", "/research", "/trending", "/history"):
        r = client.get(path)
        for label in LIVE_NAV:
            assert f">{label}</a>" in r.text, f"{label} missing from {path}"


def test_legend_on_catalog_pages(tmp_path):
    client = TestClient(create_app(tmp_path))
    for path in ("/models", "/research"):
        assert "Rings" in client.get(path).text   # legend include marker
```

Static twin: assert the static nav labels (with "Changes feed" instead of "Sources") on models/techniques/trending/history pages, and legend markers on static_models/static_techniques output.

- [ ] **Step 2: Run to verify failure.**

- [ ] **Step 3: Implement.** Replace each `{% set nav = {...} %}` with the canonical dict for its surface (verbatim from Global Constraints). Add `{% include "_legend.html" %}` after the hero/summary section in the four catalog templates (mirror index.html's placement).

- [ ] **Step 4: Run tests** — web + static suites → PASS.

- [ ] **Step 5: Lint + commit**

```bash
git add src/radar/web/templates/ tests/test_web.py tests/test_static_site.py
git commit -m "feat: canonical 7-item nav on every page + legend on catalog pages"
```

---

### Task 5: static_compare design parity (finding #8b)

**Files:**
- Modify: `src/radar/web/templates/static_compare.html`
- Test: `tests/test_static_site.py` or the compare-page test file (`grep -rln "compare" tests/ | head`) — append

**Interfaces:**
- Consumes: `_base_styles.html`, `_hero.html`, `_footer.html` (as `static_history.html` composes them — read it as the conversion example), `.table-wrap` (T1), the static canonical nav (T4).

- [ ] **Step 1: Write the failing tests**

```python
def test_static_compare_uses_design_system(...):
    # render/export the compare page via its existing test fixture, then:
    assert 'class="hero"' in text            # shared hero present
    assert "--hero-bg" in text               # shared stylesheet inlined
    assert "#f9fafb" not in text             # bespoke light-only style gone
    assert '<div class="table-wrap">' in text
```

(Find how compare pages are currently rendered/tested — `grep -rn "static_compare" src/radar/` for the render entry point and reuse its test fixture; the asserts are the contract.)

- [ ] **Step 2: Run to verify failure.**

- [ ] **Step 3: Implement.** Rebuild `static_compare.html` on the `static_history.html` skeleton: `_base_styles` include, `_hero` with the static canonical nav + a compare-appropriate `page_title`/`tagline`, the existing comparison-matrix body wrapped in `.table-wrap`, `_footer` include. Delete the bespoke `<style>` block. Keep whatever context variables the render call already passes (check the renderer for available context — `asset_base`, `generated_at` etc. — and mirror static_history's usage).

- [ ] **Step 4: Run tests** — compare + static suites + a full `radar export` smoke (existing export tests) → PASS.

- [ ] **Step 5: Lint + commit**

```bash
git add src/radar/web/templates/static_compare.html tests/
git commit -m "feat: compare page adopts the shared design system"
```

---

### Task 6: aria-sort + docs + full gates (finding #17)

**Files:**
- Modify: `_models_sort_script.html`, `_techniques_sort_script.html`, `README.md`, `CHANGELOG.md`
- Test: `tests/test_web.py` (append a marker assertion)

- [ ] **Step 1: Read both sort scripts**, then add: initial `aria-sort="none"` on sortable `<th>` (set in the script's init pass if headers are enhanced by JS, else in the templates), and on each sort click set `aria-sort="ascending"|"descending"` on the active header and reset siblings to `"none"`. Add a test asserting `aria-sort` appears in the models/techniques page output.

- [ ] **Step 2: Docs.** CHANGELOG Unreleased→Fixed (or Changed): one entry — readability pass, all 18 findings (hero AA contrast via the brand's darker shade, dark-mode status tokens, responsive table wrappers, numeric alignment + units, ring/fit/trend/risk badges + Status headers, legend on catalogs, canonical nav, compare design parity, aria-sort). README: badge to the exact full-gate count.

- [ ] **Step 3: Full gates + visual QA.** `uv run pytest && uv run ruff check . && uv run mypy src/radar` green; run `uv run radar export --root . --out <scratch>` and eyeball trending/models/techniques/compare/model-detail pages for obvious breakage (report what you looked at).

- [ ] **Step 4: Commit**

```bash
git add src/radar/web/templates/_models_sort_script.html src/radar/web/templates/_techniques_sort_script.html \
  tests/test_web.py README.md CHANGELOG.md
git commit -m "feat: aria-sort on sortable headers; readability-pass docs"
```

---

## Self-Review Notes (already applied)

- All 18 findings mapped: #1 #2 #9 #10 #13 #14 #16→T1; #3 #9 #18→T2; #4 #5 #7 #11 #12→T3; #6 #8 #15→T4; #8b→T5; #17→T6.
- Two plan-time refinements flagged in Global Constraints: 7-label nav (lockup doesn't link home; static has no sources page) and adopt-blue instead of green for positive badges (no new hues).
- Collision guard: the new numeric class is scoped `td.num, th.num` because `.stat .num` already exists.
- T2 excludes static_compare (converted in T5); T4 excludes digest.html (subdir, unaudited).
- Twins rule restated per task; shared partials (_model_detail, _legend, _hero) edited once.
