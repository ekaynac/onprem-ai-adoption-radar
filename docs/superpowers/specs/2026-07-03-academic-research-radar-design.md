# Academic Research Radar — Design

Date: 2026-07-03
Status: approved (interactive brainstorm; §1–§3 confirmed section-by-section)

## Context

The radar decides on **tools** (`DecisionCard`) and **models** (`ModelEntry`).
Academic research appears only as supporting evidence: per-project arXiv
mention counts (`enrichment/arxiv.py`, curated `paper_query` on 7 sources) and
HF daily-papers repo discovery (`discovery/hf_papers.py`). Papers themselves
carry no decision.

This program makes **research techniques** a first-class decision surface: a
third radar that answers *"is this technique production-ready for on-prem?"*
with the same reproducible, deterministic ring verdicts the other two radars
give — e.g. *"speculative decoding: ADOPT — implemented in vLLM (adopt), TGI
(adopt), llama.cpp (adopt); 400+ citations; open reference code."*

Killer output (decided): **"adopt this technique" decision cards**, on a
`/research` surface like `/models`. Domain scope (decided): techniques across
**all 9 existing categories** from the start — inference/serving, fine-tuning,
RAG, agent architecture, sandboxing/safety, orchestration.

## Program decomposition (umbrella)

Four sub-projects, sequenced like the local-model radar (catalog → decision →
surface). **This spec designs sub-project 1 in full**; 2–4 are roadmap
summaries (§9) and get their own plans later.

1. **Core** (this spec): technique seed, closed-loop deterministic scoring,
   citation enrichment, metrics/history persistence, CLI + report section.
2. **Surfaces**: `/research` catalog + per-technique pages (incl. the
   research→production timeline), MCP tools, movers, change feeds.
3. **Cross-linking**: tool/model cards gain research pedigree (canonical
   papers, citation velocity, implemented-techniques list); pedigree feeds
   back into tool evidence.
4. **Discovery**: `radar research discover` proposes emerging techniques
   (HF daily papers, arXiv, citation-velocity spikes) into a human-reviewed
   proposals file; a track-record view of early calls later.

## Non-goals (sub-project 1)

- No web pages or MCP tools (sub-project 2).
- No changes to existing tool/model cards or their scoring (sub-project 3).
- No automated technique discovery or proposals (sub-project 4).
- No LLM anywhere in the path; identical inputs → identical rings.
- No paper-level entities: papers are *attributes of techniques*, never
  scored/ringed themselves (paper-first was considered and rejected — rings
  fit techniques, not papers; paper-first thinking powers sub-project 4).
- No graph store (considered and rejected — the seed's typed links *are* the
  graph edges; a graph view can be derived later without new infrastructure).
- No new third-party dependencies (httpx, feedparser, pydantic in-tree).
- Papers With Code is **not** a data source (service sunset in 2025).

## Architecture (decided)

Mirror the models radar: new module `src/radar/research_radar/`, curated
`config/technique-seed.yaml`, deterministic scoring, best-effort enrichment,
own metrics store + history JSONL, `radar research …` CLI group. The
differentiator is **closed-loop scoring**: implementation breadth/maturity are
computed offline from the radar's *own* tool cards and model entries, so the
three radars form one system whose verdicts move together.

## 1. Entity & data model

New module `src/radar/research_radar/entities.py`:

- **`TechniqueDomain`** (str enum): `inference | fine_tuning | rag |
  agent_architecture | safety_sandboxing | orchestration | embodied` (the
  last covers `physical_ai_infrastructure`-category techniques such as
  sim-to-real and VLA methods).
- **`PaperRole`** (str enum): `canonical | followup | survey`.
- **`PaperLink`** (frozen): `arxiv_id`, `title`, `role`
  (default `canonical`), `published` (ISO date, optional).
- **`ImplKind`** (str enum): `tool | model`.
- **`ImplementationLink`** (frozen): `kind`, `ref` (a source id from
  `config.yaml` when `kind=tool`, a model id from `model-seed.yaml` when
  `kind=model`), `note` (optional).
- **`TechniqueSeed`** (`extra="forbid"`): `id` (slug), `name`, `category`
  (existing `Category` enum — techniques slot into existing filters for
  free), `domain` (`TechniqueDomain` — the research-native grouping),
  `aliases: list[str]`, `papers: list[PaperLink]`,
  `implementations: list[ImplementationLink]`, `open_code: bool` (canonical
  paper has public reference code), `onprem_impact` (enum §2),
  `superseded_by: str | None` (technique id), `enabled: bool = True`,
  `notes: str | None`.
