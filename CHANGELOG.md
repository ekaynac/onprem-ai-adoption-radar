# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and the project aims to follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Fixed
- **Frontend readability pass (18 findings)** — an accessibility/contrast audit
  of the web UI surfaced 18 findability and readability issues, all now fixed:
  the hero banner uses the brand's darker shade (`#005F85`, AA-contrast against
  white hero text) instead of the lighter brand blue; dark-mode "watch"/"avoid"
  status tokens are retuned (avoid → `#EC6A60`) so ring/status pill text stays
  AA-compliant against its background in both themes; every table on every
  page (live and static) is now wrapped in a responsive `.table-wrap` so wide
  tables scroll horizontally on narrow viewports instead of breaking layout;
  numeric table columns (params, context, memory, citations, impls, etc.) are
  right-aligned with unit-bearing headers (`Context (tokens)`, `Min mem (GB)`)
  via a shared `td.num, th.num` rule; the techniques catalog gained ring-pill
  parity with the models catalog; hardware-fit verdicts are humanized (5
  verdicts: Fits / Fits (tight) / Fits (quantized) / Won't fit / Unknown)
  instead of raw enum tokens like `wont_fit`; trend arrows are color-coded
  (rising/falling/steady); risk badges plus a legend column make risk levels
  scannable at a glance; ambiguous "Ring"-only columns are now labeled
  "Status" where they mix ring + risk signal; a shared legend explains
  rings/backers/risk on both catalog pages; every page (dashboard, catalogs,
  compare, history, trending, sources, model/technique detail — live and
  static) now renders the same canonical 7-item nav
  (Radar/Models/Research/Trending/Compare/History/Sources, with the static
  site substituting a Changes-feed link where a live-only route doesn't
  exist); `/compare` and `/history` (live and static) were rebuilt onto the
  shared hero/table/footer design system instead of bespoke inline styles;
  and sortable table headers (`/models`, `/research`, live and static) now
  expose `aria-sort="none"` initially and toggle
  `aria-sort="ascending"/"descending"` on the active column on click (siblings
  reset to `"none"`), so assistive tech can track sort state.

- **Data-quality audit fixes (six issues)** — a research-and-model-data audit
  surfaced six correctness bugs, all now fixed: (1) the trending hub mislabeled
  steady (momentum-3) techniques as "rising" — `RISING_MOMENTUM` corrected to
  `4`, matching the canonical momentum scale where 4 means "citations rising
  ≥10%"; (2) technique momentum flapped on citation-index noise — a baseline
  floor (counts < 50 → no signal) and a −2% falling deadband now separate real
  decline from measurement jitter; (3) model ring-change momentum could be
  swayed by a promotion/demotion from months ago — `compute_model_momentum`
  now takes an explicit `now` and only honors ring events from the last 30
  days; (4) a HuggingFace scrape error left `Ornith-1.0-35B` recorded as
  0.664M params (rendering "0.0B" and falsely claiming an 8GB-GPU fit) — the
  seed entry is corrected to 35B, and the autopilot's `plausible_params` guard
  now rejects (drops + warns on) any future scrape more than 5x off a model
  name's declared size token, erring toward dropping the value rather than
  publishing an implausible one; (5) `radar export` now warns (without
  blocking the daily publish) when the technique pages it renders come from a
  missing, empty, or 2+ days stale research run, so a silent
  local-vs-published divergence is now visible instead of invisible; (6)
  technique detail pages gained a "Momentum: {direction} — {note}" line so the
  momentum signal that already drove ranking is now visible to readers, not
  just consumed internally.

### Changed
- **Recency/staleness pass** — Emerging rows on `/trending` now show a "Last
  seen" date and a STALE badge once a candidate stops appearing in the daily
  sweep (its frozen numbers are no longer misleading), and both autopilot
  momentum gates (`models promote`, `trending promote`) now measure sustained
  growth over the last 14 days relative to now — "rising right now", fail-closed
  on stale data — instead of growth since the earliest-ever observation, so the
  gates no longer saturate over time.
- **Absolute feed URLs** — `radar export` gained `--base-url`; when set, the
  Atom (`changes.xml`) and RSS (`changes.rss`) feeds emit absolute self/link
  URLs instead of relative filenames (strict-validator-friendly). The publish
  workflow derives it from the repo context (`https://<owner>.github.io/<repo>`),
  so the published feeds are now self-describing. Local exports default to the
  prior relative behavior.
- **MCP context optimization** — the list tools (`list_recommendations`,
  `try_this_week`) now return a **compact** card by default (project, category,
  backer, ring, score, risk, trend, upgrade-risk, pinned, summary + one
  `headline` evidence line), sorted by score, with a `limit`. This cuts a
  `try_this_week` response from ~13.4k to ~4.1k tokens (~70%; `limit=5` ≈ 520
  tokens). Full payloads remain available via `detail="full"` or
  `get_project(<name>)` — the intended browse-then-drill flow.
- **License: Unlicense → MIT** (© 2026 Enes Kaynakcı). Updated `LICENSE`,
  `pyproject.toml`, README, and CONTRIBUTING accordingly.
- **Company name** shown in credits is now the legal name **Mega Bilgisayar Tic.
  Ltd. Şti.**; site URL corrected to **www.megabilgisayar.com.tr**.

### Added
- **Untracked paper candidate discovery** — a daily `radar research candidates
  scan` records untracked hot arXiv/HF papers (via the existing candidate
  fetchers) into a committed `data/technique-candidate-observations.jsonl`;
  `/trending` shows them in an "Emerging — not yet tracked" sub-section under
  Trending Techniques, ranked by HF-upvote velocity (citations shown as
  secondary), linking to arxiv.org. Papers stay human-gated — no promotion
  gate; the surface just makes emerging work visible for review. Guarded reads
  keep a corrupt store from breaking `/trending` or the export. (Trending hub
  Phase 2b — this completes the models + papers hub.)
- **Untracked model candidate discovery** — a daily `radar models candidates
  scan` records untracked HF-trending models (via the existing
  `discover_trending_models`) into a committed
  `data/model-candidate-observations.jsonl`; `/trending` shows them in an
  "Emerging — not yet tracked" sub-section ranked by download velocity, and
  `radar models promote` now requires **sustained download momentum** (≥3
  observation days over ≥5 with ≥25% growth) before auto-adding a model —
  not just a high absolute download count. Guarded reads keep a corrupt store
  from breaking `/trending`, the export, or promotion. (Trending hub Phase 2a;
  untracked papers are a future phase.)
- **Trending hub for models & techniques** — `/trending` (dashboard + static
  site) now shows "Trending Models" (fastest-rising by download growth) and
  "Trending Techniques" (by citation momentum) sections, each unioned with the
  items added/promoted this ISO week, with a top-model/technique line on the
  index strip. Model download-velocity is made durable across CI runs by a new
  committed `data/model-metrics.jsonl` log (mirroring the technique-metrics
  log). Guarded reads keep a corrupt store from breaking `/trending` or the
  daily export. (Phase 1 — untracked model/paper discovery is a future phase.)
- **Weekly digest + social cards** — `radar digest generate` assembles the
  ISO week's top trending (both lanes), autopilot additions, and ring changes
  across all three radars into `digests/digest_<year>-W<week>.html`, with
  Atom (`digest.xml`) + RSS (`digest-rss.xml`) newsletter feeds built from a
  committed `data/digest-log.jsonl`, a fire-and-forget webhook ping, and
  deterministic Mega-branded SVG cards (Instagram-portrait + OG) rasterized
  to PNG via `rsvg-convert` in a weekly `digest.yml` workflow. Separate from
  the daily publish, so a digest failure never stales the site.
- **Adopt-ring social card** — the weekly digest now emits a third Mega-branded
  card for repos/models/techniques that reached the **adopt** ring during the
  week (completing spec §4's card set); the digest webhook fires once per ISO
  week (a manual re-run no longer re-pings subscribers).
- **Trending surfaces** — a `/trending` page (dashboard + static site) shows
  the two-lane GitHub trending signal (on-prem radar candidates + elsewhere in
  AI) with star velocity, NEW-repo badges, and first-seen dates; the index
  gains a top-3 strip and a Trending nav link, and MCP gains `list_trending`.
  All read the committed observation store — a corrupt store degrades to "no
  trending data" rather than breaking any page.
- **Source autopilot** — `radar trending promote` auto-adds sustained-momentum
  strict-lane trending repos into `config/seed-sources.yaml` behind hard code
  gates (≥3 observation days over ≥5, ≥30 stars/day or ≥25% growth, ≥800
  stars, permissive-license allowlist, a confident deterministic category,
  org/repo denylists, weekly quota, validate-or-abort write). Fully offline —
  it reads the committed observation store (license/stars/topics already
  captured there). Every add is tagged `auto-added` and logged to
  `data/autopilot-log.jsonl`; a weekly `source-autopilot.yml` runs it and
  refreshes the live site. The broader lane never promotes; techniques stay
  human-gated.
- **Trending radar engine** — a daily two-lane GitHub sweep (`radar trending
  scan`) appends repo observations to an append-only
  `data/trending-observations.jsonl` committed by CI; `radar trending list`
  derives star velocity and newly-created-repo flags from it. The strict
  `onprem` lane matches the radar's identity; the `broader` lane catches
  general AI heat. This is the engine the source autopilot and the trending
  surfaces (both coming next) build on.
- **Discovery extras + research-data hardening** — `radar research discover`
  gains an arXiv category sweep (`--source all|hf|arxiv`, keyword-gated like
  the HF source) and ranks all candidates by a deterministic citations/day
  velocity proxy (Semantic Scholar batch, best-effort); `radar research
  track-record` reports each technique's paper→radar lag with a median
  (flag-to-implementation hit-rate stays deferred until history accumulates).
  All research-run reads now go through one guarded loader, so a corrupt or
  schema-drifted research run can no longer break any dashboard page, export,
  scan, or MCP query — it degrades to "no research data" everywhere.
- **Technique discovery + durable citation velocity** — `radar research
  discover` proposes technique candidates from Hugging Face daily papers
  (keyword-gated by title, deduped against the seed, upvote floor) into
  `data/proposed-technique-seeds.yaml` for human review — techniques are never
  auto-added. Citation metrics now dual-write to an append-only
  `data/technique-metrics.jsonl` that the publish workflow commits back;
  a fresh CI checkout rehydrates its metrics store from the log, so published
  citation-velocity momentum finally survives across daily runs (arXiv
  category sweeps and velocity-spike proposals stay deferred).
- **Research pedigree cross-linking** — the three radars now reference each
  other: tool decision cards carry an "Implements N tracked research
  techniques" evidence line (best-effort, never affects scoring), project and
  model pages show the techniques they implement (with rings + citations,
  linked to the technique pages), technique pages link implementations back to
  project/model pages, and MCP `get_project`/`get_model` payloads gain a
  `techniques` list.
- **Academic research radar (surfaces)** — the technique radar is now visible
  everywhere the models radar is: a `/research` catalog page + per-technique
  pages (with a research→production timeline merging paper dates and ring
  history) on both the live dashboard and the static site, a Research summary
  on the index, MCP tools (`list_techniques`, `get_technique`,
  `technique_movers`), Atom/JSON research change feeds
  (`changes-research.xml`/`.json`), a Technique History (JSONL) download, and
  a daily `radar research scan` in the publish workflow. Also fixes the
  scan-health panel to read the latest *tool* scan instead of the latest run
  of any kind.
- **Academic research radar (core)** — research techniques are now a third
  ringed decision surface alongside tools and models. A curated
  `config/technique-seed.yaml` (15 techniques, live-verified arXiv ids) is
  scored on six deterministic dimensions; the key two are **closed-loop**:
  implementation breadth and maturity are computed offline from the radar's
  own tool cards and model history, so research verdicts move when tool
  verdicts move. Citations enrich best-effort (Semantic Scholar batch →
  OpenAlex fallback, same-source-only velocity); zero-implementation or
  superseded techniques cannot rank above `watch`. New CLI:
  `radar research scan | list | show`, per-scan metrics in `radar.db`, and an
  append-only `data/technique-history.jsonl` ring timeline.
- **RSS 2.0 change feed** — the static site now also publishes `changes.rss`
  alongside the existing `changes.xml` (Atom) and `changes.json`, built from the
  same ring-change timeline (newest-first, capped at `_FEED_LIMIT`). Each
  `<item>` is one ring change — title `Cline: watch → pilot (promoted)`,
  description = the human-readable reasons — for the older readers/tools that
  prefer `<rss>` over Atom. It appears in the index/history download lists.
- **Mega Bilişim corporate rebrand** — the dashboard and static site now follow
  the Mega Bilgisayar Tic. Ltd. Şti. design standard: Process Blue `#009FDA` hero
  band with the **real Mega logo** (chameleon + wordmark, white variant on the
  blue band) and a chameleon favicon, Cool Gray surfaces, Centrale Sans
  typography (system-ui fallback), ring/stat accents in the brand palette, a
  subtle Buka dot-pattern on the header and footer, and a Mega attribution
  footer. Light + dark. Design generated with the Open Design app from the
  corporate standard, then ported into the shared `_base_styles` design system
  (so live + static stay identical). Brand assets live in `web/static/brand/`
  (served at `/static` live, copied into the published site): **vector (SVG)**
  logos traced from the original, a favicon, and a bundled **Hanken Grotesk**
  web font (SIL OFL) as a free near-match for the commercial Centrale Sans
  (used via `local()` only, never redistributed).
- **Self-sustaining daily publish** — the publish workflow now commits the
  durable history log back to the repo after each scan (`[skip ci]`). This makes
  the timeline durable in git (not an evictable cache) **and** counts as
  repository activity, so GitHub never auto-disables the daily schedule after 60
  idle days. The public site now runs indefinitely with no manual intervention.
- **Downloadable history** — the full append-only timeline is published as
  `history.jsonl` next to the site (with a "Download data" section in the footer
  and a button on the History page) and served by the dashboard at
  `/history.jsonl`. Change feeds (`changes.json`, `changes.xml`) are linked too.
- **Redesigned dashboard & static site** — a shared design system (one
  `_base_styles.html`, used by live + static so they can't drift): a hero header
  with tagline, a ring-distribution stat bar, ring **pill** badges, a
  rings/backer **legend**, a sticky filter bar, a footer with downloads + source
  link, and automatic dark mode via `prefers-color-scheme`.
- **Provider / backer dimension** — every project is classified by who stands
  behind it: 🏢 Big Tech, 🚀 Startup, 🌐 Community, 👤 Individual, or 🎓 Academic.
  Shown as a colored "Backed by" badge on the dashboard and static index (with a
  new backer filter), on each project page, and in the MCP card payload. Curated
  for all shipped sources via a `backer: {name, type}` field on each source.
- **Evidence-based scoring** — per-scan `metrics_store` records stars, forks,
  license, release cadence; `ProjectEvidence` compares the current scan to the
  previous one. Observed momentum lifts open-source maturity; known OSV.dev
  security advisories cap the security score. Cards gain an "Observed" section.
- **License-change & upgrade-risk detection** — a tracked project's license
  flip is flagged the scan it happens; release notes are scanned for breaking
  changes / migrations / security fixes into an `upgrade_risk` level.
- **Enrichment collectors** — OSV.dev advisories, Hacker News mention counts,
  and PyPI/npm weekly downloads (all on by default, individually togglable,
  best-effort). Sources gain an optional `package: {ecosystem, name}`.
- **Momentum & movers** — `rising`/`falling`/`steady` per project; a Movers
  section opens the report, trend arrows show in the dashboard/static site,
  and a new `radar movers` command.
- **Overrides & decision journal** — `radar override` pins a ring with a
  reason (drift vs the computed ring is surfaced); `radar trial` records
  outcomes. Stored in a portable `data/overrides.yaml`; both journal to the
  timeline.
- **Scoring profiles** — named per-dimension weight presets
  (`security-first`/`solo-dev`/`demo-hunter`); `radar scan --profile` and
  `radar report --profile` re-rank the same data through a lens.
- **Offline replay** — `radar scan --replay <run-id>` re-scores a past run's
  raw signals with current config; no network, no persistence.
- **Source health** — dead-feed detection; `radar seed list` flags sources
  with no signals for several consecutive scans.
- **Auto-discovery** — `radar discover` proposes trending untracked GitHub
  repos to `data/proposed-seeds.yaml` for review (never auto-added).
- **Webhooks & change feeds** — optional post-scan webhook (generic JSON or
  Slack format) on ring changes; the static export publishes `changes.xml`
  (Atom) and `changes.json`.
- **Dashboard search/filter** — the index (live + static) gains a category
  dropdown and text search via a tiny dependency-free inline filter; the static
  "Try This Week" highlight stays unfiltered.
- **Scan health** — each scan's collector/enrichment/firehose warnings (already
  in run meta) are surfaced as a compact "scan health" line on the dashboard,
  the static site, and `radar scan` output.
- **CI scoring gate** — `radar calibrate-report --check` exits non-zero when
  rings stop discriminating; wired into the daily publish workflow so a scoring
  collapse fails the run instead of shipping silently.
- **Wider enrichment coverage** — 9 more projects mapped to PyPI packages
  (OSV advisories + download counts now cover 14, up from 5).
- **Per-project detail pages** — a page per tracked project (live
  `/project/{name}` and static `project_<slug>.html`) showing the full card:
  7-dimension score breakdown, on-prem rubric, evidence notes, upgrade-risk,
  risks, the metrics history table, and the ring timeline. Index pages link to
  them.
- **Scoring backtest** — `radar backtest [--profile X] [--runs N]` re-scores
  past runs and reports how rings would differ (a profile's weights vs default,
  or current config vs each run's persisted decision). Read-only; creates no
  run artifacts.
- **Scoring calibration diagnostic** — `radar calibrate-report` measures
  score spread, ring distribution, evidence impact, and ring stability so you
  can tell whether the rings actually discriminate (read-only, deterministic).
- **Richer read surfaces** — the MCP server and dashboard now expose the v2
  evidence (trend, evidence notes, upgrade-risk, advisories) and human pins.
- **CLI** — `radar seed list` (plain, pipe-friendly source listing) and
  `radar report --json` for scripting.
- **Config refresh** — `radar init --force` rewrites `data/config.yaml` from
  the bundled seed (backing up the existing one as `config.yaml.bak`), so a
  project initialized before later config additions (enrichment, profiles,
  package mappings) can adopt them without a manual merge. Default `init` stays
  non-destructive.
- **Quality gates** — ruff (lint) and mypy (types, pydantic plugin) configured
  and enforced in CI alongside the test suite with an 80% coverage floor;
  CI now tests Python 3.12 and 3.13.
- **Architecture doc** — `docs/architecture.md` with the data flow, module
  map, and the pipeline's key invariants.

### Fixed
- **Collector robustness** — draft GitHub releases (`published_at: null`),
  malformed timestamps, and partial release payloads are skipped instead of
  aborting every GitHub source; RSS responses that don't parse as a feed are
  logged instead of silently yielding nothing; unparseable RSS entry dates
  fall back to "now"; per-collector failures accumulate in the run meta
  (`collector_warnings`) instead of overwriting one another.
- **History durability** — a corrupt line in `data/history.jsonl` is skipped
  with a warning instead of making every future scan fail; history summaries
  order events by `observed_at`, not insertion order, so merged or rehydrated
  logs report correct first-seen/last-change times.
- **Deterministic scoring** — keyword scoring no longer depends on set
  iteration order (the hash seed); same input, same score, every process.
- **Dedupe** — signals are deduplicated per (URL, project) so firehose
  re-attribution can't collapse two projects sharing a link.
- **Report text quality** — release-note highlights no longer leak HTML
  comments, dangling `[text](` fragments, or trailing `by @user in`
  attributions (bot accounts included); RSS summaries are tag-stripped and
  entity-unescaped before they reach a card.
- **Collection pipeline** — GitHub releases, RSS/Atom, registry, and manual
  collectors; deterministic dedupe.
- **Scoring & decision cards** — 7-dimension deterministic scoring plus an
  on-prem adoption rubric, producing per-project decision cards.
- **Hybrid ring calibration** — absolute gates (security/excellence) plus a
  quartile-aware, size-capped relative promotion so rings (`adopt`/`pilot`/
  `watch`/`avoid`) discriminate on real, compressed score distributions.
- **Firehose classification** — broad vendor blogs are re-attributed entry-by-
  entry to tracked projects via normalized name/alias/slug matching; unmatched
  entries are dropped and counted. Optional, off-by-default local LLM analyst for
  the ambiguous tail.
- **Delta report** — a separate "Try This Week" report of only what changed.
- **Durable history** — append-only `data/history.jsonl` event log as the source
  of truth, with SQLite as a rebuildable cache; survives a lost database.
- **Comparison matrices** — side-by-side project comparison by category or set.
- **Sandbox playbooks** — per-tool disposable trial recipes.
- **MCP server** — `list_recommendations`, `try_this_week`, `get_project`,
  `list_tracked_projects`, `compare`, `sandbox_plan`.
- **Local dashboard** (cards, compare, history, add-source form) and **static
  export** (index + compare + history) for GitHub Pages.
- **Fun/experimental category** for playful local-AI projects.
- **CI** (tests on push/PR) and **scheduled publish** to GitHub Pages.
- Released under the MIT License.

[Unreleased]: https://github.com/ekaynac/onprem-ai-adoption-radar/commits/main
