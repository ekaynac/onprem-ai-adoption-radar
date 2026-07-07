# Data-Quality Fixes (audit follow-up) — Design

Date: 2026-07-07
Status: approved (findings verified interactively; decisions confirmed)

## Context

A read-only data-quality audit of the published site + underlying data
(`data/technique-metrics.jsonl`: 1055 rows / 65 techniques / 17 runs;
`data/model-metrics.jsonl`; the 178-page static export) found two confirmed
data bugs, one export fragility, and three signal-quality flaws. A parallel
frontend-readability review found 18 items — those are **sub-project 2**
(separate spec); this spec covers only the data-quality fixes.

Cleared during verification (no action): flash-attention's "100%" was a CSS
`width:100%` artifact, not a momentum value; the live site's citation counts
and momentum are correct (the audit's "62/65 divergent" finding was an
artifact of exporting locally against an empty `radar.db` — which is exactly
the fragility item 5 hardens); no s2↔openalex source-switch bugs; no
null/zero baselines; no stale-log techniques.

## Decisions (confirmed in brainstorm)

1. `RISING_MOMENTUM = 4` — match the canonical scale.
2. Citation floor ≥ 50 + falling deadband −2% on the technique momentum signal.
3. Ring events windowed to the last 30 days in model momentum.
4. Export rehydrates technique metrics from the committed log when the store
   is empty (mirror of `run_research_scan`).

## The six fixes

### 1. Momentum mislabel — steady-3 techniques shown as "rising" (Critical)

