# On-Prem AI Adoption Radar: Usability, Information Depth, and Model Lineage Investigation

**Audience:** Fable and subsequent implementation agents  
**Date:** 2026-08-03  
**Primary persona:** Infrastructure architect  
**Product mode:** Public, single-role command center; no login required  
**Production snapshot audited:** `2026-08-03T11:37:35.081295Z`  
**Latest remote commit audited:** `1beb5a46dce1966d1e5f5fdd1adee732704bddbd`  
**Status:** Investigation and recommendation; no implementation is included in this report

## 1. Purpose

The owner asked whether the latest radar will naturally become more useful over time, whether Hugging Face base models and derivative relationships can be parsed, and whether the richer information supplied by the older radar can be restored without abandoning the current platform.

This report compares:

1. The pre-React, curated radar at and before commit `f9b113e`.
2. The latest deployed React command center and canonical intelligence pipeline.
3. The live public snapshot and all nine deployed model-index shards.
4. Hugging Face's current official model-card and API lineage capabilities.

The central conclusion is:

> The latest platform has a stronger operational foundation, but it will not become decision-useful merely by accumulating more repository records. Preserve the new freshness, provenance, recovery, APIs, and health monitoring; restore the older radar's architect-oriented decision depth; and introduce model lineage so base releases are separated from fine-tunes, merges, adapters, quantizations, and conversions.

## 2. Executive assessment

### 2.1 Direct answers

**Will the radar get better if it is left to run?**

Partially. Freshness, repository breadth, download counts, license coverage, and verification throughput will improve. Search quality, base-model authority, model lineage, architectural completeness, capacity guidance, and release-stream significance will not improve sufficiently under the current data model and ranking policy.

**Can base models be parsed?**

Yes. Hugging Face already exposes the required declared relationships through `cardData.base_model`, `cardData.base_model_relation`, lineage tags, and the API's `baseModels` property. The radar requests model-card metadata today but discards these fields.

**Was the older radar more informative?**

Yes. This is an objective information-architecture regression, not only a visual preference. The older radar exposed deployment facts and recommendations directly in its catalog and model detail pages. The current default surface prioritizes generic lifecycle and provenance fields while most operational information is absent, hidden, or only reachable through classic pages.

**Can the latest version be improved rather than reverted?**

Yes, and that is the recommended approach. The correct product is a composition of:

- **Radar:** what to adopt and why.
- **Intelligence:** what changed, how fresh it is, and how strong the evidence is.
- **Planner:** what hardware, topology, memory, throughput, and cost are required.

This is consistent with the approved restoration direction in [`docs/superpowers/specs/2026-07-31-radar-restoration-and-elevation-design.md`](../superpowers/specs/2026-07-31-radar-restoration-and-elevation-design.md).

## 3. Production findings

### 3.1 Operational health is substantially improved

The deployed system now has:

- A two-hour discovery and publication policy.
- Durable canonical-state recovery through the `radar-state` GitHub Release.
- Bounded verification and enrichment work.
- Publication concurrency controls and deployment retries.
- A sharded model index instead of a truncated catalog.
- Source-health, freshness, quality, review, and stale-claim reporting.
- Restored project, research, hardware, platform, RSS, JSON feed, and detail routes.

This means the radar is no longer primarily blocked by deployment instability. The principal problem has moved up the stack to semantic quality and product usefulness.

### 3.2 The production index is broad but semantically weak

The live model index contained the following at the audit time:

| Measure | Count | Share |
|---|---:|---:|
| Complete model/repository index | 17,423 | 100% |
| Provisional publishers | 16,211 | 93.0% |
| Official or mapped publishers | 1,212 | 7.0% |
| Verified lifecycle | 13,535 | 77.7% |
| Detected lifecycle | 3,741 | 21.5% |
| Recommended lifecycle | 147 | 0.8% |
| Records with parameters | 457 | 2.6% |
| Records with context length | 215 | 1.2% |
| Records with a quantization format | 18 | 0.1% |
| Name-detectable derivative artifacts | 3,766 | at least 21.6% |
| Records with parent/base lineage | 0 | 0% |

The derivative percentage is a conservative lower bound based only on names containing terms such as `GGUF`, `AWQ`, `GPTQ`, `EXL2`, `FP8`, `MLX`, `LoRA`, `adapter`, `merge`, `pruned`, or `distill`. It does not identify derivatives with neutral names.

