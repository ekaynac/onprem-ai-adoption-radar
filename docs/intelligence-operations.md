# Intelligence operations

This runbook operates the canonical intelligence platform behind the live and
public-static command center.

## Freshness policy

The policy is platform-wide, not source-specific:

| Cadence | Jobs | Expected outcome |
| --- | --- | --- |
| Every two hours | discovery, new-record verification, public export | Major releases appear as `Detected` within two hours with an official or trusted citation. |
| Daily | enrichment, qualification, recommendations, research/trending | Model and platform facts, artifacts, fit assumptions, and decisions are refreshed. |
| Weekly | trusted-claim verification | Changed, missing, stale, or conflicting evidence is surfaced for review. |

Automation is `automated-with-review-exceptions`: deterministic changes proceed
without approval, while ambiguous identity, authoritative conflicts, unsafe
lifecycle transitions, and missing evidence stop at the review queue.

## Scheduler modes

GitHub-hosted operation uses:

- `.github/workflows/intelligence-discovery.yml` for the two-hour release SLO;
- `.github/workflows/publish.yml` for daily enrichment and weekly verification;
- `.github/workflows/ci.yml` for SQLite/Postgres, API, frontend, and browser gates.

For an internal always-on deployment:

```bash
uv run radar intelligence-migrate --root .
uv run radar intelligence-replay-events --root .
uv run radar intelligence-scheduler --root .
```

For externally managed cron or Kubernetes CronJobs, invoke
`radar intelligence-run <kind>` individually. Job leases and schedule-window
idempotency prevent duplicate work.

## Environment

| Variable | Required | Purpose |
| --- | --- | --- |
| `RADAR_DATABASE_URL` | No | SQLAlchemy URL. Defaults to `sqlite:///data/intelligence.db`; use `postgresql+psycopg://…` for shared deployments. |
| `TEST_POSTGRES_URL` | CI only | Runs repository contract tests against PostgreSQL. |
| `GITHUB_TOKEN` | Recommended | Raises GitHub API limits and permits workflow persistence/deployment. |
| `HF_TOKEN` | Optional | Authenticates Hugging Face requests for gated or higher-rate access. |
| `RADAR_API_TOKEN` | Optional | Protects a separately exposed deployment API or reverse proxy. |
| `RADAR_WEBHOOK_SECRET` | For webhooks | HMAC-SHA256 signing secret for event delivery. |

Use a least-privilege GitHub token. The scheduled workflow itself needs
`contents: write`, `pages: write`, and `id-token: write`; source reads do not
need repository administration.

## Storage and recovery

The database is the canonical query store. The append-only
`data/intelligence/events.jsonl` is a portable public event mirror, and
`data/intelligence/snapshots/` holds content-addressed raw evidence. Public
exports contain `data/public-snapshot.v1.json` but never local workspaces.

SQLite backup:

```bash
sqlite3 data/intelligence.db ".backup 'intelligence-backup.db'"
```

PostgreSQL backup and restore:

```bash
pg_dump --format=custom "$RADAR_DATABASE_URL" > intelligence.dump
pg_restore --clean --if-exists --dbname "$RADAR_DATABASE_URL" intelligence.dump
```

After restoring or rebuilding a node:

```bash
uv run radar intelligence-migrate --root .
uv run radar intelligence-replay-events --root .
uv run radar intelligence-shadow --root . --check
```

Run migration and replay twice during a rehearsal; the second pass must report
zero new imports/events.

## Source health and incidents

Each adapter records latency, item count, consecutive failures, and its circuit
state. Five consecutive failures open a two-hour circuit so a broken upstream
cannot consume the whole freshness window.

When a source degrades:

1. Check `/operations` for the failing adapter, last error, and affected claims.
2. Confirm credentials, rate-limit headers, response schema, and system time.
3. Leave uncertain claims visible as stale/unknown; do not manufacture support.
4. Fix or disable the adapter in `config/intelligence-sources.yaml`.
5. Run discovery manually, then verification and the public snapshot invariant.
6. Resolve review exceptions only with cited replacement evidence.

If publishing fails after ingestion, retain the database, event log, and raw
snapshots; rerun export and deployment. If the React cutover itself must be
rolled back, restore the previous Jinja root handler while leaving canonical
ingestion and event persistence running.