- **`TechniqueScore`** (frozen): the six 1–5 dimensions of §2 + `average`.
- **`TechniqueEntry`** (frozen): seed fields + enriched `citation_count`,
  `citation_velocity` (both optional), `resolved_implementations` (each link
  + the referenced entity's current ring or `None`), `score`,
  `score_breakdown`, `ring`, `warnings: list[str]`.

Seed example:

```yaml
techniques:
  - id: speculative-decoding
    name: Speculative Decoding
    category: model_serving
    domain: inference
    aliases: ["speculative sampling", "draft model"]
    papers:
      - arxiv_id: "2211.17192"
        title: "Fast Inference from Transformers via Speculative Decoding"
        role: canonical
    implementations:
      - kind: tool
        ref: github-vllm
      - kind: model
        ref: llama-3.3-70b
    open_code: true
    onprem_impact: reduces_latency
```

Load-time validation (`research_radar/seed.py`, mirrors `load_model_seed`):
pydantic validation with `extra="forbid"`, unique ids, every `superseded_by`
must reference a seeded technique id — violations **abort the scan loudly**
before any network. Implementation `ref`s are resolved against the tool and
model catalogs at *assembly* time: a dangling ref becomes a per-entry warning
and is excluded from scoring — never a crash (a removed tool must not break
the research scan).

## 2. Scoring & ring

`research_radar/scoring.py`, pure functions, all dimensions 1–5:

| Dimension | Source | Ladder |
|---|---|---|
| `implementation_breadth` | offline, own catalog | resolved impls: 0→1, 1→2, 2→3, 3–4→4, ≥5→5 |
| `implementation_maturity` | offline, own catalog | ≥2 adopt-ring impls→5, 1 adopt→4, best is pilot→3, watch only→2, none/unringed→1 |
| `validation` | citations + venue (enriched) | peer-reviewed + citations ≥500→5; ≥100→4; ≥25 or peer-reviewed→3; preprint <25→2; no data→**neutral 2**; `superseded_by` set→**forced 1** |
| `reproducibility` | seed + impls | `open_code` and ≥1 resolved tool impl→5; `open_code` only→4; impl only→3; neither→1 |
| `momentum` | technique-metrics store | new resolved impl since last scan→5; citation velocity above threshold→4; steady→3; velocity negative→2; a previously-resolved impl gone→2 (falling) even when citations are flat or rising, →1 when citations are also falling (defaults; constants tunable) |
| `onprem_impact` | curated seed enum | `reduces_memory`→5, `reduces_latency`→5, `enables_scale`→4, `improves_safety`→4, `improves_quality`→3 |

Exact citation thresholds and the maturity weighting live as module constants
(like `_OPENNESS_SCORE`) so they are tunable without touching callers.

Ring gate (`technique_ring`, mirrors `model_ring`'s absolute-gates style):

- **Zero resolved implementations → cannot rank above WATCH** (you cannot
  adopt what you cannot run on-prem, regardless of citations; AVOID remains
  reachable below the cap). Every entry in the tool/model catalogs is
  on-prem-runnable by construction, so any resolved link satisfies the cap.
- **`superseded_by` set → cannot rank above WATCH** (a technique with a named
  successor is never an adopt/pilot call, however broadly implemented; the
  card names the successor). Combined with the forced `validation=1`, heavily
  superseded techniques sink toward AVOID, which stays reachable below the cap.
- `average ≥ 4.0` **and** `implementation_maturity ≥ 4` → **ADOPT**.
- `average < 2.0` → **AVOID**.
- `average ≥ 3.0` → **PILOT**, else **WATCH**.

Closed loop: `implementation_maturity` reads the **latest tool decision cards
and model entries** (their current rings) — zero network. When vLLM's ring
moves, the next research scan moves every technique vLLM implements.

## 3. Enrichment (best-effort, never fails a scan)

`research_radar/citations.py`, routed through the shared
`enrichment/retry.get_with_retry`:

- **Primary — Semantic Scholar Graph API** (keyless): batch lookup by arXiv
  id for `citationCount`, venue/publication info. Batched (one request per
  ~100 papers) to respect the unauthenticated rate limit.
- **Fallback — OpenAlex** (keyless): same fields when Semantic Scholar fails.
- Peer-review detection kept deliberately simple and deterministic: a
  non-empty venue that is not arXiv/preprint ⇒ peer-reviewed.
- Any failure degrades to a warning + **last-known citations from the
  metrics store**, so offline scans remain fully deterministic; never-fetched
  citations leave `validation` at neutral 2 and the entry carries a
  "citations unknown" warning.

Exact endpoints, field names, and rate limits are verified during plan
writing (research step), not assumed.

## 4. Pipeline & persistence

`research_radar/pipeline.py` — scan flow:

1. Load + validate seed (fail loud).
2. Assemble: resolve implementation links against source config, model seed,
   latest cards/model entries (rings).
3. Enrich citations (async, best-effort).
4. Persist per-scan metrics to the **`technique_metrics` store** (new table
   mirroring `model_metrics`: technique id, scan/run id, citation_count,
   resolved impl count) → compute velocity + momentum.
5. Score + ring (pure).
6. Diff rings vs previous scan → append changes to
   **`data/technique-history.jsonl`** (append-only, portable, same pattern
   as `model-history.jsonl`; becomes the sub-project-2 timeline data).
7. Surface enrichment/resolution warnings through the existing scan-health
   channel.

## 5. CLI

`radar research` group, mirroring `radar models`:

- `radar research scan` — full pipeline (network for citations only).
- `radar research list [--ring R] [--domain D] [--category C]` — table:
  ring, name, domain, breadth, maturity, citations, momentum.
- `radar research show <id>` — one technique: score breakdown, papers,
  resolved implementations with their rings, warnings, ring history.
- Report artifact: each research scan saves a markdown report (movers +
  technique table) into its run directory via the run store. (An earlier
  draft said "a Research section in `radar report`, same shape as the Models
  section" — that premise was wrong: `radar report` renders tool cards only
  and has no Models section either. Dashboard/static-site Research sections
  are sub-project 2.)

## 6. Error handling

| Failure | Behavior |
|---|---|
| Seed invalid (dup id, bad enum, dangling `superseded_by`) | Abort scan with a clear message before network |
| Implementation `ref` unresolvable | Per-entry warning; link excluded from breadth/maturity; scan-health warning |
| Referenced tool/model has no ring yet | Counts for breadth, contributes 1 (unringed) to maturity |
| Semantic Scholar down/429 | Retry w/ backoff (shared helper) → OpenAlex fallback → last-known metrics + warning |
| Both citation APIs down | Last-known citations; never-fetched → neutral validation + "citations unknown" warning |
| Metrics store empty (first scan) | Momentum steady (3); no history diff emitted |

## 7. Testing (TDD, pytest + ruff + mypy, ≥80% coverage)

- **Unit**: seed-loader rejection cases (dup ids, unknown fields, bad enums,
  dangling `superseded_by`); link resolution (tool / model / dangling / no
  ring); every scoring-dimension ladder boundary; ring gates incl. the
  no-open-impl WATCH cap, ADOPT maturity gate, and superseded→AVOID path;
  velocity/momentum math; citation parsers over canned JSON fixtures
  (Semantic Scholar + OpenAlex shapes); retry/fallback behavior with fake
  clients.
- **Integration**: full `research scan` over a fixture seed + fake tool/model
  catalogs — asserts determinism (same input → same rings twice), metrics
  persisted, history appended on a ring change and silent when unchanged.
- No live API calls in tests, matching existing enricher test style.

## 8. Seed curation plan

Initial seed of **~60–100 techniques across all 9 categories**, drafted via a
deep-research pass at implementation time (same flow as the 33-model seed:
Claude drafts the YAML with papers/impls/links, user reviews). Coverage
sketch: inference (speculative decoding, PagedAttention, FlashAttention,
continuous batching, AWQ/GPTQ/GGUF quantization families, KV-cache tricks,
MoE serving), fine-tuning (LoRA/QLoRA/DoRA, DPO/ORPO), RAG (hybrid retrieval,
reranking, GraphRAG), agent architecture (ReAct, reflection, planning,
tool-use, multi-agent, computer-use, memory), safety/sandboxing (guardrails,
sandboxed execution, prompt-injection defenses), orchestration/serving-infra.
Fuzzier agent/RAG entries are kept honest by the evidence: few resolved
implementations → low breadth/maturity → WATCH by construction.

## 9. Roadmap (sub-projects 2–4, summaries only)

- **Surfaces**: `/research` catalog + `/technique/{id}` pages on dashboard
  and static export (reusing the models-page shell + filter/sort scripts);
  research→production timeline per technique rendered from paper dates and
  `technique-history.jsonl` ring events (implementation-appearance-in-metrics
  deferred with the `radar.db` CI-persistence decision — appearance dates are
  meaningless on the published site until metrics persist across CI runs); MCP
  `list_techniques` / `get_technique` / `technique_movers`; change feeds.
  Known items to address in this sub-project: CI wiring for
  `radar research scan` in publish.yml (commit `technique-history.jsonl`
  like the model history); the citation-velocity limitation that `radar.db`
  is not persisted across CI runs (published momentum would always read
  "first scan" — needs a persistence decision); and the pre-existing
  scan-health panel reading the latest run of *any* kind (should filter to
  tool-scan runs now that a third run kind exists).
- **Cross-linking**: tool/model cards show canonical papers + citation
  velocity + "implements N techniques (rings)"; research pedigree becomes an
  evidence line on tool cards (never a hard score input without its own
  design pass).
- **Discovery**: `radar research discover` proposes technique candidates
  from HF daily papers + arXiv categories + citation-velocity spikes into
  `data/proposed-technique-seeds.yaml` (human-gated like tool discovery, not
  autopilot — techniques need judgment); later a track-record view: how
  early did the radar flag a technique vs its first mainstream
  implementation (backtest-style, needs accumulated history first).

## Open items for plan time

- Verify Semantic Scholar batch endpoint, field names, and unauthenticated
  rate limits; same for OpenAlex (polite-pool contact email via env var).
- Confirm `technique_metrics` schema against the actual `model_metrics`
  table shape before writing migrations.
- Sanity-check that `Category` covers all planned technique groupings, or
  whether any technique is better filed under `fun_experimental`.
