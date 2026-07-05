# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and the project aims to follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Changed
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
