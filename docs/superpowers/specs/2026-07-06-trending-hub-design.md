# Trending Hub (Models + Techniques parity) — Design

Date: 2026-07-06
Status: approved (interactive brainstorm; §1–§3 confirmed section-by-section)

## Context

The repo trending radar shipped a `/trending` page, a source autopilot, MCP
`list_trending`, and a weekly digest. Models and techniques have discovery
pipelines and rich momentum data, but **no equivalent "what's rising + what's
new" frontend surface** — their newness is visible only as ring-change events
on `/history` and in the weekly digest. This closes that asymmetry.

Decided in brainstorming:

1. **Two phases.** Phase 1 (this spec): a momentum-within-catalog surface for
   models and techniques from data that already exists. Phase 2 (separate
   future spec): untracked-candidate discovery (trending HF models + hot
   papers not yet cataloged), which needs new observation-store infra like the
   repo trending engine. **This spec is Phase 1 only.**
2. **Form: a unified `/trending` hub.** Extend the existing `/trending` page
   into a "what's hot across the whole radar" hub — the current repo lanes,
   plus a Models section and a Techniques section.
3. **Model velocity must be made durable.** Technique citation-velocity is
   already durable on the live site (`technique-metrics.jsonl` is committed),
   but model download-velocity is not (model metrics live only in the
   un-persisted `radar.db`). Phase 1 adds a committed `data/model-metrics.jsonl`
   — a mirror of the existing `technique_metrics_log.py` pattern — so "rising
   models by downloads" actually works in production.

## Non-goals (Phase 1)

- No untracked-candidate discovery for models/techniques (that is Phase 2).
- No new detail pages — rows link to the existing `/model/{id}` and
  `/technique/{id}`.
- No network in the render path; no LLM; no new Python dependencies.
- No duplication of the full catalogs — the hub shows a focused rising ∪
  new-this-week cut; `/models` and `/research` remain the full listings.

## Architecture

`/trending` becomes a hub with three sections, top to bottom:

1. **Repos** — the existing two lanes (On-prem radar candidates / Elsewhere in
   AI), unchanged.
2. **Trending Models** — the tracked models rising fastest by download growth,
   unioned with models added/promoted this ISO week.
3. **Trending Techniques** — the tracked techniques rising fastest by citation
   momentum, unioned with techniques new/promoted this ISO week.

A new pure builder module derives each section; guarded loaders keep any
corrupt/absent store from breaking the page or the daily export (the invariant
carried from the repo trending sub-projects).

### Model metrics durability (the enabling change)

`radar models scan` currently persists model metrics only into `radar.db`,
which CI does not carry between runs, so download-velocity always reads "first
scan" on the published site. Phase 1 adds:

- `src/radar/storage/model_metrics_log.py` — `append_model_metrics(path, rows)`
  / `load_model_metrics(path)` over `data/model-metrics.jsonl`, a direct mirror
  of `src/radar/storage/technique_metrics_log.py` (append-only JSONL, missing
  file → `[]`, corrupt lines skipped with a warning, guarded file read).
- `radar models scan` appends each run's `ModelMetrics` rows to the log.
- `publish.yml` commits `data/model-metrics.jsonl` in the history-commit block
  (`git add -f`), like its siblings.

Model momentum for the hub is then computed from the committed log (grouping
rows by model id) via the existing `compute_model_momentum` — the same
function `model_movers` uses — so the live site gets real rising/falling
direction + `downloads_growth_pct`.

## Components

### `src/radar/web/hub_sections.py` (pure)

- `HubRow` (frozen): `id`, `name`, `subtitle` (family for models | domain for
  techniques), `metric` (downloads | citations, `int | None`), `growth`
  (`float | None` — the download-growth % for models; `None` for techniques,
  which rank by the momentum score), `momentum` (`int | None` — the technique
  1–5 momentum score; `None` for models, which use `growth`), `direction`
  (`rising` | `falling` | `steady`), `ring` (`str | None`), `is_new` (bool),
  `href` (`/model/{id}` or `/technique/{id}`). Each type populates the field
  natural to it; the template shows whichever is present.
- `build_model_section(entries, model_metrics, model_events, now, *, top_n=10)
  -> list[HubRow]` — compute momentum per model from `model_metrics` (grouped
  by id) + `model_events`; take the top `top_n` rising by
  `downloads_growth_pct`, then append any model whose `model_events` show a
  `new`/`promoted` change within the ISO week of `now` and isn't already
  included (marked `is_new`). Rows sorted rising-first, then new, then name.
