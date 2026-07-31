# Radar Restoration Phase 0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the post-cutover regressions by unblocking canonical enrichment and qualification, restoring non-empty subscriber feeds, eliminating the persistence race, reconnecting the classic radar, and making public documentation match the shipped product.

**Architecture:** Preserve the canonical intelligence store as the future-facing core while treating the legacy radar as the authoritative compatibility surface during restoration. Canonicalize model repository identity as `hf_repo`, route lifecycle changes through `LifecycleService`, and introduce one export-level feed composer so legacy ring events and intelligence lifecycle events share stable public filenames without multiple writers. Consolidate scheduled mutation and deployment in `publish.yml`; expose classic pages and downloads through snapshot-backed React navigation until later phases reach parity.

**Tech Stack:** Python 3.12+, FastAPI, SQLAlchemy, Pydantic, Typer, Jinja/static export, React 19, TypeScript, TanStack Query, Vite, Vitest, Playwright, GitHub Actions.

## Global Constraints

- Implement only Phase 0 from `docs/superpowers/specs/2026-07-31-radar-restoration-and-elevation-design.md` in this branch.
- Branch name: `feature/restoration/phase-0-stop-the-bleeding`; conventional commits; no direct push to `main`.
- Never break a URL or feed that previously shipped.
- Legacy data remains authoritative for curated entities until Phase 4 field-level shadow comparison proves canonical parity.
- Preserve append-only semantics for `data/*.jsonl`; corrections supersede and never rewrite history.
- Every phase gate must pass: Ruff, mypy, pytest, frontend typecheck/lint/build, Playwright, plus Phase 0-specific gates.
- The two-hour schedule is a collection cadence, not a universal claim-validity duration.
- Do not weaken an existing assertion to make a gate pass.

---

### Task 1: Canonical repository identity and lifecycle migration

**Files:**
- Modify: `src/radar/intelligence/pipeline.py`
- Modify: `src/radar/intelligence/migration.py`
- Modify: `src/radar/intelligence/repositories.py`
- Modify: `src/radar/intelligence/lifecycle.py`
- Test: `tests/intelligence/test_pipeline.py`
- Test: `tests/intelligence/test_migration.py`
- Test: `tests/e2e/test_migration_rehearsal.py`

**Interfaces:**
- Consumes: `SqlAlchemyIntelligenceRepository.list_claims_for_subject(release_id)`, `LifecycleService.transition(...)`, legacy `ModelSeed.hf_repo`.
- Produces: `IntelligenceJobRunner._repository_identity(release_id) -> str | None`, canonical `hf_repo` claims, and durable `LifecycleTransition` rows for migrated verified seeds.

- [ ] **Step 1: Write the failing migrate → enrich → qualify regression**

Add a fixture adapter whose `enrich(repo_id)` records the received repository and returns a documented `library_name` compatibility claim. Seed a spec-verified legacy model using `hf_repo: acme/Sample-8B`, run `import_legacy_state`, then run ENRICHMENT and QUALIFICATION.

```python
@pytest.mark.asyncio
async def test_migrated_hf_repo_enriches_and_qualifies(tmp_path):
    seed_legacy_root(tmp_path)
    repository = repository_for(tmp_path)
    import_legacy_state(tmp_path, repository)
    adapter = MigratedFixtureEnricher()
    runner = IntelligenceJobRunner(
        root=tmp_path,
        repository=repository,
        adapters=[adapter],
        clock=lambda: NOW,
    )

    enriched = await runner.run(JobKind.ENRICHMENT, "job:enrich:migrated")
    qualified = await runner.run(JobKind.QUALIFICATION, "job:qualify:migrated")

    assert adapter.seen == ["acme/Sample-8B"]
    assert enriched.updated == 1
    assert qualified.updated == 1
    assert repository.get_release_required(
        "release:legacy:sample-8b"
    ).lifecycle is LifecycleState.QUALIFIED
```

- [ ] **Step 2: Run the regression and confirm the predicate dead-end**

Run: `uv run pytest tests/intelligence/test_pipeline.py::test_migrated_hf_repo_enriches_and_qualifies -v`

