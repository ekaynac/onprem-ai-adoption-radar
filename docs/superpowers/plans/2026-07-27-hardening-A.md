# Sub-project A: Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop collection outages from corrupting rings/history, make source failures visible, repair the 21 outage-polluted runs via corrective events, make source-health durable, gate broken catalog entries, and clean up strays — Phase 0 of the capacity-planning radar v3 spec (`docs/superpowers/specs/2026-07-27-capacity-planning-radar-v3-design.md`).

**Architecture:** Collectors gain per-source failure reporting; the orchestrator records per-source outcomes (`ok|empty|error`) and aborts before scoring when the error rate crosses a threshold; history gains a `corrected` change type + an "effective view" filter; a one-off repair command neutralizes outage artifacts; source health gets an append-only JSONL log mirroring `history.jsonl`.

**Tech Stack:** Python 3.12, pydantic v2, typer, httpx, sqlite3, pytest. Run everything with `uv run`.

## Global Constraints

- Deterministic core: no LLM, no randomness in any new scoring/gating path.
- `data/history.jsonl` is append-only — events are NEVER rewritten or deleted; corrections are new appended events (spec D1).
- Collectors degrade, never abort: a failing source costs its own signals only. The new gate stops the run *after* collection, before scoring.
- Enrichment/notify stay best-effort and must never fail a scan.
- Immutability style: pydantic models frozen where existing ones are; return new objects, don't mutate inputs.
- Gates before commit: `uv run pytest -q && uv run ruff check . && uv run mypy src`.
- Coverage ≥80% is enforced; every new module ships with tests.
- Commit format `<type>: <description>` (feat/fix/refactor/docs/test/chore). NO Co-Authored-By line (attribution disabled globally).
- Do not touch `data/history.jsonl`, `data/*.jsonl`, or `radar.db` contents in git except where a task explicitly says so.

---

### Task 1: GitHubCollector failure reporting + missing-token warning

58/68 sources are GitHub repos whose failures never reach `collector_warnings` (`orchestrator.py:218` reads `getattr(collector, "warnings", [])`; only `RSSCollector` defines it). Also no warning when `GITHUB_TOKEN` is unset.

**Files:**
- Modify: `src/radar/collectors/github.py`
- Test: `tests/test_collectors_github.py` (append)

**Interfaces:**
- Consumes: nothing new.
- Produces: `GitHubCollector.warnings: list[str]`, `GitHubCollector.failed_source_ids: set[str]` (Task 3 consumes both). Warning strings formatted `"github <source_id>: <what> failed: <reason>"`, token warning `"github: GITHUB_TOKEN not set; <N> repo sources share the 60 req/hr unauthenticated limit"`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_collectors_github.py`; reuse that file's existing fake-client style if one exists, else use these self-contained fakes):

```python
import httpx
import pytest

from radar.collectors.github import GitHubCollector
from radar.models import SourceConfig


class _FailingClient:
    async def get(self, url, **kwargs):
        raise httpx.ConnectError("boom")


def _gh_source(i: int = 1) -> SourceConfig:
    return SourceConfig(
        id=f"github-proj{i}", type="github_repo", project=f"Proj{i}",
        category="model_serving", url=f"https://github.com/org/proj{i}",
    )


