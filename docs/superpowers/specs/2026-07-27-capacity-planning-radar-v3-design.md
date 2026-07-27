# Capacity-Planning Radar (v3) — Design

**Date:** 2026-07-27 · **Status:** approved direction, spec under review
**Owner:** Enes Kaynakcı (Mega Bilişim Teknolojileri)

## 1. Purpose

Upgrade the radar from an adoption tracker with a memory-fit checker into the
**primary source of information for sizing on-prem inference deployments on
selected GPUs**. The north-star acceptance test:

> "DeepSeek-V4-Pro, FP8 weights, FP8 KV cache, 32k average context,
> 200 concurrent users, ≥30 tok/s/user → **N × (8×H200) nodes, TP=8,
> with X% memory headroom**, alternative fleets compared, a starting vLLM
> config emitted, and every number traceable to a documented formula or a
> cited measurement."

Two prerequisites make this a program, not a feature:

1. **Trust (hardening).** The 2026-07-27 audit found ~44% of recorded scans
   (21/48) were network outages silently written into durable history,
   producing provably artificial ring churn (96% of promotions for the five
   manual-source hardware projects happened on outage days). A primary source
   cannot sit on corrupted history.
2. **Knowledge (coverage).** 37/43 models lack architecture fields, so memory
   estimates ignore context entirely; the KV formula assumes MHA (wrong by
   4–50× for GQA/MLA models); devices carry only a memory number; datacenter
   quant formats (FP8/NVFP4) are absent from the bits table.

## 2. Approved decisions

| # | Decision |
|---|----------|
| D1 | **History repair via corrective events.** The 21 outage runs are identifiable by run-id; append corrective events that neutralize their ring changes. `history.jsonl` stays append-only; corrections are visible in the timeline, never hidden. |
| D2 | **Engine priority: vLLM → SGLang → TensorRT-LLM** for the platform matrix and config generator. llama.cpp/Ollama/MLX remain covered for the existing homelab lens. |
| D3 | **No actual cost data in this repo.** TCO layer uses indicative public list prices and TDP only. No private Mega procurement overlay. |
| D4 | **Hugging Face links are first-class.** Every tracked model surfaces a clickable HF link on model pages (dashboard + static site), in MCP outputs (`list_models` detail, `get_model`, capacity tools), in the published JSON API, and in planner outputs. Catalog validation warns when `hf_repo` is missing and the model exists on HF. |
| D5 | **CI is the sole writer of committed history** (chosen default, flagged for review). Local scans write to `data/local/` (gitignored) unless `--publish-history` is passed. Ends the local-vs-CI pollution of the shared timeline (302 uncommitted local lines at audit time). |
| D6 | **Hybrid estimation model.** Deterministic analytical backbone (always answers, assumptions explicit) + curated measured-benchmark evidence layer with provenance that displays alongside estimates and calibrates efficiency factors. Mirrors the existing "deterministic core, best-effort evidence" philosophy. |

## 3. Non-goals

- Training-capacity planning (inference only, for now).
- Automatic benchmark execution in CI (a local, opt-in harness only).
- Real procurement/pricing data (D3).
- Replacing the existing adoption radar, homelab fit checker, or rings — the
  datacenter lens is additive (new profile + new tiers), not a rewrite.

## 4. Phase 0 — Harden the instrument

Everything here targets a defect confirmed in the 2026-07-27 audit.

### 4.1 Outage detection and gating
- Per-source outcome on `source_health` rows: `ok | empty | error` (+ error
  kind). "Source published nothing" and "we could not reach the source"
  become distinguishable.
- Scan-level gate: if the source error rate exceeds a threshold (default
  50%), the run is marked `degraded`, **scoring/calibration/history writes
  are skipped**, and the report says why. CLI exits non-zero.
- Publish gate keyed on the run (not the DB union): `publish.yml` refuses to
  export when the latest run is degraded or below a minimum signal volume.

### 4.2 Warning propagation
- `GitHubCollector` gains a `warnings` list (same contract as RSS);
  orchestrator harvest unchanged.
- Warn when `GITHUB_TOKEN` is unset and >5 GitHub sources are configured
  (60 req/hr cannot serve ~116 calls).
- Enrichment warnings must carry non-empty reasons (`repr(exc)` fallback).
- OSV + HackerNews enrichers routed through `get_with_retry`; retry budget
  raised for 68-project bursts (pypistats 429s exhausted the current one).

### 4.3 History repair (D1)
- One-off `radar history repair` command: identifies the 21 outage run-ids
  from `source_health`, appends `corrected` events reverting their ring
  changes, with `reason: "collection outage artifact"` and a pointer to this
  spec. Dashboard/timeline render corrections distinctly.
- Guard so repaired events are idempotent (re-running appends nothing).

### 4.4 Durability and staleness
- `source_health` gets an append-only JSONL log (`data/source-health.jsonl`)
  committed by CI like the other logs; SQLite stays a rebuildable projection.
  This also makes stale-feed detection work in CI (empty-DB problem).
- Card staleness surfaced: `updated_at` age shown on dashboard/static cards;
  mixed-age card sets get a banner.
