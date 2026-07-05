# Trending Radar & Source Autopilot — Design

Date: 2026-07-05
Status: approved (interactive brainstorm; §1–§3 confirmed section-by-section)

## Context

The radar runs itself daily (scan → export → deploy → history commits) and the
**model** catalog grows itself weekly (catalog-autopilot, code-as-gate). But
the **tool** catalog does not grow itself — `radar discover` writes a local,
gitignored proposals file a human promotes by hand — and nothing surfaces
*trending or newly created* repos: discovery observations are thrown away each
run, so there is no velocity for untracked repos, no "new this week", no
trending page, no digest, no shareable content (the "githubsignals" gap).

This program makes the radar **self-growing and content-producing**:

1. Decided: **auto-add with code gates** — the models-autopilot precedent
   extends to tool sources. Code is the gate; thresholds are tunable.
2. Decided: trending output = **/trending page + weekly digest with Atom AND
   RSS feeds + shareable social cards**. NO auto-posting to platforms.
3. Decided: **two lanes** — a strict on-prem/radar-identity lane (drives the
   autopilot and digest headline) and a broader "elsewhere in AI" lane
   (content only, never promotes into the catalog).

## Program decomposition (umbrella)

Four sub-projects, each its own plan (precedent: the academic-radar program).
**This spec fully designs sub-projects 1 and 2**; 3 and 4 are scoped (§5–§6)
and get detail at plan time.

1. **Trending engine**: observation sweep + committed JSONL store + velocity/
   new detection + `radar trending` CLI + daily CI wiring.
2. **Source autopilot**: weekly gated auto-promotion of strict-lane candidates
   into `config/seed-sources.yaml`.
3. **Trending surfaces**: `/trending` page (live + static), index strip + nav,
   MCP `list_trending`.
4. **Digest + cards**: weekly digest page + Atom/RSS newsletter feed + webhook
   post + Mega-branded SVG social cards (PNG rasterized in CI).

## Non-goals

- No auto-posting to social platforms (credentials/ToS burden rejected).
- No technique auto-add — techniques keep the human gate (impl/paper links
  need judgment); this is the deliberate exception to "fully automated".
- No broader-lane promotion into the catalog, ever (identity firewall).
- No github/trending scraping, no GH Archive/BigQuery (keyless public APIs
  only, per repo philosophy).
- No LLM anywhere in the default path.
- No new Python dependencies (SVG generated as strings; PNG rasterization via
  an apt package in CI, not in Python).

## Architecture (decided)

**Approach A — observation store, everything derives from it.** GitHub's
search API cannot report growth, so growth is *observed*: a daily sweep
appends star counts for lens-matching repos to an append-only JSONL committed
by CI (the proven history/metrics-log pattern). Velocity, "new this week",
the trending page, digest, cards, and the autopilot's sustained-momentum gate
all read the same store. Stateless snapshots (no velocity → weak gates) and
external trending data (scraping/BigQuery) were considered and rejected.

## 1. Trending engine (sub-project 1)

### Observation store

`data/trending-observations.jsonl` — append-only, committed daily by
publish.yml in the history-commit block. One row per repo per scan day:

```json
{"repo": "owner/name", "lane": "onprem", "stars": 1234,
 "observed_at": "2026-07-05T07:00:00+00:00",
 "repo_created_at": "2026-06-20T00:00:00+00:00",
 "description": "…", "topics": ["llm", "inference"]}
```

- `lane`: `onprem` (strict) | `broader`.
- Loader mirrors the sibling logs: missing file → `[]`, corrupt lines skipped
  with a warning. ~80 rows/day; compaction is a recorded future option (same
  note as the metrics log), not built now.

### Sweep (`discovery/trending_sweep.py`)

Daily, best-effort (API failure → no new observations + warning; surfaces
render the last committed data). Two curated query sets (module constants,
tunable), each run through the existing retry helper with the CI GitHub
token:

- **Lane `onprem` (strict)**: radar-identity topics and phrases — e.g.
  `topic:llm-inference`, `topic:ai-agents`, `topic:mcp-server`,
  `topic:local-llm`, `topic:self-hosted` + a small set of keyword searches
  ("llm serving", "agent framework"). Exact query strings verified at plan
  time against the live search API.
- **Lane `broader`**: general AI heat — `topic:llm`, `topic:generative-ai`,
  high-star young repos.

Two query *shapes* per lane:

- **Rising candidates**: topic/keyword match + star floor + recently pushed,
  sorted by stars, capped (~top 20 per lane).
- **Born recently**: `created:>{now-14d}` + modest star floor (~50), so
  genuinely new repos are observed before they are big.

Repos already tracked as sources are excluded (their momentum shows on the
radar already). Dedup within a sweep by repo full name; a repo matching both
lanes lands in `onprem` (strict wins).

### Detection (`discovery/trending_detect.py`, pure)

- `star_velocity(rows)` — stars gained ÷ days across the observation window
  (default 7 days), `None` with fewer than 2 observations. Day one of the
  system shows new arrivals only; velocity appears from day two.
- `is_new(row)` — `repo_created_at` within `NEW_WINDOW_DAYS = 14`.
- `TrendingEntry` (frozen): `repo`, `lane`, `stars`, `velocity_per_day:
  float | None`, `is_new: bool`, `first_seen: date`, `description`,
  `topics`.
- `build_trending(observations, now) -> list[TrendingEntry]` — one entry per
  repo from its observation rows; ranking velocity-desc (None last) for the
  main list, stars-desc for the new-arrivals view. `now` is a parameter.

### CLI + CI

- `radar trending scan` — sweep → append observations → one-line summary
  (counts per lane).
- `radar trending list [--lane onprem|broader] [--new]` — table from the
  store: repo, stars, velocity/day, NEW badge, first-seen.