Expected: FAIL because `_enrich` only queries `repo_id`, so the adapter is never called and qualification updates zero releases.

- [ ] **Step 3: Canonicalize repository lookup**

Add a focused helper in `IntelligenceJobRunner` and use it from `_enrich`:

```python
def _repository_identity(self, release_id: str) -> str | None:
    for predicate in ("hf_repo", "repo_id"):
        value = self._claim_value(release_id, predicate)
        if isinstance(value, str) and "/" in value:
            return value
    return None
```

`hf_repo` is canonical; `repo_id` remains a read fallback for discoveries already stored under the old predicate. New discovery candidates from Hugging Face must emit `hf_repo`, not create a second identity vocabulary.

- [ ] **Step 4: Add migration lifecycle coverage**

Extend `tests/intelligence/test_migration.py`:

```python
def test_verified_legacy_seed_records_detected_to_verified_transition(tmp_path):
    seed_legacy_root(tmp_path)
    repository = repository_for(tmp_path)
    import_legacy_state(tmp_path, repository)

    transitions = repository.list_lifecycle_transitions(
        "release:legacy:sample-8b"
    )
    assert [(row.from_state, row.to_state) for row in transitions] == [
        (LifecycleState.DETECTED, LifecycleState.VERIFIED)
    ]
    assert transitions[0].evidence_ids == [
        "evidence:legacy:model-seed:sample-8b"
    ]
```

- [ ] **Step 5: Route verified legacy imports through `LifecycleService`**

Create migrated releases as `DETECTED`, persist evidence and claims, then call:

```python
LifecycleService(repository).transition(
    release_id,
    LifecycleState.VERIFIED,
    reason="Legacy seed carries human-verified specifications",
    evidence_ids=[evidence.id],
    now=LEGACY_OBSERVED_AT,
)
```

On idempotent re-import, do not replay an existing transition. Add or reuse a repository query that detects the current state/transition before invoking the service. Preserve unverified seeds as `DETECTED`.

- [ ] **Step 6: Run lifecycle and rehearsal coverage**

Run:

```bash
uv run pytest tests/intelligence/test_migration.py tests/intelligence/test_pipeline.py tests/e2e/test_migration_rehearsal.py -v
```

Expected: PASS; at least one migrated fixture release reaches Qualified; transition count remains stable after a second import.

- [ ] **Step 7: Commit the canonical pipeline fix**

```bash
git add src/radar/intelligence/pipeline.py src/radar/intelligence/migration.py \
  src/radar/intelligence/repositories.py src/radar/intelligence/lifecycle.py \
  tests/intelligence/test_pipeline.py tests/intelligence/test_migration.py \
  tests/e2e/test_migration_rehearsal.py
git commit -m "fix(intelligence): unblock migrated model qualification"
```

---

### Task 2: One unified, backward-compatible feed writer

**Files:**
- Create: `src/radar/reports/unified_feeds.py`
- Modify: `src/radar/web/react_export.py`
- Modify: `src/radar/web/static_site.py`
- Modify: `src/radar/cli.py`
- Test: `tests/test_feeds.py`
- Test: `tests/test_react_export.py`
- Test: `tests/test_cli.py`
- Test: `frontend/e2e/public-static.spec.ts`

**Interfaces:**
- Consumes: `list[ProjectHistoryEvent]`, `list[IntelligenceEvent]`, base URL, site title.
- Produces: `UnifiedFeedItem`, `collect_unified_feed_items(...)`, and `write_unified_feeds(out_dir, ...)` as the only writer for `changes.xml`, `changes.rss`, and `changes.json`.

- [ ] **Step 1: Write failing feed-continuity tests**

Add tests proving both event families appear newest-first and retain stable IDs:

```python
def test_unified_feed_keeps_legacy_ring_events_when_intelligence_is_empty(tmp_path):
    write_unified_feeds(
        tmp_path,
        project_events=[_event("vLLM", 12, ChangeType.PROMOTED, Ring.ADOPT)],
        intelligence_events=[],
        site_title="Radar",
        base_url="https://example.test/radar",
    )
    rss = ElementTree.fromstring((tmp_path / "changes.rss").read_text())
    assert [item.findtext("title") for item in rss.findall("./channel/item")] == [
        "vLLM promoted to adopt"
    ]

def test_unified_feed_merges_lifecycle_and_ring_events_newest_first(tmp_path):
    ...
    assert ids == ["intelligence:release-qualified:...", "project:run-12:vLLM"]
```