The public/recent snapshot exposed 1,535 models and reported:

| Quality measure | Count | Share of public models |
|---|---:|---:|
| Verified or better | 196 | 12.8% |
| With parameters | 48 | 3.1% |
| With license | 48 | 3.1% |
| With hardware tier | 48 | 3.1% |
| With context length | 39 | 2.5% |
| Open review exceptions | 310 | n/a |

The live evidence is published at:

- [Public snapshot](https://ekaynac.github.io/onprem-ai-adoption-radar/data/public-snapshot.v1.json)
- [Model-index manifest](https://ekaynac.github.io/onprem-ai-adoption-radar/data/model-index.v1.json)

### 3.3 `Verified` does not currently mean architect-ready

For deployable releases, the verification service requires an authoritative license claim and an artifact or repository identity. It does not require:

- Parameters or active parameters.
- Context length.
- Architecture or attention geometry.
- Base-model lineage.
- Hardware fit.
- Runtime compatibility.
- Benchmarks.
- Capacity or throughput estimates.
- A recommendation.

Consequently, a 77.7% verified rate in the complete index should be interpreted as repository-level trust, not deployment-intelligence completeness.

## 4. Root causes

### 4.1 Repository activity is being modeled as release significance

The Hugging Face adapter queries each supported pipeline category using:

```python
{
    "pipeline_tag": pipeline_tag,
    "sort": "lastModified",
    "direction": -1,
    "full": True,
    "cardData": True,
    "config": True,
}
```

See [`src/radar/intelligence/sources/huggingface.py`](../../src/radar/intelligence/sources/huggingface.py).

Each qualifying repository is then resolved into a release-shaped entity. A community GGUF upload, a fine-tune, a model merge, an adapter, an experimental checkpoint, and an official upstream base release therefore compete in nearly the same conceptual space.

This conflates two different events:

1. **A model release:** a meaningful new upstream capability or version.
2. **An artifact publication:** another packaging, precision, format, adapter, or derived checkpoint for an existing release.

### 4.2 Hugging Face lineage data is fetched and discarded

The adapter sets `cardData: True`, but `_metadata_claims()` retains only:

- Repository ID.
- Pipeline tag.
- Library.
- Modification time.
- SHA.
- Downloads and likes.
- Gating.
- License.
- Safetensors parameter total.

It does not retain:

- `cardData.base_model`.
- `cardData.base_model_relation`.
- `baseModels`.
- `childrenModelCount`.
- `base_model:*` tags.

The published index predicate set in [`src/radar/web/intelligence_snapshot.py`](../../src/radar/web/intelligence_snapshot.py) likewise has no lineage fields.

Hugging Face officially supports a single base, multiple bases for merges, and the relations `adapter`, `merge`, `quantized`, and `finetune`:

- [Hugging Face model-card documentation](https://huggingface.co/docs/hub/model-cards)
- [Hugging Face Hub API documentation](https://huggingface.co/docs/huggingface_hub/en/package_reference/hf_api)

### 4.3 Enrichment is all-or-nothing around `config.json`

The enrichment flow successfully retrieves model metadata, then requires `config.json` to return a successful response before creating the final enrichment result. Repositories without a compatible root `config.json` can therefore lose otherwise useful card metadata, license, lineage, tags, sibling files, downloads, and likes.

The correct behavior is partial, evidence-preserving enrichment:

- Metadata failure: fail the repository enrichment.
- Missing `config.json`: keep metadata/card evidence and mark architecture fields unknown.
- Missing README: keep metadata/config evidence.
- Invalid optional artifact: open a scoped review only when it affects a required claim.

### 4.4 The pipeline is bounded but not significance-aware

Current defaults are:

- Verification: 500 records per two-hour run.
- Enrichment: 100 records per two-hour run.

At twelve scheduled runs per day, the theoretical maximum enrichment rate is 1,200 records per day. One pass over 13,535 verified records takes more than eleven days before accounting for failures and incoming repositories.

The scheduling priority favors never/least-recently attempted records and known publishers, but it does not prioritize:

- Base/root releases.
- Official publishers strongly enough in public ranking.
- Popular parent models with many descendants.
- Recently announced major releases.
- Records blocking many downstream lineage resolutions.
- Models close to becoming decision-complete.

### 4.5 Search and release-stream ordering reward the wrong novelty

The compact model index is ordered by effective release/modification timestamp and confidence. Static catalog search preserves that order. The default release stream also emphasizes recent observations.

This causes a recently modified low-value clone to outrank an older but authoritative upstream model. Authority, upstream novelty, derivative relationship, impact, and deployment relevance need to precede repository modification time in the significance ranking.

### 4.6 The current catalog answers an inventory question

The React catalog table exposes:

- Model.
- Category.
- Lifecycle.
- Lane.
- Public posture.
- Observed date.

See [`frontend/src/features/catalog/CatalogTable.tsx`](../../frontend/src/features/catalog/CatalogTable.tsx).

This answers, “What entities exist and what trust state are they in?” It does not adequately answer the infrastructure architect's primary questions:

- What is the upstream/base model?
- Is this official or derived?
- What changed relative to its parent?
- Can it run on my hardware?
- At what quantization and memory requirement?
- Which runtime supports it?
- What is the expected throughput/cost?
- What evidence supports the recommendation?
- Is it worth evaluating now?

## 5. Kimi-K3 case study

Kimi-K3 was used as the concrete freshness and ranking test.

At the audit time:

- The deployed index contained 189 Kimi-K3-named records.
- The official `moonshotai/Kimi-K3` record was approximately position 5,080 in the complete timestamp-ordered index.
- The official record had roughly 968,000 downloads and 9,700 likes.
- Search could present a newly modified, zero-download community repository before the official model.

The live Hugging Face search returned 226 Kimi-K3 results:

- 73 declared a base model.
- 72 carried a `base_model:*` tag.
- 59 explicitly named `moonshotai/Kimi-K3` as a base.
- 24 explicitly declared a relation type.

For example, [GrEarl/Kimi-K3-GGUF](https://huggingface.co/GrEarl/Kimi-K3-GGUF) declares:

```yaml
base_model: moonshotai/Kimi-K3
base_model_relation: quantized
```

This means a substantial part of the Kimi-K3 noise can be collapsed using authoritative metadata immediately. The remaining ambiguous records should be inferred cautiously or sent to review.

## 6. Why the older radar felt more useful

The older radar was curated around an operational decision rather than a universal inventory.

### 6.1 Older catalog information

The classic model catalog exposed nine sortable, architect-relevant columns:

- Model.
- Family.
- Ring.
- Hardware tier.
- Total and active parameters.
- Context length.
- License.
- Use case.
- Minimum memory.

It also supported a datacenter-first lens and a device picker. See [`src/radar/web/templates/models.html`](../../src/radar/web/templates/models.html).

### 6.2 Older model-detail information

The classic model detail exposed:

- Adoption ring and hardware tier.
- Total and active parameters.
- Context and release date.
- Quantization table.
- Estimated memory at 4K and 32K context.
- Architecture and attention type.
- KV-head geometry and MLA fields.
- MoE expert counts.
- Curated benchmarks with source links.
- Device and datacenter “runs on” matrices.
- Tenure and download history.
- Research-technique pedigree.
- Copy-ready ring and fit badges.

See [`src/radar/web/templates/_model_detail.html`](../../src/radar/web/templates/_model_detail.html).

### 6.3 What the latest version improved

The latest version should not be discarded. It added important capabilities:

- Canonical identities and evidence-backed claims.
- Explicit detected, verified, qualified, and recommended lifecycle states.
- Review exceptions instead of silently invented facts.
- Source-health and freshness operations.
- Public API, MCP, snapshot, feeds, and sharded delivery.
- State recovery and race-safe deployment.
- Wider model, project, research, hardware, and platform coverage.

The regression is therefore not “old good, new bad.” It is that the new trust platform replaced rather than wrapped the older decision product.

## 7. Target model and artifact ontology

The canonical catalog should distinguish the following levels:

```text
Publisher
└── Model family
    └── Base release
        ├── Official checkpoints/artifacts
        ├── Fine-tunes and instruction variants
        ├── Distilled or pruned derivatives
        ├── Adapters / LoRAs
        ├── Merges with one or more parents
        └── Deployment variants
            ├── GGUF
            ├── AWQ / GPTQ / EXL2
            ├── FP8 / NVFP4 / INT4
            └── MLX / ONNX / other conversions
```

### 7.1 Required lineage record

Each parent relationship should contain:

```yaml
child_release_id: string
parent_release_id: string
root_release_id: string
relation: base | finetune | adapter | merge | quantized | converted | distilled | pruned | checkpoint
declared: boolean
confidence: 0.0-1.0
evidence_ids: [string]
extractor_version: string
review_status: clear | open | resolved
```

Merges require multiple parent edges. Root resolution must be transitive, deterministic, and cycle-safe.

### 7.2 Extraction confidence tiers

#### Tier 1: declared, authoritative

- HF API `baseModels`.
- Model-card `base_model`.
- Model-card `base_model_relation`.
- `base_model:*` tags.
- Official publisher/model ownership.

These can normally be accepted automatically when the referenced repository resolves unambiguously.

#### Tier 2: artifact-declared

- `adapter_config.json` → `base_model_name_or_path`.
- PEFT configuration.
- Merge recipes and merge configuration.
- GGUF base-model metadata.
- Quantization metadata.
- `_name_or_path` and related config ancestry fields.

These can be accepted automatically when they resolve to an exact repository and do not conflict with Tier 1.

#### Tier 3: inferred

- Normalized repository naming.
- Architecture/config fingerprints.
- Tokenizer hashes.
- Weight shape and parameter signatures.
- README links and natural-language references.
- Publisher/repository naming conventions.

Inferred edges must carry lower confidence. Ambiguous or conflicting inference should open a review exception rather than silently merging identities.

## 8. Target product behavior

### 8.1 Default catalog: base releases, not all artifacts

The primary catalog should show one row per meaningful base/upstream release by default. Add explicit modes:

- **Base models** — default architect view.
- **Curated deployable** — qualified or recommended models and variants.
- **All artifacts** — complete repository inventory for forensic use.

Recommended default columns:

- Model and publisher.
- Base/root model.
- Official/derived status.
- Relation type.
- Release date.
- Adoption ring.
- Parameters and active parameters.
- Context.
- License.
- Modality/use case.
- Best available deployment format.
- Minimum memory.
- Hardware tier.
- Supported serving engines.
- Evidence confidence.

### 8.2 Search ranking

Search should rank using significance classes before recency:

1. Exact official repository match.
2. Exact base/root release match.
3. Official publisher release.
4. Curated or recommended release.
5. High-impact derivative with a declared parent.
6. Other verified derivative.
7. Unresolved/provisional repository.

Within a class, use:

- Name/token relevance.
- Release date.
- Download and like momentum.
- Completeness.
- Evidence strength.
- Runtime relevance.

Repository `lastModified` should be a freshness indicator, not the primary definition of product significance.

### 8.3 Grouped release stream

A major base release should produce one prominent event. Related repository activity should be grouped beneath it:

> Kimi-K3 released by Moonshot AI  
> 47 new quantizations · 8 fine-tunes · 3 adapters · 2 serving-platform updates

The raw records remain accessible after expansion. The default stream should not show dozens of nearly identical derivative rows.

Suggested event types:

- New base release.
- New official version/checkpoint.
- Material architecture/specification change.
- Official quantization or deployment package.
- Important community deployment variant.
- Serving-platform compatibility added/removed.
- New benchmark evidence.
- License or access change.
- Security or operational warning.
- Aggregated derivative activity.

### 8.4 Model detail

The React detail page should combine trust and operational depth in this order:

1. **Architect decision brief** — recommendation, fit, change significance, risks.
2. **Lineage** — parents, root, children, relationship confidence.
3. **Specifications** — params, context, modality, license, architecture.
4. **Deployment and capacity** — memory, topology, throughput, concurrency, power/TCO.
5. **Runs on** — device/node/cluster matrix and best viable quant.
6. **Variants** — official artifacts first, then grouped community artifacts.
7. **Benchmarks** — curated and contextualized, with sources.
8. **Research and ecosystem** — techniques, papers, runtimes, platform support.
9. **History and momentum** — release history, downloads, tenure, changes.
10. **Claims and provenance** — claim-level evidence and conflicts.

Provenance remains essential, but it should support the decision rather than dominate the first screen.

### 8.5 Overview

The infrastructure-architect overview should lead with:

- Major upstream releases.
- Recommendation/ring changes.
- Important serving-platform changes.
- Hardware and capacity implications.
- Research developments with operational consequences.
- Source or quality problems requiring attention.

Raw review records and derivative uploads should be summarized unless they materially change a decision.

## 9. Implementation sequence optimized for reuse

Do not perform another frontend rewrite. Reuse the existing React shell, canonical repository, source adapters, classic model engines, capacity solver, device catalog, platform matrix, research radar, and public snapshot delivery.

### Phase A — Correct the semantic model

1. Add lineage edges and root-release resolution to canonical contracts and persistence.
2. Extract HF declared lineage during discovery, not only enrichment.
3. Make missing optional config/card artifacts nonfatal.
4. Separate release entities from artifact entities.
5. Backfill lineage for the existing index.
6. Add conflict and unresolved-parent review codes.

### Phase B — Correct significance and ranking

1. Add publisher authority and upstream/derivative classification.
2. Add a deterministic significance score with an explanation/factor list.
3. Rank exact official/base results first.
4. Group derivative activity in the release stream and feeds.
5. Preserve an unfiltered all-artifacts mode.

### Phase C — Restore architect information depth

1. Upgrade the catalog table to match or exceed the classic nine-column view.
2. Port architecture, quant, capacity, min-memory, and runs-on data.
3. Restore benchmark, tenure, momentum, research, and history sections.
4. Connect the existing capacity engine to model details and compare.
5. Keep classic pages until each parity item has an automated acceptance test.

### Phase D — Improve sustained data quality

1. Prioritize enrichment of roots, official publishers, and high-descendant models.
2. Enable validated official announcement sources and external evidence adapters.
3. Add architecture and lineage extraction coverage metrics.
4. Monitor review-queue inflow versus automated resolution.
5. Add daily targeted reconciliation for unresolved popular families.

## 10. Acceptance gates

The improvement should not be considered complete until all of the following are true:

### Freshness

- A major official release appears within the two-hour platform freshness objective.
- Its official repository is identifiable even when derivatives arrive first.
- Feed and release events use the upstream release as the primary subject.

### Lineage

- At least 90% of the top 500 models have a resolved root release.
- Declared relations are preserved with their source evidence.
- Multi-parent merges render correctly.
- Cycles and conflicting parents create review exceptions.
- Search for a family returns the official root first.

### Information quality

- At least 80% of curated base releases have parameters, context, and license.
- Every curated deployable model has a hardware-fit or explicit unknown result.
- Every computed value exposes assumptions and evidence.
- “Verified” and “decision-complete” are reported separately.

### Usability

- Derivatives are collapsed by default.
- The catalog restores the classic decision columns.
- Model details restore quant, architecture, capacity, runs-on, benchmark, history, and research depth.
- All research papers, evidence sources, repositories, and detail entities are clickable.
- The infrastructure architect remains the sole default persona; no login is required.

### Robustness

- Missing optional files do not discard successful metadata enrichment.
- Review backlog does not grow faster than resolution throughput.
- Full-index publication remains sharded and count-validated.
- State recovery, feeds, APIs, MCP, and classic URLs remain backward compatible.

## 11. Explicit non-goals

- Do not delete derivative repositories; group them.
- Do not infer high-confidence lineage from names alone.
- Do not replace deterministic extraction with an LLM-only classifier.
- Do not hide unknown or conflicting data.
- Do not retire classic pages before React parity is proven.
- Do not introduce multiple personas, roles, accounts, or authentication.
- Do not solve semantic quality with another visual-only redesign.

## 12. Final recommendation to Fable

Design and implement a **restoration-plus-lineage** evolution of the current command center.

The product should feel like the older radar in information density and architect usefulness, while retaining the latest platform's operational strengths. The base release—not the individual Hugging Face repository—must become the principal model concept. Derivatives should remain searchable and auditable, but grouped beneath their upstream release and prevented from overwhelming search, overview, feeds, and the release stream.

The highest-value first deliverable is not a new visual system. It is a thin end-to-end lineage slice:

1. Parse declared Hugging Face base relationships.
2. Persist parent/root edges with evidence.
3. Put official/root models first in search.
4. Collapse Kimi-K3 derivatives beneath `moonshotai/Kimi-K3`.
5. Render the lineage on the model detail page.

Once that slice is correct, restore the classic catalog fields and capacity/device-fit experience using the engines already present in the repository.

