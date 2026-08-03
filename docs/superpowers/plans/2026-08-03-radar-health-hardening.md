# Radar Health Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the two-hour radar pipeline finish reliably and make every public health, freshness, search, filter, ranking, and navigation behavior truthful and usable.

**Architecture:** Bound expensive pipeline stages with deterministic priority batches and resume discovery from source watermarks. Separate detection from deployability, compute ranking and age from upstream evidence, reconcile publication against current main, and drive frontend controls from the same complete sharded catalog contract.

**Tech Stack:** Python 3.12+, SQLAlchemy, Typer, pytest, GitHub Actions, React 19, TypeScript, TanStack Query, Vitest, Playwright.

## Global Constraints

- Preserve the no-login, single infrastructure-architect persona.
- Keep GitHub Pages and the GitHub Release state bundle.
- Never print or persist secret values.
- Never hide low-confidence records from explicit catalog search; exclude them only from priority surfaces.
- All behavior changes use a failing test first.

---

### Task 1: Bound and resume the intelligence pipeline

**Files:**
- Modify: `src/radar/intelligence/pipeline.py`
- Modify: pipeline service/repository contracts required for priority selection
- Modify: CLI commands that invoke verification/enrichment
- Test: focused intelligence pipeline and CLI tests

- [ ] Add failing tests proving discovery starts at `last_success_at - overlap`, not a fixed lookback.
- [ ] Add failing tests proving verification/enrichment select a deterministic bounded batch with official/new/high-signal items first and report remaining queue depth.
- [ ] Add failing tests proving a generic HF artifact is not automatically `deployable_onprem`.
- [ ] Implement the minimal watermark, prioritization, batch, timeout, and classification changes.
- [ ] Run focused tests, Ruff, and MyPy; commit the green task.

### Task 2: Make publication race-safe and observable

**Files:**
- Modify: `.github/workflows/publish.yml`
- Create or modify: a focused publication reconciliation script if required
- Test: `tests/test_publish_workflow.py` plus script behavior tests

- [ ] Add a failing integration-style test using a temporary bare repository where remote `main` advances before persistence; assert publication rebases/retries and preserves both commits.
- [ ] Add a failing workflow-contract test for phase metrics and artifact upload ordering.
- [ ] Implement reconciliation, bounded retries, and phase/queue telemetry without exposing secrets.
- [ ] Run focused workflow tests and `git diff --check`; commit the green task.

### Task 3: Correct recency, ranking, source health, and quality metrics

**Files:**
- Modify: intelligence source contracts/adapters and snapshot/export ranking modules
- Modify: `src/radar/storage/source_health_store.py` and public health projection
- Test: adapter, ranking, snapshot, and source-health tests

- [ ] Add failing fixtures where upstream publication time differs from observation time and assert displayed/ranked recency uses upstream time.
- [ ] Add failing ranking tests proving authoritative recent releases outrank historical low-signal detections.
- [ ] Add failing health tests for explicit failure, open circuits, cadence-aware staleness, and healthy low-frequency empty feeds.
- [ ] Add failing snapshot tests for quality coverage metrics and enabled/disabled adapter-family visibility.
- [ ] Implement minimal semantics and run focused tests, Ruff, and MyPy; commit the green task.

### Task 4: Make frontend controls and claims real

**Files:**
- Modify: `frontend/src/app/shell/TopBar.tsx`
- Modify: catalog query/filter/client modules and tests
- Modify: overview trust/freshness components and tests
- Modify: compare selection and static-mode action/link components
- Modify: Playwright static-site specifications

- [ ] Add failing tests for global-search URL navigation.
- [ ] Add failing tests proving every rendered filter populates from facets and filters complete-index results before the 500-row cap.
- [ ] Add failing tests proving trust counts require healthy status and wall-clock age derives from timestamps.
- [ ] Add failing tests for searchable compare selection, honest static copy, hidden review/workspace actions, and relative/static-safe integration links.
- [ ] Implement the minimal UI/client changes, removing any control without backing data.
- [ ] Run Vitest, typecheck, ESLint, build, and focused Playwright tests; commit the green task.

### Task 5: Verify data depth, navigation, and feeds locally

**Files:**
- Modify only code/tests required by failures.

- [ ] Export a clean static site from representative state and validate non-empty JSON/RSS feeds when history exists.
- [ ] Validate complete model-index manifest counts and every shard.
- [ ] Exercise project, research, hardware, platform, model, and release details plus external evidence links.
- [ ] Run full backend and frontend quality suites and a 20,000-release performance fixture.
- [ ] Review the complete diff for secrets, unsafe state handling, dead UI, and unrelated changes.

### Task 6: Integrate and prove production

**Files:**
- No planned source files; deployment failures require their own test-first scoped commit.

- [ ] Push `codex/radar-health-hardening`, open a ready PR, and wait for required checks.
- [ ] Merge the green PR and dispatch exactly one publish workflow if no current main run exists.
- [ ] Verify the state release asset, publish job, Pages deployment, fresh counts/timestamp, all shards, JSON/RSS feeds, newest-model search, and each detail-route family.
- [ ] Confirm `HF_TOKEN` by secret name only.
- [ ] Delete the deployment heartbeat after production verification and report the PR, commits, runs, counts, and residual external risks.
