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
| `pipeline/` | `classify` re-attributes firehose entries to tracked projects (with `llm_classify` as an optional, off-by-default second pass); `dedupe`; `delta` computes new/promoted/demoted/updated; `quotas` caps categories; `cards` builds `DecisionCard`s. |
| `scoring/` | `deterministic` scores 7 dimensions + the on-prem rubric from tags/metadata; `rings` maps score → ring; `calibrate` applies hybrid absolute + quartile calibration across the batch. |
| `storage/` | `config` (YAML load/save with env expansion), `run_store` (per-run artifacts), `database` (cards cache), `history_store` (SQLite projection of the timeline), `history_log` (append-only JSONL source of truth), `seed_store` (add sources). |
| `reports/` | Markdown renderers: full report, Try This Week (delta-only), history, comparison matrices, sandbox plans, JSON export. |
| `web/` | FastAPI dashboard (`app`) and the self-contained static export (`static_site`) used by the Pages workflow. |
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
