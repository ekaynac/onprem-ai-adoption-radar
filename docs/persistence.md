# Persistence & History Durability

## Intelligence store

The unified command center adds a canonical relational projection alongside the
legacy decision-card store:

```text
data/intelligence.db                       canonical SQLite projection
RADAR_DATABASE_URL=postgresql+psycopg://…  optional shared PostgreSQL projection
data/intelligence/events.jsonl             append-only public event mirror
data/intelligence/snapshots/<sha256>.bin   content-addressed raw evidence
```

The scheduled publisher force-adds the canonical SQLite database and
content-addressed evidence snapshots despite the local `data/*.db` ignore
rule. This preserves complete releases, claims, provenance, compatibility,
and job leases across ephemeral GitHub Actions runners. Local workspace
databases remain ignored and must never be copied into the published lane.

The SQL schema owns publishers, families, releases, evidence, claims,
compatibility assertions, qualifications, lifecycle transitions, review
exceptions, source health, job leases, workspace profiles, events, and webhook
attempts. Alembic migrations are mirrored by deterministic test schema
creation. PostgreSQL runs the same repository contract as SQLite.

Bootstrap and recovery are intentionally idempotent:

```bash
radar intelligence-migrate --root .
radar intelligence-replay-events --root .
radar intelligence-shadow --root . --check
```

Run those commands twice in a migration rehearsal. The second import/replay
must add nothing, and shadow counts/rings/history must remain equivalent.
Back up the SQL database, event mirror, and raw snapshots together when exact
claim provenance is required. The public snapshot is derived and rebuildable.

Workspace profiles are private mutable state in the live local installation.
They are never serialized into `public-snapshot.v1.json`, public events, or
feeds. Deleting a workspace does not alter canonical evidence or public
recommendations.

Rollback is delivery-only: restore the previous Jinja root route while keeping
canonical ingestion, SQL migrations, and append-only events active. No data
downgrade is required.

The radar's accumulated **history** (when each project first appeared, every ring
change over time) is its most valuable, irreplaceable data. This document
explains how it is stored and how to keep it safe when self-hosting.

## The model: event log is the source of truth, SQLite is a cache

```
data/history.jsonl   ← durable source of truth (append-only event log)
data/radar.db        ← fast queryable projection, rebuilt from the log
data/runs/           ← per-scan artifacts (reports); disposable
data/config.yaml     ← your source list
```

- **`data/history.jsonl`** — one JSON object per line, append-only. Every history
  event is written here first. It is plain text: greppable, diff-friendly,
  mergeable, and depends on no service. **This is the file to back up.**
- **`data/radar.db`** — a SQLite database used for fast queries (dashboard, MCP,
  reports). It is a *projection*: on every scan the radar rebuilds it from the
  log, so it is safe to delete. If it is ever lost, the next `radar scan`
  reconstructs the full timeline from `history.jsonl`.

This is deliberately boring and portable: no external database, no cloud service,
no lock-in. A laptop, a Raspberry Pi, a CI runner, and an air-gapped server all
persist history the same way — a single text file you own.

## Who writes the log

To keep the committed timeline free of local noise (spec D5), `radar scan`
defaults to a **local lane**: ring-change events always reach the SQLite
projection, but the JSONL append goes to `data/local/history.jsonl` — a
gitignored, disposable file — instead of the committed `data/history.jsonl`.
Only `radar scan --publish-history` appends to the committed log, and the
`publish.yml` CI workflow is the one caller that passes it. This makes CI the
sole writer of the shared timeline *in the common case*, so laptop/dev scans
never diverge it from what's committed. `data/source-health.jsonl` (per-source
collection outcomes) follows the identical rule: `--publish-history` scans
append to the committed file, everything else appends to the gitignored
`data/local/source-health.jsonl` lane instead — but a scan always rehydrates
the DB projection from the committed log only, never the local one.

One exception: if the committed log is ever missing or empty while the
database still has events, the next scan's legacy backfill (below) regenerates
`data/history.jsonl` from the database — including events that originated from
local scans. On a fresh self-hosted root, pass `--publish-history` from the
very first scan (or delete `data/radar.db` along with the log) to keep the two
lanes clean from the start.

## Guarantees

- **Delete the database, keep the timeline.** `rm data/radar.db` then
  `radar scan` → history is rebuilt from the log. (Verified by tests and live.)
- **No duplicate events.** Rehydration is idempotent (keyed on project + run +
  change type), and a project already in the log is never re-recorded as "new"
  after a database wipe.
- **Legacy backfill.** If you have an older database with history but no log yet,
  the next scan writes the log from the database automatically.

## How to keep your history safe (pick one)

1. **Commit it to your fork (recommended).** The log is small and append-only, so
   it versions beautifully:
   ```bash
   git add -f data/history.jsonl
   git commit -m "chore: update radar history"
   ```
   It is git-ignored by default so casual/test runs don't commit local data;
   `-f` opts in. Now your history is versioned, diffable, and restorable anywhere.

2. **Back up the file.** Copy `data/history.jsonl` to any backup target (rsync,
   object storage, a synced folder). Restore by dropping it back into `data/`.

3. **CI (GitHub Actions).** The publish workflow caches `data/history.jsonl`
   across runs and copies it into the published site (`/history.jsonl`) so the
   full timeline is downloadable and not dependent on the evictable Actions
   cache.

## Moving or sharing a radar

To move a radar to a new machine, copy `data/history.jsonl` (and optionally
`data/config.yaml`). Run `radar scan` — the database is rebuilt and the timeline
continues seamlessly.