- [ ] **Step 2: Run feed tests and confirm overwrite behavior**

Run: `uv run pytest tests/test_feeds.py tests/test_react_export.py -v`

Expected: FAIL because `export_react_site` overwrites `changes.rss` and `changes.json` with intelligence-only output.

- [ ] **Step 3: Implement transport-neutral unified feed items**

Define a frozen model/dataclass with exact public fields:

```python
@dataclass(frozen=True)
class UnifiedFeedItem:
    id: str
    title: str
    url: str
    summary: str
    occurred_at: datetime
    kind: Literal["project_ring", "intelligence_lifecycle"]
```

Map legacy IDs from immutable history identity (`run_id`, project, change type) and canonical IDs from `IntelligenceEvent.id`. Deduplicate by ID, sort by `(-occurred_at.timestamp(), id)`, and cap only after merging.

- [ ] **Step 4: Make `write_unified_feeds` the single writer**

Move filename ownership for `changes.xml`, `changes.rss`, and `changes.json` to `src/radar/reports/unified_feeds.py`. Remove those writes from `static_site._write_feeds` and `react_export.export_react_site`; keep the legacy render helpers as item-formatting dependencies if useful. Call the unified writer once from the top-level export after legacy HTML rendering and after the canonical repository is available.

Keep these independent files untouched and published: `changes-models.*`, `changes-research.*`, `changes.xml`, `digests/digest.xml`, `digests/digest-rss.xml`.

- [ ] **Step 5: Add an export invariant**

At the unified writer boundary, enforce:

```python
if backing_event_count and not rendered_item_count:
    raise FeedContinuityError(
        "backing history is non-empty but the unified public feed has no items"
    )
```

Do not fail legitimately empty new installations. Add a unit test for both sides of the condition.

- [ ] **Step 6: Strengthen browser feed assertions**

Update `frontend/e2e/public-static.spec.ts`:

```typescript
const rssText = await rss.text();
expect(rssText).toContain("<rss");
expect(rssText).toContain("<item>");

const jsonFeed = await page.request.get("/changes.json");
expect((await jsonFeed.json()).items.length).toBeGreaterThan(0);
```

Also assert the auxiliary model/research/digest feed URLs return HTTP 200.

- [ ] **Step 7: Run export and feed gates**

Run:

```bash
uv run pytest tests/test_feeds.py tests/test_react_export.py tests/test_cli.py -v
uv run radar export --root . --out _site-test
cd frontend && npx playwright test e2e/public-static.spec.ts
```

Expected: PASS; `changes.rss` and `changes.json` have at least one item with the committed non-empty history.

- [ ] **Step 8: Commit feed continuity**

```bash
git add src/radar/reports/unified_feeds.py src/radar/web/react_export.py \
  src/radar/web/static_site.py src/radar/cli.py tests/test_feeds.py \
  tests/test_react_export.py tests/test_cli.py frontend/e2e/public-static.spec.ts
git commit -m "fix(feeds): restore subscriber continuity"
```

---

### Task 3: Consolidated two-hour workflow and predicate-class freshness

**Files:**
- Delete: `.github/workflows/intelligence-discovery.yml`
- Modify: `.github/workflows/publish.yml`
- Modify: `src/radar/intelligence/freshness.py`
- Modify: `tests/intelligence/test_freshness.py`
- Modify: `tests/test_intelligence_workflows.py`

**Interfaces:**
- Consumes: existing `radar intelligence-run discovery`, `verify-new`, enrichment, qualification, recommendations commands.
- Produces: one scheduled mutator/deployer and `FRESHNESS_WINDOWS` with predicate-specific durations.

- [ ] **Step 1: Write failing workflow ownership tests**

Replace the discovery-workflow expectation with a repository-wide invariant:

