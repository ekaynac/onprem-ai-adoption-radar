# Production Stabilization Implementation Plan

> **For Codex:** Execute this plan with `superpowers:executing-plans`, use `superpowers:test-driven-development` for every behavior change, and use `superpowers:verification-before-completion` before integration.

**Goal:** Make scheduled intelligence ingestion resumable, keep the complete model catalog searchable with bounded publication cost, and deploy a genuinely fresh GitHub Pages build.

**Architecture:** Store canonical operational state in a safe versioned archive attached to a dedicated GitHub Release. Export a bounded detailed snapshot plus a compact, sharded index containing every canonical model. Load the index lazily in the frontend and cap only the rendered result set, not search coverage.

**Tech stack:** Python 3.12+, Typer, Pydantic, SQLite, pytest, GitHub Actions/CLI, React 19, TypeScript, Vite, Vitest, Playwright.

---

## Task 1: Implement safe canonical-state bundles

**Files:**

- Create: `src/radar/intelligence/state_bundle.py`
- Modify: `src/radar/cli.py`
- Test: `tests/intelligence/test_state_bundle.py`

### Step 1: Write failing archive tests

Add tests that:

- round-trip `data/intelligence.db`, `data/intelligence/events.jsonl`, and nested `data/intelligence/snapshots/**`;
- exclude unrelated files under `data/`;
- reject absolute paths, `..` traversal, and symbolic/hard links without changing existing state;
- expose pack and restore through the CLI.

Run:

```bash
uv run pytest tests/intelligence/test_state_bundle.py -q
```

Expected: FAIL because the bundle module and commands do not exist.

### Step 2: Implement the minimal safe archive API

Create a versioned manifest and:

```python
def pack_intelligence_state(root: Path, destination: Path) -> StateBundleManifest: ...
def restore_intelligence_state(root: Path, archive: Path) -> StateBundleManifest: ...
```

Use an explicit member allowlist. Validate every member before extraction, reject links, extract into a temporary directory, and atomically replace individual target files/directories only after the complete archive validates.

Add `intelligence-state-pack` and `intelligence-state-restore` Typer commands with `--root`, `--out`, and `--archive` options.

### Step 3: Verify the task

Run:

```bash
uv run pytest tests/intelligence/test_state_bundle.py -q
uv run ruff check src/radar/intelligence/state_bundle.py src/radar/cli.py tests/intelligence/test_state_bundle.py
uv run mypy src/radar/intelligence/state_bundle.py src/radar/cli.py
```

Expected: PASS.

### Step 4: Commit

```bash
git add src/radar/intelligence/state_bundle.py src/radar/cli.py tests/intelligence/test_state_bundle.py
git commit -m "feat: add durable intelligence state bundles"
```

## Task 2: Make the publish workflow resumable

**Files:**

- Modify: `.github/workflows/publish.yml`
- Modify: `tests/test_publish_workflow.py`
- Modify: `docs/persistence.md`

### Step 1: Write failing workflow-policy tests

Assert that the workflow:

- restores `intelligence-state.tar.gz` before migration;
- checkpoints after discovery and after verification/scanning, before export;
- uploads with `gh release upload radar-state ... --clobber`;
- never stages the raw database, events log, or snapshot directory;
- uses an explicit 180-minute job timeout;
- accepts `HF_TOKEN` from repository secrets without logging it.

Run:

```bash
uv run pytest tests/test_publish_workflow.py -q
```

Expected: FAIL against the current workflow.

### Step 2: Implement restore and checkpoint stages

Restore the release asset before migration, treating a missing release/asset as first-run bootstrap. Split discovery and `verify-new` into separate steps. Pack and upload checkpoints after discovery and after the verification/scan gates. Keep Git persistence limited to small public artifacts.

Document Release assets as canonical workflow persistence and document optional `HF_TOKEN` setup and behavior.

### Step 3: Verify the task

Run:

```bash
uv run pytest tests/test_publish_workflow.py tests/test_intelligence_workflows.py -q
git diff --check
```

Expected: PASS.

### Step 4: Commit

```bash
git add .github/workflows/publish.yml tests/test_publish_workflow.py docs/persistence.md
git commit -m "ci: checkpoint intelligence state during publish"
```

## Task 3: Bound detailed projection and export the complete model index

**Files:**

- Modify: `src/radar/intelligence/services/catalog.py`
- Modify: `src/radar/intelligence/services/releases.py`
- Modify: `src/radar/intelligence/ports.py` or the repository protocol modules used by those services
- Modify: `src/radar/web/intelligence_snapshot.py`
- Modify: `src/radar/web/react_export.py`
- Test: `tests/intelligence/test_catalog_service.py`
- Test: `tests/intelligence/test_release_service.py`
- Modify: `tests/test_intelligence_snapshot.py`
- Modify: `tests/test_react_export.py` if export coverage resides there

### Step 1: Write failing keyed-lookup tests

Use a repository spy whose `list_all_releases()` raises and whose `get_release()` returns the requested release. Prove `CatalogService.get()` and `ReleaseService.get()` use the keyed operation.

Run:

