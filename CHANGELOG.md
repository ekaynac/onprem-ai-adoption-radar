# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and the project aims to follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
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
- Released into the public domain under The Unlicense.

[Unreleased]: https://github.com/ekaynac/onprem-ai-adoption-radar/commits/main
