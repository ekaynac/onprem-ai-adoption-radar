# Untracked Model Candidate Discovery (Trending Hub Phase 2a) — Design

Date: 2026-07-06
Status: approved (interactive brainstorm; §1–§3 confirmed section-by-section)

## Context

The trending hub Phase 1 surfaces *tracked* models & techniques rising within
the catalog. The repo trending radar already discovers *untracked* trending
repos (observation store → velocity → `/trending` lanes → source autopilot).
Models have discovery too — `radar models discover` fetches untracked
HF-trending models via `discover_trending_models` — but it writes a
**gitignored snapshot** (`data/proposed-model-seeds.yaml`), thrown away each
run: no durable velocity, no frontend, and the catalog autopilot promotes on a
single-snapshot download count.

This closes that gap for models (Phase 2a). Phase 2b (untracked papers) is a
separate future spec — the user chose to decompose and do models first because
the discovery + autopilot machinery already exists, so 2a mainly adds the
committed observation store, velocity, a surface, and a momentum gate.

Decided in brainstorming:

1. **Scope: models only (Phase 2a).** Papers = Phase 2b, later, same pattern.
2. **Surface: two labeled sub-sections** under the Phase 1 "Trending Models"
   header — "Rising in the catalog" (Phase 1, tracked) + "Emerging — not yet
   tracked" (Phase 2a candidates, linking out to `huggingface.co`).
3. **Autopilot: add a sustained-velocity promotion gate.** `models promote`
   now requires sustained download momentum (≥3 observation days of growth),
   not just a high absolute download count.

## Non-goals

- No untracked *paper*/technique discovery (Phase 2b).
- No new HF-fetching code — the sweep reuses `discover_trending_models`.
- No network in the render or promote-gate path (only the daily sweep hits HF).
- No new Python dependencies; no LLM.
- No new detail pages — emerging rows link out to `huggingface.co/{repo}`.
- No change to the validate-or-abort write mechanism of `models promote`.

## Architecture

Phase 2a mirrors the repo trending engine + source autopilot, for untracked HF
model candidates. Four pieces:

### Observation store

`data/model-candidate-observations.jsonl` — append-only, committed daily by
publish.yml (the proven history/metrics-log pattern). One row per untracked
candidate per scan day:

```json
{"hf_repo": "owner/name", "name": "Name", "family": "Fam",
 "downloads": 12345, "likes": 42, "observed_at": "2026-07-06T07:00:00+00:00"}
```

`storage/model_candidate_log.py`: `append_model_candidates(path, rows)` /
`load_model_candidates(path)` — hardened guarded read (`errors="replace"` +
`except OSError` + per-line `except ValueError`; missing → `[]`), like
`model_metrics_log.py`.

### Daily sweep

`radar models candidates scan` — wired into publish.yml's scan block next to
`radar models scan`. It calls the **existing** `discover_trending_models(seeds,
client, …)` (which already excludes seeded/tracked repos and returns
untracked HF-trending `ModelProposal`s), maps each to a
`ModelCandidateObservation` stamped `observed_at=now`, and appends to the
store. Best-effort: an HF/network failure yields no new observations + a
warning — the surfaces render the last committed data. No new HF-fetching
logic; we record the existing discovery over time so velocity can emerge.

### Velocity detection (pure)

`discovery/model_candidate_detect.py`:

- `ModelCandidateEntry` (frozen): `hf_repo`, `name`, `family`, `downloads`,
  `downloads_per_day: float | None`, `is_new: bool`, `first_seen: str`.
- `build_model_candidates(observations, now) -> list[ModelCandidateEntry]` —
  one entry per repo from its observation rows; `downloads_per_day` = downloads
  gained ÷ calendar-day span over a window (default 7 days), `None` with fewer
  than 2 in-window rows; `is_new` = `first_seen` within a NEW window (14 days);
  ranked velocity-desc (None last), then downloads-desc. `now` a parameter.
  Day-one shows arrivals only; velocity fills in from day two.
- `has_sustained_download_momentum(rows) -> bool` — ≥3 distinct observation
  days spanning ≥5 days with sustained growth (avg download velocity ≥ a tuned
  floor OR ≥ a growth-% floor). Mirrors the repo source-autopilot's
  `has_sustained_momentum`; the gate the autopilot uses.

## Surfaces