```bash
uv run pytest tests/intelligence/test_catalog_service.py tests/intelligence/test_release_service.py -q
```

Expected: FAIL because both services currently scan all releases.

### Step 2: Implement keyed service lookups

Add `get_release` to the relevant repository protocols and replace service scans with the keyed method. Preserve not-found behavior.

### Step 3: Write failing bounded-export tests

Add tests proving:

- detailed projection receives every legacy release plus no more than the 250 newest non-legacy releases;
- the latest low-download release is retained by recency;
- the compact model-index manifest count equals the complete canonical release count;
- each shard contains at most 2,000 rows and every release appears exactly once;
- shard ordering and filenames are deterministic.

Run:

```bash
uv run pytest tests/test_intelligence_snapshot.py tests/test_react_export.py -q
```

Expected: FAIL because export currently projects every release and has no model index.

### Step 4: Implement bounded detail and sharded index

Select bounded releases before calling detail services. Add a model-index reference to the public snapshot and write `data/model-index.v1.json` plus `data/model-index/*.json` from canonical release fields without per-release service calls. Use 2,000 records per shard.

### Step 5: Verify the task

Run:

```bash
uv run pytest tests/intelligence/test_catalog_service.py tests/intelligence/test_release_service.py tests/test_intelligence_snapshot.py tests/test_react_export.py -q
uv run ruff check src/radar/intelligence src/radar/web tests/intelligence tests/test_intelligence_snapshot.py tests/test_react_export.py
uv run mypy src/radar
```

Expected: PASS.

### Step 6: Commit

```bash
git add src/radar/intelligence src/radar/web tests/intelligence tests/test_intelligence_snapshot.py tests/test_react_export.py
git commit -m "perf: bound snapshot projection and shard model index"
```

## Task 4: Search the complete index with bounded rendering

**Files:**

- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/api/client.test.ts`
- Modify: frontend API types only if required by the manifest contract

### Step 1: Write failing client tests

Prove that:

- compact index rows merge with detailed snapshot models by `release_id`, with detailed data winning;
- filtering/searching happens before the 500-row response cap, so a match beyond the first 500 remains discoverable;
- `next_cursor` is present when more than 500 filtered rows exist;
- an index-fetch failure falls back to snapshot models.

Run:

```bash
cd frontend
npm test -- --run src/api/client.test.ts
```

Expected: FAIL because the client only reads `snapshot.models`.

### Step 2: Implement lazy index loading

Fetch the manifest and its shards only for catalog/model-detail static requests. Cache the promise, merge by release ID, filter and sort the complete collection, then cap the response at 500. Preserve existing static/API-mode behavior and snapshot fallback.

### Step 3: Verify the task

Run:

```bash
cd frontend
npm test -- --run src/api/client.test.ts
npm run typecheck
npm run lint
```

Expected: PASS.

### Step 4: Commit

```bash
git add frontend/src/api/client.ts frontend/src/api/client.test.ts frontend/src/api
git commit -m "feat: search complete sharded model catalog"
```

## Task 5: Run full local quality and performance verification

**Files:**

- Modify only files required to correct regressions discovered by the gates.

### Step 1: Backend gates

Run from repository root:

```bash
uv run ruff check .
uv run mypy src/radar
uv run pytest -q
```

Expected: PASS with a fresh zero exit status.

### Step 2: Frontend gates

Run:

```bash
cd frontend
npm test -- --run
npm run typecheck
npm run lint
npm run build
npm run test:e2e
```

Expected: PASS.

### Step 3: Large-catalog export check

Run the focused large-catalog test or fixture with at least 20,000 releases. Confirm detailed projection calls remain bounded, index output contains all releases, and generated publication files stay within the specified shard limits.

### Step 4: Review and commit fixes

Inspect the complete branch diff for scope, secret exposure, unsafe archive handling, and accidental raw-state staging. Commit only necessary corrections.

## Task 6: Integrate and prove production freshness

**Files:**

- No planned source changes; deployment-only corrections require their own tested commit.

### Step 1: Push and open the pull request

```bash
git push -u origin codex/production-stabilization
gh pr create --fill
```

Wait for every required check and inspect failures rather than rerunning blindly.

### Step 2: Merge the verified pull request

Merge only when local and remote gates are green. Resolve the exact active stale publish run and cancel it if it still blocks concurrency, then dispatch one controlled publish workflow on `main`.

### Step 3: Verify workflow and deployment

Confirm the controlled run:

- restores or bootstraps state;
- publishes both checkpoints;
- exports and uploads Pages within 180 minutes;
- deploys the merged commit.

### Step 4: Smoke-test production

Verify over HTTPS:

- the public snapshot `generated_at` reflects the controlled run;
- project, research, platform, and hardware data remain populated;
- the release/change stream is non-empty;
- `model-index.v1.json` reports the complete catalog and every shard is reachable;
- newest model search works, including a recent low-download release;
- project, research, hardware, platform, and model detail routes open successfully.

### Step 5: Report evidence

Return the pull request, merged commit, workflow run, deployment URL, production timestamp/counts, and any remaining external requirement such as a missing `HF_TOKEN` secret.
