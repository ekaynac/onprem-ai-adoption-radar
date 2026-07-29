# Sub-project D: Capacity Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The capacity engine (spec §6): architecture-correct KV/memory math replacing the MHA-blind estimator, per-rank TP/PP/EP accounting, roofline throughput with documented per-engine efficiency constants, a two-direction solver (`radar capacity plan` / `max`), MCP tools, a vLLM-first config generator, and an indicative TCO layer — so the radar answers *"how many H200s for DeepSeek-V4-Pro at N users?"* with cited inputs and an explicit assumption sheet.

**Architecture:** A new pure package `src/radar/capacity/` (types → kv → memory → throughput → solver → recipe → tco), consuming B's `ArchitectureSpec` (already threaded and unused at every estimate site), C's device v2 fields (per-GPU bandwidth/TFLOPS/TDP) and node/cluster presets, and the platform matrix for engine-support warnings. The existing homelab estimator (`models_radar/memory.py`) is upgraded in place to delegate to the new KV math when architecture is known, keeping both of its production call sites (`assemble.py:181/184`, `device_fit.py:39`) on one formula.

**Tech Stack:** Python 3.12, pydantic v2 (frozen models), typer, pytest. `uv run` for everything. No new dependencies.

## Global Constraints

- **Deterministic and honest.** Pure functions, injected inputs, no wall-clock, no network in the engine. Every capacity answer carries an `AssumptionSheet` (spec §9: "capacity answers list their assumption sheet"). Degradation is explicit: missing architecture → flagged upper bound; missing bandwidth (custom devices) → memory-only answer with a stated reason; never a silent guess.
- **Solver invariant (spec §10 property):** any returned plan must satisfy its own memory feasibility check; infeasible requests return structured "why not" reasons, never empty results (spec §9).
- **Per-GPU semantics from C:** `DeviceProfile.total_memory_gb`, `memory_bandwidth_gbs`, `tflops_*`, `tdp_watts` are per-GPU; `gpu_count` scales them. `usable_memory_gb` = total × USABLE_FRACTION[kind] × gpu_count.
- **Bands and tiers move only deliberately** (spec §10): the pinned estimator bands (`[5.0,5.8]` weights-only, `[7.0,9.0]` 8B-with-arch) and the `test_device_fit.py` fixtures update in the same commit as the formula change, each with a stated recomputation.
- **Persisted-vs-recomputed mixing:** `device_fit._quant_memory` recomputes and falls back to stored `est_memory_gb_4k` — old persisted entries carry v1 numbers until the next scan. Acceptable (daily CI scan); note it in the CHANGELOG.
- **Engine efficiency constants are documented estimates** (spec 6.2), named in `AssumptionSheet`, calibrated by sub-project E later — they are not measurements and must never be presented as such.
- **NVFP4 bits correction (carried from B's final review):** 4.25 → **4.5** bits/weight (4-bit weights + FP8 E4M3 scale per 16-element block = +0.5); MXFP4 stays 4.25 (E8M0 scale per 32 = +0.25). Cite in the comment.
- Prices: `indicative_price_usd` is None on every datacenter device (vendors publish none) — TCO is kW-first; $-outputs render only when a price exists (spec D3).
- Gates before every commit: `uv run pytest -q && uv run ruff check . && uv run mypy src` (suite starts at 1203 passed). Commit `<type>: <description>`, NO Co-Authored-By. Never commit `data/` files.
- Branch: `feature/capacity-radar/capacity-engine-D` (checked out).

**Context map (recon-verified 2026-07-29, file:line):**
- Estimator: `models_radar/memory.py` (72 lines, quoted in recon) — `estimate_memory_gb(params_total, bits, context, num_layers, hidden_size)`, flat `OVERHEAD=1.2`, MHA-blind KV `2*2*layers*ctx*hidden/1e9`. Callers: `assemble.py:181/184` (inside `add()`; the merged `architecture` is bound at `:127`, in scope and unused — zero re-ordering needed; `params_active` only via `seed.params_active`), `device_fit.py:39` (`_quant_memory`, passes entry fields; `model.architecture` in scope unused).
- Output pins: `test_models_radar_memory.py:11-30` (bands), `test_models_radar_assemble.py:27-31` ([7,9] + laptop tier; inputs 8B/32L/4096h), `test_device_fit.py:8-15` fixture hardcodes `*1.2` (weights-only est values) with verdict pins at `:18-30,:68-74,:78-84`.
- `ArchitectureSpec` fields (entities.py:55-73): attention_kind(mha/gqa/mla/hybrid/unknown), num_attention_heads, num_key_value_heads, head_dim, kv_lora_rank, qk_rope_head_dim, num_experts, experts_per_token, sliding_window, vocab_size. NO num_layers (lives on the entry).
- Curated anchors (model-seed.yaml): deepseek-v3/r1 = 671B/37B active, MLA (kv_lora 512, rope 64, 128 heads) but **no num_layers/hidden in seed** (Task 2 pins them); hf-deepseek-v4-pro = 1.6T/49B, hybrid, 61L/7168h, kv_heads=1, head_dim=512, rope 64, 1M ctx; v4-flash = 284B/13B, 43L, kv 1×512; glm-5-2 = 753B/40B, MLA 512+64, 78L; gpt-oss-120b = 120B/5.1B, hybrid, 36L, kv 8×64, sliding 128; llama-3.1-70b = 70B, ctx 131072, NO arch (degradation case); qwen3-8b = no data offline (HF fills at scan).
- Devices (device-seed.yaml, all cited): h100-80gb bw 3350/fp16 989.5/fp8 1979/700W; h200-141gb bw 4800/fp8 1979/700W; b200-192gb bw 7700/fp8 4500/fp4 9000/1000W; b300-270gb bw 7700/fp8 4500/fp4 14000/1100W; mi300x bw 5300/fp8 2610/750W; mi325x bw 6000/fp8 2610/1000W; mi355x bw 8000/fp8 5000/fp4 10100/1400W; a100-80gb bw 2039/fp16 312/NO fp8/400W. FP4 only on b200/b300/mi355x. All prices None.
- Nodes/clusters: NODE_PRESETS/CLUSTER_PRESETS flatten to DeviceProfile (per-GPU fields inherited; gpu_count set); hgx-h200-8 → 141GB×8, usable 958.8; gb200-nvl72 → 192×72; resolve_device falls back DEVICE→NODE→CLUSTER; custom dicts carry NO bandwidth/tflops.
- Bits: `assemble.py:26-33` `_BITS_BY_FORMAT` — "fp8": 8.0, "nvfp4": 4.25 (→4.5 here), "mxfp4": 4.25; pinned at `test_models_radar_assemble.py:136-141`.
- CLI: sub-apps registered at `cli.py:29-43`; command bodies use function-local imports; entries load via `_latest_model_cards(root)` (mcp_server/model_queries.py:37-51, returns raw dicts, kind=="models" run walk); cli.py is 2271 lines.
- MCP: `build_mcp_server` (server.py:22-28) instantiates services; 16 tools today; `ModelQueryService(root)` holds root/db_path/history_path; platform matrix via `load_platform_entries(root)` (model_queries.py:54-69) with `PlatformSeed.features` dict of Support literals — vllm has mla/fp8/nvfp4 "yes".
- Docs: architecture.md module map (insert row after `models_radar/platform_matrix`), README Highlights bullet style (C's at README.md:57), CHANGELOG `### <name> (sub-project X)` newest-first at line 9.

**Worked golden values used in the tests below (hand-derived; fp16 = 2 bytes/elt, fp8 = 1):**
- GQA per-token bytes/layer = `2 × kv_heads × head_dim × dtype_bytes`; MLA = `(kv_lora_rank + qk_rope_head_dim) × dtype_bytes` (single latent copy, no K/V pair); MHA fallback when only hidden known = `2 × hidden × dtype_bytes` (legacy upper bound); hybrid = GQA formula on published (kv_heads, head_dim), flagged as upper bound.
- Llama-70B-class GQA (80L, 8 kv × 128, fp16): 2·8·128·2 = 4096 B/layer → ×80 = 327,680 B/token → 32k ctx: **10.74 GB**.
- DeepSeek-V3 MLA (61L, 512+64, fp16): 576·2 = 1152 B/layer → ×61 = 70,272 B/token → 32k: **2.30 GB**; fp8: **1.15 GB**; 128k fp16: **9.21 GB**. (The v1 formula said 350 GB at 32k — the headline correction of this sub-project.)
- V4-Pro hybrid-as-GQA (61L, 1 kv × 512, fp16): 2·1·512·2 = 2048 B/layer → ×61 = 124,928 B/token → 32k: **4.09 GB**; fp8 **2.05 GB**.
- V4-Pro FP8 weights: 1.6e12 × 8/8 = **1600 GB** → won't fit 8×H200 (958.8 usable) → 16×H200 = 100 GB weights/rank.

---

### Task 1: `capacity/types.py` + `capacity/kv.py` — pure KV math with goldens

**Files:**
- Create: `src/radar/capacity/__init__.py` (empty docstring module), `src/radar/capacity/types.py`, `src/radar/capacity/kv.py`
- Test: `tests/test_capacity_kv.py` (new)

**Interfaces (produced — later tasks import these exact names):**

`types.py`:

```python
"""Shared frozen types for the capacity engine (spec §6)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

DTYPE_BYTES: dict[str, float] = {"fp16": 2.0, "bf16": 2.0, "fp8": 1.0, "int8": 1.0, "fp4": 0.5}


class Workload(BaseModel):
    """What the deployment must serve."""

    model_config = ConfigDict(frozen=True)

    concurrent_requests: int = Field(ge=1)
    avg_context_tokens: int = Field(ge=1)
    target_tokens_per_sec_per_user: float | None = None  # None = memory-only planning


class Parallelism(BaseModel):
    """A candidate sharding layout."""

    model_config = ConfigDict(frozen=True)

    tensor_parallel: int = 1
    pipeline_parallel: int = 1
    expert_parallel: int = 1

    @property
    def world_size(self) -> int:
        return self.tensor_parallel * self.pipeline_parallel * self.expert_parallel


class AssumptionSheet(BaseModel):
    """Every estimate's honesty ledger — rendered with every answer."""

    model_config = ConfigDict(frozen=True)

    lines: tuple[str, ...] = ()

    def plus(self, *notes: str) -> "AssumptionSheet":
        return AssumptionSheet(lines=self.lines + notes)
```

`kv.py`:

```python
def kv_bytes_per_token(
    architecture: ArchitectureSpec | None,
    *,
    num_layers: int | None,
    hidden_size: int | None,
    kv_dtype: str = "fp16",
) -> tuple[float | None, list[str]]:
```

Returns `(bytes_per_token, assumption_notes)`. Dispatch, in order:
1. `architecture.kv_lora_rank` present (MLA): `(kv_lora_rank + (qk_rope_head_dim or 0)) × dtype_bytes × num_layers`; note `"KV: MLA latent cache ({rank}+{rope})/layer"`.
2. `architecture.num_key_value_heads` and `head_dim` present (GQA/MHA/HYBRID): `2 × kv_heads × head_dim × dtype_bytes × num_layers`; if `attention_kind is HYBRID`, append note `"KV: hybrid attention approximated as full GQA on published kv geometry — upper bound (sliding-window layers cost less)"`.
3. No architecture but `num_layers` and `hidden_size`: legacy MHA upper bound `2 × hidden_size × dtype_bytes × num_layers`; note `"KV: architecture unknown — MHA upper bound from hidden_size"`.
4. Otherwise `(None, ["KV: no architecture data — KV cache not modeled"])`.
`num_layers` missing in cases 1-2 → falls to 3/4 rules. Unknown `kv_dtype` → `ValueError` listing `DTYPE_BYTES` keys.

Also: `def kv_gb(bytes_per_token: float, context_tokens: int, concurrent_requests: int = 1) -> float` = `bytes_per_token × context × requests / 1e9` (round 2).

- [ ] **Step 1: Write the failing golden tests** (`tests/test_capacity_kv.py`):

```python
"""Architecture-correct KV math — the headline fix of the capacity engine."""

from __future__ import annotations

import pytest

from radar.capacity.kv import kv_bytes_per_token, kv_gb
from radar.models_radar.entities import ArchitectureSpec, AttentionKind


MLA_V3 = ArchitectureSpec(attention_kind=AttentionKind.MLA, num_attention_heads=128,
                          num_key_value_heads=128, kv_lora_rank=512, qk_rope_head_dim=64)
GQA_70B = ArchitectureSpec(attention_kind=AttentionKind.GQA, num_attention_heads=64,
                           num_key_value_heads=8, head_dim=128)
HYBRID_V4 = ArchitectureSpec(attention_kind=AttentionKind.HYBRID, num_attention_heads=128,
                             num_key_value_heads=1, head_dim=512, qk_rope_head_dim=64,
                             sliding_window=128)


def test_mla_golden_deepseek_v3():
    bpt, notes = kv_bytes_per_token(MLA_V3, num_layers=61, hidden_size=7168, kv_dtype="fp16")
    assert bpt == (512 + 64) * 2 * 61  # 70,272 bytes/token
    assert kv_gb(bpt, 32768) == pytest.approx(2.30, abs=0.01)
    assert kv_gb(bpt, 131072) == pytest.approx(9.21, abs=0.01)
    assert any("MLA" in n for n in notes)


def test_mla_fp8_halves():
    bpt16, _ = kv_bytes_per_token(MLA_V3, num_layers=61, hidden_size=7168, kv_dtype="fp16")
    bpt8, _ = kv_bytes_per_token(MLA_V3, num_layers=61, hidden_size=7168, kv_dtype="fp8")
    assert bpt8 == bpt16 / 2


def test_gqa_golden_llama70b_class():
    bpt, _ = kv_bytes_per_token(GQA_70B, num_layers=80, hidden_size=8192, kv_dtype="fp16")
    assert bpt == 2 * 8 * 128 * 2 * 80  # 327,680
    assert kv_gb(bpt, 32768) == pytest.approx(10.74, abs=0.01)


def test_hybrid_uses_gqa_upper_bound_and_flags_it():
    bpt, notes = kv_bytes_per_token(HYBRID_V4, num_layers=61, hidden_size=7168, kv_dtype="fp16")
    assert bpt == 2 * 1 * 512 * 2 * 61  # 124,928
    assert any("upper bound" in n for n in notes)


def test_legacy_mha_fallback_without_architecture():
    bpt, notes = kv_bytes_per_token(None, num_layers=32, hidden_size=4096, kv_dtype="fp16")
    assert bpt == 2 * 4096 * 2 * 32
    assert any("MHA upper bound" in n for n in notes)


def test_nothing_known_returns_none_with_reason():
    bpt, notes = kv_bytes_per_token(None, num_layers=None, hidden_size=None)
    assert bpt is None
    assert any("not modeled" in n for n in notes)


def test_concurrency_scales_linearly_and_dtype_validated():
    bpt, _ = kv_bytes_per_token(MLA_V3, num_layers=61, hidden_size=7168)
    assert kv_gb(bpt, 4096, concurrent_requests=200) == pytest.approx(
        kv_gb(bpt, 4096) * 200, rel=0.01)
    with pytest.raises(ValueError, match="fp16"):
        kv_bytes_per_token(MLA_V3, num_layers=61, hidden_size=7168, kv_dtype="fp3")
```

- [ ] **Step 2: Verify RED** (`ModuleNotFoundError`). **Step 3: Implement** types.py + kv.py exactly per the interfaces (kv.py's dispatch mirrors the ordered rules; arch with kv_heads but missing head_dim falls through to rule 3 — partial data never silently guesses). **Step 4: GREEN; full gates.** **Step 5: Commit** — `feat: capacity engine core — architecture-correct KV math with hand-derived goldens`

---

### Task 2: Estimator v2 — the homelab surfaces get the correct KV math

**Files:**
- Modify: `src/radar/models_radar/memory.py` (estimate_memory_gb v2), `src/radar/models_radar/assemble.py` (thread `architecture` into `add()`; NVFP4 4.5), `src/radar/models_radar/device_fit.py:37-43` (pass `model.architecture`), `config/model-seed.yaml` (pin deepseek-r1/v3 `num_layers: 61`, `hidden_size: 7168` — same config.json citation as their architecture blocks, comment `# verified 2026-07-28 (config.json, same source as architecture)`)
- Test: `tests/test_models_radar_memory.py` (bands updated deliberately + MLA sanity), `tests/test_models_radar_assemble.py` ([7,9]→recomputed band + NVFP4 4.5 pin), `tests/test_device_fit.py` (fixture + affected verdict recomputations), `tests/test_models_radar_seed.py` (R1/V3 layer pins)

**Interfaces:**
- `estimate_memory_gb(params_total, bits_per_weight, context, num_layers, hidden_size, architecture: ArchitectureSpec | None = None) -> float | None` — additive kwarg. New formula: `weights_gb × FRAGMENTATION + kv_gb + RUNTIME_BASELINE_GB` where `FRAGMENTATION = 1.05`, `RUNTIME_BASELINE_GB = 1.5` (module constants with the spec-§6.1 rationale comment: "engine overhead is a fixed few GB per rank, not a 20% proportional tax"), and the KV term comes from `capacity.kv.kv_bytes_per_token(architecture, num_layers=…, hidden_size=…, kv_dtype="fp16")` (None → 0.0). `OVERHEAD = 1.2` DELETED.
- Recomputed pins (state these in the tests as comments):
  - weights-only 8B@4.5b: 4.5×1.05 + 1.5 = **6.22** → band `[5.9, 6.6]`.
  - 8B/32L/4096h no-arch (assemble test): 4.72 + 2.15 + 1.5 = **8.37** → band `[7.5, 9.0]` (tier stays LAPTOP: 4k min-viable ≤ 16 ✓ — verify Q4 value).
  - `test_device_fit.py` `_model` helper: change `* 1.2` to `* 1.05 + 1.5` with a comment; recompute the `fits_tight` band comment at `:68` accordingly.
- `_BITS_BY_FORMAT["nvfp4"] = 4.5` with the cited comment (E4M3 scale per 16 elements = +0.5 bits; MXFP4 keeps 4.25, E8M0 per 32 = +0.25); update `test_models_radar_assemble.py:136-141` pin deliberately.
- `assemble.add()` passes `architecture=architecture`; `device_fit._quant_memory` passes `architecture=model.architecture`.
- New MLA sanity anchor (the program's headline):

```python
def test_mla_model_32k_estimate_is_sane_not_terabytes():
    # DeepSeek-V3 class: v1 formula produced ~350 GB of KV at 32k; v2 with MLA
    # architecture produces ~2.3 GB. 671B fp8 weights ≈ 671 GB.
    arch = ArchitectureSpec(attention_kind=AttentionKind.MLA, kv_lora_rank=512,
                            qk_rope_head_dim=64, num_key_value_heads=128,
                            num_attention_heads=128)
    gb = estimate_memory_gb(671_000_000_000, 8.0, 32768, 61, 7168, architecture=arch)
    assert 700 <= gb <= 715  # 671*1.05 + 2.3 + 1.5 = 708.3 — NOT 1000+
```

- [ ] **Step 1: Update the pinned tests deliberately FIRST** (each changed assert gets a `# v2:` recomputation comment) + add the MLA anchor + the R1/V3 seed-pin test (`seeds["deepseek-r1"].num_layers == 61` etc.). **Step 2: RED.** **Step 3: Implement + YAML pins.** **Step 4: FULL suite triage** — any other test moving means an unplanned consumer; investigate before touching it, list every touched test with its recomputation in the report. **Step 5: Full gates; commit** — `feat: estimator v2 — architecture-correct KV replaces the MHA-blind formula and flat 1.2 overhead`

---

### Task 3: `capacity/memory.py` — per-rank accounting + parallelism feasibility

**Files:**
- Create: `src/radar/capacity/memory.py`
- Test: `tests/test_capacity_memory.py` (new)

**Interfaces:**

```python
class RankMemory(BaseModel):  # frozen
    weights_gb: float
    kv_gb: float
    baseline_gb: float          # RUNTIME_BASELINE_GB per rank
    fragmentation_gb: float     # (weights+kv) * 0.05
    total_gb: float


class MemoryPlan(BaseModel):  # frozen
    per_rank: RankMemory
    usable_per_gpu_gb: float
    fits: bool
    headroom_fraction: float    # (usable - total)/usable, negative when over
    assumptions: AssumptionSheet


class InfeasibleError(ValueError):
    """Carries structured reasons — never raised empty."""
    def __init__(self, reasons: list[str]): ...


def check_sharding(architecture: ArchitectureSpec | None, num_layers: int | None,
                   parallelism: Parallelism) -> list[str]:
    # returns problem strings (empty = feasible):
    # tp>1 and kv_heads known and kv_heads % tp != 0 (MLA exempt: latent is replicated;
    #   note instead), ep>1 and num_experts known and num_experts % ep != 0,
    # ep>1 and num_experts unknown -> problem "expert parallelism requested but expert
    #   count unknown", pp>1 and num_layers known and num_layers % pp != 0.


def plan_memory(*, params_total: int, bits_per_weight: float,
                architecture: ArchitectureSpec | None, num_layers: int | None,
                hidden_size: int | None, workload: Workload, parallelism: Parallelism,
                device: DeviceProfile, kv_dtype: str = "fp16") -> MemoryPlan:
```

`plan_memory` math (documented in docstring): `weights_per_rank = weights_gb / world_size` (EP shards experts ≈ total for MoE — honest simplification noted in assumptions: "expert weights assumed evenly shardable; shared/dense layers replicated cost not itemized"); `kv_per_rank = kv_gb(bpt, ctx, concurrency) / tensor_parallel` (KV shards over TP only, replicated across PP stages' own layers — per-stage layers = num_layers/pp so KV divides by pp too via layer split: use `/ (tp × pp)`); baseline 1.5/rank; fragmentation 5% of (weights+kv) share. `usable_per_gpu_gb = total_memory_gb × USABLE_FRACTION[kind]` (per single GPU — NOT × gpu_count; the solver chooses counts). `fits = total ≤ usable_per_gpu`. Requires `world_size ≤ device.gpu_count` when the device is a preset with fixed gpu_count? NO — `plan_memory` is per-rank pure math; the SOLVER owns count logic. Sharding problems → raise `InfeasibleError(reasons)`.

- [ ] **Step 1: Failing tests** (worked values):

```python
def test_v4_pro_fp8_tp16_fits_h200_rank():
    # 1600 GB weights / 16 ranks = 100 GB; KV 32k×200 users fp8 hybrid-GQA:
    # 124928/2 B/token ×32768×200 /1e9 = 409.4 GB /(tp16 × pp1) = 25.6 GB
    # rank: 100×1.05? no — fragmentation itemized: 100 + 25.6 + 1.5 + 0.05×125.6 = 133.4 > 119.85 → does NOT fit at 200 users
    plan = plan_memory(params_total=1_600_000_000_000, bits_per_weight=8.0,
                       architecture=HYBRID_V4, num_layers=61, hidden_size=7168,
                       workload=Workload(concurrent_requests=200, avg_context_tokens=32768),
                       parallelism=Parallelism(tensor_parallel=16),
                       device=resolve_device("h200-141gb"), kv_dtype="fp8")
    assert plan.per_rank.weights_gb == pytest.approx(100.0)
    assert plan.fits is False  # 200 concurrent at 32k needs more than 16 GPUs' memory
    # at 50 users it fits:
    plan50 = plan_memory(..., workload=Workload(concurrent_requests=50, avg_context_tokens=32768), ...)
    assert plan50.fits is True and plan50.headroom_fraction > 0


def test_sharding_infeasibility_reasons():
    problems = check_sharding(GQA_70B, num_layers=80,
                              parallelism=Parallelism(tensor_parallel=3))
    assert any("kv_heads" in p and "3" in p for p in problems)  # 8 % 3 != 0
    with pytest.raises(InfeasibleError) as exc:
        plan_memory(..., parallelism=Parallelism(tensor_parallel=3), ...)
    assert exc.value.reasons


def test_mla_tp_exempt_from_kv_head_divisibility():
    assert check_sharding(MLA_V3, num_layers=61, parallelism=Parallelism(tensor_parallel=16)) == []
```

(Reuse Task 1's fixture specs via a shared `tests/capacity_fixtures.py` helper module — create it here with `MLA_V3/GQA_70B/HYBRID_V4` and import in both test files; refactor test_capacity_kv.py to use it in this task.)

- [ ] **Step 2-5: RED → implement → GREEN → gates → commit** — `feat: per-rank memory accounting with TP/PP/EP sharding feasibility`

---

### Task 4: `capacity/throughput.py` — roofline with documented engine constants

**Files:**
- Create: `src/radar/capacity/throughput.py`
- Test: `tests/test_capacity_throughput.py` (new)

**Interfaces:**

```python
ENGINE_EFFICIENCY: dict[str, dict[str, float]] = {
    # DOCUMENTED ESTIMATES (spec 6.2), calibrated by sub-project E's measured
    # benchmarks. decode_mbu = fraction of peak HBM bandwidth realized during
    # decode; prefill_mfu = fraction of peak dense TFLOPS realized in prefill.
    "vllm": {"decode_mbu": 0.60, "prefill_mfu": 0.50},
    "sglang": {"decode_mbu": 0.60, "prefill_mfu": 0.50},
    "tensorrt-llm": {"decode_mbu": 0.65, "prefill_mfu": 0.55},
    "llama-cpp": {"decode_mbu": 0.50, "prefill_mfu": 0.30},
}


class ThroughputEstimate(BaseModel):  # frozen
    aggregate_decode_tps: float          # tokens/sec across the fleet at this batch
    per_user_decode_tps: float           # aggregate / concurrent_requests
    prefill_tps: float | None            # None when TFLOPS for the dtype unavailable
    ttft_seconds: float | None           # avg_context / prefill_tps
    assumptions: AssumptionSheet


def weight_dtype_for_bits(bits_per_weight: float) -> str:
    # >= 12 -> "fp16"; >= 6 -> "fp8"(int8-class byte width); else "fp4"


def estimate_throughput(*, params_active: int | None, params_total: int,
                        bits_per_weight: float, kv_bytes_per_token: float | None,
                        workload: Workload, device: DeviceProfile, n_gpus: int,
                        engine: str = "vllm") -> ThroughputEstimate | None:
```

Math (docstring-documented): `active = params_active or params_total` (dense fallback; MoE note when params_active used: "decode reads active expert weights only"). Per decode step with batch B=concurrent_requests: `bytes_per_step = active × bits/8 + B × ctx × kv_bpt`; `aggregate_bw = n_gpus × memory_bandwidth_gbs × 1e9 × decode_mbu`; `aggregate_decode_tps = aggregate_bw × B / bytes_per_step`; per_user = /B. Prefill: pick `tflops_fp16/fp8/fp4` via `weight_dtype_for_bits`; missing that dtype on the device → try fp16 with note "prefill computed at fp16 TFLOPS (no {dtype} figure published)"; still missing → prefill_tps None with note. `prefill_tps = n_gpus × tflops × 1e12 × prefill_mfu / (2 × active)`; `ttft = avg_context / prefill_tps`. `device.memory_bandwidth_gbs is None` → return None (caller degrades to memory-only with the reason). Unknown engine → `ValueError` listing keys. Assumptions always include the engine constants used, verbatim numbers.

- [ ] **Step 1: Failing tests** with hand-derived values:

```python
def test_v4_pro_decode_on_16x_h200_at_200_users():
    # active 49B fp8 = 49 GB/step weights; KV read 200×32768×62464 B = 409.4 GB/step
    # bytes/step = 458.4 GB; agg bw = 16×4800e9×0.6 = 46.08e12 B/s
    # agg tps = 46.08e12 × 200 / 458.4e9 ≈ 20,105 t/s → per-user ≈ 100.5 t/s
    est = estimate_throughput(params_active=49_000_000_000, params_total=1_600_000_000_000,
                              bits_per_weight=8.0, kv_bytes_per_token=124928 / 2,
                              workload=Workload(concurrent_requests=200, avg_context_tokens=32768),
                              device=resolve_device("h200-141gb"), n_gpus=16, engine="vllm")
    assert est.per_user_decode_tps == pytest.approx(100.5, rel=0.02)
    assert est.prefill_tps == pytest.approx(16 * 1979e12 * 0.5 / (2 * 49e9), rel=0.01)
    assert any("0.6" in n or "0.60" in n for n in est.assumptions.lines)


def test_no_bandwidth_returns_none():
    custom = resolve_device({"kind": "gpu", "total_memory_gb": 141, "gpu_count": 8})
    assert estimate_throughput(..., device=custom, n_gpus=8, ...) is None


def test_batch_amortizes_weight_reads():
    one = estimate_throughput(..., workload=Workload(concurrent_requests=1, avg_context_tokens=4096), ...)
    many = estimate_throughput(..., workload=Workload(concurrent_requests=64, avg_context_tokens=4096), ...)
    assert many.aggregate_decode_tps > one.aggregate_decode_tps * 10  # batching wins
    assert many.per_user_decode_tps < one.per_user_decode_tps        # but per-user drops
```

- [ ] **Step 2-5: RED → implement → GREEN → gates → commit** — `feat: roofline throughput model with documented per-engine efficiency estimates`

---

### Task 5: `capacity/solver.py` — both directions + anchors

**Files:**
- Create: `src/radar/capacity/solver.py`
- Test: `tests/test_capacity_solver.py` (new)

**Interfaces:**

```python
class CapacityPlan(BaseModel):  # frozen
    model_id: str
    device_id: str
    n_gpus: int
    n_nodes: int | None          # when the device is a node/cluster preset: count of nodes
    parallelism: Parallelism
    memory: MemoryPlan
    throughput: ThroughputEstimate | None
    meets_target: bool | None    # None when no target or no throughput model
    assumptions: AssumptionSheet


class MaxWorkload(BaseModel):  # frozen
    model_id: str; device_id: str; n_gpus: int
    max_concurrent_at_context: int
    per_user_decode_tps_at_max: float | None
    assumptions: AssumptionSheet


def plan_capacity(entry: ModelEntry, device_spec: str, workload: Workload, *,
                  quant_format: str | None = None, kv_dtype: str = "fp16",
                  engine: str = "vllm") -> CapacityPlan:  # raises InfeasibleError

def max_workload(entry: ModelEntry, device_spec: str, n_gpus: int, *,
                 avg_context_tokens: int, quant_format: str | None = None,
                 kv_dtype: str = "fp16", engine: str = "vllm") -> MaxWorkload
```

Solver logic (documented): resolve device; candidate GPU counts = multiples of the preset's `gpu_count` granularity (single GPU → 1,2,4,8 then node-multiples 16,24,32,…,512 cap; node/cluster preset → multiples of its gpu_count). Quant selection: `quant_format` given → match entry.quants by substring (error listing available); else best viable quant (highest bits with `bits >= VIABLE_MIN_BITS`) — noted. For each count ascending: parallelism = `Parallelism(tensor_parallel=min(count, 8), pipeline_parallel=count//8 or 1, expert_parallel=1)` — the canonical layout (TP within node, PP across; note "layout heuristic: TP≤8 intra-node, PP across nodes; EP not auto-selected"), skip counts whose layout fails `check_sharding` (record last reasons); first count where `plan_memory().fits` and (no target OR throughput meets target) wins. Exhausted → `InfeasibleError` with the accumulated reasons (including the largest-count memory shortfall). `n_nodes = count // 8` for node presets. `max_workload`: binary-search concurrency (1..100k) for the largest B with `plan_memory(...).fits`; throughput at that B reported.

Engine-support cross-check: load platform matrix via `load_platform_entries` — if the entry's `architecture.attention_kind is MLA` and the chosen engine's `features["mla"]` is `"no"`, or quant dtype fp8/nvfp4 unsupported, add an assumption WARNING line (never a hard failure — matrix is advisory): `"WARNING: {engine} platform matrix lists {feature}: {support}"`. Wrap in try/except PlatformMatrixError → skip silently (matrix is optional here).

- [ ] **Step 1: Failing anchor tests** (the program's reason to exist — use real seeds):

```python
def _entry(seed_id: str) -> ModelEntry:
    # build via load_model_seed + build_model_entry(seed, None, []) — offline, deterministic
    seeds = {s.id: s for s in load_model_seed(_REPO_ROOT / "config" / "model-seed.yaml")}
    return build_model_entry(seeds[seed_id], None, [])


def test_anchor_v4_pro_needs_two_h200_nodes_for_50_users():
    plan = plan_capacity(_entry("hf-deepseek-v4-pro"), "hgx-h200-8",
                         Workload(concurrent_requests=50, avg_context_tokens=32768),
                         quant_format="FP8", kv_dtype="fp8")
    assert plan.n_gpus == 16 and plan.n_nodes == 2
    assert plan.memory.fits and plan.memory.headroom_fraction > 0
    assert plan.throughput is not None and plan.throughput.per_user_decode_tps > 30


def test_anchor_v4_pro_wont_fit_single_h200_and_says_why():
    with pytest.raises(InfeasibleError) as exc:
        plan_capacity(_entry("hf-deepseek-v4-pro"), "h200-141gb",
                      Workload(concurrent_requests=1, avg_context_tokens=4096),
                      quant_format="FP8")
    assert any("memory" in r.lower() for r in exc.value.reasons)


def test_anchor_deepseek_v3_fits_one_h200_node_fp8():
    plan = plan_capacity(_entry("deepseek-v3"), "hgx-h200-8",
                         Workload(concurrent_requests=20, avg_context_tokens=32768),
                         quant_format="FP8", kv_dtype="fp8")
    assert plan.n_gpus == 8  # 671 GB weights + tiny MLA KV ≤ 958.8 usable


def test_solver_result_satisfies_own_memory_check():  # spec §10 property
    plan = plan_capacity(_entry("hf-glm-5-2"), "hgx-h200-8",
                         Workload(concurrent_requests=10, avg_context_tokens=16384),
                         quant_format="FP8", kv_dtype="fp8")
    assert plan.memory.fits is True


def test_max_workload_direction():
    mw = max_workload(_entry("deepseek-v3"), "hgx-h200-8", 8,
                      avg_context_tokens=32768, quant_format="FP8", kv_dtype="fp8")
    assert mw.max_concurrent_at_context >= 50  # ~250 GB KV headroom / 1.15 GB per user


def test_property_memory_monotone_and_gpu_count_antitone():  # spec §10 properties
    entry = _entry("deepseek-v3")
    base = Workload(concurrent_requests=20, avg_context_tokens=16384)
    more_users = Workload(concurrent_requests=80, avg_context_tokens=16384)
    more_ctx = Workload(concurrent_requests=20, avg_context_tokens=65536)
    p_base = plan_capacity(entry, "hgx-h200-8", base, quant_format="FP8", kv_dtype="fp8")
    p_users = plan_capacity(entry, "hgx-h200-8", more_users, quant_format="FP8", kv_dtype="fp8")
    p_ctx = plan_capacity(entry, "hgx-h200-8", more_ctx, quant_format="FP8", kv_dtype="fp8")
    # memory monotone in users and context (same gpu count -> per-rank total grows,
    # or the solver escalates the count; either way never shrinks):
    assert p_users.memory.per_rank.total_gb >= p_base.memory.per_rank.total_gb \
        or p_users.n_gpus > p_base.n_gpus
    assert p_ctx.memory.per_rank.total_gb >= p_base.memory.per_rank.total_gb \
        or p_ctx.n_gpus > p_base.n_gpus
    # gpu count antitone in quant bits: FP8 (8 bits) never needs FEWER gpus than
    # a 4.5-bit quant of the same model at the same workload:
    p_q4 = plan_capacity(entry, "hgx-h200-8", base, quant_format="Q4_K_M", kv_dtype="fp8")
    assert p_q4.n_gpus <= p_base.n_gpus
```

**Anchor pre-check for the FP8 quant path:** `deepseek-v3`/`hf-deepseek-v4-pro` seeds have no `manual_quants` and, built offline with `hf=None`, get the SYNTHESIZED GGUF ladder (no "FP8" format!). `quant_format="FP8"` would fail. Resolve in this task: `plan_capacity` accepts `quant_format` matching case-insensitively against quants, AND falls back to interpreting unmatched known formats via `bits_for_format` ("FP8" → 8.0 bits) with assumption note `"quant FP8 not in catalog for this entry — using 8.0 bits/weight nominal"`. Test that note appears.

- [ ] **Step 2-5: RED → implement → GREEN (hand-verify each anchor's arithmetic in the report) → gates → commit** — `feat: capacity solver — GPU counts from workloads and workloads from fleets, with anchors`

---

### Task 6: CLI — `radar capacity plan` / `radar capacity max`

**Files:**
- Modify: `src/radar/cli.py` (new `capacity_app` at ~line 43 + two commands; function-local imports per house style)
- Test: `tests/test_capacity_cli.py` (new)

**Interfaces:**
- `capacity_app = typer.Typer(help="Datacenter capacity planning (memory + throughput + solver).", no_args_is_help=True)`; `app.add_typer(capacity_app, name="capacity")`.
- `radar capacity plan --model <id> --device <preset> --users N --context C [--target-tps T] [--quant FP8] [--kv-dtype fp8] [--engine vllm] [--root .]` — loads entries via `_latest_model_cards(root)`; model not found → red error listing available ids, exit 1; InfeasibleError → prints each reason on a `[red]` line, exit 2; success prints: header (model, device, count, nodes, layout), memory table (per-rank weights/kv/baseline/fragmentation/total vs usable + headroom %), throughput block (per-user t/s, aggregate, TTFT) when available, then `Assumptions:` bullet list (every AssumptionSheet line).
- `radar capacity max --model <id> --device <preset> --gpus N --context C [...]` — same conventions.
- **Offline fallback:** when no scan exists (`_latest_model_cards` returns []), fall back to seed-built entries (`build_model_entry(seed, None, [])` over `load_model_seed`, path via the parents[2] idiom) with a yellow note `"(no scan found — using bundled seed specs)"` — capacity planning must work on a fresh clone.

- [ ] **Step 1: Failing CLI tests** (CliRunner, house substring style): plan happy-path against the bundled seed on an empty tmp root (asserts "16" + "2" nodes + "Assumptions:" + exit 0 for the V4-Pro/hgx-h200-8/50-user case); infeasible single-H200 case exits 2 with a memory reason; unknown model exits 1 listing ids; `max` prints max concurrency. **Step 2-5: RED → implement → GREEN → gates → commit** — `feat: radar capacity plan/max CLI with assumption sheets`

---

### Task 7: MCP — `plan_capacity`, `max_workload`, `compare_devices`

**Files:**
- Create: `src/radar/mcp_server/capacity_queries.py`
- Modify: `src/radar/mcp_server/server.py` (instantiate service + 3 tools)
- Test: `tests/test_capacity_queries.py` (new), `tests/test_mcp_server.py` (tool-names pin — extend the existing `<=` set assert)

**Interfaces:**
- `class CapacityQueryService:` mirroring ModelQueryService (`__init__(self, root: Path)`; `_entries()` via `_latest_model_cards` + the Task 6 seed fallback, extracted into a shared helper `_entries_or_seed(root)` in capacity_queries and REUSED by cli via import — single source).
- `plan_capacity(model_id, device, concurrent_requests, avg_context_tokens, target_tps_per_user=None, quant=None, kv_dtype="fp16", engine="vllm") -> dict | None` — None for unknown model; InfeasibleError → `{"feasible": False, "reasons": [...]}` (structured, never an exception across MCP); success → `CapacityPlan.model_dump(mode="json")` + `{"feasible": True}`.
- `max_workload(model_id, device, n_gpus, avg_context_tokens, ...) -> dict | None`.
- `compare_devices(model_id, devices: list[str], concurrent_requests, avg_context_tokens, ...) -> list[dict]` — one plan-or-reasons dict per device id (each entry independently solved with the same workload; unknown device id → `{"device": id, "error": "..."}` row, never a raised exception).
- server.py: `capacity = CapacityQueryService(root)` beside the other services; three `@mcp.tool()` registrations with docstrings stating the assumption-sheet honesty contract ("estimates carry an assumptions list; engine efficiency constants are documented estimates, not measurements").

- [ ] **Step 1: Failing tests** (service-level with tmp root + bundled-seed fallback; the V4-Pro compare across ["hgx-h200-8", "hgx-b200-8", "mi300x-oam-8"] returns 3 rows each feasible-or-reasoned; tool-name pin `{"plan_capacity", "max_workload", "compare_devices"} <= tool_names` in test_mcp_server.py). **Step 2-5: RED → implement → GREEN → gates → commit** — `feat: MCP capacity tools — plan, max workload, device comparison`

---

### Task 8: `capacity/recipe.py` — launch-config generator (vLLM → SGLang → TensorRT-LLM)

**Files:**
- Create: `src/radar/capacity/recipe.py`
- Modify: `src/radar/cli.py` (plan command prints the recipe block), `src/radar/mcp_server/capacity_queries.py` (plan dict gains `"recipe"`)
- Test: `tests/test_capacity_recipe.py` (new), extend `tests/test_capacity_cli.py`

**Interfaces:**

```python
def launch_recipe(plan: CapacityPlan, entry: ModelEntry, *, engine: str = "vllm",
                  kv_dtype: str = "fp16") -> str:
```

Returns a fenced multi-line command string per engine (spec 6.4 — sandbox-playbook style with cautions):
- vllm: `vllm serve {hf_repo} --tensor-parallel-size {tp} [--pipeline-parallel-size {pp}] --max-model-len {ctx} --max-num-seqs {concurrency} [--kv-cache-dtype fp8] [--quantization fp8|modelopt per quant] --gpu-memory-utilization 0.85` + comment lines: `# usable-memory fraction matches the radar's 0.85 planning assumption`, `# headroom {x}% at {users} users × {ctx} ctx — reduce max-num-seqs if OOM`, HF link line (D4).
- sglang: `python -m sglang.launch_server --model-path {repo} --tp {tp} ...` equivalent flags.
- tensorrt-llm: a 3-line caution recipe (`trtllm-serve {repo} --tp_size {tp} ...` + note that engine build steps differ per version — link repo).
- Unknown engine → ValueError listing supported. `entry.hf_repo` None → recipe uses `<model-path>` placeholder + note.

- [ ] **Step 1: Failing tests**: vllm recipe for the V4-Pro plan contains `--tensor-parallel-size 8`? no — layout tp=min(16,8)=8, pp=2: assert `--tensor-parallel-size 8` AND `--pipeline-parallel-size 2` AND `--kv-cache-dtype fp8` AND `huggingface.co/deepseek-ai/DeepSeek-V4-Pro`; sglang variant `--tp 8`; unknown engine raises; CLI plan output includes the vllm block by default. **Step 2-5** → commit — `feat: launch-recipe generator — vLLM, SGLang, TensorRT-LLM starting configs`

---

### Task 9: `capacity/tco.py` + docs + CHANGELOG

**Files:**
- Create: `src/radar/capacity/tco.py`
- Modify: `src/radar/cli.py` (plan output TCO block + `--electricity-usd-kwh` / `--amortization-months` options), `src/radar/mcp_server/capacity_queries.py` (plan dict gains `"tco"`), `docs/architecture.md` (module-map row after `models_radar/platform_matrix`), `README.md` (Highlights bullet, house style per C's), `CHANGELOG.md` (`### Capacity engine (sub-project D)` at line 9, with the deferral bullet)
- Test: `tests/test_capacity_tco.py` (new)

**Interfaces:**

```python
class TCOEstimate(BaseModel):  # frozen
    fleet_power_kw: float                     # n_gpus × tdp_watts / 1000
    tokens_per_sec_per_kw: float | None       # aggregate_decode_tps / fleet_power_kw
    usd_per_million_tokens: float | None      # only when device price exists
    assumptions: AssumptionSheet


DEFAULT_ELECTRICITY_USD_PER_KWH = 0.12   # documented default, CLI-overridable
DEFAULT_AMORTIZATION_MONTHS = 36


def estimate_tco(plan: CapacityPlan, *, electricity_usd_per_kwh: float = ...,
                 amortization_months: int = ...) -> TCOEstimate | None:
```

`None` when `device.tdp_watts` is None. `usd_per_million_tokens` = (amortized hardware $/s + electricity $/s) / (aggregate_tps / 1e6); hardware term only when `indicative_price_usd` present (today: none of the datacenter devices — the field renders "n/a (no public list price)" and the math is electricity-only with note `"$/Mtok excludes hardware capex: no public list price"`). Assumptions always name both defaults with values. GPU TDP is board TDP — note "fleet power excludes host CPUs/cooling (~+30-50% at the rack)".

Docs: architecture row `| capacity/ | Deterministic capacity engine: architecture-correct KV math, per-rank TP/PP/EP memory, roofline throughput (documented engine-efficiency estimates), two-direction solver, launch recipes, kW-first TCO. Powers radar capacity plan/max + MCP plan_capacity/max_workload/compare_devices. |`. README bullet: 🧮 **Capacity planner** — house style, naming the north-star question, the assumption-sheet honesty contract, and the three MCP tools. CHANGELOG section covering Tasks 1-9 + deferral bullet (per-layer hybrid KV modeling awaits published compress-ratio semantics; MBU/MFU calibration lands with sub-project E's measured benchmarks; EP auto-selection not attempted).

- [ ] **Step 1: Failing tests** (kW math for 16×H200 = 11.2 kW; tokens/s/kW ≈ 20105/11.2 ≈ 1795; $/Mtok electricity-only at defaults = (11.2 × 0.12/3600) $/s ÷ (20105/1e6) ≈ $0.0186/Mtok — hand-verify; None-TDP device → None). **Step 2-5** → commit — `feat: kW-first TCO estimates + capacity engine docs`

---

## Final verification (whole sub-project)

- [ ] `uv run pytest -q && uv run ruff check . && uv run mypy src` — all green.
- [ ] **The north-star command, live:** `uv run radar capacity plan --model hf-deepseek-v4-pro --device hgx-h200-8 --users 50 --context 32768 --quant FP8 --kv-dtype fp8` → 2 nodes / 16 GPUs, headroom stated, per-user t/s, TTFT, vLLM recipe, assumption sheet, TCO block. Paste the full output in the review/PR.
- [ ] `radar capacity max --model deepseek-v3 --device hgx-h200-8 --gpus 8 --context 32768 --kv-dtype fp8` sane; `compare_devices` over hgx-h200-8/hgx-b200-8/mi300x-oam-8 returns 3 reasoned rows.
- [ ] MLA regression proof stated in the PR: DeepSeek-V3 32k KV = 2.3 GB (v2) vs ~350 GB (v1 formula).
- [ ] Homelab surfaces sanity: models table min-memory values shift only per the documented recomputations; tiers stable for the 8B class.
- [ ] Subagent-driven reviews per task + final whole-branch review; PR with checks verified green BEFORE merge.
