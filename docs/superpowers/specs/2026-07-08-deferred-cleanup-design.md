# Deferred-Items Cleanup Pass — Design

Date: 2026-07-08
Status: approved (basket design confirmed; all items carry review-triaged fix
directions from the data-quality (36ffa44) and readability (e5547e5) final
reviews — see `.superpowers/sdd/progress.md` + `final-review-fixes.md`)

## Context

The two audit sub-projects deliberately deferred a set of small items rather
than let their branches creep. This pass closes every deferred item that is
actionable today, and documents the ones that are intentionally not fixed.
Verified starting facts: `sources.html` is the last bespoke page (143 lines,
own `<style>` at line 7, "← Dashboard" as its only nav at line 85, a table at
88 and a POST form at 117; NO static twin exists — correct, the export has no
sources page); six `reversed(run_store.list_runs())` walk sites exist
(cli.py:522, cli.py:1555, scan_health.py:94, model_queries.py:27,
technique_queries.py:25, plus orchestrator.py:452 which uses list_runs
differently); the 3 ambiguous MoE seeds are all `nvidia/*-NVFP4` repos
(hf-qwen3-6-35b-a3b-nvfp4 → 18683860336, hf-gemma-4-26b-a4b-nvfp4 →
14386941232, hf-qwen3-6-27b-nvfp4 → 18164649200).

## Work items (5)

### 1. `sources.html` design-system conversion

Convert the last bespoke page exactly like compare/history were (proven
skeleton: `static_history.html` / the converted `compare.html`):
`_base_styles` + `_hero` (canonical LIVE 7-item nav dict, verbatim as every
other live page) + `_footer`; bespoke `<style>` dropped; the table wrapped in
`.table-wrap`; the POST form adopts `.filter-bar` (the label/button rules
exist since the readability fix wave); its `class="error"` output is now
backed by the shared `.error` rule. Sensible `page_title`/`tagline` (e.g.
"Sources" / "Seed sources the radar scans — add or review"). Behavior (form
action/method/fields, the POST route) unchanged. Then RESTORE the CHANGELOG
sentence that was trimmed ("sources" now genuinely renders the canonical
nav — reword the readability entry's correction or add a line to this pass's
entry). Live-only; no static twin created.

### 2. Heading-inside-table-wrap normalization (4 sites)

`trending.html` + `static_trending.html` first table block, and
`_project_detail.html` ×2 ("Score breakdown", "On-prem rubric" + its
paragraph), `_model_detail.html` ×1 ("Runs on"): move headings (and the
`on_prem_fit` paragraph) and whole-table `{% if %}` guards OUTSIDE the
`.table-wrap` div so (a) headings don't scroll horizontally with an
overflowing table, (b) no empty `<div class="table-wrap"></div>` is emitted
when a guard is false. All other 22 sites already wrap tightly — end state:
a `.table-wrap` div contains exactly one `<table>` and nothing else. A test
pins that (no `<h2>`/`<h3>`/`<p>` between `<div class="table-wrap">` and
`<table>` in any template, and no empty wrap divs in a full export).

### 3. Keyboard-operable sortable headers

The sortable `<th>`s carry `aria-sort` but are mouse-only (`onclick`, no
keyboard path). In `models.html`/`static_models.html`/`techniques.html`/
`static_techniques.html` sortable headers: add `tabindex="0"` and
`role="button"`. In `_models_sort_script.html`/`_techniques_sort_script.html`:
add a shared `keydown` handler (Enter or Space → same sort function +
`preventDefault` for Space scrolling). Twins byte-identical per block. Test:
markup carries tabindex/role on exactly the sortable headers (count matches
the `data-key`/onclick count).

### 4. `latest_run_of_kind` dedup

Add ONE helper — `RunStore.latest_run_of_kind(kind: str) -> str | None`
(walks `reversed(self.list_runs())`, returns the first run_id whose meta
`kind` matches; `None` if none) — and convert the walk sites that match the
pattern: cli.py:522, cli.py:1555 (`_research_snapshot_status`),
scan_health.py:94, model_queries.py:27, technique_queries.py:25. Each caller
keeps its own stage/meta reads and its own guards (the guarded gateways'
try/except behavior must not change). orchestrator.py:452 is checked at plan
time and converted ONLY if it is genuinely the same pattern; otherwise left.
Pure refactor — existing tests pin behavior; add unit tests for the helper
(match, no-match, kind filtering, empty store).

### 5. MoE seed params verification (evidence, not guessing)

For the 3 seeds: query the HF API (the same endpoints `models scan` uses)
for each `nvidia/*-NVFP4` repo's reported parameter total, and for the base
model repos if discoverable (e.g. the unquantized `Qwen3.6-35B-A3B`).
Decide with evidence:
- If the scraped `params_total` is wrong (base repo shows the true total and
  the NVFP4 count is a packing artifact) → correct the seed values.
- If the values are legitimate quantized-checkpoint totals or evidence is
  inconclusive → leave values, add a YAML comment on each entry documenting
  the finding (e.g. `# NVFP4 checkpoint total per HF; nominal 35B-A3B`).
Never guess. The fit/memory math consequences of any correction are covered
by existing tests. Network best-effort: HF unreachable → annotate as
unverified, do not block the pass.

## Won't-fix (documented, deliberate)

- **`_MOE_TOKEN` A3B bypass**: gets a one-line code comment in
  `model_promotion.py` stating the `A<N>B` active-param suffix is
  deliberately not matched — the guard fails toward less data; teaching it
  A3B would keep mis-scraped active counts (the worse failure). No behavior
  change.
- **Export clock-read nit** (fresh `datetime.now(UTC)` vs `generated_at`):
  unobservable, won't fix.
- **Dead `{% if url %}` guard in project nav loops**: byte-copy of the
  `_hero`/`_footer` loop idiom; removing it would break copy-consistency.
  Won't fix.

## Blocked (untouched)

- Flag-to-implementation hit-rate (academic-radar design): needs months of
  accumulated implementation history; cannot be built yet.

## Non-goals

- No new pages, no static sources page, no redesign, no new dependencies.
- No change to guarded-gateway degradation behavior (item 4 is walk-extraction
  only; the try/except shells stay).
- No autopilot/scoring changes (item 5 touches seed data + comments only).

## Error handling

Items 1-3 are template/JS-only. Item 4 must preserve each gateway's existing
guarded behavior (helper failures surface exactly like the old inline walks).
Item 5 is an offline seed edit informed by a best-effort online check.
Daily-publish invariant untouched throughout.

## Testing (TDD; gates: pytest ≥80% + ruff + mypy)

- Sources: /sources renders hero + canonical 7 nav labels + `.filter-bar` +
  `.table-wrap`; POST behavior unchanged (existing route tests keep passing);
  no bespoke `<style>` remains.
- Wrap hygiene: no heading/paragraph inside any `.table-wrap` before its
  `<table>`; a full export emits no empty wrap divs.
- Keyboard sort: tabindex/role counts match sortable-header counts on all 4
  templates; the keydown handler is present in both scripts.
- `latest_run_of_kind`: unit tests (latest match wins, kind filter, None on
  empty/no-match); all existing run-reading tests keep passing.
- MoE: seed still validates; if values change, the models fit tests still
  pass; the YAML comments/corrections match the report's evidence.

## Scope

One implementation plan, ~5 tasks (one per work item; won't-fix comment folds
into item 5's commit or a docs task), branch `chore/deferred-cleanup`.
