# On-Prem Intelligence Platform Redesign — Design

**Date:** 2026-07-30  
**Status:** Approved design; written specification under user review  
**Primary persona:** Enterprise AI and infrastructure architect  
**Delivery strategy:** Contract-first, data-first rebuild with one integrated product release

## 1. Purpose

Transform the On-Prem AI Adoption Radar from a collection of strong but
separate reports into a unified, continuously updated on-prem AI intelligence
platform.

The product must answer three questions from one command center:

1. What changed in the on-prem AI market?
2. What should this organization adopt, pilot, watch, or avoid?
3. Which model, platform, hardware topology, and operating constraints fit a
   specific workload?

Infrastructure architects are the default audience. Engineers receive deeper
artifacts, commands, compatibility details, and evidence. Executives receive
condensed market movement, risk, and decision implications. These are views of
the same data, not separate products.

## 2. Current-state findings

The repository already contains valuable production foundations:

- Deterministic scoring, append-only history, capacity planning, source health,
  discovery, model and research radars, static publishing, feeds, and MCP.
- 47 seeded models, 8 serving platforms, 73 project sources, 65 research
  techniques, and 60 device presets as of 2026-07-30.
- Daily persisted observations for models, techniques, and trending projects.
- GitHub Actions for daily publishing and weekly catalog/source autopilot.

The redesign addresses four structural limitations:

- Model coverage is seed-first and incomplete. Only 7 of 47 seeded models have
  verified architecture data; 32 have context length; 25 have a use-case
  description.
- Platform capability is an eight-platform manually verified snapshot rather
  than a version-aware intelligence stream.
- RSS coverage consists of four broad firehose feeds. Releases are discovered
  through several separate pipelines, but there is no single release lifecycle.
- The frontend is a dense collection of server-rendered tables. It exposes
  facts but does not organize them into a daily architect workflow.

## 3. Product principles

### 3.1 Fast publication without false certainty

New releases appear quickly with an explicit trust state. Speed never grants
authority: unverified claims cannot silently become trusted facts.

### 3.2 One intelligence core

The React application, FastAPI API, MCP tools, feeds, alerts, CLI, and static
edition must read the same canonical application services and contracts.

### 3.3 Provenance at claim level

Every material value records its source, retrieval time, evidence strength,
verification state, and freshness. `unknown`, `conflicting`, and `stale` are
first-class values.

### 3.4 Deterministic decisions

LLMs may extract candidate claims or assist natural-language presentation.
They may not verify facts, resolve conflicts, establish lifecycle status, or
assign adoption recommendations by themselves.

### 3.5 Public intelligence, private local context

The public edition remains read-only. Self-hosted installations may save
multiple organizational workspaces with hardware, workload, policy, watchlist,
and alert settings. No user accounts or login system are required.

### 3.6 Graceful degradation

A failed or changed source cannot block unrelated ingestion, erase prior
trusted facts, or prevent users from reading the last valid projection.

## 4. Success criteria

The integrated release is successful when:

- At least 95% of qualifying official major-model releases become publicly
  visible as **Detected** within two hours of the first observable official
  artifact or trusted registry record.
- A synthetic Kimi K3-style release passes end to end from source observation
  through identity resolution and Detected publication.
- No **Verified**, **Qualified**, or **Recommended** value exists without
  qualifying provenance under the rules in this document.
- Text/reasoning, multimodal, embedding/reranking, speech/audio, image/video,
  and vision/OCR/document model categories have distinct schemas and
  qualification rubrics.
- Model/platform compatibility is version-aware and carries documented,
  tested, or inferred evidence strength.
- API, MCP, feeds, static export, and React surfaces return equivalent current
  facts for the same query and workspace.
- Existing project, model, research, history, capacity, and scoring data
  migrate without losing effective history.
- A self-hosted user can create multiple workspaces and obtain different
  recommendations from different estates or policies without logging in.
- The public edition contains no workspace-specific private data or mutation
  controls.
- The production build, full automated test suite, migration rehearsal,
  accessibility checks, and static export all pass before cutover.

## 5. Scope and release policy

### 5.1 Intelligence lanes

Every model release belongs to one of three lanes:

1. **Deployable on-prem** — weights are available and the release is
   technically deployable under its license and artifact format.
2. **On-prem adjacent** — weights are announced, gated, restricted, incomplete,
   or not yet practically deployable.
3. **Market reference** — proprietary or API-only releases retained for
   capability and market context.

