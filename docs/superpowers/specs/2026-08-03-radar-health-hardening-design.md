# Radar Health Hardening — Design

**Date:** 2026-08-03
**Status:** Approved by the user's “fix all” instruction
**Extends:** `2026-07-31-radar-restoration-and-elevation-design.md` and `2026-08-03-production-stabilization-design.md`
**Primary persona:** Infrastructure architect

## Outcome

The radar must operate as a trustworthy command center, not merely render a large catalog. A scheduled publication must finish inside its two-hour cadence, preserve progress across failures, publish atomically despite unrelated bot commits, and expose honest, actionable data. Every visible search, filter, link, health indicator, and freshness statement must be backed by working behavior.

## 1. Bounded incremental intelligence pipeline

- Discovery resumes from each adapter's `last_success_at` with a small overlap, rather than replacing elapsed downtime with a fixed two-hour lookback.
- Verification and enrichment process bounded priority batches. New, high-signal, official, and previously verified releases rank ahead of low-signal historical candidates. Remaining candidates stay queued for later scheduled runs.
- Network work has explicit concurrency and per-operation timeouts. One slow source cannot consume the full workflow budget.
- Checkpoints remain durable between discovery, verification, and publication. Queue depth and processed counts are exported so operators can distinguish healthy backlog drainage from a stuck job.
- An HF repository is a detected artifact, not proof of deployability. `deployable_onprem` requires usable weights/artifacts plus supported task or runtime evidence; insufficient evidence remains `onprem_adjacent` or `market_reference`.

## 2. Transaction-safe publication

- Publication artifacts are built and tested before persistence.
- The small generated-history commit is rebased onto current `origin/main` immediately before push and retried on non-fast-forward races.
- Pages upload/deploy is not silently skipped because an unrelated keepalive commit raced.
- Workflow tests exercise the reconciliation script as behavior, not source-text matching.
- Workflow telemetry reports phase duration, queue depth, selected count, and checkpoint identity without exposing credentials.

## 3. Trustworthy recency, ranking, and health

- Release recency uses upstream publication or modification time. Observation time is retained separately and never presented as the release date.
- Default ranking combines actual recency, source authority, verification state, popularity, metadata completeness, and on-prem relevance. Retrieval order is not a ranking signal.
- Official releases such as Kimi K3 surface immediately when detected from authoritative sources, even while lower-signal backlog remains.
- Source health evaluates adapter status, consecutive failures, circuit state, and cadence-aware staleness. A low-frequency feed with no new post is not unhealthy merely because it produced zero items in a two-hour scan.
- UI ages are computed from timestamps at render time. Static snapshot `age_hours` is compatibility data only.

## 4. Complete, honest frontend behavior

- Global search submits to the catalog and preserves the query in the URL.
- Every visible catalog filter either has populated facet options and affects results in static/API modes, or is removed. Supported filters are publisher, license, hardware tier, modality, platform, freshness, review state, category, lifecycle, and lane.
- Trust summaries count only sources whose explicit status is healthy and whose circuit is closed.
- Static mode says when the snapshot was generated and when the browser checked it; it does not claim per-minute live data or applied estate policies when those capabilities are unavailable.
- Compare provides searchable model selection across the complete index, not the first ingestion-ordered rows.
- Static-only deployments hide disabled workspace/review actions and never emit broken absolute `/api` links.
- Project, research, hardware, platform, release, and model rows and cards retain direct detail navigation and outbound evidence links.

## 5. Data-quality reporting

- Public snapshot quality includes coverage metrics for verification, license, parameters, context, hardware compatibility, evidence, and hardware specifications.
- Low-confidence records are labeled and excluded from priority surfaces rather than deleted from the searchable catalog.
- Feed generation remains non-empty when backing change history exists; RSS/JSON timestamps and item links are validated during export.
- Source configuration exposes all enabled/disabled adapter families and their reason, making coverage gaps visible to the infrastructure architect.

## 6. Verification and rollout

- Every behavior change follows red-green-refactor tests.
- Backend: Ruff, MyPy, full pytest, focused large-catalog/performance tests.
- Frontend: Vitest, typecheck, ESLint, production build, Playwright static-site suite.
- Deployment: merged PR, successful publish and Pages jobs, current `generated_at`, complete shard retrieval, non-empty changes feeds, newest-model search, and every detail-route family checked over HTTPS.
- The deployment monitor is removed only after all production checks pass.

## Non-goals

- Authentication or multiple roles.
- Replacing GitHub Pages or the GitHub Release state bundle in this release.
- Automatically declaring recommendations without evidence.
- Fully enriching the historical Hugging Face corpus in one workflow run.
