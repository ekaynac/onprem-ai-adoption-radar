# Radar Restoration & Elevation — Design

**Date:** 2026-07-31
**Status:** Approved direction; execution spec for the implementation agent
**Supersedes in part:** `2026-07-30-onprem-intelligence-platform-redesign-design.md`
(the platform vision stands; this spec corrects its delivery and restores what
the cutover lost)
**Primary persona:** Enterprise AI and infrastructure architect

## 0. Read this first — what actually happened

PR #9 built the intelligence platform skeleton (canonical store, trust
lifecycle, FastAPI, React workspace) and cut the published site over to it.
PR #10 bolted legacy data back onto the new UI through a read-adapter. The
result today, verified against the committed database, the deployed Pages
site, and the code:

1. **The old site was never deleted — it is orphaned.** `radar export`
   (`src/radar/cli.py:2458`) still renders every legacy page (models,
   per-model detail, techniques, platforms, trending, projects, compare,
   history, digests, badges) into `_site/`, then
   `src/radar/web/react_export.py:58` overwrites `index.html` — the only page
   that linked to them. Zero inbound links remain (`grep` across
   `frontend/src/` confirms).
2. **The canonical pipeline produces nothing.** All 47 releases in
   `data/intelligence.db` are `release:legacy:*` migration imports. The
   lifecycle stalls at Verified (7 rows); 0 Qualified, 0 Recommended,
   0 events, 0 compatibility assertions, 0 lifecycle transitions.
3. **The root cause is one predicate mismatch.**
   `src/radar/intelligence/pipeline.py::_enrich` selects releases by claim
   predicate `repo_id`; `src/radar/intelligence/migration.py::_claim_values`
   writes the predicate `hf_repo`. Enrichment therefore matches zero
   releases → no compatibility assertions → `qualifiers/base.py` rejects all
   7 candidates (it requires ≥1 non-inferred assertion) → `_recommend` skips
   everything → no transitions → no events → empty feeds and a permanently
   empty "Recommended actions" panel.
4. **The public product lost its core artifact.** All 283 rows in
   `data/intelligence/public-snapshot.v1.json` have `public_ring: null`. The
   adopt/pilot/watch/avoid ring — the product's reason to exist — appears
   nowhere on the published site. The old HTML pages sitting unlinked in the
   same `_site/` still carry real rings.
5. **Subscribers were broken.** `react_export.py:70-82` overwrites the legacy
   `changes.rss` / `changes.json` (project ring changes) with feeds generated
   from the empty `intelligence_events` table. Existing feed subscribers now
   receive zero items. The e2e test only asserts `<rss>` exists, so an empty
   feed passes.
6. **The "priority intelligence" stream is junk.** The 236 `release:hf:*`
   rows are synthesized at export time from
   `data/model-candidate-observations.jsonl`
   (`src/radar/web/intelligence_snapshot.py:118-200`) with hardcoded
   `confidence: 0.7` and `lifecycle: "detected"`. The homepage leads with
   "MyAwesomeModel-TestRepo" (listed twice) and 135M-param hobby uploads.
   207 of 283 releases carry `first_observed_at` equal to the scan timestamp,
   so ~73% of the stream claims to be under an hour old regardless of the
   real release date.
7. **Two workflows race on the same binary file.** `publish.yml` and
   `intelligence-discovery.yml` share cron `17 */2 * * *` and
   `concurrency: group: pages`, and both force-add and push
   `data/intelligence.db` to main. No discovery output has ever landed in the
   committed store.
8. **Delivered UI is thinner than designed.** `/planner` computes feasibility
   as `device_id === "hgx-h200-8"` (`frontend/src/features/planner/PlannerPage.tsx`);
   `/watchlists` is a 30-line placeholder; Compare shows only four coarse
   fields; five of the catalog filter dropdowns contain only "Any" and are
   never sent to the API; `/planner`, `/workspaces`, `/watchlists`,
   `/operations/reviews` are stripped from the static build entirely.