The first two lanes may receive deployment-fit analysis and adoption
recommendations. Market-reference releases receive comparison and market
context but no on-prem adoption ring.

### 5.2 Model categories

The target catalog covers:

- Text and reasoning LLMs
- Multimodal and vision-language models
- Embedding and reranking models
- Speech-to-text, text-to-speech, and audio models
- Image and video generation models
- Vision, OCR, and document-understanding models

All categories share release identity, publisher, artifact, license,
provenance, and lifecycle contracts. Each category has its own capability,
fit, benchmark, and qualification fields.

### 5.3 Explicit non-goals

- Hosting or redistributing model weights
- Automatically running expensive model benchmarks
- Treating community rumors as public verified releases
- Letting an LLM verify facts or assign adoption rings
- Building accounts, login, role management, OAuth, or tenant isolation
- Rewriting current deterministic Python logic that can be safely wrapped
- Requiring Redis or another standalone queue for the default deployment

## 6. System architecture

The system contains six layers.

### 6.1 Source mesh

Adapters collect from:

- Hugging Face organizations, models, collections, files, model cards, and
  structured APIs
- ModelScope and other model registries with stable public metadata
- Ollama and deployable-format registries
- Official GitHub organizations, repositories, releases, tags, and files
- Official vendor blogs, documentation sites, RSS/Atom feeds, and announcement
  pages
- Package and container registries
- Official benchmark maintainers and evaluation repositories
- Papers and research indexes
- Security and license sources such as OSV and package advisories

Official artifacts outrank official documentation; official documentation
outranks trusted third-party registries; aggregators and community sources are
discovery signals only.

### 6.2 Ingestion and evidence ledger

The ingestion layer performs:

- Scheduled discovery every two hours
- Event or webhook ingestion when a source offers a reliable mechanism
- Publisher and release identity resolution
- Cross-source deduplication
- Structured claim extraction
- Raw snapshot retention
- Claim-level provenance recording
- Idempotent event emission

The default job runner uses database-backed job records, leases, and
idempotency keys. It runs as an in-process scheduler, CLI/cron jobs, or GitHub
Actions without changing domain behavior.

### 6.3 Trust lifecycle

All releases and material platform changes follow:

`Detected → Verified → Qualified → Recommended`

A release may enter `Review exception` from any automated verification or
qualification step. Review exceptions do not erase the last trusted value.

### 6.4 Canonical intelligence store

SQLite is the default local database. PostgreSQL is an optional deployment
target for larger catalogs or installations. Both implement the same
repository interfaces.

The store contains:

- Append-only observations, evidence, lifecycle transitions, and corrections
- Current projections for fast reads
- Models, releases, artifacts, platforms, compatibility, benchmarks, devices,
  research, and recommendations
- Saved workspaces, estates, workloads, policies, watchlists, and alerts
- Source/job health, review exceptions, webhook attempts, and feed cursors

Raw observations are never rewritten. Corrections supersede prior records.

### 6.5 Domain intelligence services

Four bounded services consume the canonical contracts:

- **Model intelligence:** category-specific model facts, benchmarks, risks,
  lifecycle, and model-to-artifact relationships
- **Platform intelligence:** engine releases, features, hardware scope,
  version-aware model support, and compatibility drift
- **Deployment intelligence:** fit, capacity, topology, throughput envelopes,
  launch guidance, power, and TCO
- **Market intelligence:** releases, news, research, momentum, risks, and
  adoption movement

### 6.6 Delivery surfaces

- React and TypeScript command center
- FastAPI REST API with OpenAPI-generated TypeScript client
- MCP server over the same application services
- CLI compatibility adapters
- Atom, RSS 2.0, and JSON Feed output
- Signed webhooks and optional notification adapters
- Read-only static public export

GraphQL is excluded from the integrated release.

## 7. Canonical intelligence model

### 7.1 Core entities

- **Publisher:** canonical organization, official domains/accounts, aliases,
  and verification state
- **Product family:** stable family identity across releases
- **Release:** immutable release identity, dates, lane, category, lifecycle,
  and aliases
- **Artifact:** weights, config, tokenizer, package, container, endpoint, or
  deployment bundle with checksum and accessibility state
- **Platform:** serving or execution system
- **Platform release:** version/tag and release evidence
- **Claim:** typed fact about an entity or relationship
- **Evidence observation:** source snapshot and extracted value supporting or
  disputing a claim
- **Compatibility assertion:** model release × platform version × hardware ×
  artifact/quantization × feature scope
- **Benchmark result:** task, dataset/version, score, evaluator, harness, and
  provenance