### A — "Emerging" sub-section on `/trending`

Under the Phase 1 "Trending Models" header, below "Rising in the catalog", a
second sub-section **"Emerging — not yet tracked"** renders
`build_model_candidates` from the observation store: columns hf_repo (link to
`https://huggingface.co/{repo}`), downloads, downloads/day, NEW badge,
first-seen. Live + static — both link out to HF (absolute URLs, so no
live/static link divergence, unlike the tracked rows). Extends the Phase 1 hub
machinery; guarded so a corrupt/absent store → empty sub-section, never a 500
or a broken export.

### B — sustained-velocity promotion gate

`models promote` (run weekly by the catalog autopilot) currently promotes any
proposal with `downloads ≥ min_downloads` (plus not-seeded / not-derivative /
not-republisher / modality checks). Phase 2a adds a required check: the
candidate's `hf_repo` must show `has_sustained_download_momentum` in the
committed observation store. The gate becomes *existing checks* **AND**
*sustained momentum* — a flat-but-popular model no longer auto-adds; only
genuinely-rising ones do. A candidate with < 3 observation days isn't promoted
yet — it waits for sustained evidence. The absolute-download floor stays as a
sanity floor, tunable at plan time (likely lowered so a fast-rising newcomer
below the old 100k can qualify on momentum). The validate-or-abort write is
unchanged.

Both surfaces read the same store the daily sweep builds: the page shows all
emerging candidates; the autopilot promotes the subset that clears the gate.

## Data flow

```
radar models candidates scan  (daily, publish.yml)
  → discover_trending_models(seeds)         [existing; untracked HF-trending models]
  → append → data/model-candidate-observations.jsonl  (committed by CI)
        │                                        │
/trending: build_model_candidates(obs, now)  → "Emerging" sub-section
        │
catalog-autopilot (weekly) → models promote → is_promotable(..., candidate_obs)
        → also requires has_sustained_download_momentum → validate-or-abort append
```

Only the CLI/route boundary reads the wall clock (`now`); the detection +
momentum helpers are pure. Once a candidate is promoted, the seeded-exclusion
in `discover_trending_models` drops it from the untracked sweep — the lifecycle
self-manages.

## Error handling

| Failure | Behavior |
|---|---|
| HF/network down during the sweep | No new observations + warning; surfaces render the last committed store |
| Observation store corrupt/absent | Loader skips bad lines / returns `[]`; Emerging sub-section empty; no raise |
| Corrupt store at promote time | No sustained momentum derivable → nothing promoted (fail-closed) |
| Render/export path | Guarded → empty sub-section; `/trending` stays 200 and `radar export` stays green (daily-publish invariant) |
| Day one of the store | One observation → no velocity → NEW-only; fills in from day two |

## Testing (TDD; gates: pytest ≥80% + ruff + mypy)

- `model_candidate_log`: round-trip, missing → `[]`, corrupt-line + non-UTF-8
  skip.
- `build_model_candidates` (pure): velocity window, is_new boundary, ranking,
  day-one single-observation.
- `has_sustained_download_momentum`: boundary cases (days/span/growth).
- Sweep: maps `discover_trending_models` output → observations over a canned
  fixture (no live HF); best-effort degrade.
- `models promote` gate: a candidate with sustained momentum promotes; a
  flat/insufficient-observation one does not (fail-closed).
- Live + static "Emerging" sub-section: renders candidates with HF links;
  corrupt/absent store → empty sub-section, page still renders.
- Publish-workflow text-parse: `models candidates scan` runs daily and
  `data/model-candidate-observations.jsonl` is committed.

## Scope

One implementation plan, ~7 tasks: candidate log → sweep + CLI + CI wiring →
detection (velocity + momentum) → promote gate → Emerging surface (live +
static) → docs. Phase 2b (untracked papers, same pattern) is a separate future
spec.

## Open items for plan time

- Confirm the exact `ModelProposal` → `ModelCandidateObservation` field mapping
  and that `discover_trending_models`' download floor is appropriate for
  candidate observation (vs the higher promote floor).
- Tune `has_sustained_download_momentum`'s velocity/growth floors and the
  promote absolute-download sanity floor (whether to lower it below 100k).
- Confirm how `models promote` loads + groups the observation store by
  `hf_repo` and threads it into `is_promotable` without breaking the existing
  call sites/tests.
