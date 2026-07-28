# Sub-project B: Model Knowledge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Model schema v2 (architecture block for GQA/MLA/MoE, datacenter quant formats, provenance, benchmarks) with automatic ingest from HF `config.json` and a weekly drift re-verify — closing the "37/43 models have no architecture fields" hole so sub-project D's capacity engine has correct inputs (spec §5.1–5.2 of `docs/superpowers/specs/2026-07-27-capacity-planning-radar-v3-design.md`).

**Architecture:** A new frozen `ArchitectureSpec` pydantic model is shared by seed (all-optional manual overrides) and entry (resolved). A new pure module `hf_config.py` parses raw HF `config.json` dicts — generic transformer keys plus DeepSeek-MLA, MoE, and GLM family layouts — and derives `attention_kind`. The HF collector passes the raw config through; assembly merges seed-over-collected per field, stamps a per-field provenance map, and emits a real FP8/NVFP4 quant variant when the repo itself is quantized (instead of today's synthesized GGUF ladder). A `radar models verify` command re-fetches configs and reports drift without ever overwriting verified seed values; a weekly workflow runs it.

**Tech Stack:** Python 3.12, pydantic v2, httpx, typer, pytest. Run everything with `uv run`.

## Global Constraints

- **`memory.py` is untouched.** The KV formula rewrite is sub-project D. B only supplies fields; the existing (knowingly wrong) estimate keeps its current behavior and tests.
- Deterministic core: parsers are pure dict→model functions; no wall-clock in library code (`retrieved_at` is an injected parameter).
- Backward compatibility: every existing `config/model-seed.yaml` entry must load unchanged; persisted old run artifacts (ModelEntry JSON without new fields) must still validate (all new fields optional with defaults).
- Merge order invariant (existing): manual seed values win over collected HF data — including inside the architecture block (per-field, not whole-block).
- Drift never silently overwrites a verified manual value (spec §5.2).
- Provenance granularity: one `SpecProvenance` per top-level spec field (`params_total`, `params_active`, `context_length`, `license`, `architecture` as a single group since it always resolves wholesale from one source per field — the seed override map is per-field within the merge, and each overridden field flips the group source to `"seed"` only if ANY architecture field came from seed → then per-field map `architecture.<field>` entries are used instead; see Task 4 code).
- Gates before every commit: `uv run pytest -q && uv run ruff check . && uv run mypy src` (suite starts at 1052 passed).
- Commit format `<type>: <description>`, NO Co-Authored-By. Never commit `data/` files.
- Branch: `feature/capacity-radar/model-knowledge-B` (already created from main).

---

### Task 1: Schema v2 entities — `ArchitectureSpec`, provenance, benchmarks

**Files:**
- Modify: `src/radar/models_radar/entities.py`
- Test: `tests/test_models_radar_entities.py` (append)

**Interfaces:**
- Consumes: existing `ModelEntry`/`ModelSeed`/`QuantVariant` (frozen pydantic, `ModelSeed` has `extra="forbid"`).
- Produces (exact names later tasks rely on):
  - `class AttentionKind(str, Enum)`: `MHA="mha"`, `GQA="gqa"`, `MLA="mla"`, `HYBRID="hybrid"`, `UNKNOWN="unknown"`.
  - `class ArchitectureSpec(BaseModel)` (frozen, all fields optional): `attention_kind: AttentionKind = AttentionKind.UNKNOWN`, `num_attention_heads: int | None`, `num_key_value_heads: int | None`, `head_dim: int | None`, `kv_lora_rank: int | None`, `qk_rope_head_dim: int | None`, `num_experts: int | None`, `experts_per_token: int | None`, `sliding_window: int | None`, `vocab_size: int | None`.
  - `class SpecProvenance(BaseModel)` (frozen): `source: str` (`"seed" | "hf-config" | "hf-api" | "synthesized"`), `url: str | None = None`, `retrieved_at: str | None = None`, `verified: bool = False`.
  - `class BenchmarkScore(BaseModel)` (frozen): `name: str`, `score: float`, `source_url: str`.
  - `ModelEntry` gains: `architecture: ArchitectureSpec | None = None`, `provenance: dict[str, SpecProvenance] = Field(default_factory=dict)`, `benchmarks: list[BenchmarkScore] = Field(default_factory=list)`.
  - `ModelSeed` gains: `architecture: ArchitectureSpec | None = None`, `benchmarks: list[BenchmarkScore] = Field(default_factory=list)`, `spec_verified: bool = False` (True = a human checked the seed's numbers against the model card; drives provenance.verified).

- [ ] **Step 1: Write the failing tests** (append to `tests/test_models_radar_entities.py`):

```python
def test_architecture_spec_defaults_and_frozen():
    from radar.models_radar.entities import ArchitectureSpec, AttentionKind

    arch = ArchitectureSpec()
    assert arch.attention_kind is AttentionKind.UNKNOWN
    assert arch.num_key_value_heads is None
    import pytest as _pytest

    with _pytest.raises(Exception):
        arch.num_key_value_heads = 8  # frozen


def test_model_entry_v2_fields_default_empty():
    from radar.models_radar.entities import ModelEntry

    entry = ModelEntry(id="m", name="M", family="F")
    assert entry.architecture is None
    assert entry.provenance == {}
    assert entry.benchmarks == []


def test_model_seed_accepts_architecture_and_benchmarks():
    from radar.models_radar.entities import (
        ArchitectureSpec,
        AttentionKind,
        BenchmarkScore,
        ModelSeed,
    )

    seed = ModelSeed(
        id="m", name="M", family="F",
        architecture=ArchitectureSpec(
            attention_kind=AttentionKind.MLA, kv_lora_rank=512, qk_rope_head_dim=64,
        ),
        benchmarks=[BenchmarkScore(name="MMLU-Pro", score=0.81,
                                   source_url="https://example.com/card")],
        spec_verified=True,
    )
    assert seed.architecture.kv_lora_rank == 512
    assert seed.spec_verified is True


def test_old_seed_shape_still_loads():
    from radar.models_radar.entities import ModelSeed

    # Exactly the fields a pre-v2 YAML entry carries — must not raise.
    seed = ModelSeed(id="m", name="M", family="F", params_total=8_000_000_000)
    assert seed.architecture is None and seed.spec_verified is False
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_models_radar_entities.py -q` → FAIL (`ImportError: cannot import name 'ArchitectureSpec'`).

- [ ] **Step 3: Implement** in `entities.py` — add after the `HardwareTier` enum:

```python
class AttentionKind(str, Enum):
    """How the model attends — determines the KV-cache formula (sub-project D)."""

    MHA = "mha"          # classic multi-head: kv_heads == heads
    GQA = "gqa"          # grouped-query: kv_heads < heads
    MLA = "mla"          # DeepSeek latent attention: compressed KV
    HYBRID = "hybrid"    # explicit mixed layer types (e.g. Gemma 3 local/global)
    UNKNOWN = "unknown"


class ArchitectureSpec(BaseModel):
    """Attention/MoE geometry from config.json (or a curated seed override).

    All fields optional: a seed may override just one number, and old
    persisted entries carry none. Consumed by the capacity engine (D).
    """

    model_config = ConfigDict(frozen=True)

    attention_kind: AttentionKind = AttentionKind.UNKNOWN
    num_attention_heads: int | None = None
    num_key_value_heads: int | None = None
    head_dim: int | None = None
    kv_lora_rank: int | None = None       # MLA latent dim (DeepSeek family)
    qk_rope_head_dim: int | None = None   # MLA rope sub-dim
    num_experts: int | None = None        # MoE routed experts
    experts_per_token: int | None = None  # MoE active experts per token
    sliding_window: int | None = None
    vocab_size: int | None = None


class SpecProvenance(BaseModel):
    """Where a spec number came from — every capacity answer cites this."""

    model_config = ConfigDict(frozen=True)

    source: str                      # "seed" | "hf-config" | "hf-api" | "synthesized"
    url: str | None = None
    retrieved_at: str | None = None  # ISO date of collection; None for seed values
    verified: bool = False           # True = human-checked against the model card


class BenchmarkScore(BaseModel):
    """One curated, cited benchmark result (never scraped)."""

    model_config = ConfigDict(frozen=True)

    name: str
    score: float
    source_url: str
```

Then on `ModelEntry` (after `hidden_size`): `architecture: ArchitectureSpec | None = None`; after `warnings`: `provenance: dict[str, SpecProvenance] = Field(default_factory=dict)` and `benchmarks: list[BenchmarkScore] = Field(default_factory=list)`. On `ModelSeed` (after `hidden_size`): `architecture: ArchitectureSpec | None = None`; after `manual_quants`: `benchmarks: list[BenchmarkScore] = Field(default_factory=list)` and `spec_verified: bool = False`.

- [ ] **Step 4: Run tests** — `uv run pytest tests/test_models_radar_entities.py tests/test_models_radar_seed.py -q` → PASS (seed file must still load).

- [ ] **Step 5: Full gates, commit** — `uv run pytest -q && uv run ruff check . && uv run mypy src` → `git commit -m "feat: model schema v2 — architecture block, provenance, benchmarks"`

---

### Task 2: HF config parsers — `hf_config.py`

**Files:**
- Create: `src/radar/models_radar/hf_config.py`
- Test: `tests/test_hf_config.py` (new)

**Interfaces:**
- Consumes: `ArchitectureSpec`, `AttentionKind` (Task 1).
- Produces:
  - `parse_architecture(cfg: dict) -> ArchitectureSpec` — pure; understands generic transformer keys, DeepSeek MLA, MoE (Mixtral/Qwen-MoE/DeepSeek), GLM's `multi_query_group_num`; unknown/empty dict → `ArchitectureSpec()` (all None, kind UNKNOWN).
  - `parse_quant_format(cfg: dict) -> str | None` — reads `quantization_config`; returns a canonical format string (`"FP8"`, `"NVFP4"`, `"MXFP4"`, `"AWQ"`, `"GPTQ"`) or None for unquantized repos.

Key mappings (implementer: verify against the live configs during Step 3 with `curl -s https://huggingface.co/<repo>/raw/main/config.json`; the fixture VALUES below are from memory and must be corrected if the live config disagrees — the KEY NAMES are the contract):

| config.json key | ArchitectureSpec field |
| --- | --- |
| `num_attention_heads` | num_attention_heads |
| `num_key_value_heads` (fallback: `multi_query_group_num` for GLM) | num_key_value_heads |
| `head_dim` (fallback: `hidden_size // num_attention_heads` when both known) | head_dim |
| `kv_lora_rank` | kv_lora_rank (presence ⇒ MLA) |
| `qk_rope_head_dim` | qk_rope_head_dim |
| `n_routed_experts` (DeepSeek) / `num_local_experts` (Mixtral) / `num_experts` (Qwen-MoE) | num_experts |
| `num_experts_per_tok` | experts_per_token |
| `sliding_window` | sliding_window |
| `vocab_size` | vocab_size |

`attention_kind` derivation (in this exact priority order): `kv_lora_rank` present → MLA; `layer_types` list present with >1 distinct value → HYBRID; both head counts known and kv < heads → GQA; both known and equal → MHA; else UNKNOWN.

- [ ] **Step 1: Write the failing tests** (`tests/test_hf_config.py`; table-driven, fixtures inline):

```python
"""Pure parsers for HF config.json → ArchitectureSpec / quant format."""

from radar.models_radar.entities import AttentionKind
from radar.models_radar.hf_config import parse_architecture, parse_quant_format


LLAMA_31_8B = {  # meta-llama/Llama-3.1-8B-Instruct (verify live in Step 3)
    "num_hidden_layers": 32, "hidden_size": 4096,
    "num_attention_heads": 32, "num_key_value_heads": 8,
    "vocab_size": 128256, "max_position_embeddings": 131072,
}

DEEPSEEK_V3 = {  # deepseek-ai/DeepSeek-V3 (verify live)
    "num_hidden_layers": 61, "hidden_size": 7168,
    "num_attention_heads": 128, "kv_lora_rank": 512, "qk_rope_head_dim": 64,
    "n_routed_experts": 256, "num_experts_per_tok": 8, "vocab_size": 129280,
}

MIXTRAL_8X7B = {  # mistralai/Mixtral-8x7B-Instruct-v0.1 (verify live)
    "num_hidden_layers": 32, "hidden_size": 4096,
    "num_attention_heads": 32, "num_key_value_heads": 8,
    "num_local_experts": 8, "num_experts_per_tok": 2, "sliding_window": None,
}

GLM_STYLE = {  # zai-org GLM family layout (verify live)
    "num_attention_heads": 32, "multi_query_group_num": 2, "hidden_size": 4096,
}

GEMMA3_HYBRID = {  # google/gemma-3-12b-it style alternating attention (verify live)
    "num_attention_heads": 16, "num_key_value_heads": 8,
    "layer_types": ["sliding_attention", "full_attention"], "sliding_window": 1024,
}


def test_gqa_derived_for_llama():
    arch = parse_architecture(LLAMA_31_8B)
    assert arch.attention_kind is AttentionKind.GQA
    assert arch.num_key_value_heads == 8
    assert arch.head_dim == 128  # 4096 / 32 fallback
    assert arch.vocab_size == 128256


def test_mla_wins_for_deepseek():
    arch = parse_architecture(DEEPSEEK_V3)
    assert arch.attention_kind is AttentionKind.MLA
    assert arch.kv_lora_rank == 512
    assert arch.qk_rope_head_dim == 64
    assert arch.num_experts == 256
    assert arch.experts_per_token == 8


def test_moe_keys_for_mixtral():
    arch = parse_architecture(MIXTRAL_8X7B)
    assert arch.num_experts == 8
    assert arch.experts_per_token == 2
    assert arch.attention_kind is AttentionKind.GQA


def test_glm_kv_heads_fallback():
    arch = parse_architecture(GLM_STYLE)
    assert arch.num_key_value_heads == 2
    assert arch.attention_kind is AttentionKind.GQA


def test_hybrid_from_layer_types():
    arch = parse_architecture(GEMMA3_HYBRID)
    assert arch.attention_kind is AttentionKind.HYBRID
    assert arch.sliding_window == 1024


def test_mha_when_counts_equal_and_unknown_when_empty():
    assert parse_architecture(
        {"num_attention_heads": 32, "num_key_value_heads": 32}
    ).attention_kind is AttentionKind.MHA
    assert parse_architecture({}).attention_kind is AttentionKind.UNKNOWN


def test_quant_format_detection():
    assert parse_quant_format(
        {"quantization_config": {"quant_method": "fp8"}}) == "FP8"
    assert parse_quant_format(
        {"quantization_config": {"quant_method": "modelopt",
                                 "quant_algo": "NVFP4"}}) == "NVFP4"
    assert parse_quant_format(
        {"quantization_config": {"quant_method": "mxfp4"}}) == "MXFP4"
    assert parse_quant_format(
        {"quantization_config": {"quant_method": "awq"}}) == "AWQ"
    assert parse_quant_format(
        {"quantization_config": {"quant_method": "gptq"}}) == "GPTQ"
    assert parse_quant_format({}) is None
```

- [ ] **Step 2: Run to verify failure** — module missing.

- [ ] **Step 3: Verify fixtures against live HF** (network is available in this environment):
`curl -s https://huggingface.co/meta-llama/Llama-3.1-8B-Instruct/raw/main/config.json | head -40` (repeat for deepseek-ai/DeepSeek-V3, mistralai/Mixtral-8x7B-Instruct-v0.1, and one NVFP4 repo from the seed, e.g. the `hf_repo` of `hf-qwen3-6-27b-nvfp4` in `config/model-seed.yaml`). Correct fixture values/keys where the live config disagrees; note corrections in your report. If a repo is gated/unreachable, keep the fixture and say so.

- [ ] **Step 4: Implement** `src/radar/models_radar/hf_config.py`:

```python
"""Pure parsers: HF config.json dict → ArchitectureSpec / quant format.

Family coverage: generic transformer keys (Llama/Qwen/Mistral/Gemma/Phi),
DeepSeek MLA (kv_lora_rank), MoE (DeepSeek/Mixtral/Qwen-MoE key variants),
GLM (multi_query_group_num). Unknown layouts degrade to UNKNOWN, never raise.
"""

from __future__ import annotations

from radar.models_radar.entities import ArchitectureSpec, AttentionKind


_QUANT_METHOD_FORMATS = {
    "fp8": "FP8",
    "mxfp4": "MXFP4",
    "awq": "AWQ",
    "gptq": "GPTQ",
}


def parse_architecture(cfg: dict) -> ArchitectureSpec:
    """Extract attention/MoE geometry. Missing keys stay None — never guess."""
    heads = _int(cfg.get("num_attention_heads"))
    kv_heads = _int(cfg.get("num_key_value_heads")) or _int(cfg.get("multi_query_group_num"))
    hidden = _int(cfg.get("hidden_size"))
    head_dim = _int(cfg.get("head_dim"))
    if head_dim is None and heads and hidden:
        head_dim = hidden // heads
    kv_lora_rank = _int(cfg.get("kv_lora_rank"))
    num_experts = (
        _int(cfg.get("n_routed_experts"))
        or _int(cfg.get("num_local_experts"))
        or _int(cfg.get("num_experts"))
    )
    return ArchitectureSpec(
        attention_kind=_attention_kind(cfg, heads, kv_heads, kv_lora_rank),
        num_attention_heads=heads,
        num_key_value_heads=kv_heads,
        head_dim=head_dim,
        kv_lora_rank=kv_lora_rank,
        qk_rope_head_dim=_int(cfg.get("qk_rope_head_dim")),
        num_experts=num_experts,
        experts_per_token=_int(cfg.get("num_experts_per_tok")),
        sliding_window=_int(cfg.get("sliding_window")),
        vocab_size=_int(cfg.get("vocab_size")),
    )


def parse_quant_format(cfg: dict) -> str | None:
    """Canonical quant label when the repo's weights are themselves quantized."""
    qc = cfg.get("quantization_config")
    if not isinstance(qc, dict):
        return None
    method = str(qc.get("quant_method") or "").lower()
    algo = str(qc.get("quant_algo") or "").upper()
    if "NVFP4" in algo or method == "nvfp4":
        return "NVFP4"
    return _QUANT_METHOD_FORMATS.get(method)


def _attention_kind(
    cfg: dict, heads: int | None, kv_heads: int | None, kv_lora_rank: int | None
) -> AttentionKind:
    if kv_lora_rank:
        return AttentionKind.MLA
    layer_types = cfg.get("layer_types")
    if isinstance(layer_types, list) and len(set(layer_types)) > 1:
        return AttentionKind.HYBRID
    if heads and kv_heads:
        return AttentionKind.GQA if kv_heads < heads else AttentionKind.MHA
    return AttentionKind.UNKNOWN


def _int(value: object) -> int | None:
    """Best-effort int: config values may be int, float, numeric str, or junk."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None
```

- [ ] **Step 5: Run tests** — `uv run pytest tests/test_hf_config.py -q` → PASS.

- [ ] **Step 6: Full gates, commit** — `git commit -m "feat: HF config parsers — architecture geometry + repo quant format"`

---

### Task 3: Collector wiring — `HFModelData` carries architecture + quant format

**Files:**
- Modify: `src/radar/models_radar/collectors/huggingface.py`
- Test: `tests/test_models_radar_hf.py` (append)

**Interfaces:**
- Consumes: `parse_architecture`, `parse_quant_format` (Task 2).
- Produces: `HFModelData` gains `architecture: ArchitectureSpec | None = None`, `repo_quant_format: str | None = None`, and `gated: bool = False` (from the HF API meta's `gated` field — it is `false` or a string like `"auto"`/`"manual"`; truthy string ⇒ gated). `fetch_hf_model` populates all three from the already-fetched responses (no extra HTTP call). Existing fields unchanged.

- [ ] **Step 1: Write the failing test** (append to `tests/test_models_radar_hf.py`, reusing that file's existing fake-client pattern — read its head first and mirror the fake that returns meta + config responses):

```python
@pytest.mark.anyio  # match the file's existing async marker convention
async def test_fetch_parses_architecture_and_quant_format():
    # Fake client: meta response minimal; config response GQA + fp8 quant.
    config = {
        "num_hidden_layers": 32, "hidden_size": 4096,
        "num_attention_heads": 32, "num_key_value_heads": 8,
        "max_position_embeddings": 131072,
        "quantization_config": {"quant_method": "fp8"},
    }
    client = _FakeClient(meta={"downloads": 5, "siblings": []}, config=config)
    data = await fetch_hf_model("org/model", client)

    assert data is not None
    assert data.architecture is not None
    assert data.architecture.num_key_value_heads == 8
    assert data.architecture.attention_kind.value == "gqa"
    assert data.repo_quant_format == "FP8"
```

(`_FakeClient` here means the file's existing meta+config fake; if its name differs, use the real one. If none exists, write a minimal two-URL fake matching `HF_MODEL_URL`/`HF_CONFIG_URL` dispatch.)

- [ ] **Step 2: Run to verify failure** — `AttributeError: architecture`.

- [ ] **Step 3: Implement.** In `huggingface.py`: import `from radar.models_radar.entities import ArchitectureSpec` and `from radar.models_radar.hf_config import parse_architecture, parse_quant_format`. Add to `HFModelData`: `architecture: ArchitectureSpec | None = None`, `repo_quant_format: str | None = None`, `gated: bool = False`. In `fetch_hf_model`, inside the config `try` block after the three existing `cfg.get` lines, add `architecture = parse_architecture(cfg)` and `repo_quant_format = parse_quant_format(cfg)` (initialize both to `None` before the `try`); gating comes from the meta response: `gated=bool(meta.get("gated"))` (HF sends `false` or `"auto"`/`"manual"`). Pass all three to the returned `HFModelData`. Extend the Step 1 test with a gated case: a fake meta of `{"gated": "manual", "siblings": []}` must yield `data.gated is True`, and the default fake (no key) `False`.

- [ ] **Step 4: Run tests** — `uv run pytest tests/test_models_radar_hf.py -q` → PASS.

- [ ] **Step 5: Full gates, commit** — `git commit -m "feat: HF collector carries architecture spec and repo quant format"`

---

### Task 4: Assembly v2 — datacenter bits, real quant variant, architecture merge, provenance

**Files:**
- Modify: `src/radar/models_radar/assemble.py`
- Test: `tests/test_models_radar_assemble.py` (append)

**Interfaces:**
- Consumes: Task 1 entities, Task 3 `HFModelData.architecture`/`repo_quant_format`.
- Produces:
  - `_BITS_BY_FORMAT` gains `"fp8": 8.0, "nvfp4": 4.25, "mxfp4": 4.25` (AWQ/GPTQ already present; 4.25 = 4-bit weights + FP8 block scales overhead, documented inline).
  - `build_model_entry(seed, hf, ollama_quants, retrieved_at: str | None = None) -> ModelEntry` — new keyword-only-style trailing param; when the repo itself is quantized (`hf.repo_quant_format`), a real variant `add(hf.repo_quant_format, bits_for_format(hf.repo_quant_format), Platform.GENERIC, f"hf:{seed.hf_repo}")` is added and the synthesized ladder is skipped even if no other quants exist.
  - `merge_architecture(seed_arch: ArchitectureSpec | None, hf_arch: ArchitectureSpec | None) -> tuple[ArchitectureSpec | None, set[str]]` — per-field seed-wins merge; returns the merged spec and the set of field names that came from the seed (for provenance). Module-level function (Task 7's verify command reuses it).
  - Provenance rules (entry.provenance keys): `params_total`, `params_active`, `context_length`, `license` → one entry each with source `"seed"` (url None, verified=seed.spec_verified) or `"hf-api"`/`"hf-config"` (url = `https://huggingface.co/{seed.hf_repo}`, retrieved_at=retrieved_at, verified False), or `"synthesized"`. Architecture: one entry per POPULATED field, key `architecture.<field>`, source per the merge origin.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_models_radar_assemble.py`; reuse the file's existing seed/HF fixture helpers — read its head and mirror):

```python
def test_fp8_repo_gets_real_variant_not_synth_ladder():
    from radar.models_radar.collectors.huggingface import HFModelData

    seed = ModelSeed(id="m-fp8", name="M-FP8", family="M", hf_repo="org/m-fp8")
    hf = HFModelData(params_total=8_000_000_000, repo_quant_format="FP8")
    entry = build_model_entry(seed, hf, [], retrieved_at="2026-07-28")

    formats = [q.format for q in entry.quants]
    assert formats == ["FP8"]                    # no synthesized GGUF/MLX ladder
    assert entry.quants[0].bits_per_weight == 8.0
    assert entry.quants[0].source == "hf:org/m-fp8"


def test_nvfp4_bits():
    from radar.models_radar.assemble import bits_for_format

    assert bits_for_format("NVFP4") == 4.25
    assert bits_for_format("MXFP4") == 4.25
    assert bits_for_format("FP8") == 8.0


def test_architecture_merge_seed_field_wins():
    from radar.models_radar.assemble import merge_architecture
    from radar.models_radar.entities import ArchitectureSpec, AttentionKind

    seed_arch = ArchitectureSpec(num_key_value_heads=4)   # curated correction
    hf_arch = ArchitectureSpec(
        attention_kind=AttentionKind.GQA, num_attention_heads=32,
        num_key_value_heads=8,
    )
    merged, from_seed = merge_architecture(seed_arch, hf_arch)
    assert merged.num_key_value_heads == 4      # seed wins per-field
    assert merged.num_attention_heads == 32     # hf fills the rest
    assert from_seed == {"num_key_value_heads"}


def test_provenance_stamped_per_source():
    from radar.models_radar.collectors.huggingface import HFModelData
    from radar.models_radar.entities import ArchitectureSpec

    seed = ModelSeed(
        id="m-p", name="M-P", family="M", hf_repo="org/m-p",
        params_active=3_000_000_000, spec_verified=True,
    )
    hf = HFModelData(
        params_total=30_000_000_000, context_length=32768,
        architecture=ArchitectureSpec(num_key_value_heads=8, num_attention_heads=32),
    )
    entry = build_model_entry(seed, hf, [], retrieved_at="2026-07-28")

    assert entry.provenance["params_active"].source == "seed"
    assert entry.provenance["params_active"].verified is True
    assert entry.provenance["params_total"].source == "hf-api"
    assert entry.provenance["params_total"].retrieved_at == "2026-07-28"
    assert entry.provenance["params_total"].url == "https://huggingface.co/org/m-p"
    assert entry.provenance["architecture.num_key_value_heads"].source == "hf-config"
    assert entry.architecture.num_key_value_heads == 8
```

- [ ] **Step 2: Run to verify failure.**

- [ ] **Step 3: Implement in `assemble.py`.**

Bits table (`assemble.py:23-27`) — add three entries with a comment:

```python
    # Datacenter formats: fp8 is weight bits; nvfp4/mxfp4 are 4-bit + block
    # scales (~0.25 bit overhead). Matched before "q4" etc. via key order.
    "fp8": 8.0, "nvfp4": 4.25, "mxfp4": 4.25,
```

**Ordering caution:** `bits_for_format` does substring matching over dict order — `"nvfp4"`/`"mxfp4"`/`"fp8"` must be checked BEFORE the generic `"q4"`/`"q8"` keys (e.g. `"fp8"` contains no `q` so it's safe, but `"nvfp4"` must not fall through to the 4.5 default and `"mxfp4"` contains no existing key either — verify with the Step 1 test; if dict order bites, sort candidates longest-key-first inside `bits_for_format`).

`merge_architecture` (new module-level function):

```python
def merge_architecture(
    seed_arch: ArchitectureSpec | None,
    hf_arch: ArchitectureSpec | None,
) -> tuple[ArchitectureSpec | None, set[str]]:
    """Per-field merge, seed wins; returns (merged, fields-that-came-from-seed).

    attention_kind counts as seed-provided only when the seed explicitly set
    it (not the UNKNOWN default).
    """
    if seed_arch is None and hf_arch is None:
        return None, set()
    base = hf_arch or ArchitectureSpec()
    if seed_arch is None:
        return base, set()
    updates: dict[str, object] = {}
    from_seed: set[str] = set()
    for field in ArchitectureSpec.model_fields:
        seed_value = getattr(seed_arch, field)
        if field == "attention_kind":
            if seed_value is not AttentionKind.UNKNOWN:
                updates[field] = seed_value
                from_seed.add(field)
            continue
        if seed_value is not None:
            updates[field] = seed_value
            from_seed.add(field)
    return base.model_copy(update=updates), from_seed
```

(Import `AttentionKind` alongside the other entities imports.)

Gating (spec §5.1 "license + gating"): change the existing openness line to prefer the collected gated flag when the seed doesn't override — `openness = seed.openness or (Openness.GATED if (hf and hf.gated) else openness_from_license(license_))` — and add a test: a seed with no explicit openness + `HFModelData(gated=True, license="llama3.1")` assembles to `Openness.GATED`, while `seed.openness` set explicitly still wins.

In `build_model_entry` — signature becomes `def build_model_entry(seed, hf, ollama_quants, retrieved_at: str | None = None) -> ModelEntry:` (annotate as in the file). After the existing `openness = ...` line add:

```python
    architecture, arch_from_seed = merge_architecture(
        seed.architecture, hf.architecture if hf else None
    )
    hf_url = f"https://huggingface.co/{seed.hf_repo}" if seed.hf_repo else None

    def _prov(from_seed: bool, source_kind: str) -> SpecProvenance:
        if from_seed:
            return SpecProvenance(source="seed", verified=seed.spec_verified)
        return SpecProvenance(
            source=source_kind, url=hf_url, retrieved_at=retrieved_at
        )

    provenance: dict[str, SpecProvenance] = {}
    if params_total is not None:
        provenance["params_total"] = _prov(seed.params_total is not None, "hf-api")
    if seed.params_active is not None:
        provenance["params_active"] = _prov(True, "hf-api")
    if context is not None:
        provenance["context_length"] = _prov(seed.context_length is not None, "hf-config")
    if license_ is not None:
        provenance["license"] = _prov(seed.license is not None, "hf-api")
    if architecture is not None:
        for field in ArchitectureSpec.model_fields:
            value = getattr(architecture, field)
            populated = value is not None and (
                field != "attention_kind" or value is not AttentionKind.UNKNOWN
            )
            if populated:
                provenance[f"architecture.{field}"] = _prov(
                    field in arch_from_seed, "hf-config"
                )
```

Quant handling — after the `if hf:` sibling-formats loop, add:

```python
    if hf and hf.repo_quant_format:
        # The repo's own weights are quantized (FP8/NVFP4/...) — one real
        # variant; never pretend a GGUF ladder exists for these.
        add(
            hf.repo_quant_format,
            bits_for_format(hf.repo_quant_format),
            Platform.GENERIC,
            f"hf:{seed.hf_repo}",
        )
```

and guard the synthesized ladder: `if not quants and params_total is not None:` stays, but it's now unreachable for quantized repos because the real variant was added above (assert via the Step 1 test).

Pass the new fields into the returned `ModelEntry`: `architecture=architecture, provenance=provenance, benchmarks=seed.benchmarks`. Add `SpecProvenance` to the entities import list.

Call-site update: `run_model_scan` (`src/radar/models_radar/scan.py`) passes `retrieved_at` — change its signature to `async def run_model_scan(seeds, client, retrieved_at: str | None = None)` forwarding to `build_model_entry(seed, hf, ollama, retrieved_at=retrieved_at)`, and in `cli.py`'s `models_scan` pass `retrieved_at=datetime.now(UTC).date().isoformat()` (import already present in cli). Grep `run_model_scan(` for other real callers (one test caller was updated in sub-project A — update it the same way or rely on the default).

- [ ] **Step 4: Run tests** — `uv run pytest tests/test_models_radar_assemble.py tests/test_models_radar_scan.py -q` → PASS.

- [ ] **Step 5: Full gates, commit** — `git commit -m "feat: assembly v2 — datacenter quant bits, repo-quant variant, architecture merge, provenance"`

---

### Task 5: Validation v2 — post-assembly gate + provenance advisories

**Files:**
- Modify: `src/radar/models_radar/validate.py`, `src/radar/cli.py` (`models_scan`)
- Test: `tests/test_model_seed_validation.py` (append)

**Interfaces:**
- Consumes: `ModelEntry` (Task 1/4), `minimum_viable_quant` from `radar.models_radar.memory` (existing).
- Produces:
  - `validate_entry(entry: ModelEntry) -> list[str]` — blocking post-assembly problems: params known but min viable memory is None or ≤ 0 (`"<id>: params known but minimum viable memory computed as <value> — spec data implausible"`). This is the sub-project-A deferred `min_memory_gb > 0` check, now possible because it runs after assembly.
  - `entry_advisories(entry: ModelEntry) -> list[str]` — warn-only: (a) `params_total ≥ 70e9` and `entry.architecture is None` → `"<id>: ≥70B model with no architecture data — capacity answers will be wrong"`; (b) any provenance entry missing for a populated `params_total`/`context_length` → `"<id>: <field> has no provenance"`.
  - `cli.py models_scan`: after `run_model_scan` returns entries and before scoring, entries failing `validate_entry` are dropped from scoring (kept in the run stage output with their warnings), printed `[red]QUARANTINED <id>:[/red] ...`; `entry_advisories` printed `[yellow]note:[/yellow] ...`; both merged into the existing `model_validation_warnings` meta list.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_model_seed_validation.py`):

```python
def _entry(**overrides):
    from radar.models_radar.entities import ModelEntry

    base = {"id": "e-1", "name": "E", "family": "F"}
    return ModelEntry(**{**base, **overrides})


def test_entry_with_params_but_no_viable_memory_is_blocking():
    from radar.models_radar.validate import validate_entry

    entry = _entry(params_total=35_000_000_000, quants=[])  # nothing computable
    problems = validate_entry(entry)
    assert any("minimum viable memory" in p for p in problems)


def test_entry_with_computable_memory_passes():
    from radar.models_radar.entities import QuantVariant
    from radar.models_radar.validate import validate_entry

    quant = QuantVariant(format="FP8", bits_per_weight=8.0, est_memory_gb_4k=9.6)
    assert validate_entry(_entry(params_total=8_000_000_000, quants=[quant])) == []


def test_big_model_without_architecture_is_advisory():
    from radar.models_radar.validate import entry_advisories

    advisories = entry_advisories(_entry(params_total=671_000_000_000))
    assert any("no architecture" in a for a in advisories)
    assert entry_advisories(_entry(params_total=8_000_000_000)) == [] or all(
        "no architecture" not in a
        for a in entry_advisories(_entry(params_total=8_000_000_000))
    )


def test_missing_provenance_is_advisory():
    from radar.models_radar.validate import entry_advisories

    advisories = entry_advisories(_entry(params_total=8_000_000_000))
    assert any("no provenance" in a for a in advisories)
```

- [ ] **Step 2: Run to verify failure.**

- [ ] **Step 3: Implement** in `validate.py` (append; keep the existing seed-level functions untouched):

```python
_BIG_MODEL_PARAMS = 70_000_000_000  # ≥70B with no architecture ⇒ D-phase answers wrong


def validate_entry(entry: ModelEntry) -> list[str]:
    """Blocking post-assembly problems; quarantined from scoring like bad seeds."""
    from radar.models_radar.memory import minimum_viable_quant

    problems: list[str] = []
    if entry.params_total is not None:
        mv = minimum_viable_quant(entry.quants)
        memory = mv.est_memory_gb_4k if mv else None
        if memory is None or memory <= 0:
            problems.append(
                f"{entry.id}: params known but minimum viable memory computed "
                f"as {memory} — spec data implausible"
            )
    return problems


def entry_advisories(entry: ModelEntry) -> list[str]:
    """Warn-only data-quality gaps on assembled entries."""
    advisories: list[str] = []
    if (
        entry.params_total is not None
        and entry.params_total >= _BIG_MODEL_PARAMS
        and entry.architecture is None
    ):
        advisories.append(
            f"{entry.id}: ≥70B model with no architecture data — "
            "capacity answers will be wrong"
        )
    for field in ("params_total", "context_length"):
        if getattr(entry, field) is not None and field not in entry.provenance:
            advisories.append(f"{entry.id}: {field} has no provenance")
    return advisories
```

(Import `ModelEntry` in the module's imports.) In `cli.py`'s `models_scan`, after entries are assembled (read the current body — the seed-level quarantine from sub-project A is already there; mirror its structure): partition entries via `validate_entry`, print/collect exactly like the seed gate, extend the same `model_validation_warnings` meta list, and feed only clean entries to `score_entries`/persistence.

- [ ] **Step 4: Run tests** — targeted files, then full gates.

- [ ] **Step 5: Commit** — `git commit -m "feat: post-assembly validation — min-memory gate and architecture/provenance advisories"`

---

### Task 6: Curated seed data — architecture + actives for the datacenter MoE models

**Files:**
- Modify: `config/model-seed.yaml`
- Test: `tests/test_models_radar_seed.py` (append)

**Interfaces:** none new — this is data. The auto-ingest (Tasks 2-4) fills architecture for every model with a reachable `config.json` at scan time; this task curates ONLY what configs can't provide (MoE `params_active`) plus verified architecture for the highest-stakes datacenter models, each number cited.

- [ ] **Step 1: Fetch and verify.** For each of: `hf-deepseek-v4-flash`, `hf-deepseek-v4-pro`, `hf-glm-5-2`, `hf-glm-5-2-nvfp4`, `hf-gpt-oss-120b`, `deepseek-r1`, `deepseek-v3` — `curl -s https://huggingface.co/<hf_repo>/raw/main/config.json` (the `hf_repo` values are in the seed file). Extract: `params_active` (from the model card's "activated params" claim — config.json does NOT carry it; check `curl -s https://huggingface.co/api/models/<repo>` cardData or the README; if only the card README states it, cite that), `kv_lora_rank`, `qk_rope_head_dim`, `num_experts`, `num_experts_per_tok`, kv-heads/heads. If a repo is gated or a number is not stated anywhere authoritative, LEAVE THE FIELD OUT and add a YAML comment `# params_active: not published as of 2026-07-28`.

- [ ] **Step 2: Write the failing test** (append to `tests/test_models_radar_seed.py`):

```python
def test_datacenter_moe_seeds_carry_active_params_or_documented_absence():
    seeds = {s.id: s for s in load_model_seed(_SEED_PATH)}  # reuse file's loader path
    # The two flagship DeepSeek-V4 seeds drove this program — they must carry
    # curated MoE data (or the YAML documents why not, which fails this test
    # deliberately so a human revisits it when the numbers get published).
    for seed_id in ("hf-deepseek-v4-flash", "hf-deepseek-v4-pro"):
        seed = seeds[seed_id]
        assert seed.params_active is not None, f"{seed_id} lacks params_active"
        assert seed.architecture is not None, f"{seed_id} lacks architecture"
        assert seed.architecture.attention_kind.value == "mla"
        assert seed.spec_verified is True
```

Adjust `_SEED_PATH` to however the file already locates `config/model-seed.yaml`. **If Step 1 found that DeepSeek-V4 active-params are genuinely unpublished, replace the assert with the documented-absence form (assert the YAML comment exists) and flag it in your report — do not invent numbers.**

- [ ] **Step 3: Edit the YAML.** For each verified model add (example shape — real numbers from Step 1):

```yaml
  - id: hf-deepseek-v4-pro
    # ... existing fields unchanged ...
    params_active: 32000000000   # model card "37B activated" → https://huggingface.co/deepseek-ai/DeepSeek-V4-Pro (verified 2026-07-28)
    spec_verified: true
    architecture:
      attention_kind: mla
      kv_lora_rank: 512          # config.json (verified 2026-07-28)
      qk_rope_head_dim: 64
      num_experts: 256
      experts_per_token: 8
```

(The numbers above are ILLUSTRATIVE — use only Step-1-verified values; every number gets a source comment with the date.)

- [ ] **Step 4: Run** — `uv run pytest tests/test_models_radar_seed.py tests/test_model_seed_validation.py -q` → PASS (shipped-seed validation must stay green).

- [ ] **Step 5: Full gates, commit** — `git commit -m "feat: curated architecture + active params for datacenter MoE seeds (cited)"`

---

### Task 7: `radar models verify` — drift detection + weekly workflow

**Files:**
- Create: `.github/workflows/spec-verify.yml`
- Modify: `src/radar/cli.py` (new `models verify` command under `models_app`)
- Test: `tests/test_models_radar_cli.py` (append), `tests/test_publish_workflow.py` (append a workflow-content test following its grep-style conventions)

**Interfaces:**
- Consumes: `load_model_seed`, `fetch_hf_model` (Task 3 shape — architecture arrives pre-parsed on `HFModelData`).
- Produces: `radar models verify [--check] [--root .]` — for every enabled seed with an `hf_repo`: fetch fresh HF data, compare collected values against the seed's explicit values for `params_total`, `context_length`, and every populated `architecture` field. A mismatch on a field the seed provides is DRIFT: printed `[red]DRIFT <id>.<field>:[/red] seed=<x> hf=<y>`. Seed values are NEVER modified (spec: drift never silently overwrites a verified manual value). Unreachable repos print `[yellow]skip <id>: <reason>[/yellow]` and never fail the command. `--check` → exit 1 iff any drift on a `spec_verified: true` seed; drift on unverified seeds is report-only either way. No drift, all reachable → prints `OK: <n> seeds verified, no drift`.

- [ ] **Step 1: Write the failing CLI test** (append to `tests/test_models_radar_cli.py`, mirroring its existing monkeypatch style — it monkeypatches scan internals; do the same for the fetcher):

```python
def test_models_verify_reports_drift_and_check_exits_1(tmp_path, monkeypatch):
    import radar.cli as cli_mod
    from radar.models_radar.collectors.huggingface import HFModelData
    from radar.models_radar.entities import ArchitectureSpec

    _write_seed(tmp_path, """
- id: drift-model
  name: Drift-7B
  family: Drift
  hf_repo: org/drift
  params_total: 7000000000
  spec_verified: true
  architecture:
    num_key_value_heads: 8
""")  # reuse/adapt the file's existing seed-writing helper

    async def fake_fetch(repo, client):
        return HFModelData(
            params_total=7_600_000_000,   # drifts from the seed's 7.0B
            architecture=ArchitectureSpec(num_key_value_heads=4),
        )

    monkeypatch.setattr(cli_mod, "_verify_fetch_hf_model", fake_fetch, raising=False)

    result = runner.invoke(app, ["models", "verify", "--root", str(tmp_path)])
    assert result.exit_code == 0                      # report-only without --check
    assert "DRIFT drift-model.params_total" in result.output
    assert "DRIFT drift-model.architecture.num_key_value_heads" in result.output

    checked = runner.invoke(app, ["models", "verify", "--root", str(tmp_path), "--check"])
    assert checked.exit_code == 1                     # verified seed drifted
```

(Adapt helper names — `_write_seed`, `runner`, `app` — to what the file actually uses; the monkeypatch target `_verify_fetch_hf_model` is the indirection you introduce in Step 3 precisely so tests can fake the network.)

- [ ] **Step 2: Run to verify failure** — no such command.

- [ ] **Step 3: Implement** in `cli.py` under `models_app`:

```python
# Module-level indirection so tests can monkeypatch the fetcher without
# touching the collector module (mirrors the models_scan test seam).
from radar.models_radar.collectors.huggingface import fetch_hf_model as _verify_fetch_hf_model


@models_app.command("verify")
def models_verify(
    root: Path = typer.Option(Path("."), help="Project root."),
    check: bool = typer.Option(
        False, "--check", help="Exit 1 on drift in a spec_verified seed."
    ),
) -> None:
    """Diff seed spec numbers against fresh HF data. Never modifies seeds."""
    import asyncio

    import httpx

    from radar.models_radar.entities import ArchitectureSpec
    from radar.models_radar.seed import load_model_seed

    seeds = [
        s for s in load_model_seed(_seed_path(root))  # reuse models_scan's path helper
        if s.enabled and s.hf_repo
    ]

    async def _collect() -> dict[str, object]:
        async with httpx.AsyncClient(timeout=15.0) as client:
            return {s.id: await _verify_fetch_hf_model(s.hf_repo, client) for s in seeds}

    fetched = asyncio.run(_collect())
    drift_verified = 0
    drift_total = 0
    for seed in seeds:
        hf = fetched.get(seed.id)
        if hf is None:
            console.print(f"[yellow]skip {seed.id}: HF unreachable[/yellow]")
            continue
        rows: list[tuple[str, object, object]] = []
        for field in ("params_total", "context_length"):
            seed_value = getattr(seed, field)
            hf_value = getattr(hf, field)
            if seed_value is not None and hf_value is not None and seed_value != hf_value:
                rows.append((field, seed_value, hf_value))
        if seed.architecture is not None and hf.architecture is not None:
            for field in ArchitectureSpec.model_fields:
                if field == "attention_kind":
                    continue  # derived, not a number to drift-check
                seed_value = getattr(seed.architecture, field)
                hf_value = getattr(hf.architecture, field)
                if seed_value is not None and hf_value is not None and seed_value != hf_value:
                    rows.append((f"architecture.{field}", seed_value, hf_value))
        for field, seed_value, hf_value in rows:
            drift_total += 1
            if seed.spec_verified:
                drift_verified += 1
            console.print(
                f"[red]DRIFT {seed.id}.{field}:[/red] seed={seed_value} hf={hf_value}"
            )
    if drift_total == 0:
        console.print(f"OK: {len(seeds)} seeds verified, no drift")
    if check and drift_verified:
        raise typer.Exit(code=1)
```

(Reuse however `models_scan` resolves the seed path — if there is no `_seed_path` helper, inline the same expression it uses. Keep imports consistent with the file's local-import style.)

- [ ] **Step 4: Workflow.** Create `.github/workflows/spec-verify.yml`:

```yaml
name: Verify model specs against HF

on:
  schedule:
    - cron: "0 7 * * 1" # Mondays 07:00 UTC, after the weekend autopilot
  workflow_dispatch: {}

jobs:
  verify:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
      - name: Install uv
        uses: astral-sh/setup-uv@v8.2.0
      - name: Set up Python
        run: uv python install 3.12
      - name: Install package
        run: uv venv && uv pip install -e .
      # A red run IS the drift flag — a human updates the seed (or the model
      # card changed and the seed is right; either way, eyes on it).
      - name: Verify specs
        run: uv run radar models verify --root . --check
```

Append to `tests/test_publish_workflow.py` (its grep-style convention):

```python
def test_spec_verify_workflow_runs_check():
    text = (_REPO_ROOT / ".github" / "workflows" / "spec-verify.yml").read_text()
    assert "radar models verify --root . --check" in text
    assert "schedule:" in text
```

(Adapt `_REPO_ROOT` to the file's existing path constant.)

- [ ] **Step 5: Run tests, full gates, commit** — `git commit -m "feat: radar models verify — weekly HF spec-drift detection, seeds never overwritten"`

---

### Task 8: Surfaces — architecture, benchmarks, provenance markers on model pages + MCP

**Files:**
- Modify: `src/radar/web/templates/_model_detail.html`, `src/radar/mcp_server/model_queries.py:72-90` (`get_model`)
- Test: `tests/test_models_radar_reports.py` or `tests/test_web.py` + `tests/test_static_site.py` (append — read where `_model_detail.html` rendering is already asserted and extend THERE; grep `_model_detail` in tests/ first), `tests/test_model_queries.py` (append)

**Interfaces:**
- Consumes: `ModelEntry.architecture/provenance/benchmarks` (Tasks 1/4).
- Produces:
  - Model detail page: an "Architecture" spec row block (attention kind badge; kv heads / head_dim; MoE experts ("256 experts, 8 active"); MLA dims when present), a "Benchmarks (curated)" list with source links, and an "unverified" marker (`<em class="prov-unverified">unverified</em>`) next to params when `provenance["params_total"].verified` is false or missing. All blocks render only when data exists — pages for old entries without v2 fields are unchanged.
  - MCP `get_model` response gains `architecture` (dict or None), `benchmarks` (list), `provenance` (dict) — via `model_dump(mode="json")` of the fields; verify how `get_model` currently shapes its payload (`model_queries.py:72-90`) and extend consistently.

- [ ] **Step 1: Write the failing tests.** First `grep -rn "_model_detail\|Architecture" tests/ | head` to find the existing model-page rendering test; append there:

```python
def test_model_page_renders_architecture_and_benchmarks():
    # Build an entry via the test file's existing entry/context helper with:
    # architecture=ArchitectureSpec(attention_kind=AttentionKind.MLA,
    #     kv_lora_rank=512, num_experts=256, experts_per_token=8),
    # benchmarks=[BenchmarkScore(name="MMLU-Pro", score=0.81,
    #     source_url="https://example.com/card")],
    # provenance={} (no params provenance -> unverified marker shows)
    html = _render_model_detail(entry)          # the file's existing render path
    assert "mla" in html.lower()
    assert "256 experts, 8 active" in html
    assert "MMLU-Pro" in html
    assert "unverified" in html
```

and to `tests/test_model_queries.py`:

```python
def test_get_model_exposes_architecture_and_provenance(tmp_path):
    # Use the file's existing persisted-run fixture; assert the payload for a
    # model whose entry carries architecture/provenance:
    payload = get_model(root, "m-arch")
    assert payload["architecture"]["kv_lora_rank"] == 512
    assert payload["provenance"]["params_total"]["source"] == "seed"
```

(These sketches MUST be adapted to the real helpers in each test file — read them first; the assertions are the contract, the plumbing follows the file's conventions.)

- [ ] **Step 2: Run to verify failure.**

- [ ] **Step 3: Implement.** `_model_detail.html` — add after the existing spec rows (match the template's row/dl markup exactly; read the surrounding block):

```html
{% if model.architecture %}
<h3>Architecture</h3>
<table class="table-wrap-inner"><tbody>
  <tr><th>Attention</th><td>{{ model.architecture.attention_kind.value }}</td></tr>
  {% if model.architecture.num_key_value_heads %}
  <tr><th>KV heads</th><td>{{ model.architecture.num_key_value_heads }}
    {%- if model.architecture.num_attention_heads %} / {{ model.architecture.num_attention_heads }} heads{% endif %}</td></tr>
  {% endif %}
  {% if model.architecture.kv_lora_rank %}
  <tr><th>MLA</th><td>kv_lora_rank {{ model.architecture.kv_lora_rank }}{% if model.architecture.qk_rope_head_dim %}, rope {{ model.architecture.qk_rope_head_dim }}{% endif %}</td></tr>
  {% endif %}
  {% if model.architecture.num_experts %}
  <tr><th>MoE</th><td>{{ model.architecture.num_experts }} experts, {{ model.architecture.experts_per_token or "?" }} active</td></tr>
  {% endif %}
</tbody></table>
{% endif %}
{% if model.benchmarks %}
<h3>Benchmarks (curated)</h3>
<ul>{% for b in model.benchmarks %}
  <li>{{ b.name }}: {{ b.score }} <a href="{{ b.source_url }}">source ↗</a></li>
{% endfor %}</ul>
{% endif %}
```

(Adjust tag/class structure to the template's existing conventions — the table-wrap hygiene rules from the 2026-07-08 cleanup apply: heading OUTSIDE the wrap div. The "unverified" marker goes next to the existing params row: `{% if not (model.provenance.get("params_total") and model.provenance["params_total"].verified) %}<em class="prov-unverified" title="number not human-verified">unverified</em>{% endif %}` — check how the template accesses dict fields; if entries are pydantic objects in Jinja, `.get` works on the dict field directly.)

`model_queries.py` `get_model` — add to the payload dict:

```python
        "architecture": (
            entry.architecture.model_dump(mode="json") if entry.architecture else None
        ),
        "benchmarks": [b.model_dump(mode="json") for b in entry.benchmarks],
        "provenance": {
            key: p.model_dump(mode="json") for key, p in entry.provenance.items()
        },
```

- [ ] **Step 4: Run tests** — targeted, then static-site parity if the static export renders the same partial (grep `_model_detail` in `static_site.py`; if shared, one test covers both).

- [ ] **Step 5: Full gates, commit** — `git commit -m "feat: architecture, benchmarks, and provenance markers on model pages + MCP"`

---

## Final verification (whole sub-project)

- [ ] `uv run pytest -q && uv run ruff check . && uv run mypy src` — all green.
- [ ] Live smoke (network): `uv run radar models scan --root .` → entries for models with reachable configs now carry `architecture` (spot-check `deepseek-v3` shows `attention_kind: mla` and the NVFP4 seeds show a single real NVFP4 variant instead of a GGUF ladder); QUARANTINED/note lines behave.
- [ ] `uv run radar models verify --root .` → runs against live HF; no drift on the Task 6 curated numbers (or explainable drift, documented).
- [ ] The A-era model pages still render for entries without v2 fields (old persisted run).
- [ ] Use superpowers:requesting-code-review flow (subagent-driven per-task reviews + final whole-branch review); merge via PR per repo convention — **verify checks are green before merging** (see 2026-07-28 lesson in project memory).