```python
def test_only_publish_workflow_mutates_intelligence_db_and_deploys_pages():
    workflows = load_all_workflows()
    owners = [
        path for path, body in workflows.items()
        if "git add -f data/intelligence.db" in all_run_commands(body)
    ]
    assert owners == [Path(".github/workflows/publish.yml")]
    commands = all_run_commands(workflows[owners[0]])
    assert "radar intelligence-run discovery" in commands
    assert "radar intelligence-run verify-new" in commands
```

- [ ] **Step 2: Restore exact predicate windows in tests**

Parameterize boundary tests:

```python
@pytest.mark.parametrize(
    ("predicate", "window"),
    [
        ("release_identity_new", timedelta(days=7)),
        ("release_identity_established", timedelta(days=30)),
        ("artifact_availability", timedelta(days=7)),
        ("license", timedelta(days=30)),
        ("platform_compatibility", timedelta(days=30)),
        ("benchmark", timedelta(days=90)),
        ("hardware_spec", timedelta(days=90)),
        ("security_advisory", timedelta(days=1)),
        ("package_release", timedelta(days=1)),
    ],
)
def test_predicate_freshness_boundary(predicate, window):
    assert service.status(predicate, NOW - window, NOW) is ClaimFreshness.FRESH
    assert service.status(
        predicate, NOW - window - timedelta(seconds=1), NOW
    ) is ClaimFreshness.STALE
```

- [ ] **Step 3: Run tests to verify the current race and flat window fail**

Run: `uv run pytest tests/test_intelligence_workflows.py tests/intelligence/test_freshness.py -v`

Expected: FAIL because two workflows own `data/intelligence.db` and every predicate currently expires after two hours.

- [ ] **Step 4: Fold discovery into publish**

In `publish.yml`, after canonical migration/replay and before enrichment, run:

```yaml
- name: Discover and verify new intelligence
  run: |
    uv run radar intelligence-run discovery --root .
    uv run radar intelligence-run verify-new --root .
```

Keep one two-hour cron and the weekly verification cron. Delete `.github/workflows/intelligence-discovery.yml`. Preserve persistence of `data/intelligence/events.jsonl` and `data/intelligence/snapshots/` in the single commit step.

- [ ] **Step 5: Restore predicate-class windows**

Replace the global two-hour comprehension with the exact mapping from Step 2. Keep the two-hour schedule comment in workflow configuration only; do not encode collection cadence into claim validity.

- [ ] **Step 6: Run workflow/freshness tests**

Run: `uv run pytest tests/test_intelligence_workflows.py tests/intelligence/test_freshness.py -v`

Expected: PASS; only `publish.yml` mutates the DB and every boundary matches the approved design.

- [ ] **Step 7: Commit workflow consolidation**

```bash
git add .github/workflows/publish.yml .github/workflows/intelligence-discovery.yml \
  src/radar/intelligence/freshness.py tests/intelligence/test_freshness.py \
  tests/test_intelligence_workflows.py
git commit -m "fix(ci): consolidate intelligence publishing"
```

---

### Task 4: Classic radar bridge and integration downloads

**Files:**
- Modify: `src/radar/web/public_context.py`
- Modify: `src/radar/web/intelligence_snapshot.py`
- Modify: `frontend/src/features/catalog/catalogQueries.ts`
- Modify: `frontend/src/app/shell/Sidebar.tsx`
- Modify: `frontend/src/features/operations/IntegrationsPage.tsx`
- Modify: `frontend/src/design/global.css`
- Test: `tests/test_intelligence_snapshot.py`
- Test: `frontend/src/app/App.test.tsx`
- Create: `frontend/src/features/operations/IntegrationsPage.test.tsx`
- Test: `frontend/e2e/public-static.spec.ts`

**Interfaces:**
- Consumes: `data/digest-log.jsonl`, existing legacy export filenames, static-mode base URL rules.
- Produces: `PublicSnapshot.latest_digest`, a `Classic radar` sidebar group, and integrations sections for history, feeds, and digest subscriptions.

- [ ] **Step 1: Write failing snapshot digest test**

Append two digest records with distinct timestamps and assert the snapshot returns the newest valid record only:

```python
assert snapshot.latest_digest == {
    "generated_at": "2026-07-31T08:00:00Z",
    "html_url": "digests/2026-07-31.html",
    "card_url": "digests/cards/2026-07-31.png",
}
```

