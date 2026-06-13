# Evidence Radar v2 — Design

Date: 2026-06-13
Status: approved (interactive scope selection, all items below confirmed)

## Goal

Turn the radar from a tag-driven snapshot tool into an evidence-driven decision
tool: scores grounded in observed data, decisions you can annotate and tune,
risk events (license flips, breaking changes, CVEs) surfaced automatically, and
results that are subscribable and interoperable. The deterministic core remains:
no LLM in the default path, identical inputs → identical decisions.

## Workstreams

### 1. Evidence-based scoring (foundation)

- **`storage/metrics_store.py`** — SQLite table `project_metrics`, one row per
  project per scan: `run_id, observed_at, stars, forks, open_issues, license,
  releases_in_window, downloads_weekly, hn_mentions, advisories_open,
  advisories_max_severity`. Append-only per scan; queries return the latest
  prior row for growth computation.
- **`models.ProjectEvidence`** — immutable, assembled per project before
  scoring: `star_growth, star_growth_pct, releases_in_window, days_since_push,
  advisories (list), hn_mentions, downloads_weekly, license_changed_from`.
  Every field optional; absent evidence means "no adjustment".
- **Scoring integration** — `score_signal(signal, config, evidence=None)`.
  Evidence adjusts dimensions deterministically (e.g. strong star growth or
  release cadence lifts maintenance/open-source-maturity; open HIGH/CRITICAL
  advisories cap `security_posture`). Tag-based logic remains the fallback.
- **Cards** — new `evidence_notes: list[str]` rendered on cards, dashboard,
  and reports ("stars +1,240 (+3.1%) since last scan", "1 open HIGH advisory").

### 2. License change detection

- Falls out of the metrics store: current license vs previous row.
- A flip produces an `evidence_notes` entry + a risk line + an UPDATED delta
  reason ("license changed Apache-2.0 → BUSL-1.1") so it lands in Try This
  Week, history, and (workstream 8) the webhook.

### 3. Upgrade-risk scanning

- Deterministic keyword scan of collected release bodies/highlights:
  BREAKING / migration required / deprecat- / security fix / CVE-….
- Produces `upgrade_risk: none|low|high` + matched phrases on the card, shown
  in reports and Try This Week.

### 4. Enrichment collectors (per-project, config-driven)

Config gains an `enrichment:` block (each enricher individually toggleable,
graceful degradation like existing collectors) and sources gain optional
`package: {ecosystem, name}`:

- **`collectors/osv.py`** — OSV.dev querybatch by package; open advisories +
  max severity feed `ProjectEvidence.advisories` and cap security scores.
- **`collectors/hackernews.py`** — Algolia HN search per project since the
  scan window; ONE aggregated mention-count signal per project (no flooding).
- **`collectors/downloads.py`** — PyPI / npm weekly downloads where a package
  mapping exists; feeds `downloads_weekly`.

Defaults: osv on (it only needs package mappings where provided), hackernews
on, downloads on where mapped. All off-switchable.

### 5. Momentum & movers

- Momentum per project from metrics rows + ring history: `rising | falling |
  steady` (score delta + star growth direction over the last N scans).
- "Movers" section at the top of report.md (ring changes, biggest risers/
  fallers), trend arrows on dashboard + static site, `radar movers` CLI.

### 6. Overrides + decision journal

- **`data/overrides.yaml`** (portable, like history.jsonl): per-project pinned
  ring with reason/author/date, plus trial outcomes
  (`radar trial --project X --outcome adopted|rejected --notes …`).
- Pinned ring wins on cards (displayed as "pinned: avoid (reason)"; computed
  ring still shown). Drift warning when computed ring ≠ pinned ring.
- CLI: `radar override --project X --ring avoid --reason …`,
  `radar override --project X --clear`, `radar trial …`.
- Trial outcomes append history events (visible in timelines).

### 7. Replay / re-score

- `radar scan --replay <run-id>`: skip collectors, load that run's persisted
  `raw_signals.json`, run classify → dedupe → score → calibrate → cards with
  CURRENT config. Writes a new run (marked `replay_of`), does NOT append
  history events or metrics (no fake observations). Offline config tuning.

### 8. Alerts (webhook) + subscribable feeds

- Config `notify: {enabled: false, webhook_url: "${RADAR_WEBHOOK_URL}",
  format: generic|slack}`. After a scan with ring-change deltas, POST JSON
  (generic: structured payload; slack: `{"text": …}` summary). Fire-and-forget
  with 10s timeout; failure logs a warning, never fails the scan.
- Static export also writes `changes.xml` (Atom) + `changes.json` from the
  last 50 history events → the Pages site becomes subscribable.

### 9. Scoring profiles

- Config `profiles: {security-first: {security_posture: 2.0, …}, …}` —
  per-dimension weight multipliers applied to the score average before
  calibration. `radar report --profile X`, `radar scan --profile X` (profile
  recorded in run meta). Default profile = current equal weights.

### 10. Source health

- Track per-source signal counts per scan (run meta / metrics). Sources with
  zero signals for N (default 3) consecutive scans are flagged "stale?" in
  `radar seed list` and the dashboard sources page.

### 11. GitHub trending auto-discovery

- `radar discover [--category X]`: GitHub search for fast-rising repos
  matching per-category topic maps, excluding tracked repos; writes proposals
  with suggested category/tags to `data/proposed-seeds.yaml`. Never auto-adds.

## Build order & dependencies

1 → (2,3 ride on 1) → 4 → 5 → 6 → 7 → 8 → 9 → 10 → 11.
Each phase: TDD, branch-per-phase, gates (pytest --cov ≥80%, ruff, mypy)
before `--no-ff` merge to main.

## Error handling & invariants

- All new network calls: graceful degradation (warn + continue), 10–30s
  timeouts, recorded in `collector_warnings`/run meta. No new hard failures.
- history.jsonl stays append-only; replay runs never write history/metrics.
- Webhook URL only via env expansion; never logged.
- Determinism: enrichment data are *inputs*; scoring math stays pure.
