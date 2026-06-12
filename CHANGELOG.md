# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and the project aims to follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
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

[Unreleased]: https://github.com/OWNER/onprem-ai-adoption-radar/commits/main