- `build_technique_section(entries, technique_metrics, technique_events, now,
  *, top_n=10) -> list[HubRow]` — rank tracked techniques by their momentum
  (the `TechniqueEntry.momentum` 1–5 score + citation direction), union with
  new/promoted-this-week from `technique_events`.
- `is_new` uses the ISO-week window (Monday-to-Monday) of `now`, reusing
  `reports.digest.iso_week_bounds` (already the project's week convention).
- Empty when nothing rising and nothing new → the section renders a quiet
  "No trending {models,techniques} this week" note (the template decides), not
  the full catalog.

### Surfaces

- **Live `/trending` route** (`web/app.py`): load model entries + model-metrics
  + model-history, technique entries + technique-metrics + technique-history;
  build both sections at `now = datetime.now(UTC)`; render below the repo
  lanes. All reads guarded (a bad store → empty section, HTTP 200).
- **Static export** (`web/static_site.py` + the `radar export` CLI): the same
  data threaded in as parameters, built at `generated_at`, rendered into the
  static `trending.html`. The live/static templates differ only in nav/link
  targets (the established convention). Back-compat: absent metrics/history →
  empty sections, page still renders.
- **Index strip** (`_trending_summary.html`): extend the existing 📈 strip with
  the single top rising model and top rising technique (compact), alongside the
  existing top-3 repos.
- **MCP**: `model_movers` and `technique_movers` already exist — no new tool
  required for Phase 1 (the hub reads the same underlying momentum).

## Data flow

```
radar models scan → append ModelMetrics → data/model-metrics.jsonl (committed by CI)
                                              │
/trending (live + static):                    ▼
  load model entries + model-metrics + model-history  → build_model_section  ─┐
  load technique entries + technique-metrics + tech-history → build_technique_section ─┤
                                                                              ▼
                                                        render Models + Techniques
                                                        sections on /trending + index strip
```

Everything derives from committed files; only the CLI/route boundary reads the
wall clock (`now`), keeping the builders pure and deterministic.

## Error handling

| Failure | Behavior |
|---|---|
| `model-metrics.jsonl` / `technique-metrics.jsonl` corrupt or absent | Loader skips bad lines / returns `[]`; the section's momentum is thin or empty; no raise |
| A history log corrupt/absent | New-this-week union is empty; section still renders from momentum |
| Section builder hits an unexpected error | Guarded at the route/export boundary → empty section; `/trending` stays 200 and `radar export` stays green (the daily-publish invariant) |
| Day one of the model-metrics log | Models have one observation → no velocity → "rising" thin; the NEW column carries the section; fills in from day two |

## Testing (TDD; gates: pytest ≥80% + ruff + mypy)

- `model_metrics_log`: round-trip, missing → `[]`, corrupt-line skip (mirror of
  the technique-metrics test).
- `hub_sections` (pure): rising order by growth; new-this-week union (a new
  item with no velocity still appears, `is_new=True`); day-one single-observation
  (no velocity, new items still shown); empty state; guarded/garbage input →
  `[]` not a raise.
- Live `/trending` route: renders Models + Techniques sections with links to
  `/model/{id}` and `/technique/{id}`; a corrupt/absent store → 200 with empty
  sections.
- Static export: writes the two sections into `trending.html`; back-compat
  (no metrics/history → page still renders, sections empty).
- Index strip: shows the top rising model + technique when present.
- Publish workflow text-parse test: `radar models scan` appends and
  `data/model-metrics.jsonl` is committed.

## Scope

One implementation plan, ~6–7 tasks mirroring the repo-surfaces sub-project:
model-metrics log → scan/CI wiring → hub section builders → `/trending`
live+static → index strip → docs. Phase 2 (untracked model/paper discovery
with its own observation stores + feeds) is a separate future spec.

## Open items for plan time

- Confirm the exact `ModelMetrics` shape logged by `radar models scan` and that
  `compute_model_momentum` consumes the log rows unchanged (vs the `radar.db`
  `ModelMetricsStore.history_for`), adapting the grouping if the interfaces
  differ.
- Confirm `TechniqueEntry.momentum` (1–5) + citation fields are populated at
  render time (they are on the /research entries) so the technique ranking
  needs no recomputation.