- Local-lane split per D5.

### 4.5 Catalog validation gate
- Schema-level sanity checks that **quarantine** a model from scoring and
  promotion (listed with a warning instead): `params_total` plausibility vs
  name pattern (existing 5× guard becomes blocking), `min_memory_gb > 0`,
  `params_active ≤ params_total`, required provenance fields, `hf_repo`
  presence check (D4). CI test over the shipped seed.
- Prevents a repeat of `Ornith-1.0-35B` (664,944 "params", tier laptop,
  auto-promoted to adopt on 2026-07-07).

### 4.6 Housekeeping
- `.gitignore` gains root `radar.db`; stray 0-byte file deleted.
- `data/config.yaml.bak` removed; `enrichment.arxiv` made explicit in config;
  `config/category-quotas.yaml` + `config/scoring.yaml` duplication resolved
  to a single source of truth.

## 5. Phase 1 — Model & platform knowledge

### 5.1 Model schema v2
`ModelSeed`/`ModelEntry` gain an `architecture` block:

```
attention_kind: mha | gqa | mla | hybrid
num_attention_heads, num_key_value_heads, head_dim
kv_lora_rank, qk_rope_head_dim        # MLA (DeepSeek family)
num_experts, experts_per_token        # MoE; params_active becomes load-bearing
sliding_window, vocab_size, max_context
```

Plus: quant variants with correct datacenter formats (`fp8 = 8.0`,
`nvfp4 ≈ 4.25` incl. scales, `mxfp4 ≈ 4.25`, existing GGUF/AWQ/GPTQ/MLX
retained); license + gating; open benchmark scores (curated, cited);
**per-number provenance** (`source_url`, `retrieved_at`, `verified`).

### 5.2 Auto-ingest and drift detection
- HF collector parses the full architecture block from `config.json` with
  deterministic per-family parsers (Llama/Qwen/DeepSeek/GLM/Mixtral/Gemma
  layouts). Closes the 37/43 architecture hole mechanically.
- Weekly re-verify job diffs stored specs against HF and flags drift; drift
  never silently overwrites a `verified` manual value.

### 5.3 Device schema v2 + catalog expansion
- `DeviceProfile` v2: `memory_bandwidth_gbs`, `tflops` by dtype
  (fp16/fp8/fp4), `interconnect` (NVLink gen / PCIe gen), `tdp_watts`,
  `indicative_price_usd` (D3), provenance. Devices move from code into
  `config/device-seed.yaml` (same seed/validation treatment as models).
- New entities: **Node** (HGX H200 8-GPU, MI300X OAM 8-GPU, …) and
  **Cluster** (N nodes + fabric). Catalog additions: H200 NVL, B300, GB200/
  GB300 NVL72, RTX PRO 6000 Blackwell, MI325X, MI355X, Gaudi 3,
  Ascend 910B/C, and the missing multi-GPU presets (8×H200, 8×B200,
  8×MI300X).

