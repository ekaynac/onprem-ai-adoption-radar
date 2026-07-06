# Recency / Staleness Consistency Pass — Design

Date: 2026-07-07
Status: approved (interactive brainstorm; §1–§3 confirmed section-by-section)

## Context

The trending-hub program shipped in three phases (Phase 1 tracked-rising, Phase
2a emerging models, Phase 2b emerging papers) plus the repo source autopilot.
Two recency loose ends were flagged in the Phase-2b whole-branch review and
recorded for a follow-up:

1. **Emerging rows never signal staleness.** `build_model_candidates` and
   `build_technique_candidates` render every observed candidate. Once a
   candidate stops appearing in the daily sweep its velocity ages to `None`
   (so it sinks in the None-last ranking) but the row still shows a *frozen*
   download/upvote count with no cue that it has gone quiet — misleading.
2. **Both autopilot momentum gates measure growth from the earliest-ever
   observation.** `has_sustained_download_momentum` (model-candidate promote
   gate) and the repo autopilot's `momentum_stats` / `has_sustained_momentum`
   compute growth from `ordered[0]` — the first row ever recorded. As the
   committed store grows, any candidate that *ever* grew past the floor stays
   "sustained" forever, so the gate slowly saturates and promotes on stale
   momentum.

This is one consistency pass across both hub phases (surface) + both autopilots
(gate). Both parts share the "recency" theme but are independent.

Decided in brainstorming:

1. **Emerging staleness: show `last seen` + STALE badge, keep the row.** The
   row stays visible (transparency — it *was* emerging and has gone quiet) but
   is clearly marked so the frozen numbers aren't misleading. No hard-drop —
   the velocity-None ranking + the 15-row cap already bound the list.
2. **Momentum window anchored to `now` (calendar-recent, fail-closed).** Keep
   only observations within ~14 calendar days of `now`, then apply the existing
   sustained-growth checks. A candidate not observed recently has < 2 recent
   rows → fails the gate → not auto-promoted. Means "rising right now", not
   "rose during its last recorded streak."

## Non-goals

- No hard-drop / cutoff of stale Emerging rows (keep + mark only).
- No change to the velocity ranking, the 15-row cap, or the guarded gateways.
- No change to the Emerging velocity window (7d) or NEW window (14d).
- No new fetching code, no new Python dependencies, no LLM.
- No new detail pages or columns beyond "Last seen".

## Architecture

Two independent parts under one plan.

### Part A — Emerging staleness signal (surface)

Both pure builders gain two derived fields per row (`now` is already a
parameter of both):

- `last_seen: str` — the *latest* observation's date (today only `first_seen`,
  the earliest, is exposed).
- `is_stale: bool` — true when `last_seen` is older than `STALE_AFTER_DAYS`
  (4) relative to `now`.

`build_model_candidates` → `ModelCandidateEntry` gains `last_seen`, `is_stale`.
`build_technique_candidates` → `TechniqueCandidateEntry` gains `last_seen`,
`is_stale`. No ranking change; stale rows already sink (velocity → `None`,
None-last) and the list stays capped at `EMERGING_LIMIT` (15). We keep the row
and mark it.

Both Emerging table blocks gain a **"Last seen"** column and a **STALE** badge
(rendered when `is_stale`), in `trending.html` AND `static_trending.html` — 4
template edits (model block + technique block, each live + static), but each
block's live/static snippet stays byte-identical (dates are plain text, no
divergence). Guarded gateways (`load_emerging_candidates`,
`load_emerging_techniques`) are untouched.

### Part B — Momentum windowing (both autopilots)

Both momentum functions take `now` and window first:

- **Model gate** — `has_sustained_download_momentum(observations, now)`: keep
  only `observations` with `observed_at >= now - MOMENTUM_WINDOW_DAYS` (14),
  then apply the existing distinct-days (≥3) / span (≥5) / growth-% (≥25)
  checks to that window. < 2 recent rows → `False` (fail-closed on stale data).
  `promotable_candidates(proposals, observations, *, min_downloads,
  seeded_repos, now)` gains `now` and threads it; the `models promote` CLI
  already computes `datetime.now(UTC)`.
- **Repo source autopilot** — `momentum_stats(rows, now)` /
  `has_sustained_momentum(rows, now)`: the same window filter before the stats.
  The `trending promote` CLI threads its `now` down.

`MOMENTUM_WINDOW_DAYS = 14` sits above the gate's `MIN_SPAN` (5), so a
genuinely-rising candidate still clears it — it just has to be rising recently.
Anchored to `now`, not the latest row, so month-old momentum can't auto-promote.

## Data flow (unchanged shape; recency added)

```
build_{model,technique}_candidates(obs, now)
  → per row: first_seen (earliest), last_seen (latest), is_stale (last_seen < now-4d)
  → Emerging table: … velocity … | Last seen | STALE?

{model promote, trending promote}(…, now)
  → has_sustained_download_momentum / has_sustained_momentum(obs, now)
  → window obs to [now-14d, now] → distinct-days/span/growth checks → promote?
```

## Error handling

No new failure surface. Detection stays pure (`now` a parameter); the guarded
gateways still degrade a corrupt/absent store to an empty section. Windowing is
a pure filter; an empty window → the existing `< 2 rows → not sustained` path
(fail-closed), consistent with the daily-publish invariant.

## Testing (TDD; gates: pytest ≥80% + ruff + mypy)

- `build_model_candidates` / `build_technique_candidates`: `last_seen` = latest
  observation date; `is_stale` boundary (observed today → not stale; newest row
  > 4 days before `now` → stale); existing velocity/ranking/NEW tests unchanged.
- `has_sustained_download_momentum(observations, now)`: strong growth but no
  observation inside the 14-day window → `False`; recent sustained growth →
  `True`; window-edge boundary.
- `momentum_stats` / `has_sustained_momentum(rows, now)`: same windowing for the
  repo autopilot.
- `promotable_candidates(…, now)` + the `trending promote` path thread `now` (a
  stale-but-formerly-hot candidate no longer promotes; a currently-rising one
  still does).
- Templates: STALE badge renders when stale; "Last seen" column present in both
  Emerging blocks, live + static.

## Scope

One implementation plan, ~6 tasks: model Emerging staleness → technique
Emerging staleness → both template blocks (live + static) → model momentum
window → repo momentum window → docs. Two independent parts (surface + gate)
sharing the recency theme; no new dependencies, no new fetch code, guarded
gateways untouched.

## Open items for plan time

- Confirm the exact `now`-threading path for both promote CLIs
  (`models promote` → `promotable_candidates` → `has_sustained_download_momentum`;
  `trending promote` → `has_sustained_momentum`) without breaking existing
  call sites/tests.
- Update existing momentum tests to pass a `now` consistent with their fixture
  observation dates (otherwise the 14-day window filters everything out).
- Tune `STALE_AFTER_DAYS` (4) and `MOMENTUM_WINDOW_DAYS` (14) if the daily
  cadence warrants; reuse existing window constants where sensible.