@pytest.mark.anyio
async def test_failed_repo_fetch_records_warning_and_failed_source(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    collector = GitHubCollector([_gh_source()], client=_FailingClient())
    from datetime import UTC, datetime

    signals = await collector.fetch(datetime(2026, 1, 1, tzinfo=UTC))

    assert signals == []
    assert "github-proj1" in collector.failed_source_ids
    assert any("github-proj1" in w for w in collector.warnings)


@pytest.mark.anyio
async def test_missing_token_warning_only_with_many_sources(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    from datetime import UTC, datetime

    many = GitHubCollector([_gh_source(i) for i in range(1, 7)], client=_FailingClient())
    await many.fetch(datetime(2026, 1, 1, tzinfo=UTC))
    assert any("GITHUB_TOKEN not set" in w for w in many.warnings)

    few = GitHubCollector([_gh_source(1)], client=_FailingClient())
    await few.fetch(datetime(2026, 1, 1, tzinfo=UTC))
    assert not any("GITHUB_TOKEN" in w for w in few.warnings)
```

If the existing file lacks an anyio/asyncio marker convention, match whatever it already uses (check its head for `pytest.mark.asyncio` vs `anyio`) — keep consistent.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_collectors_github.py -q`
Expected: FAIL — `AttributeError: 'GitHubCollector' object has no attribute 'failed_source_ids'`.

- [ ] **Step 3: Implement.** In `src/radar/collectors/github.py`:

In `__init__` (after `self.base_url = ...`):

```python
        # Per-source soft failures, harvested by the orchestrator into the
        # run's collector_warnings (same contract as RSSCollector.warnings).
        self.warnings: list[str] = []
        # Sources whose fetch errored (vs. legitimately returned nothing) —
        # feeds source-health outcome recording.
        self.failed_source_ids: set[str] = set()
```

Add a module-level helper (above the class):

```python
def _reason(exc: Exception) -> str:
    """Non-empty failure reason: some httpx errors stringify to ''."""
    return str(exc).strip() or exc.__class__.__name__
```

At the top of `fetch()` (before the source loop):

```python
        enabled = [s for s in self.sources if s.enabled]
        if os.getenv("GITHUB_TOKEN") is None and len(enabled) > 5:
            self.warnings.append(
                f"github: GITHUB_TOKEN not set; {len(enabled)} repo sources "
                "share the 60 req/hr unauthenticated limit"
            )
```

In `_fetch_repo_snapshot`'s `except` branch, replace the body with:

```python
        except (KeyError, httpx.HTTPError) as exc:
            message = f"github {source.id}: repo snapshot failed: {_reason(exc)}"
            logger.warning(message)
            self.warnings.append(message)
            self.failed_source_ids.add(source.id)
            return None
```

In `_fetch_releases`'s `except httpx.HTTPError` branch, replace the body with:

```python
        except httpx.HTTPError as exc:
            message = f"github {source.id}: releases fetch failed: {_reason(exc)}"
            logger.warning(message)
            self.warnings.append(message)
            self.failed_source_ids.add(source.id)
            return []
```

In `fetch()`, the invalid-URL branch also appends: `self.warnings.append(f"github {source.id}: invalid GitHub URL, skipped")`.

- [ ] **Step 4: Run tests** — `uv run pytest tests/test_collectors_github.py -q` → PASS. Then full gates: `uv run pytest -q && uv run ruff check . && uv run mypy src`.

- [ ] **Step 5: Commit** — `git add -A src/radar/collectors/github.py tests/test_collectors_github.py && git commit -m "fix: GitHub collector reports per-source failures and missing-token warning"`

---

### Task 2: Non-empty enrichment warnings + OSV/HN retry + bigger retry budget

Run-20260726 meta contains warnings like `"enrichment osv:Aider failed: "` (empty reason — some httpx exceptions stringify empty). OSV and HN bypass `get_with_retry`/`post_with_retry` (unretried 429s); pypistats 429s exhausted the small budget (`MAX_RETRIES=3`, max sleep 5s).

**Files:**
- Modify: `src/radar/enrichment/runner.py:128-135` (`_safe`), `src/radar/enrichment/osv.py:31-36`, `src/radar/enrichment/hackernews.py:22-31`, `src/radar/enrichment/retry.py:22-25`
- Test: `tests/test_enrichment.py` (append), `tests/test_retry_post.py` (check pinned constants)

**Interfaces:**
- Consumes: `get_with_retry(client, url, *, label, **kwargs)` / `post_with_retry(client, url, *, label, **kwargs)` from `radar.enrichment.retry` (existing).
- Produces: no signature changes; constants become `MAX_RETRIES = 4`, `RETRY_MAX_SLEEP_SECONDS = 30.0`.

- [ ] **Step 1: Write failing tests** (append to `tests/test_enrichment.py`):

```python
import httpx
import pytest


@pytest.mark.anyio
async def test_safe_warning_reason_never_empty():
    from radar.enrichment.runner import _safe

    async def _boom():
        raise httpx.ConnectError("")  # stringifies to ""

    warnings: list[str] = []
    result = await _safe(_boom(), "osv:Aider", warnings)
    assert result is None
    assert warnings == ["enrichment osv:Aider failed: ConnectError"]


class _Flaky429Client:
    """First call returns 429, second succeeds — retry must absorb the 429."""

    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    def _response(self):
        self.calls += 1
        status = 429 if self.calls == 1 else 200
        return httpx.Response(
            status, json=self.payload, headers={"Retry-After": "0"},
            request=httpx.Request("GET", "https://x"),
        )

    async def get(self, url, **kwargs):
        return self._response()

    async def post(self, url, **kwargs):
        return self._response()


@pytest.mark.anyio
async def test_hn_mentions_retries_429():
    from datetime import UTC, datetime
    from radar.enrichment.hackernews import fetch_hn_mentions

    client = _Flaky429Client({"nbHits": 7})
    count = await fetch_hn_mentions("vLLM", client, since=datetime(2026, 1, 1, tzinfo=UTC))
    assert count == 7
    assert client.calls == 2


@pytest.mark.anyio
async def test_osv_retries_429():
    from datetime import UTC, datetime
    from radar.enrichment.osv import fetch_recent_advisories
    from radar.models import PackageRef

    client = _Flaky429Client({"vulns": []})
    found = await fetch_recent_advisories(
        PackageRef(ecosystem="PyPI", name="vllm"), client,
        now=datetime(2026, 1, 1, tzinfo=UTC), window_days=90,
    )
    assert found == []
    assert client.calls == 2
```

(Match the file's existing async marker convention, as in Task 1. Check `PackageRef`'s actual field names in `src/radar/models.py` before running — adjust if they differ.)

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_enrichment.py -q`. Expected: the `_safe` test fails on message mismatch; the 429 tests fail with `httpx.HTTPStatusError` (no retry today).

- [ ] **Step 3: Implement.**

`runner.py` `_safe` except branch:

```python
    except Exception as exc:
        reason = str(exc).strip() or exc.__class__.__name__
        message = f"enrichment {label} failed: {reason}"
        logger.warning(message)
        warnings.append(message)
        return None
```

`osv.py`: add `from radar.enrichment.retry import post_with_retry`; replace the `client.post(...)` + `response.raise_for_status()` pair with:

```python
    response = await post_with_retry(
        client,
        OSV_QUERY_URL,
        label=f"osv {package.name}",
        json={"package": {"ecosystem": package.ecosystem, "name": package.name}},
    )
```

`hackernews.py`: add `from radar.enrichment.retry import get_with_retry`; replace `client.get(...)` + `raise_for_status()` with:

```python
    response = await get_with_retry(
        client,
        HN_SEARCH_URL,
        label=f"hackernews {project}",
        params={
            "query": f'"{project}"',
            "tags": "story",
            "numericFilters": f"created_at_i>{int(since.timestamp())}",
            "hitsPerPage": 0,
        },
    )
```

`retry.py`: `MAX_RETRIES = 4`, `RETRY_MAX_SLEEP_SECONDS = 30.0` (Retry-After values up to 30s now honored instead of clamped to 5s).

- [ ] **Step 4: Fix pinned constants.** `uv run pytest tests/test_retry_post.py tests/test_enrichment.py -q` — if `test_retry_post.py` (or any other test) pins `MAX_RETRIES == 3` or the 5.0 clamp, update those assertions to 4 / 30.0 deliberately.

- [ ] **Step 5: Full gates** — `uv run pytest -q && uv run ruff check . && uv run mypy src` → PASS.

- [ ] **Step 6: Commit** — `git commit -am "fix: retry OSV/HN enrichers, raise retry budget, never-empty warning reasons"`

---

### Task 3: Per-source outcome recording (`ok|empty|error`)

Today `source_health` rows record only a count — "feed published nothing" and "we couldn't reach it" are indistinguishable, which poisons stale-feed detection and enables outage churn.

**Files:**
- Modify: `src/radar/storage/source_health_store.py`, `src/radar/orchestrator.py:201-233` (`_collect_raw`)
- Test: `tests/test_source_health.py` (append), `tests/test_orchestrator.py` (append)

**Interfaces:**
- Consumes: `collector.warnings`, `collector.failed_source_ids` (Task 1), `collector.sources`.
- Produces:
  - `SourceHealthStore.record(run_id: str, observed_at: datetime, counts: dict[str, int], statuses: dict[str, str] | None = None) -> None` — `statuses` values are `"ok"|"empty"|"error"`; when omitted, derived as `"ok" if count > 0 else "empty"`.
  - `stale_source_ids()` ignores `status='error'` rows (they are not evidence of a quiet feed); legacy `NULL` rows still count.
  - `CollectionHealth` frozen dataclass in `radar/orchestrator.py`: `total_sources: int`, `errored_sources: int`, property `error_fraction: float` (0.0 when no sources).
  - `_collect_raw` returns `tuple[list[Signal], CollectionHealth]`.

- [ ] **Step 1: Write failing store tests** (append to `tests/test_source_health.py`):

```python
def test_record_with_statuses_and_error_rows_excluded_from_stale(tmp_path):
    from datetime import UTC, datetime
    from radar.storage.source_health_store import SourceHealthStore

    store = SourceHealthStore(tmp_path / "radar.db")
    store.initialize()
    when = datetime(2026, 7, 1, tzinfo=UTC)
    # 7 scans of zero: 4 genuine empties + 3 network errors.
    for i in range(4):
        store.record(f"run-empty-{i}", when, {"rss-x": 0}, {"rss-x": "empty"})
    for i in range(3):
        store.record(f"run-err-{i}", when, {"rss-x": 0}, {"rss-x": "error"})
    # Only 4 non-error zero scans -> below the 7-scan window -> not stale.
    assert store.stale_source_ids() == set()
    # 3 more genuine empties -> 7 non-error zeros -> stale.
    for i in range(3):
        store.record(f"run-empty2-{i}", when, {"rss-x": 0}, {"rss-x": "empty"})
    assert store.stale_source_ids() == {"rss-x"}


def test_record_derives_status_when_omitted(tmp_path):
    import sqlite3
    from datetime import UTC, datetime
    from radar.storage.source_health_store import SourceHealthStore

    store = SourceHealthStore(tmp_path / "radar.db")
    store.initialize()
    store.record("run-1", datetime(2026, 7, 1, tzinfo=UTC), {"a": 3, "b": 0})
    with sqlite3.connect(tmp_path / "radar.db") as conn:
        rows = dict(conn.execute("SELECT source_id, status FROM source_health"))
    assert rows == {"a": "ok", "b": "empty"}


def test_initialize_migrates_legacy_table(tmp_path):
    import sqlite3
    from datetime import UTC, datetime
    from radar.storage.source_health_store import SourceHealthStore

    # Simulate a pre-status database.
    with sqlite3.connect(tmp_path / "radar.db") as conn:
        conn.execute(
            "CREATE TABLE source_health (id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " source_id TEXT NOT NULL, run_id TEXT NOT NULL,"
            " observed_at TEXT NOT NULL, signal_count INTEGER NOT NULL)"
        )
    store = SourceHealthStore(tmp_path / "radar.db")
    store.initialize()  # must add the column, not crash
    store.initialize()  # idempotent
    store.record("run-1", datetime(2026, 7, 1, tzinfo=UTC), {"a": 1})
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_source_health.py -q` → FAIL (`no such column: status` / unexpected keyword `statuses`).

- [ ] **Step 3: Implement store.** In `source_health_store.py`:

`initialize()` — after the existing CREATE/INDEX statements:

```python
            # Migration: pre-2026-07 tables lack the status column. ALTER is
            # idempotent-by-exception: "duplicate column name" means done.
            try:
                conn.execute("ALTER TABLE source_health ADD COLUMN status TEXT")
            except sqlite3.OperationalError as exc:
                if "duplicate column name" not in str(exc):
                    raise
```

`record()` — new signature and insert:

```python
    def record(
        self,
        run_id: str,
        observed_at: datetime,
        counts: dict[str, int],
        statuses: dict[str, str] | None = None,
    ) -> None:
        """One row per source for this scan. status: ok|empty|error.

        Without an explicit status a source is 'ok' if it produced signals,
        'empty' otherwise. 'error' means the fetch failed — an empty result
        that must NOT count as evidence the feed is dead.
        """
        if not counts:
            return
        statuses = statuses or {}
        with sqlite3.connect(self.path) as conn:
            conn.executemany(
                "INSERT INTO source_health(source_id, run_id, observed_at, signal_count, status) "
                "VALUES (?, ?, ?, ?, ?)",
                [
                    (
                        source_id,
                        run_id,
                        observed_at.isoformat(),
                        count,
                        statuses.get(source_id, "ok" if count > 0 else "empty"),
                    )
                    for source_id, count in counts.items()
                ],
            )
```

`stale_source_ids()` — change the per-source window query to exclude error rows:

```python
                recent = conn.execute(
                    "SELECT signal_count FROM source_health WHERE source_id = ? "
                    "AND (status IS NULL OR status != 'error') "
                    "ORDER BY observed_at DESC, id DESC LIMIT ?",
                    (source_id, window),
                ).fetchall()
```

- [ ] **Step 4: Store tests pass** — `uv run pytest tests/test_source_health.py -q` → PASS.

- [ ] **Step 5: Write failing orchestrator test** (append to `tests/test_orchestrator.py`; the RSS URL points at a closed local port so the fetch errors fast):

```python
def test_collect_records_error_status_for_unreachable_source(tmp_path: Path):
    import sqlite3

    initialize_project(tmp_path)
    (tmp_path / "data" / "config.yaml").write_text(
        """
version: "1.0"
sources:
  - id: mcp-docs
    type: manual
    enabled: true
    project: Model Context Protocol
    category: mcp_tooling
    url: https://modelcontextprotocol.io/docs/getting-started/intro
    tags: [mcp]
  - id: rss-dead
    type: rss
    enabled: true
    project: DeadFeed
    category: model_serving
    url: http://127.0.0.1:1/feed.xml
    tags: []
quotas:
  mcp_tooling: 4
  model_serving: 4
scoring:
  default_ring: watch
""",
        encoding="utf-8",
    )

    RadarOrchestrator(root=tmp_path).scan(days=2)

    with sqlite3.connect(tmp_path / "data" / "radar.db") as conn:
        rows = dict(conn.execute("SELECT source_id, status FROM source_health"))
    assert rows["rss-dead"] == "error"
    assert rows["mcp-docs"] == "ok"
```

RSSCollector today appends a warning but exposes no failed ids — this test forces the orchestrator to derive error status from warnings-bearing collectors. Give `RSSCollector` the same `failed_source_ids: set[str]` attribute (initialize in `__init__`, add `self.failed_source_ids.add(source.id)` in `_fetch_source`'s `except httpx.HTTPError` branch of `src/radar/collectors/rss.py:50-54`).

- [ ] **Step 6: Implement orchestrator wiring.** In `orchestrator.py`:

Add near the top (after imports):

```python
@dataclass(frozen=True)
class CollectionHealth:
    """How collection went: the input for the degraded-run gate."""

    total_sources: int
    errored_sources: int

    @property
    def error_fraction(self) -> float:
        if self.total_sources == 0:
            return 0.0
        return self.errored_sources / self.total_sources
```

Rework `_collect_raw` (keep existing behavior, add outcome tracking; new return type `tuple[list[Signal], CollectionHealth]`):

```python
        async with httpx.AsyncClient(timeout=30.0) as client:
            collectors = build_collectors(config, client)
            raw: list[Signal] = []
            collector_warnings: list[str] = []
            failed_source_ids: set[str] = set()
            for collector in collectors:
                try:
                    raw.extend(await collector.fetch(since))
                except Exception as exc:
                    collector_warnings.append(f"{collector.__class__.__name__}: {exc}")
                    # The whole collector died: every enabled source it owns errored.
                    failed_source_ids.update(
                        s.id for s in getattr(collector, "sources", []) if s.enabled
                    )
                collector_warnings.extend(getattr(collector, "warnings", []))
                failed_source_ids.update(getattr(collector, "failed_source_ids", set()))
            if collector_warnings:
                self.run_store.update_meta(run_id, {"collector_warnings": collector_warnings})
```

After the existing `source_counts` computation, replace the `record` call with:

```python
        statuses = {
            source_id: (
                "error" if source_id in failed_source_ids
                else "ok" if count > 0
                else "empty"
            )
            for source_id, count in source_counts.items()
        }
        self.source_health.record(run_id, datetime.now(UTC), source_counts, statuses)
        health = CollectionHealth(
            total_sources=len(source_counts),
            errored_sources=sum(1 for s in statuses.values() if s == "error"),
        )
        return raw, health
```

In `_scan`, change the call site to `raw, health = await self._collect_raw(config, run_id, since)` (`health` is consumed by Task 4; unused for now — name it `_health` until Task 4 to keep ruff quiet, then rename).

- [ ] **Step 7: Full gates** — `uv run pytest -q && uv run ruff check . && uv run mypy src` → PASS.

- [ ] **Step 8: Commit** — `git commit -am "feat: per-source ok/empty/error outcomes in source health; errors excluded from stale detection"`

---

### Task 4: Degraded-run gate — outages stop before scoring

21/48 recorded scans were near-total collection failures scored and written into history as real observations. New invariant (spec §9): **a degraded run never writes rings, history, metrics, or cards.**

**Files:**
- Modify: `src/radar/constants.py` (add threshold), `src/radar/orchestrator.py` (`ScanResult`, `_scan`), `src/radar/cli.py:93-133` (`scan`)
- Test: `tests/test_scan_gate.py` (new)

**Interfaces:**
- Consumes: `CollectionHealth` (Task 3).
- Produces:
  - `DEGRADED_SOURCE_ERROR_THRESHOLD = 0.5` in `radar/constants.py`.
  - `ScanResult` gains `degraded: bool = False`, `degraded_reason: str | None = None`.
  - Run meta keys: `"degraded": True`, `"degraded_reason": str` (Task 5 consumes).
  - CLI: `radar scan` exits code 2 on a degraded run.

- [ ] **Step 1: Write failing tests** (`tests/test_scan_gate.py`, new file — config helper mirrors `tests/test_orchestrator.py`):

```python
"""Degraded-run gate: collection outages must not reach scoring or history."""

from pathlib import Path

from radar.init_project import initialize_project
from radar.orchestrator import RadarOrchestrator


def _write_config(tmp_path: Path, n_dead_rss: int, with_manual: bool) -> None:
    sources = ""
    if with_manual:
        sources += """
  - id: mcp-docs
    type: manual
    enabled: true
    project: Model Context Protocol
    category: mcp_tooling
    url: https://modelcontextprotocol.io/docs/getting-started/intro
    tags: [mcp]
"""
    for i in range(n_dead_rss):
        sources += f"""
  - id: rss-dead-{i}
    type: rss
    enabled: true
    project: DeadFeed{i}
    category: model_serving
    url: http://127.0.0.1:1/feed-{i}.xml
    tags: []
"""
    (tmp_path / "data" / "config.yaml").write_text(
        f"""
version: "1.0"
sources:{sources}
quotas:
  mcp_tooling: 4
  model_serving: 12
scoring:
  default_ring: watch
""",
        encoding="utf-8",
    )


def test_outage_run_is_degraded_and_writes_no_history(tmp_path: Path):
    initialize_project(tmp_path)
    _write_config(tmp_path, n_dead_rss=3, with_manual=True)  # 3/4 sources error

    result = RadarOrchestrator(root=tmp_path).scan(days=2)

    assert result.degraded is True
    assert result.degraded_reason and "3/4" in result.degraded_reason
    assert result.cards == []
    assert result.deltas == []
    # Nothing durable was written.
    assert not (tmp_path / "data" / "history.jsonl").exists()
    run_dir = tmp_path / "data" / "runs" / result.run_id
    assert (run_dir / "raw_signals.json").exists()  # evidence is kept
    assert not (run_dir / "decision_cards.json").exists()

    import json

    meta = json.loads((run_dir / "meta.json").read_text())
    assert meta["degraded"] is True


def test_healthy_run_is_not_degraded(tmp_path: Path):
    initialize_project(tmp_path)
    _write_config(tmp_path, n_dead_rss=0, with_manual=True)

    result = RadarOrchestrator(root=tmp_path).scan(days=2)

    assert result.degraded is False
    assert len(result.cards) == 1
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_scan_gate.py -q` → FAIL (`ScanResult` has no `degraded`).

- [ ] **Step 3: Implement.**

`src/radar/constants.py` — append:

```python
# A scan whose source error-rate reaches this fraction is a collection outage:
# it is recorded (raw signals + meta) but never scored — scoring near-empty
# input produces artificial ring churn (see 2026-07-27 hardening spec).
DEGRADED_SOURCE_ERROR_THRESHOLD = 0.5
```

`orchestrator.py` — `ScanResult` gains fields (with defaults so existing constructor calls stay valid):

```python
    degraded: bool = False
    degraded_reason: str | None = None
```

In `_scan`, right after `raw, health = await self._collect_raw(...)`:

```python
        if health.error_fraction >= DEGRADED_SOURCE_ERROR_THRESHOLD:
            reason = (
                f"collection outage: {health.errored_sources}/{health.total_sources} "
                "sources failed — run recorded but not scored"
            )
            self.run_store.update_meta(run_id, {"degraded": True, "degraded_reason": reason})
            report_path = self.run_store.save_report(
                run_id, f"# Degraded run\n\n{reason}\n"
            )
            return ScanResult(
                run_id=run_id, cards=[], report_path=report_path,
                delta_report_path=report_path, history_report_path=report_path,
                deltas=[], degraded=True, degraded_reason=reason,
            )
```

Import the constant: `from radar.constants import DEGRADED_SOURCE_ERROR_THRESHOLD`.

`cli.py` `scan` — after `result = orchestrator.scan(...)`:

```python
    if result.degraded:
        console.print(f"[red]DEGRADED:[/red] {result.degraded_reason}")
        console.print("No cards, history, or metrics were written.")
        raise typer.Exit(code=2)
```

- [ ] **Step 4: Run tests** — `uv run pytest tests/test_scan_gate.py tests/test_orchestrator.py -q` → PASS (note: the Task 3 error-status test scans with 1 dead source out of 2 = 0.5 fraction → now degraded; that test only asserts source_health rows, which are written before the gate, so it still passes — verify).

- [ ] **Step 5: Full gates** — `uv run pytest -q && uv run ruff check . && uv run mypy src` → PASS.

- [ ] **Step 6: Commit** — `git commit -am "feat: degraded-run gate — collection outages are recorded, never scored"`

---

### Task 5: `radar scan-health --check` + publish workflow gate

`calibrate-report --check` reads the upserted DB union, so it cannot detect a collapsed run. Publish must gate on the *run*.

**Files:**
- Modify: `src/radar/cli.py` (new command, near `calibrate-report` at `cli.py:1388`), `.github/workflows/publish.yml:52-55`
- Test: `tests/test_cli.py` (append), `tests/test_publish_workflow.py` (append)

**Interfaces:**
- Consumes: run meta `degraded` (Task 4), `raw_signals.json` stage, `latest_tool_scan_meta` from `radar.web.scan_health` (existing — filters out models/research runs).
- Produces: `radar scan-health [--check] [--min-signals 20]` — exit 1 when the latest main-scan run is degraded or below the signal floor; exit 0 otherwise.

- [ ] **Step 1: Write failing tests** (append to `tests/test_cli.py`, using its existing `CliRunner` pattern — check the file head for the runner fixture name and mirror it):

```python
def test_scan_health_check_fails_on_degraded_run(tmp_path):
    import json

    from typer.testing import CliRunner

    from radar.cli import app
    from radar.storage.run_store import RunStore

    runner = CliRunner()
    store = RunStore(tmp_path / "data" / "runs")
    run_id = store.create_run()
    store.save_stage(run_id, "raw_signals", [])
    store.update_meta(run_id, {"degraded": True, "degraded_reason": "outage"})

    result = runner.invoke(app, ["scan-health", "--root", str(tmp_path), "--check"])
    assert result.exit_code == 1
    assert "degraded" in result.output.lower()


def test_scan_health_check_fails_below_signal_floor(tmp_path):
    from typer.testing import CliRunner

    from radar.cli import app
    from radar.storage.run_store import RunStore

    runner = CliRunner()
    store = RunStore(tmp_path / "data" / "runs")
    run_id = store.create_run()
    store.save_stage(run_id, "raw_signals", [{"id": "s1"}] * 5)

    result = runner.invoke(
        app, ["scan-health", "--root", str(tmp_path), "--check", "--min-signals", "20"]
    )
    assert result.exit_code == 1

    ok = runner.invoke(
        app, ["scan-health", "--root", str(tmp_path), "--check", "--min-signals", "3"]
    )
    assert ok.exit_code == 0
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_cli.py -q -k scan_health` → FAIL (no such command).

- [ ] **Step 3: Implement** in `cli.py` (place next to `calibrate_report`):

```python
@app.command("scan-health")
def scan_health_cmd(
    root: Path = typer.Option(Path("."), help="Project root."),
    check: bool = typer.Option(False, "--check", help="Exit non-zero if unhealthy."),
    min_signals: int = typer.Option(20, help="Minimum raw signals for a publishable run."),
) -> None:
    """Health of the latest main scan run (the publish gate reads this)."""
    from radar.storage.run_store import RunStore
    from radar.web.scan_health import latest_tool_scan_meta

    run_store = RunStore(root / "data" / "runs")
    found = latest_tool_scan_meta(run_store)
    if found is None:
        console.print("[red]No main scan run found.[/red]")
        raise typer.Exit(code=1 if check else 0)
    run_id, meta = found
    problems: list[str] = []
    if meta.get("degraded"):
        problems.append(f"run is degraded: {meta.get('degraded_reason', 'unknown reason')}")
    try:
        raw = run_store.load_stage(run_id, "raw_signals")
    except FileNotFoundError:
        raw = []
    if len(raw) < min_signals:
        problems.append(f"only {len(raw)} raw signals (< {min_signals})")
    if problems:
        for problem in problems:
            console.print(f"[red]UNHEALTHY:[/red] {problem}")
        raise typer.Exit(code=1 if check else 0)
    console.print(f"OK: {run_id} — {len(raw)} raw signals, not degraded")
```

**Check `latest_tool_scan_meta`'s actual signature** in `src/radar/web/scan_health.py` first — if it returns only a meta dict (not `(run_id, meta)`), adapt: iterate `run_store.list_runs()` newest-first, `read_meta`, skip metas whose `kind` is set (models/research/trending runs), and use the first match. Write it exactly as the existing helper does.

- [ ] **Step 4: Wire the workflow.** In `.github/workflows/publish.yml`, insert after the `Scan` step (before `Scoring quality gate`):

```yaml
      # Publish gate keyed on the RUN (not the DB union): refuse to export a
      # degraded or near-empty scan (see 2026-07-27 hardening spec).
      - name: Scan health gate
        run: uv run radar scan-health --root . --check
```

If `tests/test_publish_workflow.py` asserts the workflow's step list, add the new step there.

- [ ] **Step 5: Full gates** — `uv run pytest -q && uv run ruff check . && uv run mypy src` → PASS.

- [ ] **Step 6: Commit** — `git commit -am "feat: scan-health publish gate keyed on the latest run"`

---

### Task 6: `corrected` change type + effective-history view

Foundation for repair (Task 7): a `corrected` event neutralizes the artifact events of one (project, run) pair. Corrections are visible in raw timelines, but summaries and momentum compute over the *effective* view.

**Files:**
- Modify: `src/radar/pipeline/delta.py:28-34` (enum), `src/radar/storage/history_store.py` (field, column, filter), `src/radar/orchestrator.py:349-358` (momentum), `src/radar/web/templates/history.html:35`, `src/radar/web/templates/static_history.html:37`, `src/radar/web/templates/_project_detail.html:127`
- Test: `tests/test_history_store.py` (append)

**Interfaces:**
- Consumes: existing `ProjectHistoryEvent`, `ChangeType`.
- Produces:
  - `ChangeType.CORRECTED = "corrected"`.
  - `ProjectHistoryEvent.corrects_run_id: str | None = None` (persisted in SQLite column `corrects_run_id` and in JSONL lines; old JSONL lines parse fine via the default).
  - `apply_corrections(events: list[ProjectHistoryEvent]) -> list[ProjectHistoryEvent]` (module function in `radar.storage.history_store`): drops every event whose `(project, run_id)` matches a corrected event's `(project, corrects_run_id)`, and drops the corrected marker events themselves.
  - `HistoryStore.summaries()` computes over the effective view (a project with no effective events is omitted).

- [ ] **Step 1: Write failing tests** (append to `tests/test_history_store.py`):

```python
def _event(project, change_type, ring, previous_ring, run_id, corrects=None):
    from datetime import UTC, datetime

    from radar.pipeline.delta import ChangeType
    from radar.models import Category, Ring
    from radar.storage.history_store import ProjectHistoryEvent

    return ProjectHistoryEvent(
        project=project,
        category=Category.MCP_TOOLING,
        change_type=ChangeType(change_type),
        ring=Ring(ring),
        previous_ring=Ring(previous_ring) if previous_ring else None,
        run_id=run_id,
        observed_at=datetime(2026, 7, 1, tzinfo=UTC),
        reasons=[],
        corrects_run_id=corrects,
    )


def test_apply_corrections_drops_artifact_and_marker():
    from radar.storage.history_store import apply_corrections

    events = [
        _event("MCP", "new", "watch", None, "run-a"),
        _event("MCP", "promoted", "pilot", "watch", "run-outage"),   # artifact
        _event("MCP", "demoted", "watch", "pilot", "run-b"),
        _event("MCP", "corrected", "watch", "pilot", "repair:run-outage",
               corrects="run-outage"),
    ]
    effective = apply_corrections(events)
    assert [e.run_id for e in effective] == ["run-a", "run-b"]


def test_summaries_use_effective_view(tmp_path):
    from radar.storage.history_store import HistoryStore

    store = HistoryStore(tmp_path / "radar.db")
    store.initialize()
    store.add_events([
        _event("MCP", "new", "watch", None, "run-a"),
        _event("MCP", "promoted", "adopt", "watch", "run-outage"),
        _event("MCP", "corrected", "watch", "adopt", "repair:run-outage",
               corrects="run-outage"),
    ])
    (summary,) = store.summaries()
    assert summary.current_ring.value == "watch"
    assert summary.change_count == 1


def test_corrects_run_id_roundtrips_through_db_and_jsonl(tmp_path):
    from radar.storage.history_log import append_events, load_events
    from radar.storage.history_store import HistoryStore

    marker = _event("MCP", "corrected", "watch", "adopt", "repair:run-x", corrects="run-x")
    store = HistoryStore(tmp_path / "radar.db")
    store.initialize()
    store.add_events([marker])
    assert store.all_events()[0].corrects_run_id == "run-x"

    log = tmp_path / "history.jsonl"
    append_events(log, [marker])
    assert load_events(log)[0].corrects_run_id == "run-x"
```

Check `Category.MCP_TOOLING` / `Ring` member names in `src/radar/models.py` and adjust the helper if the enum members differ.

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_history_store.py -q` → FAIL.

- [ ] **Step 3: Implement.**

`delta.py` — add enum member: `CORRECTED = "corrected"` (after `UPDATED`).

`history_store.py`:
- `ProjectHistoryEvent` — add field: `corrects_run_id: str | None = None`.
- `initialize()` — same ALTER-guard pattern as Task 3 for `corrects_run_id TEXT` on `project_history`.
- `add_events` INSERT gains the column; `_event_row` appends `event.corrects_run_id`; both `SELECT` statements (in `all_events` / `history_for` / `summaries`) add `corrects_run_id` as the last column; `_row_to_event` maps `corrects_run_id=row[8]`.
- New module function (place above `HistoryStore`):

```python
def apply_corrections(events: list[ProjectHistoryEvent]) -> list[ProjectHistoryEvent]:
    """The effective timeline: corrected (project, run) pairs removed.

    A `corrected` event neutralizes every event its project recorded in
    `corrects_run_id`'s run (a proven collection-outage artifact). Marker
    events themselves are also excluded — they are display-only. Raw readers
    (feeds, the timeline page) still see everything via the unfiltered list.
    """
    corrected_pairs = {
        (e.project, e.corrects_run_id)
        for e in events
        if e.change_type == ChangeType.CORRECTED and e.corrects_run_id
    }
    return [
        e
        for e in events
        if e.change_type != ChangeType.CORRECTED
        and (e.project, e.run_id) not in corrected_pairs
    ]
```

- `summaries()` — after grouping `events_by_project`, filter each list: `events = apply_corrections(sorted(unordered, key=lambda e: e.observed_at))` and `if not events: continue`.

`orchestrator.py` `_compute_momentums` — wrap: `ring_events=apply_corrections(self.history.history_for(card.project))` (import `apply_corrections` from `radar.storage.history_store`).

Templates — in the three `<td>{{ e.change_type.value }}</td>` cells (files/lines in **Files** above), render corrections distinctly:

```html
<td>{% if e.change_type.value == "corrected" %}<em title="neutralizes an outage artifact">corrected</em>{% else %}{{ e.change_type.value }}{% endif %}</td>
```

- [ ] **Step 4: Run tests** — `uv run pytest tests/test_history_store.py tests/test_history_log.py -q` → PASS.

- [ ] **Step 5: Full gates** — `uv run pytest -q && uv run ruff check . && uv run mypy src` → PASS. (`reports/history.py`, feeds, and digest render `change_type.value` generically — corrections appear there as `corrected` rows by design: transparency, no code change.)

- [ ] **Step 6: Commit** — `git commit -am "feat: corrected change type + effective-history view for summaries and momentum"`

---

### Task 7: `radar history repair` — neutralize the 21 outage runs

**Files:**
- Create: `src/radar/storage/history_repair.py`
- Modify: `src/radar/cli.py:1215-1231` (convert `history` into a sub-app preserving `radar history [--project]`)
- Test: `tests/test_history_repair.py` (new)

**Interfaces:**
- Consumes: `source_health` table (Task 3 schema), `HistoryStore.all_events()`, `apply_corrections`, `append_events`.
- Produces:
  - `outage_run_ids(db_path: Path, *, zero_fraction: float = 0.5, min_sources: int = 10) -> set[str]` — runs where ≥ `zero_fraction` of recorded sources produced 0 signals, considering only runs with ≥ `min_sources` recorded rows (audit-verified criterion for the 21 outage runs; the criterion works on legacy rows with NULL status).
  - `build_corrections(events: list[ProjectHistoryEvent], outage_runs: set[str], observed_at: datetime) -> list[ProjectHistoryEvent]` — one marker per artifact promoted/demoted event, `run_id=f"repair:{artifact.run_id}"`, `ring=artifact.previous_ring or artifact.ring`, `previous_ring=artifact.ring`, `corrects_run_id=artifact.run_id`, reasons `["collection outage artifact; neutralizes <type> from <run_id> (2026-07-27 hardening spec)"]`. Idempotent: pairs already corrected in `events` are skipped.
  - CLI: `radar history` (unchanged behavior) and `radar history repair [--dry-run]`.

- [ ] **Step 1: Write failing tests** (`tests/test_history_repair.py`, reuse the `_event` helper shape from Task 6's tests):

```python
"""Corrective-event repair for outage-polluted history."""

from datetime import UTC, datetime
from pathlib import Path


def _seed_source_health(db_path: Path, run_id: str, zero: int, ok: int) -> None:
    from radar.storage.source_health_store import SourceHealthStore

    store = SourceHealthStore(db_path)
    store.initialize()
    counts = {f"z{i}": 0 for i in range(zero)} | {f"s{i}": 1 for i in range(ok)}
    store.record(run_id, datetime(2026, 7, 1, tzinfo=UTC), counts)


def test_outage_run_ids_thresholds(tmp_path: Path):
    from radar.storage.history_repair import outage_run_ids

    db = tmp_path / "radar.db"
    _seed_source_health(db, "run-outage", zero=60, ok=6)    # 91% zero
    _seed_source_health(db, "run-healthy", zero=10, ok=58)  # 15% zero
    _seed_source_health(db, "run-tiny", zero=3, ok=0)       # < min_sources

    assert outage_run_ids(db) == {"run-outage"}


def _event(project, change_type, ring, previous_ring, run_id, corrects=None):
    # Deliberate copy of the helper in tests/test_history_store.py — tests
    # never import from other test modules here.
    from radar.models import Category, Ring
    from radar.pipeline.delta import ChangeType
    from radar.storage.history_store import ProjectHistoryEvent

    return ProjectHistoryEvent(
        project=project,
        category=Category.MCP_TOOLING,
        change_type=ChangeType(change_type),
        ring=Ring(ring),
        previous_ring=Ring(previous_ring) if previous_ring else None,
        run_id=run_id,
        observed_at=datetime(2026, 7, 1, tzinfo=UTC),
        reasons=[],
        corrects_run_id=corrects,
    )


def test_build_corrections_is_idempotent(tmp_path: Path):
    from radar.storage.history_repair import build_corrections

    when = datetime(2026, 7, 27, tzinfo=UTC)
    events = [
        _event("MCP", "promoted", "adopt", "pilot", "run-outage"),
        _event("MCP", "updated", "adopt", None, "run-healthy"),
    ]
    first = build_corrections(events, {"run-outage"}, when)
    assert len(first) == 1
    marker = first[0]
    assert marker.change_type.value == "corrected"
    assert marker.corrects_run_id == "run-outage"
    assert marker.run_id == "repair:run-outage"
    assert marker.ring.value == "pilot"          # reverts to pre-artifact ring
    assert marker.previous_ring.value == "adopt"

    # Second pass over the already-repaired timeline appends nothing.
    assert build_corrections(events + first, {"run-outage"}, when) == []
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_history_repair.py -q` → FAIL (module missing).

- [ ] **Step 3: Implement** `src/radar/storage/history_repair.py`:

```python
"""One-off corrective repair for outage-polluted ring history.

The 2026-07-27 audit proved that scans which failed to reach most sources
were still scored, promoting the few network-free (manual) projects and
demoting them again the next healthy day. Those runs are identifiable from
per-source signal counts; this module appends `corrected` marker events that
neutralize their ring changes. The log stays append-only — nothing is ever
rewritten (spec D1).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from radar.pipeline.delta import ChangeType
from radar.storage.history_store import ProjectHistoryEvent


def outage_run_ids(
    db_path: Path,
    *,
    zero_fraction: float = 0.5,
    min_sources: int = 10,
) -> set[str]:
    """Runs where >= zero_fraction of recorded sources produced 0 signals.

    Runs with fewer than min_sources recorded rows are skipped — a tiny
    test/dev scan is not evidence of an outage. Works on legacy rows (status
    NULL) because the criterion needs only counts.
    """
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT run_id, COUNT(*), SUM(CASE WHEN signal_count = 0 THEN 1 ELSE 0 END) "
            "FROM source_health GROUP BY run_id"
        ).fetchall()
    return {
        run_id
        for run_id, total, zeros in rows
        if total >= min_sources and zeros / total >= zero_fraction
    }


def build_corrections(
    events: list[ProjectHistoryEvent],
    outage_runs: set[str],
    observed_at: datetime,
) -> list[ProjectHistoryEvent]:
    """Marker events neutralizing promoted/demoted artifacts from outage runs.

    Idempotent: (project, run) pairs already corrected in `events` are skipped,
    so re-running repair appends nothing.
    """
    already = {
        (e.project, e.corrects_run_id)
        for e in events
        if e.change_type == ChangeType.CORRECTED and e.corrects_run_id
    }
    corrections: list[ProjectHistoryEvent] = []
    for event in events:
        if event.run_id not in outage_runs:
            continue
        if event.change_type not in (ChangeType.PROMOTED, ChangeType.DEMOTED):
            continue
        if (event.project, event.run_id) in already:
            continue
        already.add((event.project, event.run_id))
        corrections.append(
            ProjectHistoryEvent(
                project=event.project,
                category=event.category,
                change_type=ChangeType.CORRECTED,
                ring=event.previous_ring or event.ring,
                previous_ring=event.ring,
                run_id=f"repair:{event.run_id}",
                observed_at=observed_at,
                reasons=[
                    "collection outage artifact; neutralizes "
                    f"{event.change_type.value} from {event.run_id} "
                    "(2026-07-27 hardening spec)"
                ],
                corrects_run_id=event.run_id,
            )
        )
    return corrections
```

- [ ] **Step 4: Module tests pass** — `uv run pytest tests/test_history_repair.py -q` → PASS.

- [ ] **Step 5: CLI.** In `cli.py`, replace the single `history` command (`cli.py:1215-1231`) with a sub-app whose callback preserves the existing flags (read the current body first and move it verbatim into the callback):

```python
history_app = typer.Typer(help="Project ring timeline.", invoke_without_command=True)
app.add_typer(history_app, name="history")


@history_app.callback()
def history(
    ctx: typer.Context,
    project: str = typer.Option("", help="Filter to one project."),
    root: Path = typer.Option(Path("."), help="Project root."),
) -> None:
    """Print the cumulative per-project timeline."""
    if ctx.invoked_subcommand is not None:
        return
    # <existing `radar history` body moved here unchanged>


@history_app.command("repair")
def history_repair(
    root: Path = typer.Option(Path("."), help="Project root."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show corrections, write nothing."),
) -> None:
    """Neutralize ring changes from collection-outage runs (append-only)."""
    from datetime import UTC, datetime

    from radar.orchestrator import RadarOrchestrator
    from radar.storage.history_log import append_events
    from radar.storage.history_repair import build_corrections, outage_run_ids

    orchestrator = RadarOrchestrator(root)
    orchestrator.history.initialize()
    orchestrator._reconcile_history()  # log -> DB so all_events() is complete
    events = orchestrator.history.all_events()
    outages = outage_run_ids(root / "data" / "radar.db")
    corrections = build_corrections(events, outages, datetime.now(UTC))
    console.print(f"Outage runs detected: {len(outages)}")
    console.print(f"Corrections to append: {len(corrections)}")
    for c in corrections:
        console.print(
            f"  {c.project}: {c.previous_ring.value} -> {c.ring.value} ({c.corrects_run_id})"
        )
    if dry_run or not corrections:
        return
    orchestrator.history.add_events(corrections)
    append_events(orchestrator.history_log, corrections)
    console.print(f"Appended {len(corrections)} corrected events.")
```

(If ruff flags the private `_reconcile_history` call, add a public wrapper `reconcile_history()` on the orchestrator delegating to it and call that.)

Add a CLI test (append to `tests/test_history_repair.py`): seed a tmp project (as in Task 4's test) with a fake outage — write source_health rows via `_seed_source_health(tmp_path / "data" / "radar.db", "run-x", zero=60, ok=6)`, add a promoted event for `run-x` through `HistoryStore.add_events` + `append_events(tmp_path / "data" / "history.jsonl", ...)`, invoke `runner.invoke(app, ["history", "repair", "--root", str(tmp_path)])`, assert exit code 0 and that `load_events` on the log now contains a `corrected` event; invoke again and assert the count didn't grow (idempotent). Also `runner.invoke(app, ["history", "--root", str(tmp_path)])` still exits 0 (callback preserved).

- [ ] **Step 6: Full gates** — `uv run pytest -q && uv run ruff check . && uv run mypy src` → PASS.

- [ ] **Step 7: Commit** — `git commit -am "feat: radar history repair — corrective events for outage-polluted runs"`

- [ ] **Step 8: Run the real repair** (working tree, not committed data): `uv run radar history repair --dry-run` — eyeball the list (expect ~50 corrections across NVIDIA Blackwell / MCP / Gaudi 3 / Ascend / MI300X / E2B etc., all from the 21 outage runs). Then `uv run radar history repair`. Do NOT commit `data/history.jsonl` — it is CI-owned (Task 11 formalizes this); the local repair validates the tool. Record the dry-run output in the PR description. The production history gets repaired by running the same command in CI once merged, or manually on a fresh clone of origin — note this as a follow-up in the PR.

---

### Task 8: Durable source-health JSONL log + rehydration

`source_health` lives only in `data/radar.db` — violating the log-is-truth invariant, and CI starts with an empty DB so stale-feed detection never fires there (long-deferred item).

**Files:**
- Create: `src/radar/storage/source_health_log.py`
- Modify: `src/radar/storage/source_health_store.py` (add `import_records`), `src/radar/orchestrator.py` (`_collect_raw` appends; `_scan` rehydrates), `.github/workflows/publish.yml:82-89` (persist list), `.gitignore`
- Test: `tests/test_source_health_log.py` (new)

**Interfaces:**
- Consumes: statuses/counts from Task 3.
- Produces:
  - `SourceHealthRecord(BaseModel)`: `run_id: str`, `observed_at: datetime`, `sources: dict[str, SourceOutcome]` where `SourceOutcome(BaseModel)`: `count: int`, `status: str`.
  - `append_source_health(path: Path, record: SourceHealthRecord) -> None` (one JSON line per scan).
  - `load_source_health(path: Path) -> list[SourceHealthRecord]` (missing file → `[]`; corrupt lines skipped with a warning — mirror `history_log.py:33-54`).
  - `SourceHealthStore.import_records(records: list[SourceHealthRecord]) -> int` — idempotent by `(source_id, run_id)`, returns inserted count.
  - Orchestrator: log lives at `data/source-health.jsonl`; `_scan` rehydrates DB from it right after `_reconcile_history()`.

- [ ] **Step 1: Write failing tests** (`tests/test_source_health_log.py`):

```python
from datetime import UTC, datetime
from pathlib import Path

from radar.storage.source_health_log import (
    SourceHealthRecord,
    SourceOutcome,
    append_source_health,
    load_source_health,
)
from radar.storage.source_health_store import SourceHealthStore


def _record(run_id: str = "run-1") -> SourceHealthRecord:
    return SourceHealthRecord(
        run_id=run_id,
        observed_at=datetime(2026, 7, 27, tzinfo=UTC),
        sources={
            "github-vllm": SourceOutcome(count=3, status="ok"),
            "rss-dead": SourceOutcome(count=0, status="error"),
        },
    )


def test_append_and_load_roundtrip(tmp_path: Path):
    log = tmp_path / "source-health.jsonl"
    append_source_health(log, _record())
    (loaded,) = load_source_health(log)
    assert loaded.sources["rss-dead"].status == "error"
    assert load_source_health(tmp_path / "missing.jsonl") == []


def test_corrupt_line_skipped(tmp_path: Path):
    log = tmp_path / "source-health.jsonl"
    append_source_health(log, _record())
    log.write_text(log.read_text() + "{not json\n", encoding="utf-8")
    assert len(load_source_health(log)) == 1


def test_import_records_rehydrates_idempotently(tmp_path: Path):
    store = SourceHealthStore(tmp_path / "radar.db")
    store.initialize()
    records = [_record("run-1"), _record("run-2")]
    assert store.import_records(records) == 4   # 2 sources x 2 runs
    assert store.import_records(records) == 0   # second import: all present
    assert store.latest_counts()["github-vllm"] == 3
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_source_health_log.py -q` → FAIL.

- [ ] **Step 3: Implement** `source_health_log.py` (mirror `history_log.py`'s append/load structure exactly, including the corrupt-line warning), plus in `source_health_store.py`:

```python
    def import_records(self, records: list["SourceHealthRecord"]) -> int:
        """Insert rows not already present (idempotent rehydration from JSONL).

        Natural key: (source_id, run_id) — a run records each source once.
        """
        from radar.storage.source_health_log import SourceHealthRecord  # local: avoid cycle

        with sqlite3.connect(self.path) as conn:
            existing = {
                (row[0], row[1])
                for row in conn.execute("SELECT source_id, run_id FROM source_health")
            }
        inserted = 0
        for record in records:
            fresh = {
                source_id: outcome
                for source_id, outcome in record.sources.items()
                if (source_id, record.run_id) not in existing
            }
            if not fresh:
                continue
            self.record(
                record.run_id,
                record.observed_at,
                {sid: o.count for sid, o in fresh.items()},
                {sid: o.status for sid, o in fresh.items()},
            )
            inserted += len(fresh)
        return inserted
```

(Use a `TYPE_CHECKING` import for the annotation if ruff prefers; keep the runtime import local to avoid a module cycle.)

Orchestrator wiring:
- `__init__`: `self.source_health_log = self.data_dir / "source-health.jsonl"`.
- `_scan`, after `self._reconcile_history()`:

```python
        self.source_health.initialize()
        self.source_health.import_records(load_source_health(self.source_health_log))
```

- `_collect_raw`, after `self.source_health.record(...)`:

```python
        append_source_health(
            self.source_health_log,
            SourceHealthRecord(
                run_id=run_id,
                observed_at=datetime.now(UTC),
                sources={
                    sid: SourceOutcome(count=count, status=statuses[sid])
                    for sid, count in source_counts.items()
                },
            ),
        )
```

Imports: `from radar.storage.source_health_log import SourceHealthRecord, SourceOutcome, append_source_health, load_source_health`.

`.gitignore`: after the `data/history.jsonl` block add `data/source-health.jsonl` with the same "force-added by CI" comment. `publish.yml`: add `git add -f data/source-health.jsonl || true` to the persist step's list.

- [ ] **Step 4: Extend the orchestrator test** — in `tests/test_scan_gate.py::test_healthy_run_is_not_degraded`, add: `assert (tmp_path / "data" / "source-health.jsonl").exists()`.

- [ ] **Step 5: Full gates** — `uv run pytest -q && uv run ruff check . && uv run mypy src` → PASS.

- [ ] **Step 6: Commit** — `git commit -am "feat: durable source-health JSONL log with idempotent DB rehydration"`

---

### Task 9: Surface card staleness

After an outage the dashboard blends fresh and day-old cards with no indicator (`decision_cards` upserts, `updated_at` stored but never shown).

**Files:**
- Modify: `src/radar/storage/database.py`, `src/radar/web/app.py:153` (index context), `src/radar/web/static_site.py` (its `scan_health` context site — grep `scan_health` in the file), `src/radar/web/templates/_scan_health.html`
- Test: `tests/test_database.py` (append), `tests/test_web.py` (append)

**Interfaces:**
- Consumes: `decision_cards(project, payload, ring, category, updated_at)` table (existing).
- Produces: `RadarDatabase.card_staleness_note() -> str | None` — `None` when all cards share one `updated_at` date (or no cards); else e.g. `"12 of 64 cards predate the latest scan (oldest 2026-07-25, newest 2026-07-27)"`. Template context key `card_staleness` on every page that includes `_scan_health.html`.

- [ ] **Step 1: Write failing test** (append to `tests/test_database.py`, using that file's existing card-construction helper — read its head and reuse; sketch):

```python
def test_card_staleness_note(tmp_path):
    # Build via the file's existing helper for DecisionCard fixtures.
    db = RadarDatabase(tmp_path / "radar.db")
    db.initialize()
    db.upsert_cards([_card("Fresh")])          # existing helper in this file
    # Backdate one card directly — upsert always stamps now.
    db.upsert_cards([_card("Stale")])
    import sqlite3

    with sqlite3.connect(tmp_path / "radar.db") as conn:
        conn.execute(
            "UPDATE decision_cards SET updated_at = '2026-07-25T06:00:00+00:00' "
            "WHERE project = 'Stale'"
        )
    note = db.card_staleness_note()
    assert note is not None and "1 of 2" in note and "2026-07-25" in note

    with sqlite3.connect(tmp_path / "radar.db") as conn:
        conn.execute("UPDATE decision_cards SET updated_at = '2026-07-27T06:00:00+00:00'")
    assert db.card_staleness_note() is None
```

- [ ] **Step 2: Run to verify failure**, then implement in `database.py`:

```python
    def card_staleness_note(self) -> str | None:
        """Human-readable note when persisted cards span multiple scan days.

        The cards table upserts per-project, so after a partial/degraded scan
        the 'latest' view silently mixes ages. None = homogeneous (or empty).
        """
        with sqlite3.connect(self.path) as conn:
            rows = conn.execute("SELECT updated_at FROM decision_cards").fetchall()
        if not rows:
            return None
        dates = sorted({row[0][:10] for row in rows})
        if len(dates) == 1:
            return None
        newest = dates[-1]
        stale = sum(1 for (stamp,) in rows if stamp[:10] != newest)
        return (
            f"{stale} of {len(rows)} cards predate the latest scan "
            f"(oldest {dates[0]}, newest {newest})"
        )
```

- [ ] **Step 3: Wire the two context sites + template.** In `web/app.py` the index context (`app.py:153`) gains `"card_staleness": orchestrator.database.card_staleness_note(),` — match how the file accesses the database (read the surrounding function; it may hold a `RadarDatabase` directly rather than an orchestrator). In `web/static_site.py`, find where `scan_health` enters the index context (grep `scan_health`) and add the same key from the same database object. In `_scan_health.html`, before the closing `</div>`:

```html
  {% if card_staleness %}
  <p class="scan-health-stale">⏱ {{ card_staleness }}</p>
  {% endif %}
```

Add a web test (append to `tests/test_web.py`, following its existing client fixture): backdate one card as in Step 1, GET `/`, assert `"predate the latest scan"` in the response text.

- [ ] **Step 4: Full gates** — `uv run pytest -q && uv run ruff check . && uv run mypy src` → PASS.

- [ ] **Step 5: Commit** — `git commit -am "feat: surface mixed-age decision cards on dashboard and static site"`

---

### Task 10: Model-catalog validation gate

`Ornith-1.0-35B` (664,944 "params" for a 35B name, `min_memory_gb` 0) scored and auto-promoted to adopt. Absurd entries must be quarantined from scoring, not silently ranked. (Spec 4.5; also D4's hf-link presence check.)

**Files:**
- Create: `src/radar/models_radar/validate.py`
- Modify: `src/radar/cli.py:239-275` (`models_scan` — quarantine before scoring)
- Test: `tests/test_model_seed_validation.py` (new)

**Interfaces:**
- Consumes: `ModelSeed` (`radar.models_radar.entities`), `plausible_params(name, params_total)` from `radar.discovery.model_promotion:188`.
- Produces:
  - `validate_seed(seed: ModelSeed) -> list[str]` — blocking problems (empty = valid): implausible `params_total` vs name size-token, `params_total <= 0`, `params_active > params_total`, `context_length <= 0`.
  - `seed_advisories(seed: ModelSeed) -> list[str]` — warn-only: missing `hf_repo` (D4).
  - `models_scan` skips invalid seeds, prints each problem, stores them in run meta `model_validation_warnings`.

- [ ] **Step 1: Write failing tests** (`tests/test_model_seed_validation.py`):

```python
"""Catalog validation: absurd seeds are quarantined, shipped seeds are clean."""

from pathlib import Path

from radar.models_radar.seed import load_model_seed
from radar.models_radar.validate import seed_advisories, validate_seed

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _seed(**overrides):
    from radar.models_radar.entities import ModelSeed

    base = {
        "id": "test-35b",
        "name": "Test-35B",
        "family": "Test",
        "params_total": 35_000_000_000,
    }
    return ModelSeed(**{**base, **overrides})


def test_implausible_params_vs_name_is_blocking():
    problems = validate_seed(_seed(params_total=664_944))  # the Ornith failure
    assert any("implausible" in p for p in problems)


def test_active_exceeding_total_is_blocking():
    problems = validate_seed(
        _seed(params_total=30_000_000_000, params_active=40_000_000_000)
    )
    assert any("params_active" in p for p in problems)


def test_nonpositive_values_are_blocking():
    assert validate_seed(_seed(params_total=0))
    assert validate_seed(_seed(context_length=0))


def test_valid_seed_has_no_problems():
    assert validate_seed(_seed(params_active=3_000_000_000, context_length=32768)) == []


def test_missing_hf_repo_is_advisory_not_blocking():
    seed = _seed(hf_repo=None)
    assert validate_seed(seed) == []
    assert any("hf_repo" in a for a in seed_advisories(seed))


def test_every_shipped_seed_passes_blocking_validation():
    seeds = load_model_seed(_REPO_ROOT / "config" / "model-seed.yaml")
    failures = {s.id: validate_seed(s) for s in seeds}
    failures = {k: v for k, v in failures.items() if v}
    assert failures == {}, f"shipped seeds must validate: {failures}"
```

Check `load_model_seed`'s exact signature in `src/radar/models_radar/seed.py:1-29` (path arg vs root arg) and `ModelSeed`'s required fields in `entities.py:100-124`; adjust the helper accordingly.

- [ ] **Step 2: Run to verify failure** — module missing. If the shipped-seed test then fails on a real seed (e.g. Ornith not yet corrected in `config/model-seed.yaml`), **fix the seed data in the same commit** — that is the point of the gate. Verify against the model's HF page and record the source URL in a YAML comment.

- [ ] **Step 3: Implement** `src/radar/models_radar/validate.py`:

```python
"""Blocking validation + advisories for model-catalog seeds.

A seed that fails validation is quarantined: excluded from scoring, rings,
and promotion, and surfaced as a warning instead. Prevents a mis-scraped
entry (664,944-param "35B") from ever ranking again.
"""

from __future__ import annotations

from radar.discovery.model_promotion import plausible_params
from radar.models_radar.entities import ModelSeed


def validate_seed(seed: ModelSeed) -> list[str]:
    """Blocking problems; an empty list means the seed may be scored."""
    problems: list[str] = []
    if seed.params_total is not None:
        if seed.params_total <= 0:
            problems.append(f"{seed.id}: params_total must be positive")
        elif plausible_params(seed.name, seed.params_total) is None:
            problems.append(
                f"{seed.id}: implausible params_total {seed.params_total} "
                f"for name {seed.name!r}"
            )
    if (
        seed.params_active is not None
        and seed.params_total is not None
        and seed.params_active > seed.params_total
    ):
        problems.append(f"{seed.id}: params_active exceeds params_total")
    if seed.context_length is not None and seed.context_length <= 0:
        problems.append(f"{seed.id}: context_length must be positive")
    return problems


def seed_advisories(seed: ModelSeed) -> list[str]:
    """Non-blocking data-quality nudges (surfaced, never quarantined)."""
    advisories: list[str] = []
    if not seed.hf_repo:
        advisories.append(
            f"{seed.id}: no hf_repo — Hugging Face link missing from model surfaces"
        )
    return advisories
```

- [ ] **Step 4: Wire into `models_scan`** (`cli.py:239-275`). After the seeds are loaded and before entries are assembled/scored:

```python
    from radar.models_radar.validate import seed_advisories, validate_seed

    quarantined: dict[str, list[str]] = {}
    advisories: list[str] = []
    valid_seeds = []
    for seed in seeds:
        problems = validate_seed(seed)
        if problems:
            quarantined[seed.id] = problems
            continue
        advisories.extend(seed_advisories(seed))
        valid_seeds.append(seed)
    for seed_id, problems in quarantined.items():
        console.print(f"[red]QUARANTINED {seed_id}:[/red] {'; '.join(problems)}")
    for advisory in advisories:
        console.print(f"[yellow]note:[/yellow] {advisory}")
    if quarantined or advisories:
        run_store.update_meta(run_id, {
            "model_validation_warnings": [
                *(p for ps in quarantined.values() for p in ps), *advisories,
            ],
        })
```

Read the actual `models_scan` body first (`cli.py:239-275`): the seed list variable and the point where `run_model_scan` receives it may differ — feed `valid_seeds` to whatever `run_model_scan` consumes, and reuse its existing `run_store`/`run_id` names.

- [ ] **Step 5: Full gates** — `uv run pytest -q && uv run ruff check . && uv run mypy src` → PASS.

- [ ] **Step 6: Commit** — `git commit -am "feat: model-catalog validation gate quarantines implausible seeds (+ hf_repo advisory)"`

**Scope note:** spec §4.5 also lists `min_memory_gb > 0` and required-provenance checks. `min_memory_gb` is computed during assembly (not a seed field) and provenance fields do not exist until schema v2 — both checks land in sub-project B where assembly/schema are reworked. The root cause of the Ornith incident (implausible `params_total`) is fully gated here.

---

### Task 11: CI-only committed history (D5 local lane)

302 uncommitted local `history.jsonl` lines diverge from the CI-committed timeline. Decision D5: CI is the sole writer of the committed log; local scans keep full function (DB, reports) but append to a gitignored local lane.

**Files:**
- Modify: `src/radar/orchestrator.py` (`scan`/`_scan` signature + `_persist_history`), `src/radar/cli.py:93-133` (`scan` flag), `.github/workflows/publish.yml:45`, `.gitignore`, `docs/persistence.md` (note)
- Test: `tests/test_orchestrator.py` (append)

**Interfaces:**
- Consumes: existing `_persist_history` / `append_events`.
- Produces: `RadarOrchestrator.scan(days: int, profile: str | None = None, publish_history: bool = False)`; `_scan` same; events always reach the SQLite projection, but the JSONL target is `data/history.jsonl` when `publish_history=True`, else `data/local/history.jsonl`. CLI flag `--publish-history` (default false). CI passes it.

- [ ] **Step 1: Write failing test** (append to `tests/test_orchestrator.py`):

```python
def test_local_scan_writes_local_history_lane(tmp_path: Path):
    initialize_project(tmp_path)
    _write_manual_config(tmp_path)

    RadarOrchestrator(root=tmp_path).scan(days=2)  # default: local lane

    assert not (tmp_path / "data" / "history.jsonl").exists()
    assert (tmp_path / "data" / "local" / "history.jsonl").exists()


def test_publish_history_writes_committed_lane(tmp_path: Path):
    initialize_project(tmp_path)
    _write_manual_config(tmp_path)

    RadarOrchestrator(root=tmp_path).scan(days=2, publish_history=True)

    assert (tmp_path / "data" / "history.jsonl").exists()
```

- [ ] **Step 2: Run to verify failure** — unexpected keyword `publish_history`.

- [ ] **Step 3: Implement.** `orchestrator.py`:

- `scan(self, days: int, profile: str | None = None, publish_history: bool = False)` → forwards to `_scan(days, profile, publish_history)`.
- `_persist_history(self, deltas, run_id, publish_history: bool)` — the `append_events` target becomes:

```python
        # D5 (2026-07-27 spec): only CI writes the committed timeline. Local
        # scans keep the DB projection + reports but log to an ignored lane,
        # so laptop runs never pollute the shared history.
        target = (
            self.history_log
            if publish_history
            else self.data_dir / "local" / "history.jsonl"
        )
        append_events(target, events)
```

- `_scan` passes the flag through: `self._persist_history(deltas, run_id, publish_history)`.
- Existing tests that assert `data/history.jsonl` after a plain `scan(...)` will break — update them to pass `publish_history=True` (they are testing the durable-lane behavior) or to expect the local lane, whichever each test actually pins. Do this deliberately, test by test.
- `_reconcile_history` stays pointed at the committed log only (the local lane is disposable by design).

`cli.py` `scan` — add option and forward:

```python
    publish_history: bool = typer.Option(
        False,
        "--publish-history",
        help="Append ring changes to the committed data/history.jsonl (CI only).",
    ),
```

`publish.yml:45` — `uv run radar scan --root . --days 7 --publish-history`.

`.gitignore` — add `data/local/` under the local-runtime block.

`docs/persistence.md` — add a short "Who writes the log" paragraph: CI (via `--publish-history`) is the sole writer of the committed `data/history.jsonl`; local scans append to `data/local/history.jsonl` (gitignored, disposable).

- [ ] **Step 4: Full gates** — `uv run pytest -q && uv run ruff check . && uv run mypy src` → PASS.

- [ ] **Step 5: Commit** — `git commit -am "feat: CI-only committed history; local scans write a gitignored lane (spec D5)"`

---

### Task 12: Housekeeping

**Files:**
- Modify: `.gitignore`, `config/seed-sources.yaml:679-684`, `tests/test_config.py:186-190`
- Delete: `/radar.db` (0-byte stray, untracked), `data/config.yaml.bak` (local), `config/category-quotas.yaml`, `config/scoring.yaml`
- Modify: `CHANGELOG.md` ([Unreleased] section)

**Interfaces:** none produced; consumers of the deleted YAMLs are tests only (verified: only `tests/test_config.py:189` reads `category-quotas.yaml`; nothing reads `config/scoring.yaml`).

- [ ] **Step 1: gitignore + strays.**

```bash
rm -f radar.db data/config.yaml.bak
```

`.gitignore` — add at the end of the local-runtime block:

```
# Stray DB created by running radar with the wrong --root (the real one is
# data/radar.db, covered by data/*.db above).
/radar.db
```

(Also confirm the Task 8 `data/source-health.jsonl` and Task 11 `data/local/` lines are present.)

- [ ] **Step 2: Make `arxiv` visible.** In `config/seed-sources.yaml`'s enrichment block (line ~679) add `arxiv: true` after `downloads: true`, with a comment: `# arXiv paper-mention enricher (defaults on; listed so operators can see/toggle it)`. Note in the PR description: existing `data/config.yaml` copies predate this key and can be refreshed with `radar init --force`.

- [ ] **Step 3: Single source of truth for quotas/scoring.** Delete `config/category-quotas.yaml` and `config/scoring.yaml`. Rewrite the test at `tests/test_config.py:186-190` to load `config/seed-sources.yaml` instead and assert its `quotas:` mapping enumerates every `Category` member (same assertion, real source of truth). Run `uv run pytest tests/test_config.py -q`.

- [ ] **Step 4: CHANGELOG.** Under `[Unreleased]`, add a `### Hardening (sub-project A)` block summarizing: outage gate, per-source outcomes, GitHub collector warnings, history corrections + repair command, source-health JSONL, card staleness, catalog validation gate, CI-only history lane, retry/warning fixes, stray cleanup.

- [ ] **Step 5: Full gates one last time** — `uv run pytest -q && uv run ruff check . && uv run mypy src` → PASS.

- [ ] **Step 6: Commit** — `git commit -am "chore: hardening housekeeping — strays, visible arxiv toggle, single config source of truth"`

---

## Final verification (whole sub-project)

- [ ] `uv run pytest -q` — full suite green (1000+ tests).
- [ ] `uv run ruff check . && uv run mypy src` — clean.
- [ ] Manual smoke: `uv run radar scan --days 2` (local, online) → healthy run, `data/local/history.jsonl` lane, no `data/history.jsonl` modification.
- [ ] Manual smoke: disconnect network → `uv run radar scan --days 2` → exits 2, prints DEGRADED, writes no cards/history.
- [ ] `uv run radar history repair --dry-run` → lists the expected ~21-run corrections; plain run is idempotent.
- [ ] `uv run radar scan-health --check` → OK on the healthy run.
- [ ] Use superpowers:requesting-code-review before merging; merge `feature/capacity-radar/design-spec` + this work per repo convention (feature branch, `--no-ff`).