Malformed trailing JSONL lines must be skipped with a warning, matching other durable-log readers.

- [ ] **Step 2: Add the snapshot contract**

Implement `load_latest_digest(root: Path) -> dict[str, str] | None` in `public_context.py`, add `latest_digest` to `PublicSnapshot`, and update the TypeScript `PublicSnapshot` type. Do not expose private workspace data.

- [ ] **Step 3: Write failing navigation tests**

Assert the sidebar contains plain anchors—not React `Link` components—for:

```text
models.html
platforms.html
techniques.html
trending.html
history.html
compare.html
<latest digest html_url>
```

Plain anchors are required because these are sibling exported documents, not SPA routes.

- [ ] **Step 4: Implement the Classic radar group**

Add a visually subordinate `Classic radar` group after the primary product groups. Preserve Mega Bilişim typography/colors, show “Deep legacy views during restoration,” and omit the digest link only when `latest_digest` is absent.

- [ ] **Step 5: Replace the integrations placeholder with real downloads**

Render three structured sections:

1. History: `history.jsonl`, `model-history.jsonl`, `technique-history.jsonl`, `trending-observations.jsonl`.
2. Feeds: `changes.rss`, `changes.json`, `changes.xml`, model/research feeds, digest Atom/RSS.
3. MCP/API: existing API docs and MCP configuration guidance already supported by the project.

Each entry must state format and purpose. Use `<a href>` for static compatibility and do not claim a file exists unless the exporter guarantees it or the snapshot advertises it.

- [ ] **Step 6: Add Playwright reachability coverage**

From the deployed SPA shell, assert every Classic radar link exists and request each URL directly. Assert the integrations feed/history links are visible and their requests return 200.

- [ ] **Step 7: Run bridge tests**

Run:

```bash
uv run pytest tests/test_intelligence_snapshot.py -v
npm test --prefix frontend -- --run
npm run typecheck --prefix frontend
npm run lint --prefix frontend
uv run radar export --root . --out _site-test
cd frontend && npx playwright test e2e/public-static.spec.ts
```

Expected: PASS; every classic target and promised download is reachable from the React product.

- [ ] **Step 8: Commit the restoration bridge**

```bash
git add src/radar/web/public_context.py src/radar/web/intelligence_snapshot.py \
  frontend/src/features/catalog/catalogQueries.ts frontend/src/app/shell/Sidebar.tsx \
  frontend/src/features/operations/IntegrationsPage.tsx frontend/src/design/global.css \
  tests/test_intelligence_snapshot.py frontend/src/app/App.test.tsx \
  frontend/src/features/operations/IntegrationsPage.test.tsx \
  frontend/e2e/public-static.spec.ts
git commit -m "feat(frontend): reconnect classic radar surfaces"
```

---

### Task 5: Documentation and durable recovery truth

**Files:**
- Modify: `README.md`
- Modify: `docs/persistence.md`
- Modify: `.github/workflows/publish.yml`
- Test: `tests/test_intelligence_workflows.py`
- Test: `tests/test_docs_contract.py` (create if no equivalent contract test exists)

**Interfaces:**
- Consumes: actual workflow schedule, source count from `data/config.yaml`, repository package layout.
- Produces: documentation that distinguishes shipped Radar, in-progress Intelligence, and CLI/MCP Planner capabilities.

- [ ] **Step 1: Write failing documentation contract tests**

```python
def test_readme_matches_shipping_cadence_and_source_count():
    readme = Path("README.md").read_text()
    assert "every two hours" in readme.casefold()
    assert "68" in readme
    assert "51 curated sources" not in readme

def test_persistence_artifacts_are_committed_by_publish_workflow():
    commands = all_run_commands(load_yaml(".github/workflows/publish.yml"))
    assert "git add -f data/intelligence/events.jsonl" in commands
    assert "git add -f data/intelligence/snapshots" in commands
```

- [ ] **Step 2: Update README product truth**

Use three explicit Highlights subsections:

- `Radar — shipping`: rings, projects, evidence, movers/feeds only where currently reachable.
- `Intelligence — restoration in progress`: canonical lifecycle/API/source health, without claiming production population gates not yet met.
- `Planner — CLI and MCP`: capacity engine commands/tools, explicitly stating the web planner arrives in Phase 3.

