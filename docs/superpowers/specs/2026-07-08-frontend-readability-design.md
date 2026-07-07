# Frontend Readability Pass (audit sub-project 2) — Design

Date: 2026-07-08
Status: approved (findings verified interactively; hero treatment decided; §1–§3 confirmed)

## Context

A frontend-readability review of the published static site (178 pages, styles
delivered as one shared inlined `<style>` block from
`src/radar/web/templates/_base_styles.html`) found 18 findings — 7 High, 6
Medium, 5 Low. Full evidence: `.superpowers/sdd/fe-findings.md` (finding
numbers below reference it). The user chose the comprehensive scope: all 18.
Sub-project 1 (data-quality fixes) already merged (36ffa44).

Decided in brainstorming:

- **Hero treatment (finding #1):** a new `--hero-bg: #005F85` token — the
  brand palette's own darker shade — backs the hero band in BOTH themes, so
  white text reaches ~6.5:1 (AA). The bright Mega brand blue `#009FDA` stays
  the accent color everywhere else (badges, links, stat cards). Not a new
  color; no change to `--blue` itself.

## Non-goals

- No redesign, no layout restructuring, no new pages, no JS beyond what
  exists. Small, high-leverage fixes only.
- No change to data/scoring (sub-project 1 handled data).
- No external CSS files (styles stay inlined per page); no new dependencies.
- The Mega brand kit stays out of the repo (existing rule).

## Section 1 — Shared stylesheet (`_base_styles.html`)

One file; propagates to every page that includes it.

**Tokens (in `:root` + the dark `@media` block):**
- `--hero-bg: #005F85` (same value both themes; dark enough for both).
  `.hero { background: var(--hero-bg); }`. Raise `.tagline` to
  `rgba(255,255,255,0.95)` and `.generated` to `rgba(255,255,255,0.9)` —
  on #005F85 both clear 4.5:1. (#1)
- `--watch: #8C6200` / `--avoid: #B93025` in `:root`; dark-mode overrides
  `--watch: #D9A519` / `--avoid: #E5534B`. Replace every hardcoded
  `#8C6200`/`#B93025` (and their rgba pill variants where applicable) in
  `.watch`, `.avoid`, `.stat-watch .num`, `.stat-avoid .num`,
  `.stat-avoid::before`, `.ring-watch`, `.ring-avoid`,
  `.scan-health summary`, `.pinned-note` with the variables. (#2)

**New rules:**
- `h3 { margin: 1.5rem 0 0.4rem; font-size: 1.05rem; font-weight: 700;
  letter-spacing: -0.01em; }` — the missing heading tier. (#10)
- `main p { max-width: 70ch; }` — measure-constrain prose. (#13)
- `th` font-size 0.72rem → 0.75rem. (#16)
- `.warning { color: var(--avoid); font-weight: 600; }` (#14)
- `.table-wrap { overflow-x: auto; }` — the site's first responsive
  affordance; consumed by Section 2. (#3)
- `.num { text-align: right; font-variant-numeric: tabular-nums; }` (#9)
- Signal classes consumed by Section 2: `.trend-up { color: var(--blue-dark) }`,
  `.trend-down { color: var(--avoid) }`, `.trend-flat { color: var(--muted) }`
  (#7); `.risk-low/-medium/-high` (reuse the ring-pill shape with
  green/`--watch`/`--avoid` hues) (#11); `.fit-yes/-tight/-no` (same ramp)
  (#5).

## Section 2 — Per-template markup

Live + static twins stay byte-identical per block (established rule).

- **Tables responsive:** wrap every `<table>` in `<div class="table-wrap">`
  across the templates (models, techniques, trending, index, compare,
  history, project/model/technique detail partials). (#3)
- **Numeric alignment:** `class="num"` on numeric `<td>`/`<th>` columns in
  models.html, techniques.html, trending.html (+ static twins). (#9)
- **Ring badge parity:** techniques.html renders Ring with the SAME
  `ring-pill ring-{value}` span models.html already uses. (#4)
- **Hardware-fit verdict:** `_model_detail.html`'s "Runs on" verdict cell
  becomes a humanized badge — `fits`→"Fits" (.fit-yes), `fits_tight`→"Fits
  (tight)" (.fit-tight), `wont_fit`→"Won't fit" (.fit-no). (#5)
- **Trend arrows:** index.html wraps ↑/→/↓ in
  `.trend-up/.trend-flat/.trend-down` spans; `title` tooltip kept. (#7)
- **Risk badge + legend:** index.html risk_level becomes a
  `.risk-{level}` badge; `_legend.html` gains a Risk column. (#11)
- **Status headers:** trending.html's four blank `<th></th>` flag columns
  become `<th>Status</th>` (+ static twin). (#12)
- **Legend on catalogs:** `{% include "_legend.html" %}` added to
  models.html, techniques.html + static twins (stays a collapsed
  `<details>` — presence resolves discoverability; finding #15 is thereby
  addressed). (#6, #15)
- **Nav unification:** one shared nav include (`_nav.html` or a shared
  Jinja mapping) with the SAME 6 items everywhere — Models, Research,
  Trending, Compare, History, Sources — replacing each template's
  hand-written subset; detail pages get the full nav too. (#8)
- **Units in headers:** numeric column headers name their unit where
  missing (e.g. "Context (tokens)", "Min mem (GB)", "Velocity (stars/day)").
  (#18)
- **Sortable a11y:** sortable `<th>` gain `aria-sort` (updated by the
  existing sort scripts) — check both `_models_sort_script.html` and
  `_techniques_sort_script.html`. (#17)

## Section 3 — compare.html design parity

`static_compare.html` currently bypasses the design system (own inline
light-only style, no hero/footer/branding, no dark mode). Convert it the way
`static_history.html` was converted: include `_base_styles.html` +
`_hero.html` + `_footer.html`, drop the bespoke style block, use the shared
table look (+ `.table-wrap` for its wide per-project matrices). (#8b)

## Error handling

Pure template/CSS changes — no new failure surface. The daily-publish
invariant is untouched; guarded gateways unchanged. Any Jinja error would be
caught by the render tests + full export test before merge.

## Testing (TDD; gates: pytest ≥80% + ruff + mypy)

Structural render tests (live + static where twins exist):
- `.table-wrap` wraps the catalog tables; `<th>Status</th>` present ×4 on
  trending; techniques catalog renders `ring-pill`; model detail renders
  "Won't fit"/"Fits" (no raw `wont_fit` text); index trend cell carries
  `.trend-up/.trend-down`; risk cell carries `.risk-*`; legend present on
  models + techniques; the SAME 6 nav links on index, models, techniques,
  trending, history, compare, and a detail page.
- String pins on `_base_styles.html` content: `--hero-bg` defined;
  `--watch`/`--avoid` defined incl. dark override; NO hardcoded
  `#8C6200`/`#B93025` outside the `:root` variable definitions; an `h3`
  rule exists; `.table-wrap` rule exists.
- compare.html export includes the hero + footer markers and no bespoke
  `<style>` with hardcoded `#f9fafb`.
- Full `radar export` runs green (existing back-compat tests).
- Post-merge: live smoke (hero color, a wrapped table, nav set).

## Scope

One implementation plan, ~6 tasks on branch `fix/frontend-readability`:
base styles (tokens + rules) → tables (wrap + num + units) → signal badges
(ring/fit/trend/risk/status) → legend + nav unification → compare.html
parity → low-polish (aria-sort) + docs + gates. All 18 findings covered
(#15 via #6). Visual QA: export + eyeball + live smoke after merge.