- **Qualification:** computed deployment, operational, license, security, and
  evidence assessment
- **Recommendation:** deterministic public or workspace-adjusted verdict
- **Lifecycle transition:** append-only status change with reason and inputs
- **Review exception:** conflict or ambiguity requiring human judgment

### 7.2 Claim contract

Every material claim records:

- Subject, predicate, typed value, unit, and applicable version/time range
- Source URL and source class
- Retrieved and effective timestamps
- Raw-content checksum and parser/extractor version
- Evidence strength: `official_artifact`, `official_documentation`,
  `official_repository`, `official_announcement`, `trusted_registry`,
  `benchmark_maintainer`, `aggregator`, or `community`
- Verification state: `candidate`, `verified`, `conflicting`, `stale`, or
  `rejected`
- Confidence used for routing and display, never as a substitute for
  verification
- Optional superseded claim and correction reason

### 7.3 Source precedence

For the same scoped fact:

1. Official artifact/config
2. Official documentation or model card
3. Official repository/release
4. Official announcement
5. Trusted registry or official benchmark maintainer
6. Aggregator
7. Community source

Lower-ranked evidence can reopen verification but cannot silently overwrite a
stronger current claim.

## 8. Release lifecycle rules

### 8.1 Candidate discovery

Any configured source may create an internal candidate. Public **Detected**
status requires at least one official source or trusted registry record.
Aggregator/community-only candidates stay in the internal review queue.

### 8.2 Detected

The minimum public Detected record contains:

- Canonical or provisional publisher
- Product/release name
- Release category or provisional category
- At least one official/trusted source
- First-observed timestamp
- Clear unverified status

Detected records may contain provisional claims, but the UI and API must label
them as unverified.

### 8.3 Verified

Automated verification promotes a release when:

- Publisher ownership is resolved to official domains/accounts.
- The official release or trusted registry identity is accessible.
- The applicable release lane is established.
- License or terms are captured from an authoritative source.
- Core identity and category-specific required claims are internally
  consistent.
- No unresolved higher-priority conflict exists.

For deployable and adjacent lanes, an accessible weights/artifact record is
required when the publisher claims weights are released. For market-reference
models, an official product/API artifact satisfies this requirement.

Failure or ambiguity creates a review exception; it does not delete the
Detected record.

### 8.4 Qualified

Qualification uses category-specific requirements. Common requirements are:

- Verified identity and license/terms
- Sufficient architecture/capability data for the category
- At least one compatibility or explicit incompatibility assessment
- Hardware or execution requirements with assumptions
- Operational, license, security, and evidence-freshness assessment

Unknown facts remain unknown. Missing evidence cannot be converted into
negative support.

### 8.5 Recommended

Only Verified and Qualified releases in deployable or adjacent lanes may
receive adoption rings. Recommendations are deterministic and contain:

- Public ring and score
- Workspace-adjusted ring and score when a workspace is selected
- Factors that changed the result
- Evidence and freshness references
- Assumptions and unknowns
- Computation version

## 9. Category-specific schemas

### 9.1 Text and multimodal language models

Architecture, total/active parameters, layers, hidden size, dense/MoE layout,
attention and KV structure, context limits, modalities, tool use, supported
quantizations, tokenizer/vocabulary, memory fit, and serving compatibility.

### 9.2 Embedding and reranking

Vector dimensions, maximum sequence length, pooling/scoring mode, supported
languages, retrieval/reranking tasks, benchmark versions, throughput, and
batching/runtime support.

### 9.3 Speech and audio

Task direction, supported languages, sample rates/codecs, streaming,
diarization, timestamps, real-time factor, context/window behavior, and
runtime/device support.

### 9.4 Image and video generation

Architecture class, media type, resolution/duration limits, conditioning,
steps/scheduler, parameterization, VRAM requirements, quantization, output
license constraints, and runtime support.

### 9.5 Vision, OCR, and document understanding

Input types, image/page limits, resolution, OCR/layout/table/form support,
structured-output behavior, document benchmarks, languages, and serving fit.

## 10. Platform intelligence

The current static platform matrix becomes a version-aware projection.

Each compatibility assertion records:

- Platform and version range
- Model release, family, architecture, or modality scope
- Hardware, operating-system, and accelerator constraints
- Quantization/artifact constraints
- Feature name and support status: `yes`, `partial`, `no`, or `unknown`
- Evidence level: `documented`, `tested`, or `inferred`
- Official evidence and last verification timestamp
- Notes and known limitations