### 5.4 Platform capability matrix
New seeded dataset + page: engines (vLLM, SGLang, TensorRT-LLM first per D2;
llama.cpp/Ollama, MLX, LMDeploy, TGI, Dynamo after) × hardware vendors ×
features: architecture support (incl. MLA), quant formats, TP/PP/EP, KV-cache
quant, speculative decoding, prefix caching, disaggregated prefill. Seeded
manually with citations; kept current by cross-linking release notes the
radar already collects (each matrix cell can carry "last confirmed by
<release> on <date>").

### 5.5 Tiering and scoring lens
- `HardwareTier.DATACENTER` splits into `single_gpu_dc / single_node /
  multi_node`.
- New scoring profile `datacenter-first` inverts the capability-tier bias so
  DeepSeek-V4-class models can earn `adopt` under that lens; the homelab
  default is untouched.
- A datacenter row set joins `COMMON_DEVICE_TIERS` for per-model "Runs on"
  tables.

## 6. Phase 2 — Capacity engine

### 6.1 Memory model v2 (replaces the flat ×1.2)

Per-GPU accounting under a parallelism layout `(tp, pp, ep)`:

```
weights_gb        = params_total × bits_per_weight / 8 / 1e9      # per quant
kv_per_token      = MHA/GQA: 2 × num_kv_heads × head_dim × bytes(kv_dtype)
                    MLA:     (kv_lora_rank + qk_rope_head_dim) × bytes(kv_dtype)
kv_gb             = kv_per_token × num_layers × avg_context × concurrent_seqs / 1e9
per_rank_memory   = weights_shard(tp, pp, ep)                     # experts split under ep
                  + replicated_tensors(embeddings, norms)
                  + kv_gb / tp
                  + engine_baseline_gb                            # per-engine constant, few GB
                  + fragmentation_reserve
```

Sharding feasibility is checked, not assumed (`num_kv_heads % tp == 0`,
expert divisibility for ep, layer divisibility for pp). MoE weights use
`params_total` for residency and `params_active` for compute — both now
load-bearing.

### 6.2 Throughput model (roofline, engine-calibrated)

```
decode tok/s/GPU  ≈ memory_bandwidth × MBU / bytes_touched_per_token
                    (active-param weights read + KV read at current context)
prefill tok/s/GPU ≈ tflops(dtype) × MFU / (2 × params_active)
```

`MBU`/`MFU` are explicit per-engine constants documented in the methodology
page, later calibrated by Phase 3 measurements. Outputs: tok/s/user at given
concurrency, TTFT estimate, max concurrency under an SLO.

### 6.3 Solver — both directions
- `radar capacity plan --model X --device h200 --users N --context C
  --target-tps T [--quant fp8 --kv-dtype fp8]` → minimal GPU/node count,
  parallelism layout, memory headroom, assumption sheet.
- `radar capacity max --model X --fleet 8x-h200 …` → max workload.
- Same via MCP: `plan_capacity`, `max_workload`, `compare_devices`,
  `get_platform_support`.

### 6.4 Config generator
Emits starting launch configs as sandbox-playbook-style recipes with
cautions: vLLM first (`--tensor-parallel-size`, `--max-model-len`,
`--kv-cache-dtype`, `--gpu-memory-utilization`, quant selection, EP flags),
then SGLang, then TensorRT-LLM (D2). Recipes carry the assumption sheet and
HF link (D4).

### 6.5 TCO layer (indicative)
`$ / M tokens` and `tokens/s/kW` per candidate fleet from indicative list
prices and TDP (D3). Clearly labeled indicative.

## 7. Phase 3 — Evidence & calibration

- `data/benchmark-observations.jsonl`: curated measured results with full
  provenance (MLPerf Inference, vendor engineering blogs, vLLM/SGLang
  published runs, own deployments). `radar bench record` for manual entry;
  optional `radar bench run` wrapping `vllm bench serving` / `llama-bench`.
- Planner output shows measured points nearest to the requested
  configuration next to the estimate ("estimate 42 tok/s · measured 38 on
  8×H100, vLLM 0.11, source ↗").
- Calibration job tunes MBU/MFU per engine/hardware against measurements;
  an accuracy page tracks estimate-vs-measured over time (capacity analog of
  `backtest`).

## 8. Phase 4 — Surfaces

- **Planner page** (dashboard + static): model, fleet, workload → plan.
- **Per-model deployment guide** section: per-device fit, per-engine
  support, recommended configs, HF link (D4).
- **JSON data API** published with the static site: `models.json`,
  `devices.json`, `platform-matrix.json`, versioned schema, HF links
  included (D4).
- **Methodology doc**: all formulas, assumptions, provenance policy, known
  error bars — the trust anchor for "primary source" status.
- Digest gains a capacity corner (new hardware, price/perf movers, matrix
  changes).

## 9. Error handling & invariants

- All existing invariants hold: deterministic core, log-is-truth, collectors
  degrade (now *visibly*), enrichment best-effort, human-in-the-loop.
- New invariant: **a degraded run never writes rings, history, or the
  published site** (Phase 0 gate).
- New invariant: **every spec number carries provenance**; unverifiable
  numbers render with an "unverified" marker, and capacity answers list
  their assumption sheet.
- Solver failures (infeasible sharding, model > fleet) return structured
  "why not" explanations, never empty results.

## 10. Testing strategy

- Golden tests for memory model v2 against hand-computed references for one
  model per attention kind (GQA: Llama-3.1-70B; MLA: DeepSeek-V3/V4; MoE+GQA:
  Mixtral/Qwen3-MoE; dense: Qwen2.5).
- Anchor tests against known-real configurations (e.g., DeepSeek-R1 FP8 on
  8×H200 fits with headroom; Llama-3.1-70B FP8 serves on 1×H100 at limited
  context; DeepSeek-V4-Pro does **not** fit a single H200).
- Property tests: memory monotone in context/users/bits; GPU count
  antitone in quant bits; solver result always satisfies its own fit check.
- Existing pinned tests that hard-assert the old formula (`[5.0, 5.8]`
  bands, tier boundaries, flat 1.2) are updated deliberately in the same
  change that replaces the formula — called out in review, never silently.
- pytest + ruff + mypy gates unchanged; ≥80% coverage maintained.

## 11. Decomposition & sequencing

Each phase is its own plan → implementation cycle (repo convention:
lettered sub-projects, feature branches, --no-ff merges):

| Sub-project | Content | Depends on |
|---|---|---|
| **A — Hardening** | Phase 0 entire | — |
| **B — Model knowledge** | 5.1, 5.2 | A (validation gate) |
| **C — Device & platform knowledge** | 5.3, 5.4, 5.5 | A |
| **D — Capacity engine** | Phase 2 | B, C |
| **E — Evidence & calibration** | Phase 3 | D |
| **F — Surfaces** | Phase 4 | D (E enriches later) |

A first *correct memory-side* answer to the north-star question (right KV
math, TP-aware, FP8-aware, concurrency-aware) lands at the end of D's first
milestone, before the throughput model matures.

## 12. Open items

- D5 (CI-sole-writer) is a chosen default, not an explicit user decision —
  confirm during spec review.
- Whether GLM-5.2 / Inkling-family architecture parsers land in B or as a
  fast-follow depends on HF config availability at implementation time.
