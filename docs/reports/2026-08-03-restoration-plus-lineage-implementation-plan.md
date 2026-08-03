# Restoration-plus-Lineage: Revised Implementation Plan

**Author:** Fable (implementor)
**Date:** 2026-08-03
**Inputs:**
- [`2026-08-03-radar-usability-and-model-lineage-investigation.md`](2026-08-03-radar-usability-and-model-lineage-investigation.md) (Sol)
- [`../superpowers/specs/2026-07-31-radar-restoration-and-elevation-design.md`](../superpowers/specs/2026-07-31-radar-restoration-and-elevation-design.md) (approved restoration spec)
- Fable's own investigation of `origin/main` (`1beb5a4`) and the live Hugging Face API, 2026-08-03

**Status:** Plan of record for implementation. Supersedes Fable's earlier
"rings first" sequencing; adopts Sol's lineage-first thin slice with
corrections noted below.

## 1. What changed after reading Sol's report

I adopt from Sol, wholesale:

1. **Lineage-first sequencing.** My earlier plan folded base-model parsing
   into the Phase 1 quality gate as a side task. Sol's production numbers
   (17,423 index rows, 93% provisional publishers, ≥21.6% name-detectable
   derivatives, 0 lineage edges) show the noise problem dominates every
   surface an architect touches daily — search, stream, catalog, feeds.
   Rings over an ungrouped index would decorate noise. The thin end-to-end
   lineage slice ships first.
2. **Release vs. artifact ontology** (Sol §7). The base release becomes the
   principal model concept; repositories become artifacts attached to it.
3. **Significance classes before recency** in search and stream ranking
   (Sol §8.2), with `lastModified` demoted to a freshness indicator.
4. **Partial, evidence-preserving enrichment** (Sol §4.3). Confirmed in
   code: `HuggingFaceAdapter.enrich()` calls
   `config_response.raise_for_status()`, so a missing `config.json`
   discards already-fetched metadata, card, license, and sibling evidence.
5. **"Verified" ≠ "decision-complete"** (Sol §3.3). Confirmed at
   `src/radar/intelligence/verification.py` — deployable verification
   requires only `license` + one of `artifact_url|hf_repo|repo_id`. The two
   measures must be reported separately.
6. **Non-goals** (Sol §11) — all adopted verbatim, especially: group
   derivatives, never delete them; no name-only high-confidence lineage; no
   LLM-only classifier; classic pages stay until parity is test-proven.

## 2. Corrections and verified sharp edges

Verified live against the HF API on 2026-08-03:

1. **`childrenModelCount` does not exist.** It is not a valid `expand`
   value. The full valid set is: `author, baseModels, cardData, config,
   createdAt, disabled, downloads, downloadsAllTime, evalResults, gated,
   inference, inferenceProviderMapping, lastModified, library_name, likes,
   mask_token, model-index, pipeline_tag, private, safetensors, sha,
   siblings, spaces, tags, transformersInfo, trendingScore, widgetData,
   gguf, resourceGroup, xetEnabled`. Derivative counts are therefore
   **computed on our side** from the lineage table (primary), optionally
   reconciled per curated root via the filterable tag query
   `GET /api/models?filter=base_model:quantized:<root>` (secondary).
2. **`expand[]=baseModels` is stronger than the report states.** It returns
   the relation *and* the server-resolved parent identity:
   `unsloth/Kimi-K3-GGUF → {"relation": "quantized", "models":
   [{"id": "moonshotai/Kimi-K3"}]}`. This is Tier-1 evidence with the
   ambiguity already resolved by the Hub. Caveat: `expand` cannot be
   combined with `full=true`, so discovery keeps `full+cardData` (the
   listing already includes `tags` with `base_model:*` entries) and the
   per-repo `expand[]=baseModels` call joins enrichment.
3. **Base models are detectable by absence.** `moonshotai/Kimi-K3` and
   `google-bert/bert-base-uncased` carry no `base_model:*` tags and a null
   `baseModels`. "No declared parent + resolvable publisher" is the base
   heuristic; it never *upgrades* confidence on its own (a base claim from
   tag absence is Tier-3 until the publisher is official or mapped).
