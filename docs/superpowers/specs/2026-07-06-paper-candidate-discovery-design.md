# Untracked Paper Candidate Discovery (Trending Hub Phase 2b) — Design

Date: 2026-07-06
Status: approved (interactive brainstorm; §1–§3 confirmed section-by-section)

## Context

Phase 2a shipped untracked *model* candidate discovery: a committed observation
store fed by the existing `discover_trending_models`, an "Emerging — not yet
tracked" surface on `/trending`, and a sustained-momentum promotion gate. Phase
2b does the same for *papers*, completing the trending-hub program.

The paper machinery already exists — `radar research discover` fetches
candidates via `discover_technique_candidates` (HF daily papers, upvotes) +
`discover_arxiv_candidates` (arXiv), enriches citation velocity, and writes a
gitignored proposals file a human promotes by hand. But it's a snapshot thrown
away each run: no durable velocity, no frontend. Notably `citations_per_day`
today is a *single-observation* proxy (citations ÷ days-since-published), not
observed over time.

Decided in brainstorming:

1. **Rank by upvote velocity, citations secondary.** HF community upvotes are
   the responsive "hot right now" signal (days); citations lag by months, so
   they'd rank genuinely-new papers poorly. Rank by upvotes/day from repeated
   observations; show citation_count for context; arXiv-only papers (no
   upvotes) fall back to their citation signal.
2. **Surface: "Emerging — not yet tracked" under Trending Techniques** — the
   exact mirror of the models Emerging section, one level over in the hub.
3. **No autopilot.** Techniques stay human-gated (the deliberate exception),
   so Phase 2b is observe + surface only — no promotion gate. Candidates still
   feed the existing human-reviewed `research discover` proposals.

## Non-goals

- No autopilot / auto-promotion gate (human-gated — the key difference from
  Phase 2a).
- No new fetching code — the sweep reuses the two existing candidate fetchers.
- No network in the render path (only the daily sweep hits HF/arXiv).
- No new Python dependencies; no LLM.
- No new detail pages — emerging rows link out to `arxiv.org/abs/{arxiv_id}`.

## Architecture

Phase 2b mirrors Phase 2a (observe → velocity → surface), minus the promotion
gate. Three pieces:

### Observation store

`data/technique-candidate-observations.jsonl` — append-only, committed daily by
publish.yml. One row per untracked candidate paper per scan day:

```json
{"arxiv_id": "2501.00001", "name": "Paper Title", "upvotes": 120,
 "citation_count": 9, "published": "2026-06-20",
 "suggested_domain": "reasoning", "suggested_category": "inference",
 "observed_at": "2026-07-06T07:00:00+00:00"}
```

`storage/technique_candidate_log.py`: `TechniqueCandidateObservation` (frozen,
`extra="forbid"`) + `append_technique_candidates` / `load_technique_candidates`
— hardened guarded read (`errors="replace"` + `except OSError` + per-line
`except ValueError`; missing → `[]`) with a naive→UTC `observed_at`
`field_validator` (baked in from the start — the fix Phase 2a needed as a
follow-up).

### Daily sweep

`radar research candidates scan` — wired into publish.yml next to `radar
research scan`. It loads the technique seed and calls the **existing** fetchers
— `discover_technique_candidates(seeds, client)` (HF daily papers) +
`discover_arxiv_candidates(seeds, client, since=now-<N>d)` (arXiv) — both of
which already drop papers whose `arxiv_id` is a tracked technique's paper
(`known_arxiv = {p.arxiv_id for s in seeds for p in s.papers}`). It dedups by
`arxiv_id` (HF wins, as `research discover` already does), optionally enriches
citations via the existing `enrich_proposals_with_velocity`, maps each
`TechniqueProposal` → `TechniqueCandidateObservation` stamped
`observed_at=now`, and appends. Best-effort (fetch failure → no observations +
warning; surfaces render the last committed data). No new fetching logic.

### Velocity detection (pure)

`discovery/technique_candidate_detect.py`:

- `TechniqueCandidateEntry` (frozen): `arxiv_id`, `name`, `upvotes`,
  `upvotes_per_day: float | None`, `citation_count: int | None`, `is_new: bool`,
  `first_seen: str`.