Platform releases, documentation checksums, and linked release notes reopen
affected claims for verification. A removed page changes a claim to stale; it
does not automatically change support to `no`.

## 11. Freshness and source health

### 11.1 Cadence

- Discovery scans: every two hours
- Candidate enrichment and qualification: daily
- Full trusted-claim re-verification: weekly
- Immediate targeted reprocessing when an observed official source checksum
  changes

### 11.2 Freshness behavior

Each claim type defines its own validity window in configuration. The initial
defaults are:

- Release identity and artifact availability: seven days during the first
  thirty days after release, then thirty days
- License and terms: thirty days
- Platform compatibility: thirty days
- Benchmark results: ninety days, unless the benchmark version changes
- Hardware specifications: ninety days
- Security advisories and package releases: daily

Expired claims remain visible as stale and cannot silently satisfy a
qualification gate requiring fresh evidence.

### 11.3 Failure isolation

- Adapters retry transient failures with bounded exponential backoff.
- Repeated failures open a source-level circuit breaker.
- Jobs record partial success and continue with unrelated sources.
- Conflicts freeze only the disputed claim.
- The last verified projection remains readable.
- Missing current evidence never causes an automatic demotion.
- Source health exposes last success, consecutive failures, latency, response
  changes, items observed, and affected claim count.

## 12. Product experience

### 12.1 Application shell

The frontend becomes a React and TypeScript application backed by FastAPI.
It retains the current Mega Process Blue visual identity while replacing
dense report tables with the approved **Architect Workspace** shell and
**Balanced Decisions** overview density.

The persistent navigation follows five workflows:

1. **Observe:** Overview, Discover, Release stream
2. **Understand:** Models, Platforms, Hardware, Research
3. **Decide:** Compare, Deployment planner, Workspaces
4. **Govern:** Watchlists, Review queue, Source health
5. **Integrate:** MCP/API, feeds, alerts, exports

### 12.2 Default overview

The architect overview shows:

- Changes since the last visit
- Priority lifecycle events
- Organization-adjusted recommended actions
- Deployment-planner entry point
- Catalog trust/freshness summary
- Watchlists and review exceptions

It must not reproduce every catalog table on the homepage.

### 12.3 Layered views

- **Architect depth:** fit, topology, compatibility, policy, risk, power, TCO
- **Engineer depth:** artifacts, specifications, commands, evidence, benchmark
  and runtime details
- **Executive depth:** market movement, decision posture, risk, and investment
  implications
- **Reviewer depth:** conflicts, evidence, source health, corrections, and
  lifecycle actions

These are selectable presentation modes, not security roles.

### 12.4 Experience rules

- Lifecycle status, evidence freshness, and confidence are visible on every
  intelligence object.
- Recommendations always explain their evidence and assumptions.
- Direct structured search is the baseline. Optional natural-language answers
  cite canonical records and cannot create trusted facts.
- Desktop is the primary surface for comparison and planning.
- Mobile supports briefings, search, watchlists, and review.
- The interface meets WCAG 2.2 AA color, keyboard, focus, and semantic
  requirements.
- No external analytics or UI assets are required for self-hosted operation.

## 13. Workspaces without authentication

The product has one unrestricted local user role and no login.

A user may create multiple named workspaces. Each stores:

- Hardware inventory and planned purchases
- Workload, concurrency, latency, context, and availability targets
- Data-residency and network-isolation rules
- Approved/prohibited licenses
- Security and operational-maturity thresholds
- Budget, power, and rack constraints
- Preferred vendors, platforms, and quantization policies
- Watchlists, feed filters, and alert rules

Workspaces are logical recommendation contexts, not security boundaries.
The workspace switcher chooses the active context. MCP and API requests may
provide `workspace_id`; otherwise the configured default workspace applies.

Self-hosted application deployments allow mutations. The static public edition
is read-only and omits workspace data. Remote self-hosted access may use a
single deployment-level API token or network controls; this is not a user
identity system.

## 14. API, MCP, feeds, and alerts

### 14.1 FastAPI

REST endpoints are versioned under `/api/v1` and grouped by:

- Releases and lifecycle events
- Models, platforms, hardware, research, and compatibility
- Comparisons and deployment plans
- Recommendations
- Workspaces, estates, workloads, policies, and watchlists
- Reviews, sources, jobs, and health
- Events, feeds, webhooks, and exports

The OpenAPI schema generates the TypeScript client used by React. Domain
services do not depend on HTTP request types.