9. **The capacity engine — the largest recent investment — has no UI.**
   `src/radar/capacity/` (solver, memory, KV, throughput, TCO, launch
   recipes) is reachable only via CLI (`radar capacity plan|max`) and MCP
   (`plan_capacity`, `max_workload`, `compare_devices`). Neither the old nor
   the new web surface ever exposed it.
10. **Docs promise what the repo doesn't do.** `docs/persistence.md` claims
    `data/intelligence/events.jsonl` and `data/intelligence/snapshots/` are
    force-committed; neither is tracked. README says "daily" publishing
    (it's two-hourly), "51 curated sources" (68), and its Highlights block
    advertises the pre-redesign feature list including feeds and rings the
    published site no longer delivers. PR #10 also collapsed every freshness
    window in `src/radar/intelligence/freshness.py` to a flat 2 hours, so
    licenses and hardware specs go "stale" between scans by design.

## 1. North star

One product, three faces, one core:

- **Radar** — *what to adopt*: rings, scores, evidence, movers, Try This
  Week, tenure, badges. This is the previous version's soul and it must lead
  the product again.
- **Intelligence** — *what is happening*: release detection, trust lifecycle,
  provenance, feeds, source health. This is PR #9's contribution; it must
  start actually producing.
- **Planner** — *what it takes to run*: fit, capacity, topology, throughput,
  launch recipes, power/TCO. This exists as a mature engine and must finally
  reach the web surface.

Everything below is organized as phases the implementation agent executes in
order. Each phase is independently shippable, lands via its own PR from a
`feature/restoration/<phase>` branch, and has explicit acceptance gates.
Conventional commits throughout. Never break a URL or feed that ever shipped.

## 2. Phase 0 — Stop the bleeding (small diffs, highest urgency)

### 2.1 Fix the predicate dead-end

- In `src/radar/intelligence/pipeline.py::_enrich`, select by `hf_repo`
  (and keep `repo_id` as a fallback), or emit both predicates from
  `migration.py::_claim_values`. Pick one canonical predicate name, migrate
  existing claims via an Alembic migration, and add a regression test that
  runs migrate → enrich → qualify on a fixture seed and asserts at least one
  release reaches Qualified.
- Route `migration.py`'s lifecycle writes through `LifecycleService` so
  transitions are recorded (today: `lifecycle=VERIFIED` is set directly,
  which is why `intelligence_lifecycle_transitions` has 0 rows).

### 2.2 Feed continuity for existing subscribers

- `changes.rss` and `changes.json` must again carry the legacy project
  ring-change items. Merge strategy: emit a unified feed — legacy ring
  events plus intelligence lifecycle events, newest first, stable IDs — from
  a single writer. `react_export.py` must not blindly overwrite what
  `static_site.py::_write_feeds` wrote; there must be exactly one feed
  writer per filename.
- Keep `changes.xml`, `changes-models.*`, `changes-research.*`,
  `digests/digest.xml`, `digests/digest-rss.xml` published and linked (see
  2.4).
- Strengthen `frontend/e2e/public-static.spec.ts` and the export gate: feeds
  must contain ≥1 item whenever their backing history is non-empty; fail the
  build otherwise.

### 2.3 Untangle the workflow race

- Offset `intelligence-discovery.yml` to a different minute/hour lane than
  `publish.yml`, or (preferred) fold `intelligence-run discovery` +
  `verify-new` into `publish.yml` as a step and delete the second workflow.
  One committer to `data/intelligence.db`, one Pages deployer.
- Restore per-class freshness windows in
  `src/radar/intelligence/freshness.py` (release identity 7d→30d, license
  30d, platform compatibility 30d, benchmarks 90d, hardware specs 90d,
  security daily — as the original design specified). The 2-hour discovery
  cadence is a *scan* cadence, not a claim-validity window.

### 2.4 Reconnect the orphaned site (temporary bridge)

Until Phase 2 reaches parity, the legacy pages are the deepest product we
have. Add a "Classic radar" section to the React sidebar
(`frontend/src/shell/Sidebar.tsx`) with plain `<a>` links to `models.html`,
`platforms.html`, `techniques.html`, `trending.html`, `history.html`,
`compare.html`, and the latest digest (read from `data/digest-log.jsonl`
into the snapshot). Restore the footer download block (history JSONLs, all
feeds) on `/integrations`. This is one afternoon of work and instantly
returns every lost feature to reachability.

### 2.5 Honesty pass on docs

- README: two-hourly cadence, 68 sources, add `intelligence/`, `api/`,
  `capacity/`, `frontend/` to Project layout, and split Highlights into
  "Radar (shipping)", "Intelligence (in progress)", "Planner (CLI/MCP)" so
  nothing is advertised that the public site doesn't do.
- `docs/persistence.md`: either start force-adding
  `data/intelligence/events.jsonl` + `data/intelligence/snapshots/` in the
  publish workflow (preferred — the recovery drill depends on them) or
  rewrite the doc to match reality. Do not leave the contradiction.

**Phase 0 gates:** migrate→enrich→qualify fixture test green; published
`changes.rss` non-empty; single writer per feed file; one workflow commits
the DB; classic links live; README contains no claim the site contradicts.

## 3. Phase 1 — Rings return to the public product

The decision ring is the product. It comes back as the first-class output of
the *new* platform, not a legacy leftover.

### 3.1 Recommendation bridge

- Replace the two-valued ring in
  `src/radar/intelligence/recommendations.py` (`PILOT if qualified else
  WATCH`, no ADOPT path) with a bridge to the existing deterministic scoring:
  for the curated catalog, the ring already computed by the legacy models
  pipeline (`src/radar/models_radar/`, persisted cards in `data/radar.db`)
  is authoritative. The canonical `Recommendation` wraps it with factors,
  evidence refs, assumptions, and computation version, exactly as the
  redesign spec §8.5 demanded. Workspace adjustment layers on top.
- `public-snapshot.v1.json` gains real `public_ring` values for every
  curated model and project. The snapshot invariant gate asserts
  `public_ring` is non-null for ≥ the count of legacy-seeded models.

### 3.2 Separate the catalog from the firehose

Curated, ring-bearing entries and raw HF detections are different products
and must stop sharing one table:

- `/catalog` shows curated + Verified-or-better releases with rings, tier,
  params, context, license, min-memory — the old `models.html` columns.
- Raw candidates move to an **Emerging** lane on `/releases` (equivalent of
  the old "Emerging — not yet tracked" tables), clearly labeled, with
  downloads/day and first-seen. They never appear in Compare's default picker
  or the Overview's "Priority intelligence" unless they pass the quality
  gate (3.3).
- Preserve the promotion path: `radar models discover/promote` remains how a
  candidate earns catalog entry; surface a "promote candidates" report in the
  review queue for the operator.

### 3.3 Detection quality gate

In `src/radar/web/intelligence_snapshot.py` (and, once live, the HF adapter
path): drop or down-rank candidates that are obvious noise — repo name
matches test/demo patterns ("MyAwesomeModel"), zero downloads and zero
likes, dedupe by repo id (the same repo currently appears twice), abliterated
/ finetune-of-finetune heuristics down-ranked. Replace the hardcoded
`confidence: 0.7` with a computed score (publisher known? downloads?
files complete? license present?). `first_observed_at` must come from the
first observation in `model-candidate-observations.jsonl`, never the scan
timestamp.

### 3.4 Overview becomes a briefing again

The old hub's information design was right. `/overview` gains:

- Ring-distribution stat tiles (Tracked / Adopt / Pilot / Watch / Avoid).
- A **Try This Week** panel (port `src/radar/reports/try_this_week.py`
  output into the snapshot): adopt+pilot picks with backer badge, trend
  arrow, risk pill, HN chip, top-2 evidence notes.
- Movers (from `src/radar/reports/movers.py`) — biggest ring/score changes.
- Latest digest link.
- "Priority intelligence" only shows gate-passing detections (3.3).

**Phase 1 gates:** every curated model shows its ring on `/catalog` and
`/overview`; snapshot invariant enforces rings; junk repos absent from
default views; Try This Week panel matches the CLI report for the same data.

## 4. Phase 2 — Full feature parity with the previous site (in React)

Port the remaining legacy depth into the React app, using the snapshot (or
API in live mode) as transport. The legacy Jinja pages remain published until
the parity checklist is fully green, then Phase 6 retires them. Inspiration
source: the old pages themselves — match or beat each feature.

Parity checklist (old → new):

| Legacy feature | Source | Target |
|---|---|---|
| Device picker with live fit recoloring | `templates/_device_picker.html`, `web/picker_context.py` | `/catalog` toolbar; picker state re-verdicts every row (green/amber/faded) using min-memory + quant data already in the snapshot |
| 9-col sortable models table | `static_models.html` | `/catalog` table upgrade: params (A-active MoE), context, license, min-mem columns; real sorting |
| Model detail: tenure line, download sparkline, quant table, architecture table, curated benchmarks with source links | `_model_detail.html`, `web/spark_series.py`, `web/tenure.py` | `ModelDetailPage.tsx` — most exists post-PR #10; add tenure, sparkline (inline SVG from history series in snapshot), architecture block |
| "Runs on" fit matrix incl. datacenter tiers | `_model_detail.html` fit report | `ModelDetailPage.tsx` fit section fed by capacity engine via snapshot precompute (see Phase 3) |
| Ring + fit badges with copy-ready Markdown | `web/badge.py`, `badges/*.svg` | Badge block on model/project detail; keep publishing `badges/*.svg` at the same URLs |
| Techniques table + detail (7-col score breakdown, momentum, papers with roles, implementations with back-links, research→production timeline, superseded-by) | `_technique_detail.html`, `research_radar/timeline.py` | `ResearchDetailPage.tsx` parity additions |
| Platform matrix citations ("Sources" per engine, verified dates, tooltips) | `static_platforms.html` | `PlatformDetailPage.tsx` already has the matrix; add the citation list + verified-at |
| Trending 7/30/90d with tab nav, two repo lanes, 14-day sparklines, NEW flags, emerging models/papers | `static_trending.html`, `web/hub_sections.py` | New `/trending` route (Intelligence group) fed by `trending-observations.jsonl` + candidate logs via snapshot |
| Project detail: score breakdown, on-prem rubric, full evidence, metrics history table + star sparkline, ring timeline, upgrade-risk | `_project_detail.html` | `ProjectDetailPage.tsx` — partially restored by PR #10; complete the remainder |
| Comparison matrices per category | `reports/comparison.py` | Fold into `/compare` (see 4.1) |
| History page (per-project ring-change tables, JSONL download) | `static_history.html` | `/releases` gains a History tab; downloads already on `/integrations` (2.4) |
| Digest archive + social cards | `digests/`, `web/cards.py` | New `/digests` route listing `digest-log.jsonl`, linking pages + cards; digest nav links fixed to point at the SPA |
| All-projects filter bar (text/category/backer) | `_filter_bar.html` | `/projects` filter upgrade |
| Scan-health + source-health panels with firehose/LLM-recovery detail | `web/scan_health.py`, `web/source_health.py` | `/operations` additions |
| Legend (rings, backer types, arrows, risk pills) | `_legend.html` | Shared `<Legend>` component, linked from every table header |

### 4.1 Compare that earns its name

`/compare` becomes three tabs, replacing the shallow four-field pin:

1. **Models** — claim-level diff of curated models: params, context, license,
   quants, min-mem per device class, benchmarks, ring + factors. Only fields
   that differ are pinned, as the current copy already promises.
2. **Devices** — port `compare_devices` (MCP `mcp_server/capacity_queries.py`)
   to the API and UI: given a model + workload, contrast device options.
3. **Projects** — the per-category comparison matrices from
   `reports/comparison.py`.

### 4.2 Catalog filters must work

Populate publisher/license/hardware/modality/platform options from snapshot
facets and apply them (client-side in static mode, query-params in live
mode). Remove any filter that has no backing data rather than shipping a
dead dropdown.

**Phase 2 gates:** every checklist row demonstrably matched (Playwright spec
per row asserting real content, not shell); no legacy page offers a feature
the React app lacks; visual regression suite updated.

## 5. Phase 3 — The Planner ships (capacity engine reaches the web)

This is the highest-leverage "new" feature and it is mostly plumbing: the
engine is done and tested.

- **API:** new `/api/v1/capacity` router wrapping
  `src/radar/mcp_server/capacity_queries.py` / `src/radar/capacity/`:
  `POST /capacity/plan` (model, workload, constraints → GPU count, per-rank
  memory breakdown, TP/PP layout, throughput envelope, kW + TCO estimate,
  assumption sheet), `POST /capacity/max` (fleet → max workload),
  `GET /capacity/devices`, `POST /capacity/fit` (model × device → verdict +
  largest fitting quant), `POST /capacity/recipe` (vLLM / SGLang /
  TensorRT-LLM launch configs from `capacity/recipe.py`).
- **UI:** rebuild `PlannerPage.tsx` on those endpoints: pick model (curated
  catalog), pick workload (concurrency, context, latency target), pick
  estate (device presets or workspace estate) → plan with the assumption
  sheet rendered honestly (every number cites its anchor, as the CLI does).
  Delete the `hgx-h200-8` mock. Expose in static mode too: precompute plans
  for the curated model × preset device grid into a planner snapshot
  section, or compile the solver's arithmetic to the client — decide by
  size; the precomputed grid is the pragmatic default.
- **Fit everywhere:** model detail "Runs on" (Phase 2) and hardware detail
  pages link into the planner pre-filled; hardware cards fix their
  "Unknown" bandwidth/power cells by reading the full preset specs (data
  exists in `models_radar/devices.py`; the snapshot mapper drops it).
- **Launch recipes** rendered as copyable blocks on the plan result and on
  model detail for the default device.

**Phase 3 gates:** planner output matches `radar capacity plan` CLI for
identical inputs (golden tests); no "Unknown" for specs present in presets;
static site includes a working planner path.

## 6. Phase 4 — Intelligence that actually produces

With Phase 0's dead-end fixed, make the pipeline earn its UI:

- **Wire the evidence adapter.** `src/radar/intelligence/sources/evidence.py`
  (`build_evidence_adapters`) has zero call sites — integrate `collect()`
  into `pipeline.py::_enrich` so benchmarks, advisories, and license texts
  become claims.
- **Enable disabled sources one at a time** (`config/intelligence-sources.yaml`):
  registries (Ollama, ModelScope) first with recorded-fixture tests, then
  announcement pages, then external evidence. Expand `official-feeds` beyond
  the current two blogs (vLLM, llama.cpp, SGLang, Mistral, Qwen, DeepSeek,
  Moonshot official channels).
- **Category expansion:** the store holds only `text_reasoning`. The HF
  adapter already maps 9 pipeline tags; seed and verify at least embedding,
  speech, and vision categories end-to-end so the six-category catalog
  claim becomes true, with the 9-line qualifiers
  (`qualifiers/{audio,media,document,embedding}.py`) given real predicate
  requirements per the redesign spec §9.
- **Identity resolution** gains alias tables for the 18 configured
  publishers plus fuzzy-with-review (exact-match-only currently sends every
  unknown publisher to a review queue nobody reads); review queue gains the
  merge action the UI already apologizes for lacking.
- **Compatibility stream:** `radar models platforms-verify` (PR #10) plus
  declared-compat from enrichment populate `intelligence_compatibility`;
  platform matrix freshness states derive from it instead of the blanket
  "stale" the snapshot currently paints.
- **Performance honesty:** stop rebuilding the public snapshot on every API
  request (`api/routes/{releases,catalog}.py` call `build_public_snapshot`
  per request) — cache it with mtime invalidation; fix
  `event_log.py::append` re-parsing the whole JSONL per event; make
  `shadow.py` compare field-level samples, not just counts.

**Phase 4 gates:** ≥1 non-legacy release reaches Qualified in production
data; ≥3 categories populated; compatibility table non-empty; feeds carry
lifecycle events from real detections; API p50 for `/catalog` under 100ms
against the committed DB.

## 7. Phase 5 — Workspaces, watchlists, alerts (complete, not placeholder)

- Workspaces: update/delete/list in service + API (PATCH/DELETE); estate
  builder picks from device presets instead of a free-text device-ID field;
  `workloads` and `policies` become typed models consumed by the
  recommendation adjuster and the planner (Phase 3) — delete any field
  nothing reads.
- Watchlists: real CRUD (entities: model, project, technique, publisher,
  platform), stored on the workspace; watched-entity changes flow into a
  `changes-watchlist` feed and the webhook path
  (`notify/intelligence_webhook.py`); `/watchlists` page replaces the
  30-line placeholder with list + add/remove + recent-events view.
- Static mode: read-only workspace/watchlist import via file, clearly
  labeled; live mode keeps mutations.

**Phase 5 gates:** watchlist change appears in feed + webhook fixture test;
workspace estate flows into planner defaults; no placeholder pages remain in
the nav.

## 8. Phase 6 — One site, honest exports

Only after the Phase 2 parity gate is green:

- Retire the dual-site export: `render_static_site` stops emitting orphaned
  HTML pages, keeping only (a) permalink redirect stubs from every legacy
  URL that ever shipped (`models.html` → `#/catalog`, `project_<slug>.html`
  → `#/projects/<slug>`, etc.), (b) `badges/*.svg`, (c) feeds, (d) digest
  archive, (e) the history JSONL downloads.
- **Crawlable HTML returns:** emit prerendered static HTML for the key
  routes (overview, catalog index, model/project/technique details) — either
  vite prerender of snapshot routes or a slim Jinja "reader edition"
  reusing the legacy templates' content blocks — linked via `sitemap.xml`
  and `<noscript>`. A crawler must never again see an empty shell titled
  "On-Prem Intelligence".
- CHANGELOG entry written from what shipped, not what was planned; the
  Mega Bilişim brand identity retained throughout (logo/fonts from
  `static/brand`, nothing from the private brand kit).

**Phase 6 gates:** zero orphaned pages in `_site`; every historical URL
redirects or serves; `curl` of `/` without JS shows real content; Lighthouse
SEO ≥ 90.

## 9. Execution rules for the implementation agent

- One phase per PR, branched `feature/restoration/<phase-slug>`, full branch
  diff reviewed before PR, conventional commits, no direct pushes to main.
- Gates are ruff + mypy + pytest + frontend typecheck/lint/build + Playwright
  + the phase-specific gates above. A phase that weakens an existing test to
  pass is rejected.
- Every number shown to a user cites its source; every unknown renders as
  unknown; no silent fallback data. This repo's differentiator is receipts.
- When legacy and canonical disagree, legacy data is authoritative for
  curated entities until Phase 4's pipeline proves itself in shadow
  comparison (field-level, per 6).
- Do not touch `data/*.jsonl` history semantics: append-only, corrections
  supersede, never rewrite.