- publish.yml: `radar trending scan` runs daily after the research scan;
  `git add -f data/trending-observations.jsonl` joins the history-commit
  block. Workflow ordering pinned by a text-parse test like its siblings.

## 2. Source autopilot (sub-project 2)

**Strict lane only.** `radar trending promote [--limit 3] [--dry-run]`
evaluates candidates from the observation store against ALL of these gates
(constants tunable, module-level, mirroring the models autopilot):

1. **Sustained momentum**: observations on ≥3 distinct days spanning ≥5
   days; average velocity ≥ 30 stars/day OR total growth ≥ 25% across the
   window. One viral day never qualifies.
2. **Size floor**: ≥ 800 stars at the latest observation.
3. **License allowlist**: repo license fetched per finalist (one API call):
   `apache-2.0, mit, bsd-2-clause, bsd-3-clause, mpl-2.0`. Unknown /
   proprietary / BUSL-style → rejected.
4. **Deterministic category classifier**: topic/keyword → `Category` map
   (HF-papers-discovery pattern). No confident match → NOT auto-added (the
   repo stays visible on the trending page instead). No triage auto-adds.
5. **Denylists + dedup**: org and repo denylists; dedup vs existing sources
   by URL, id, and project name.
6. **Weekly quota**: max 3 auto-adds per run, best velocity first.

**Action**: append a full `SourceConfig` entry to `config/seed-sources.yaml`
— id `github-<slug>`, `type: github_repo`, project = repo display name,
category from the classifier, url, tags = topics (≤5) **plus `auto-added`**
(provenance visible in `radar seed list` and on the site; the prune lever).
Write is validate-or-abort: temp file → `load_config` round-trip → unique-id
check → replace only on success. Every promotion also appends one line to
`data/autopilot-log.jsonl` (repo, date, category, gate stats) — the digest's
"added this week" source and a durable audit trail.

**Schedule**: new `.github/workflows/source-autopilot.yml` — weekly, Monday
07:30 UTC (offset from catalog-autopilot) + manual dispatch: fresh
`trending scan` → `trending promote --limit 3` → inline config-load gate →
commit `config/seed-sources.yaml` + `data/autopilot-log.jsonl` if changed →
`gh workflow run publish.yml`.

**Accepted residual risk** (same shape as the models autopilot): a
well-licensed, high-momentum repo that is genuinely off-mission can slip in;
mitigations are the classifier gate, the denylists, the weekly quota, and
the `auto-added` tag making pruning trivial.

## 3. Trending surfaces (sub-project 3 — scoped)

- `/trending` live + static page pair (models/techniques page shell +
  live/static nav convention): section "On-prem radar candidates" (strict
  lane) and "Elsewhere in AI" (broader lane); columns: repo (GitHub link),
  stars, velocity/day, NEW badge, first-seen, description.
- Index: top-3 strict-lane trending strip + "Trending" nav link (live and
  static).
- MCP: `list_trending(lane: str | None, limit: int)` over the store.
- Daily freshness comes free from the existing publish run.

## 4. Digest + cards (sub-project 4 — scoped)

- `reports/digest.py`: one digest per ISO week assembling: top strict-lane
  trending + best-of broader lane (observation store), sources auto-added
  that week (`autopilot-log.jsonl`), ring changes across all three radars
  (history JSONLs, week-windowed), new models/techniques.
- Published as `digest_<year>-W<week>.html` + "latest digest" link on the
  index; **newsletter-style feeds** `digest.xml` (Atom) and `digest-rss.xml`
  (RSS 2.0), one entry per weekly digest; fire-and-forget webhook post via
  the existing notify channel.
- `web/cards.py`: deterministic SVG strings (unit-testable, zero deps) using
  the existing brand assets — cards for: top-3 strict-lane trending, biggest
  mover of the week, new adopt-ring entries. Two sizes: 1080×1350 (portrait,
  Instagram) and 1200×630 (landscape OG). Written into the export under
  `/cards/`; a CI step (`apt-get install librsvg2-bin`; `rsvg-convert`)
  rasterizes PNG siblings. Font strategy (brand font availability on the CI
  runner vs a safe sans-serif stack in SVG) is a plan-time decision — the
  Mega brand kit itself must never enter the repo beyond the existing web
  assets.
- A weekly `digest-autopilot`-style workflow generates + commits the digest
  so it can never break the daily publish.

## Error handling

| Failure | Behavior |
|---|---|
| GitHub search API down/limited | No new observations; warning; surfaces render last committed store |
| Observation store corrupt lines | Skipped with warning (sibling-log pattern) |
| License/classifier fetch fails for a finalist | That candidate is skipped this week, not guessed |
| Autopilot write invalid | Validate-or-abort: nothing committed, job fails loudly |
| Digest/cards generation fails | Its own workflow fails; daily publish unaffected |

## Testing (TDD, gates: pytest ≥80% + ruff + mypy)

Canned GitHub-search fixtures (no live API in tests); velocity and gate
boundary unit tests (each gate independently + the all-gates path);
validate-or-abort round-trip tests; workflow text-parse ordering tests; SVG
content assertions (brand elements + repo text present, both sizes);
live/static page tests mirroring the existing surface suites; digest
golden-content assertions over fixed fixture data.

## Open items for plan time

- Verify exact GitHub search API query strings, sort options, and
  unauthenticated-vs-token rate limits; confirm `license` field shape on the
  search/repo payloads.
- Confirm `librsvg2-bin` availability on the `ubuntu-latest` runner and the
  font fallback story for `rsvg-convert`.
- Choose the trending-page slug set and dedupe the "Trending" nav label with
  existing nav lengths on mobile.