Update Project layout with `src/radar/intelligence/`, `src/radar/api/`, `src/radar/capacity/`, and `frontend/`. State the two-hour cadence and derive the source number from current config rather than repeating stale prose elsewhere.

- [ ] **Step 3: Align persistence docs and workflow**

Keep the preferred recovery contract: `publish.yml` force-adds `data/intelligence/events.jsonl` and `data/intelligence/snapshots/` when present. Document the SQLite store, JSONL event ledger, raw snapshot blobs, replay order, and the fact that generated public snapshots are projections—not primary history.

- [ ] **Step 4: Run docs/workflow contracts**

Run: `uv run pytest tests/test_docs_contract.py tests/test_intelligence_workflows.py -v`

Expected: PASS; docs contain no daily/51-source contradiction and recovery artifacts are persisted by the sole workflow.

- [ ] **Step 5: Commit documentation honesty**

```bash
git add README.md docs/persistence.md .github/workflows/publish.yml \
  tests/test_docs_contract.py tests/test_intelligence_workflows.py
git commit -m "docs: align radar capabilities and persistence"
```

---

### Task 6: Phase 0 release gate and full-diff review

**Files:**
- Modify only if a gate reveals a defect in a Phase 0-owned file.
- Verify: entire branch diff against `origin/main`.

**Interfaces:**
- Consumes: deliverables from Tasks 1–5.
- Produces: a reviewable Phase 0 branch satisfying every acceptance gate in the approved spec.

- [ ] **Step 1: Run the complete backend quality gate**

```bash
uv run pytest -q
uv run ruff check .
uv run mypy src/radar
git diff --check origin/main...HEAD
```

Expected: all tests pass (one existing platform-dependent skip is acceptable); Ruff and mypy report no issues; diff check is silent.

- [ ] **Step 2: Run the complete frontend quality gate**

```bash
npm test --prefix frontend -- --run
npm run typecheck --prefix frontend
npm run lint --prefix frontend
npm run build --prefix frontend
```

Expected: all Vitest files pass; TypeScript/ESLint/build exit 0.

- [ ] **Step 3: Build the real static product and run browser gates**

```bash
uv run radar export --root . --out _site-test \
  --base-url https://ekaynac.github.io/onprem-ai-adoption-radar
cd frontend && npx playwright test
```

Expected: feeds contain items, classic links resolve, current SPA routes remain accessible, and all accessibility/responsive journeys pass.

- [ ] **Step 4: Prove the Phase 0 invariants directly**

Run read-only checks against `_site-test` and a fixture canonical database:

```bash
rg -c '<item>' _site-test/changes.rss
uv run python -c 'import json; print(len(json.load(open("_site-test/changes.json"))["items"]))'
rg -n 'models.html|platforms.html|techniques.html|trending.html|history.html|compare.html' \
  _site-test/assets/*.js
```

Also run the migrate → enrich → qualify fixture test alone and record its passing output in the PR description.

- [ ] **Step 5: Review the complete branch diff**

Inspect:

```bash
git diff --stat origin/main...HEAD
git diff origin/main...HEAD -- . ':!frontend/src/api/generated/schema.d.ts'
git status --short
```

Confirm: one feed writer per public filename, one DB-mutating workflow, no unrelated data-history rewrites, no dead Classic radar URL, and no capability overclaim in docs.

- [ ] **Step 6: Request final code review and address only evidence-backed findings**

Use the requesting-code-review workflow on the complete branch. Re-run the smallest relevant regression after each fix, then repeat Steps 1–5 before claiming completion.

- [ ] **Step 7: Push Phase 0 and open a non-draft PR**

```bash
git push -u origin feature/restoration/phase-0-stop-the-bleeding
gh pr create --base main \
  --head feature/restoration/phase-0-stop-the-bleeding \
  --title "Restore radar pipeline and subscriber continuity" \
  --body-file /tmp/radar-phase-0-pr.md
```

The PR body must enumerate each Phase 0 gate with command evidence and must not promise Phase 1–6 features.
