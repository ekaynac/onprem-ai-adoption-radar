# Persistence & History Durability

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