- `build_technique_candidates(observations, now) -> list[TechniqueCandidateEntry]`
  — one entry per `arxiv_id`; `upvotes_per_day` = upvotes gained ÷ calendar-day
  span across a window (default 7 days), `None` with < 2 in-window rows or zero
  span; latest row supplies current upvotes/name/citations; `first_seen` =
  earliest `observed_at` date; `is_new` = first_seen within a NEW window (14
  days); ranked by upvote velocity desc (None last), then citation_count desc,
  then arxiv_id. `now` a parameter.
- `load_emerging_techniques(root, now, *, limit) -> list[TechniqueCandidateEntry]`
  — the guarded gateway (the shape Phase 2a converged on): load observations →
  `build_technique_candidates` → filter out papers now tracked (any `arxiv_id`
  in the current technique seed's `papers`) → cap at `limit` → `try/except →
  []` with a `logger.warning`. Used by BOTH the `/trending` route helper and
  `radar export` — safe from every caller.

## Surface

"Emerging — not yet tracked" sub-section under Trending Techniques (live +
static), the exact mirror of the models Emerging section. Columns: paper name
(link to `https://arxiv.org/abs/{arxiv_id}` — absolute, so the live and static
snippets are identical, no divergence), upvotes, upvotes/day, citations, NEW
badge, first-seen. Guarded via `load_emerging_techniques` so a corrupt/absent
store → empty sub-section; header present when empty; `/trending` stays 200 and
`radar export` stays green.

No promotion gate: candidates feed the human's eye (the surface) and the
existing `research discover` proposal file a person promotes by hand.

## Data flow

```
radar research candidates scan  (daily, publish.yml)
  → discover_technique_candidates(seeds) + discover_arxiv_candidates(seeds, since)  [existing; exclude tracked]
  → dedup by arxiv_id (HF wins) → enrich citations → map → append
  → data/technique-candidate-observations.jsonl  (committed by CI)
        │
/trending: load_emerging_techniques(root, now)  → build_technique_candidates → filter tracked + cap
        → "Emerging" sub-section under Trending Techniques (live + static)
```

Only the CLI/route/export boundary reads the wall clock (`now`); detection is
pure. Once a candidate paper is added to the catalog, the fetchers'
tracked-exclusion drops it from the sweep AND `load_emerging_techniques`
filters it from the surface — the lifecycle self-manages.

## Error handling

| Failure | Behavior |
|---|---|
| HF/arXiv down during the sweep | No new observations + warning; surfaces render the last committed store |
| Observation store corrupt/absent | Loader skips bad lines / returns `[]`; a naive `observed_at` normalizes to UTC; Emerging sub-section empty; no raise |
| Render/export path | `load_emerging_techniques` guarded → empty sub-section; `/trending` stays 200, `radar export` stays green (daily-publish invariant) |
| Day one of the store | One observation → no velocity → NEW-only; fills in from day two |

## Testing (TDD; gates: pytest ≥80% + ruff + mypy)

- `technique_candidate_log`: round-trip, missing → `[]`, corrupt/non-UTF-8
  skip, naive `observed_at` → normalized UTC-aware.
- `build_technique_candidates` (pure): upvote-velocity window, is_new boundary,
  ranking (upvote-desc, None last, citations tiebreak), day-one single-obs.
- Sweep: maps the two fetchers' output → observations over canned fixtures (no
  live network), dedup HF-wins.
- `load_emerging_techniques`: tracked-paper filter (a seeded `arxiv_id`
  excluded), cap, guarded-empty on a corrupt store.
- Live + static "Emerging" sub-section under Trending Techniques: renders
  candidates with arxiv links; corrupt/absent store → empty sub-section, page
  still renders.
- Publish-workflow text-parse: `research candidates scan` runs daily and
  `data/technique-candidate-observations.jsonl` is committed.

## Scope

One implementation plan, ~6 tasks: candidate log → detection (velocity +
guarded gateway) → sweep + CLI + CI → Emerging surface live → static + export →
docs. NO promote-gate task (human-gated). This completes the trending-hub
program (models Phase 2a + papers Phase 2b).

## Open items for plan time

- Confirm the exact `TechniqueProposal` → `TechniqueCandidateObservation` field
  mapping, and whether to run `enrich_proposals_with_velocity` in the sweep (it
  adds a citations fetch — best-effort) or record upvotes-only and skip
  citation enrichment at sweep time.
- Confirm `discover_arxiv_candidates`' `since` window and the HF/arXiv dedup
  order used by `research discover`, to mirror it in the sweep.
- Tune the emerging list cap and the velocity/NEW windows (reuse Phase 2a's
  values unless papers warrant different ones).