### 14.2 MCP

The MCP server exposes context-efficient tools for:

- Searching and browsing intelligence
- Listing releases or changes since a timestamp
- Explaining a model, platform claim, compatibility assertion, or
  recommendation with citations
- Comparing models, platforms, devices, and deployments
- Finding releases matching a workspace
- Planning capacity and deployment
- Reading watchlists, source health, review exceptions, and market movement

MCP delegates to the same application services as the API and never reparses
database records independently.

### 14.3 News and feeds

News is entity-linked intelligence rather than a separate unstructured feed.
Every published item links to affected releases, platforms, techniques,
hardware, claims, or recommendations and is deduplicated across sources.

Channels include:

- Major releases
- Lifecycle transitions
- Platform compatibility changes
- License and security changes
- Recommendation/ring changes
- Research and market signals
- Workspace watchlists

Each channel supports Atom, RSS 2.0, and JSON Feed with stable item IDs and
filter parameters. Daily and weekly digests are projections over the same
event stream.

News cannot change a recommendation until it creates verified and qualified
evidence.

### 14.4 Webhooks

Webhooks use the versioned event schema, HMAC signatures, idempotency keys,
bounded retries, and delivery history. Email, Slack, and Teams remain optional
notification adapters, not core dependencies.

## 15. Migration and compatibility

The migration proceeds behind stable contracts:

1. Define canonical entities, repositories, events, and API schemas.
2. Import YAML catalogs and append-only JSONL histories.
3. Wrap current scoring, capacity, fit, research, and report logic behind
   application services.
4. Run legacy and new projections in shadow mode.
5. Compare catalog counts, effective histories, recommendations, and exported
   facts.
6. Cut API, MCP, feeds, and React to the new services.
7. Keep existing CLI commands through compatibility adapters.
8. Generate the public static edition from the new projections.

No legacy source-of-truth file is removed until migration rehearsal and shadow
comparison pass.

## 16. Operational model

Supported execution modes:

- Continuously running self-hosted service with built-in scheduler
- CLI commands invoked by cron
- GitHub Actions for public ingestion and publishing

Every job records:

- Scheduled, started, and completed timestamps
- Lease and idempotency key
- Source and adapter version
- Items discovered, created, updated, rejected, and conflicted
- Partial failures and retry state
- Freshness/SLO impact

Backups include the database plus raw evidence snapshots not embedded in it.
Workspace export/import uses a versioned portable document.

## 17. Verification strategy

### 17.1 Data and lifecycle

- Contract tests for canonical entities and lifecycle transitions
- Provenance invariant tests
- Source-precedence and conflict-resolution tests
- Deduplication tests across registries, repositories, and announcements
- Category-specific verification and qualification tests
- Version-aware platform compatibility tests
- Property tests preventing invalid state transitions or uncited trusted facts

### 17.2 Adapters and operations

- Fixture and golden-response tests for every adapter
- Retry, circuit-breaker, idempotency, and partial-failure tests
- Changed-source targeted-reprocessing tests
- Source-health and stale-claim tests
- Synthetic major-release SLO test

### 17.3 Delivery parity

- API/MCP/feed/static-export parity tests
- OpenAPI-to-TypeScript client generation check
- Workspace-adjusted recommendation tests
- Legacy migration and history-equivalence tests
- CLI compatibility tests

### 17.4 Frontend

- React component and interaction tests
- Keyboard and screen-reader semantics
- Automated WCAG checks
- Playwright desktop and mobile workflows
- Deterministic visual regression snapshots
- Production bundle and static-edition verification

### 17.5 Cutover gates

Cutover requires:

- Full Python and frontend test suites passing
- Python and TypeScript type checks passing
- Lint and production builds passing
- Migration rehearsal passing on a copy of committed data
- Shadow projections reconciled or explicitly accepted
- Static export and feed validation passing
- No critical accessibility or security finding open

## 18. Implementation decomposition

The product is implemented contract-first and data-first, then released as one
integrated product:

1. Canonical contracts, persistence, migration, and event ledger
2. Source mesh, release detection, trust lifecycle, and review exceptions
3. Model-category and platform intelligence
4. Delivery API, MCP, feeds, alerts, and static projections
5. Workspace context and organization-adjusted recommendations
6. React Architect Workspace and all catalog/planning views
7. Shadow migration, full-system verification, and cutover

Workstreams depend on the contracts established in step 1. Frontend work starts
only after the relevant API schemas are stable, minimizing rework and
token-expensive iteration.