4. **Predicate fix already landed.** `pipeline.py` now normalizes
   `repo_id → hf_repo` (PR #11), and confidence is computed, not the old
   hardcoded 0.7. The plan builds on origin/main (`1beb5a4`), which is ~40
   commits ahead of the local checkout — implementation branches from
   origin/main after a pull.
5. **Time fixes the trends, not the semantics.** Metrics/trending history
   has 26–27 consecutive days (since 2026-07-05/06); 7d/14d windows are
   live, 30d fills ~2026-08-05, 90d fills ~2026-10-03. Nothing in this plan
   needs to wait for data; nothing in the data obviates this plan.

## 3. Unified sequencing

Sol's Phases A–D and the restoration spec's Phases 1–6 interleave into five
PR-sized milestones. Each lands via `feature/restoration/<slug>` per repo
convention; ruff + mypy + pytest + frontend typecheck/build + Playwright
gates apply to all, plus the per-milestone gates below.

| Milestone | Branch slug | Source phases |
|---|---|---|
| M1 Lineage core | `lineage-core` | Sol A |
| M2 Significance & grouping | `significance-ranking` | Sol B |
| M3 Rings return | `rings-return` | Spec Phase 1 |
| M4 Architect depth | `catalog-depth` | Spec Phase 2 / Sol C |
| M5 Planner + enrichment priority | `planner-and-priority` | Spec Phase 3 / Sol D |

Spec Phases 4–6 (intelligence production, workspaces, single-site retirement)
continue afterward as written; they are not displaced by this plan.

### M1 — Lineage core (thin end-to-end slice, backend)

**Contracts & persistence**
- New `LineageEdge` frozen model in `src/radar/intelligence/contracts.py`:
  `child_release_id, parent_release_id, root_release_id, relation, declared,
  confidence, evidence_ids, extractor_version, review_status` (Sol §7.1).
  `relation` enum: `base | finetune | adapter | merge | quantized |
  converted | distilled | pruned | checkpoint`.
- Alembic migration: `intelligence_lineage_edges` table; unique on
  `(child, parent, relation)`; index on `parent`, on `root`.
- Multi-parent merges: one edge per parent; a merge is its own root
  (parents retained as edges, `relation=merge`).

**Extraction (Tier 1 first, discovery-time)**
- `sources/huggingface.py::_metadata_claims` additionally retains:
  `tags` (filtered to `base_model:*`), `cardData.base_model`,
  `cardData.base_model_relation`. Discovery emits lineage claims — not
  only enrichment (Sol A.2; the listing response already contains tags).
- `enrich()` adds a `GET /api/models/{repo}?expand[]=baseModels` record;
  its `{relation, models[]}` is the authoritative Tier-1 edge.
- Tier-2 (artifact-declared: `adapter_config.json`
  `base_model_name_or_path`, GGUF metadata, config `_name_or_path`) and
  Tier-3 (name/config fingerprints) land behind lower confidence values;
  Tier-3 never auto-accepts — conflicts and ambiguity open review
  exceptions with new codes `lineage-conflict`, `lineage-unresolved-parent`.

**Root resolution**
- Pure function in new `src/radar/intelligence/lineage.py`: iterative
  parent-following, visited-set cycle guard (cycle ⇒ review exception,
  root = self), deterministic tie-break (highest-confidence edge, then
  lexicographic), unresolved parent ⇒ root = deepest resolvable ancestor
  with `review_status=open`.

**Robustness fix (Sol §4.3)**
- `enrich()`: only the metadata fetch is fatal. Missing/invalid
  `config.json` ⇒ keep metadata/card/siblings evidence, architecture
  fields unknown. Missing README ⇒ keep the rest. Regression test with a
  404-config fixture asserting license and lineage claims survive.

**Backfill**
- CLI `radar intelligence lineage backfill [--limit N --order downloads]`:
  walks existing releases, replays stored HF metadata evidence where
  present, fetches `expand[]=baseModels` where absent, writes edges +
  roots. Idempotent; bounded per run; scheduled inside the existing
  two-hourly pipeline until coverage converges.

**M1 gates**
- Fixture test: migrate → discover → enrich → resolve produces correct
  edges for a Kimi-K3-shaped fixture (official root, GGUF quant, finetune,
  two-parent merge, cycle, missing parent).
- ≥90% of the top 500 index models by downloads have a resolved root after
  backfill (Sol §10).
- Declared relations preserved with source evidence IDs; no edge without
  evidence.

### M2 — Significance & grouping (publish + surfaces)

**Classification & score**
- `significance.py`: deterministic class per Sol §8.2 —
  `official-root > base-release > official-publisher > curated/recommended
  > declared-parent derivative > other verified derivative >
  provisional`. Within-class score from name relevance (search only),
  release date, download/like momentum, completeness, evidence strength;
  every score carries a factor list (repo rule: numbers cite sources).
- Snapshot rows gain `base_release`, `root_release`, `relation`,
  `is_official`, `derivative_counts` (computed from edges, per relation),
  `significance` {class, score, factors}. Snapshot invariant gate: fields
  present for all rows; counts consistent with the edge table.

**Ranking & grouping**
- Model-index shards and static search order by (class, score), not
  `lastModified` (`intelligence_snapshot.py`, index writer, catalog
  search). `lastModified` stays as a displayed freshness value.
- Release stream: one event per base release; derivative activity
  aggregates beneath it ("47 quantizations · 8 fine-tunes"), expandable
  to raw records; feeds emit the grouped event with the upstream release
  as subject (Sol §8.3).
- Emerging lane (`discovery/model_candidate_detect.py`): candidates with a
  declared parent collapse under the parent chip; derivative-count itself
  surfaces as an adoption signal on the parent. "All artifacts" mode
  preserved everywhere.

**M2 gates**
- Searching a family name returns the official root first (Playwright +
  unit test on the ranking function).
- Kimi-K3: 189 records render as one root row with grouped derivative
  counts in catalog/stream defaults; raw list reachable in two clicks.
- Default stream contains no two rows whose subjects share a root.

### M3 — Rings return (restoration spec Phase 1, unchanged scope)

- Bridge legacy deterministic scoring (`src/radar/models_radar/`,
  `data/radar.db` cards) into canonical `Recommendation`; replace the
  two-valued `PILOT if qualified else WATCH` in `recommendations.py`
  with the full adopt/pilot/watch/avoid ring + factors + evidence refs.
- `public-snapshot.v1.json`: non-null `public_ring` for every curated
  model/project; invariant gate enforces the count.
- Overview becomes the briefing: ring-distribution tiles, Try This Week
  (port `reports/try_this_week.py`), movers, latest digest; "Priority
  intelligence" shows only gate-passing, significance-classed detections.
- M1/M2 make this better than the original spec version: ring rows carry
  lineage context, and the derivative-count signal feeds the momentum
  factor.

**M3 gates:** spec Phase 1 gates verbatim (every curated model shows its
ring; junk absent from defaults; Try This Week matches CLI output).

### M4 — Architect depth (spec Phase 2 ∩ Sol §6/§8.4, catalog + detail first)

- Catalog default view = **Base models** (Sol §8.1); modes: base /
  curated-deployable / all-artifacts. Columns restore and exceed the
  classic nine: publisher, root, relation, ring, tier, params (A-active),
  context, license, use case, min-memory, best deployment format, engines,
  evidence confidence. Filters populated from snapshot facets; no dead
  dropdowns.
- Model detail reordered per Sol §8.4: decision brief → lineage (parents,
  root, children with confidence) → specs → deployment/capacity → runs-on
  → variants (official first, community grouped) → benchmarks → research →
  history/momentum → claims/provenance. Tenure line and download sparkline
  from history series (26+ days available now, growing).
- Remaining spec-Phase-2 parity rows (device picker, platform citations,
  trending tabs, digest archive, compare matrices) follow inside this
  milestone as separate commits, each with a Playwright spec asserting
  real content — classic pages retire only per-row as tests go green.

**M4 gates:** spec Phase 2 checklist rows demonstrably matched for
catalog + model detail; derivatives collapsed by default; every entity
clickable (Sol §10 usability).

### M5 — Planner ships + enrichment gets significance-aware

- Spec Phase 3 as written: `/api/v1/capacity` router over the existing
  solver, PlannerPage rebuilt, precomputed curated-model × preset-device
  grid for static mode, launch recipes, "Unknown" spec cells fixed.
- Enrichment scheduler (`pipeline.py::_enrich` eligibility sort): priority
  = roots first, official publishers, high-descendant-count parents,
  recently announced majors, records one field away from
  decision-complete (Sol §4.4/D.1). Budget stays bounded; order changes.
- New coverage metrics in the quality panel: lineage coverage, root
  resolution rate, architecture extraction rate, review inflow vs.
  resolution (Sol D.3–D.5). "Verified" and "decision-complete" reported
  as separate numbers on `/operations`.

**M5 gates:** planner output matches `radar capacity plan` golden tests;
enrichment queue drains roots/official measurably first (fixture);
coverage metrics visible and non-regressing in CI.

## 4. Acceptance gates (overall)

Sol §10 is adopted as the program-level definition of done, with one
amendment: the lineage-coverage gate ("≥90% of top 500 have resolved
roots") attaches to M1, and the freshness gate ("official repo
identifiable even when derivatives arrive first") attaches to M2. Sol §11
non-goals are binding for all milestones.

## 5. Immediate next steps

1. `git pull` — local main is ~40 commits behind origin/main.
2. Branch `feature/restoration/lineage-core` from origin/main.
3. M1 order of work: contracts + migration → extraction → root resolver →
   partial-enrichment fix → backfill CLI → fixture suite → gates.