`src/radar/web/hub_sections.py:29` sets `RISING_MOMENTUM = 3` and re-derives
`direction = "rising" if mom >= RISING_MOMENTUM ...`, but the canonical scale
in `src/radar/research_radar/momentum.py` defines score 3 as **steady**
(`momentum_signal`'s catch-all returns `score=3, direction="steady"`).
Every technique in the current data has momentum 3, so the "Trending
Techniques" table labels all of them "3/5 rising" while their own detail
pages say steady — a direct cross-surface contradiction. (Introduced in
trending-hub Phase 1 when the threshold was lowered 4→3 to unblock an empty
section, without reconciling the label.)

**Fix:** `RISING_MOMENTUM = 4`. The technique hub section then contains
genuinely-rising (4-5) techniques plus new-this-week — honest, even if the
rising half is often empty day-to-day. The models path already uses
`mom.direction` directly and is unaffected. Update the Phase-1 test that
pinned `RISING_MOMENTUM == 3` and any fixture relying on momentum-3 rows
appearing in the section (give them momentum 4, or assert exclusion).

### 2. Momentum signal noise — asymmetric thresholds (Medium)

`momentum.py`: "rising" requires ≥ `CITATION_RISING_PCT` (10%) growth, but
"falling" fires on **any** negative same-source delta. Audit evidence: `kto`
jumped 7→11 citations (+57% on a baseline of 7 — index noise, read "rising");
`self-consistency` dipped 7091→7089 (−0.03% — crawl noise, read "falling").
Of 990 same-source consecutive steps in the log, those were the only two
non-zero signals — both noise.

**Fix (pure, in `momentum.py`):**
- `CITATION_BASELINE_FLOOR = 50` — if the comparable prior row's
  `citation_count < 50`, percentage comparisons are skipped (growth treated
  as no-signal → steady). Kills the kto class.
- `CITATION_FALLING_PCT = -2.0` — "falling" only below −2% (was: any
  negative). Kills the self-consistency class. Rising stays at +10%.

### 3. Stale ring-event forces "falling" forever (Medium)

`src/radar/models_radar/momentum.py`: `compute_model_momentum` scans
`ring_events[-RECENT_EVENTS:]` (last 3 by count, no time bound) and returns
"falling" unconditionally on a DEMOTED match. `gemma-3-12b`'s single
demotion (2026-06-23) is its most recent event by definition, so it would
render "falling" indefinitely in any momentum-driven list.

**Fix:** only ring events with `observed_at` within
`RING_EVENT_WINDOW_DAYS = 30` of `now` count as momentum overrides; older
events fall through to the downloads-growth signal. `now` is already a
parameter of the surrounding path (or is added, matching this session's
pattern: pure functions take `now`, only CLIs read the clock).

### 4. Ornith params_total wrong by ~5 orders of magnitude + plausibility guard (Critical)

`config/model-seed.yaml:498`: `params_total: 664944` for
`Ornith-1.0-35B` (a 35B model; compare GLM-5.2's correct
`params_total: 753329940480`). Rendered consequences (confirmed on the
export): "Params: 0.0B", every quant memory column "? GB", the "Runs on"
table claiming it fits every device including an 8 GB RTX 4060 at FP16, and
`data-tier="laptop"` misclassification. The value came from the catalog
autopilot's HF scrape.

**Fix (two parts):**
- Correct the seed value to `35_000_000_000` (35B nominal; if the HF repo
  reports an exact safetensors total at build time, use that).
- **Plausibility guard in the autopilot** (`build_seed` /
  `is_promotable` path in `radar.discovery.model_promotion`): parse the
  leading `<N>B`/`<N>b` size token from the model name (e.g. "35B", "0.5B",
  "8x7B" excluded — MoE naming skipped); if a token parses and
  `params_total` differs from `N × 1e9` by more than **5×** in either
  direction, drop `params_total` (leave it unset → renders "?" honestly)
  and log a warning, rather than seeding a wildly wrong value. Pure helper
  `plausible_params(name, params_total) -> int | None`, unit-tested on the
  Ornith case + Mixtral-style MoE names (8x7B → skipped, kept as-is) +
  sub-1B names ("SmolLM2-1.7B").
- The 3 MoE "AxB"-named entries the audit flagged as ~1.5-2× off
  (qwen3-6-35b-a3b, qwen3-6-27b, gemma-4-26b-a4b) are genuinely ambiguous
  total-vs-active naming — left for human review, NOT auto-changed (the
  guard's MoE exclusion also keeps the autopilot from touching that class).

### 5. Export silently renders empty/stale technique metrics (fragility)

`run_research_scan` rehydrates a fresh database from
`data/technique-metrics.jsonl` before scoring — but `radar export` reads
whatever `radar.db` contains, with no rehydration. On a machine (or CI
change) where `radar.db` is missing/empty, export renders "?" citations and
momentum 3 everywhere — silently wrong, discovered only by eyeballing the
site. This is exactly how the audit's local export diverged from live.

**Fix:** in the export path where technique entries are loaded, if the
technique-metrics store is empty and `data/technique-metrics.jsonl` exists,
rehydrate the store from the log (same `load_metrics` → `store.record`
gateway `run_research_scan` uses) before assembling entries. Guarded:
rehydration failure degrades to today's behavior (empty store), never
crashes the export — the daily-publish invariant holds.

### 6. Momentum note never rendered on technique pages (Medium)

`_technique_detail.html` shows only the bare 1-5 momentum integer.
`MomentumSignal.note` ("Citations +12.3% since last comparable scan.",
"+1 tracked implementation(s) since last scan.") and `.direction` are never
surfaced — a user cannot tell why momentum is 3 vs 4. The note/direction
must flow from the scan into the rendered entry (check whether
`TechniqueEntry` already carries them; if not, add optional fields threaded
from `score_technique_entries`).

**Fix:** render direction + note next to the momentum score on technique
detail pages (live + static, byte-identical block, plain text — no new
styling; the visual treatment belongs to sub-project 2).

## Non-goals

- The 18 frontend-readability findings (sub-project 2, next spec).
- No re-tuning of the ring/scoring model beyond the six fixes.
- No change to the guarded gateways or the committed-log formats.
- No new dependencies; no fetching-code changes.

## Error handling

All fixes are pure-function or seed-data changes except #5, which adds a
guarded rehydration (failure → today's behavior). The autopilot guard (#4)
fails toward *less* data (drop the implausible value, log a warning) — never
blocks a promotion outright on a parse quirk.

## Testing (TDD; gates: pytest ≥80% + ruff + mypy)

- #1: momentum-3 technique excluded from the rising section / labeled steady;
  momentum-4 included as rising; Phase-1 fixtures updated.
- #2: baseline <50 → steady regardless of %; −0.03% on a large baseline →
  steady; −3% → falling; +12% → rising (floor + deadband + existing bar).
- #3: a 40-day-old demotion no longer forces "falling"; a 5-day-old one does.
- #4: `plausible_params` unit tests (Ornith rejected, GLM kept, 8x7B skipped,
  1.7B kept); seed value corrected; models.html no longer claims Ornith fits
  an 8 GB GPU (fit math sane again).
- #5: export against an empty store + a populated committed log renders real
  citation counts (not "?"); corrupt log → degrades, export still succeeds.
- #6: technique detail page (live + static) shows the momentum note text.

## Scope

One implementation plan, ~6 tasks (one per fix; #1+#2 may merge as the
momentum-signal task). Branch `fix/data-quality-audit`. Sub-project 2
(frontend readability, 18 findings) follows as its own spec → plan.
