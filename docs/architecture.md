# Architecture

A scan is a single deterministic pass: collect signals, attribute them to
tracked projects, score them, calibrate rings across the batch, and persist
both the snapshot (cards) and the diff (history events). Everything else —
reports, dashboard, static export, MCP server — is a read-only view over the
persisted results.

```
                       ┌──────────────────────────────────────────────┐
config/seed-sources    │ orchestrator.RadarOrchestrator._scan         │
  └─ radar init ──▶ data/config.yaml                                  │
                       │                                              │
  collectors/          │  github · rss · manual    (per-source errors │
                       │  degrade to warnings, never abort the scan)  │
  pipeline/classify    │  firehose entries re-attributed to projects  │
                       │  (deterministic match; optional LLM tail)    │
  pipeline/dedupe      │  key = (normalized URL, project)             │
  scoring/             │  7 dimensions + on-prem rubric, deterministic│
  pipeline/cards       │  one card per project; rings calibrated      │
                       │  across the batch (scoring/calibrate)        │
  pipeline/quotas      │  category caps                               │
  pipeline/delta       │  diff vs last persisted cards                │
                       └───────────────┬──────────────────────────────┘
                                       │
              ┌────────────────────────┼─────────────────────────┐
              ▼                        ▼                         ▼
   storage/run_store       storage/database (SQLite)   storage/history_log
   data/runs/<run-id>/     cards cache for readers     data/history.jsonl
   stage artifacts +                                   append-only source of
   report.md etc.                                      truth for the timeline
                                                       (DB is rebuilt from it)
              │                        │                         │
              └──────────┬─────────────┴────────────┬────────────┘
                         ▼                          ▼
              reports/ (markdown, try-this-week,   web/ (FastAPI dashboard,
              history, comparison, sandbox)        static export for Pages)
                                                   mcp_server/ (read-only
                                                   queries over the same data)
```

## Module map

| Package | Responsibility |
| --- | --- |
| `collectors/` | Fetch raw `Signal`s. `github` (releases + repo snapshots), `rss` (feeds, incl. firehose vendor blogs), `manual` (static entries), `registry` (config → collector instances). |
| `enrichment/` | Best-effort observation: `osv` (security advisories), `hackernews` (mention counts), `downloads` (PyPI/npm); `runner` merges them into per-project metrics, every failure degrading to a warning. |
| `pipeline/` | `classify` (firehose re-attribution, + optional `llm_classify`); `dedupe`; `evidence` (signals→metrics→`ProjectEvidence`); `upgrade_risk` (release-note scanning); `momentum` (rising/falling/steady); `delta`; `quotas`; `cards`. |
| `scoring/` | `deterministic` scores 7 dimensions + on-prem rubric (evidence caps security on advisories, lifts maturity on momentum); `rings`; `calibrate` (hybrid absolute + quartile); `profiles` (per-dimension weight presets + re-rank). |
| `storage/` | `config`, `run_store`, `database` (cards cache), `history_store`/`history_log` (timeline projection + durable JSONL truth), `metrics_store` (per-scan observed metrics), `source_health_store` (dead-feed detection), `overrides_store` (pins + trial journal), `seed_store`. |
| `discovery/` | `github_trending` proposes untracked fast-rising repos; `proposals` writes/reads the review-only `proposed-seeds.yaml`. |
| `notify/` | `webhook` posts a fire-and-forget notification on ring changes (generic JSON or Slack format), off by default. |
| `reports/` | Markdown renderers: full report (+ movers, evidence, upgrade-risk, pins), Try This Week, history, comparison, sandbox, JSON export, `movers`, and `feeds` (Atom + JSON change feeds). |
| `web/` | FastAPI dashboard (`app`) and the self-contained static export (`static_site`, with change feeds) used by the Pages workflow. |
| `mcp_server/` | Read-only MCP tools (`queries` + stdio `server`) so agents can ask the radar questions. |

## Key invariants

- **Deterministic core.** The default scan never calls an LLM; identical
  inputs produce identical scores and rings. Keyword scoring uses membership
  checks, never set-iteration order.
- **The JSONL log is the source of truth.** `data/history.jsonl` is
  append-only; the SQLite history table is a rebuildable projection. Corrupt
  lines are skipped with a warning, never fatal. See
  [persistence.md](persistence.md).
- **Collectors degrade, never abort.** A draft release, malformed timestamp,
  broken feed, or network error costs at most that source's signals and is
  recorded in the run meta (`collector_warnings`).
- **Nothing is silently dropped.** Firehose entries that match no tracked
  project are counted and sampled into the run meta; quota cuts and ring
  calibration are bounded and documented in the README.
- **Enrichment and notifications are best-effort.** OSV/HN/download lookups
  and webhooks never fail a scan — failures are logged and recorded in the run
  meta (`enrichment_warnings`). Evidence is collected *input*; the scoring math
  over it stays deterministic.
- **Observed evidence compares against the previous scan.** Metrics are read
  before the current scan's rows are recorded, so star growth and license
  changes reflect change since last time, not against themselves.
- **The human is in the loop, visibly.** Pinned rings (`overrides.yaml`) win
  over computed rings but never hide them — drift is shown. Discovery only ever
  *proposes* sources; nothing is auto-added to the tracked config.
- **Replays don't pollute state.** `scan --replay` re-scores persisted raw
  signals with current config but writes no history, metrics, or card-DB rows.
