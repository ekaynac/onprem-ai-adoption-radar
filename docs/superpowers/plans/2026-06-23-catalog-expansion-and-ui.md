# Catalog Expansion + Styled Model Pages Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Broaden the local-model radar from a narrow prototype (19 devices, 8 models, unstyled model pages) into a comprehensive, well-presented catalog — more GPUs, more models with richer metadata, more accurate quant/memory data, and model pages that share the dashboard's visual shell with filter/sort UX.

**Architecture:** Pure data + presentation expansion on the existing deterministic pipeline. No new subsystems. Device presets grow in `models_radar/devices.py`; the model catalog grows in `config/model-seed.yaml`; `ModelEntry`/`ModelSeed` gain two metadata fields; `assemble.py` enriches the synthesized quant ladder; the bare `static_models.html`/`static_model.html` templates adopt the same `_base_styles`/`_hero`/`_footer` shell as `static_index.html`, plus a client-side filter mirroring `_filter_bar.html`/`_filter_script.html`.

**Tech Stack:** Python 3.12, pydantic v2 (frozen models), Jinja2, YAML seed config, framework-free vanilla JS, pytest/ruff/mypy.

## Global Constraints

- Python ≥ 3.12; new modules begin with `from __future__ import annotations`; NO new third-party dependencies; deterministic core, no LLM.
- Immutability: `DeviceProfile`/`ModelEntry`/`ModelSeed`/`QuantVariant` stay frozen pydantic models; build new objects, never mutate.
- Reuse existing helpers (`usable_memory_gb`, `estimate_memory_gb`, `minimum_viable_quant`, `bits_for_format`, `_gpu`/`_mac`, `picker_context`, `fit_by_tier`, the `_base_styles`/`_hero`/`_footer` partials). Do NOT re-derive memory math or duplicate the shell.
- Single source of truth preserved: usable fractions + presets injected from Python (already done); the new filter JS is framework-free and reads injected/`data-*` values only.
- Hardware and model specs MUST be accurate (real VRAM, real param counts, real context windows, real licenses). When unsure, omit a field rather than guess.
- `COMMON_DEVICE_TIERS` keys must always exist in `DEVICE_PRESETS`.
- Brand kit / corporate identity is never committed; only the existing web logo/font assets under `static/brand` belong in the repo.
- ruff + mypy clean; coverage ≥ 80%; full gate (`ruff check src tests && mypy src && pytest -q`) before every commit; commit on the current branch only.

---

### Task 1: Richer model metadata schema

**Files:**
- Modify: `src/radar/models_radar/entities.py`
- Modify: `src/radar/models_radar/assemble.py`
- Test: `tests/test_models_radar_assemble.py`

**Interfaces:**
- Produces: `ModelEntry.release_date: str | None`, `ModelEntry.use_case: str | None`; `ModelSeed.release_date: str | None`, `ModelSeed.use_case: str | None`. `build_model_entry` carries both from the seed (curated, not collected).

- [ ] **Step 1: Add fields to both models.** In `entities.py`, add to `ModelEntry` (after `last_modified`) and `ModelSeed` (after `openness`):

```python
    release_date: str | None = None   # ISO date "YYYY-MM" or "YYYY-MM-DD"
    use_case: str | None = None        # short note, e.g. "reasoning", "coding", "general chat"
```

- [ ] **Step 2: Write the failing test** in `tests/test_models_radar_assemble.py`:

```python
def test_build_carries_release_date_and_use_case():
    seed = ModelSeed(id="x", name="X", family="F", params_total=8_000_000_000,
                     release_date="2025-01", use_case="reasoning")
    m = build_model_entry(seed, None, [])
    assert m.release_date == "2025-01" and m.use_case == "reasoning"
```

- [ ] **Step 3: Carry the fields in `build_model_entry`.** In the `ModelEntry(...)` return in `assemble.py`, add:

```python
        release_date=seed.release_date,
        use_case=seed.use_case,
```

- [ ] **Step 4: Run gate** (`ruff check src tests && mypy src && pytest -q`) → green. Commit.

---

### Task 2: Comprehensive device presets (~45)

**Files:**
- Modify: `src/radar/models_radar/devices.py`
- Test: `tests/test_devices.py`

**Interfaces:**
- Consumes: `_gpu(name, gb, count=1)`, `_mac(name, gb)`, `DeviceProfile`, `usable_memory_gb`.
- Produces: an expanded `DEVICE_PRESETS` dict. `COMMON_DEVICE_TIERS` unchanged (its 6 keys already exist and remain).

- [ ] **Step 1: Add a CPU helper** next to `_gpu`/`_mac` in `devices.py`:

```python
def _cpu(name: str, gb: float) -> DeviceProfile:
    return DeviceProfile(name=name, kind="cpu", total_memory_gb=gb)
```

- [ ] **Step 2: Replace `DEVICE_PRESETS`** with the comprehensive set below (keep every existing key + value; add the rest). Use real VRAM. Order: consumer GPU, pro/workstation GPU, datacenter GPU, AMD, multi-GPU rigs, Apple unified, CPU/RAM.

```python
DEVICE_PRESETS: dict[str, DeviceProfile] = {
    # Consumer NVIDIA
    "rtx-3060-12gb": _gpu("RTX 3060 (12GB)", 12),
    "rtx-3080-10gb": _gpu("RTX 3080 (10GB)", 10),
    "rtx-3090-24gb": _gpu("RTX 3090 (24GB)", 24),
    "rtx-4060-8gb": _gpu("RTX 4060 (8GB)", 8),
    "rtx-4060-ti-16gb": _gpu("RTX 4060 Ti (16GB)", 16),
    "rtx-4070-12gb": _gpu("RTX 4070 (12GB)", 12),
    "rtx-4070-ti-super-16gb": _gpu("RTX 4070 Ti Super (16GB)", 16),
    "rtx-4080-16gb": _gpu("RTX 4080 (16GB)", 16),
    "rtx-4090-24gb": _gpu("RTX 4090 (24GB)", 24),
    "rtx-5070-12gb": _gpu("RTX 5070 (12GB)", 12),
    "rtx-5070-ti-16gb": _gpu("RTX 5070 Ti (16GB)", 16),
    "rtx-5080-16gb": _gpu("RTX 5080 (16GB)", 16),
    "rtx-5090-32gb": _gpu("RTX 5090 (32GB)", 32),
    # Pro / workstation NVIDIA
    "rtx-a6000-48gb": _gpu("RTX A6000 (48GB)", 48),
    "rtx-6000-ada-48gb": _gpu("RTX 6000 Ada (48GB)", 48),
    "a10-24gb": _gpu("A10 (24GB)", 24),
    "a40-48gb": _gpu("A40 (48GB)", 48),
    "l4-24gb": _gpu("L4 (24GB)", 24),
    "l40s-48gb": _gpu("L40S (48GB)", 48),
    "t4-16gb": _gpu("T4 (16GB)", 16),
    "v100-32gb": _gpu("V100 (32GB)", 32),
    # Datacenter NVIDIA
    "a100-40gb": _gpu("A100 (40GB)", 40),
    "a100-80gb": _gpu("A100 (80GB)", 80),
    "h100-80gb": _gpu("H100 (80GB)", 80),
    "h100-nvl-94gb": _gpu("H100 NVL (94GB)", 94),
    "h200-141gb": _gpu("H200 (141GB)", 141),
    "gh200-96gb": _gpu("GH200 (96GB)", 96),
    "b200-192gb": _gpu("B200 (192GB)", 192),
    # AMD
    "mi210-64gb": _gpu("MI210 (64GB)", 64),
    "mi250-128gb": _gpu("MI250 (128GB)", 128),
    "mi300x-192gb": _gpu("MI300X (192GB)", 192),
    # Multi-GPU rigs
    "2x-rtx-4090-24gb": _gpu("2x RTX 4090 (24GB)", 24, count=2),
    "4x-rtx-4090-24gb": _gpu("4x RTX 4090 (24GB)", 24, count=4),
    "2x-a100-80gb": _gpu("2x A100 (80GB)", 80, count=2),
    "4x-a100-80gb": _gpu("4x A100 (80GB)", 80, count=4),
    "8x-h100-80gb": _gpu("8x H100 (80GB)", 80, count=8),
    # Apple unified memory
    "mac-16gb": _mac("Mac (16GB unified)", 16),
    "mac-24gb": _mac("Mac (24GB unified)", 24),
    "mac-32gb": _mac("Mac (32GB unified)", 32),
    "mac-48gb": _mac("Mac (48GB unified)", 48),
    "mac-64gb": _mac("Mac (64GB unified)", 64),
    "mac-96gb": _mac("Mac (96GB unified)", 96),
    "mac-128gb": _mac("Mac (128GB unified)", 128),
    "mac-192gb": _mac("Mac (192GB unified)", 192),
    "mac-256gb": _mac("Mac Studio (256GB unified)", 256),
    "mac-512gb": _mac("Mac Studio (512GB unified)", 512),
    # CPU / system RAM
    "laptop-16gb-cpu": _cpu("Laptop (16GB, no GPU)", 16),
    "workstation-64gb-cpu": _cpu("Workstation (64GB RAM, no GPU)", 64),
    "server-256gb-cpu": _cpu("Server (256GB RAM, no GPU)", 256),
}
```

- [ ] **Step 2b:** Confirm `laptop-16gb-cpu` now uses `_cpu(...)` (behaviorally identical to the old inline `DeviceProfile`). `COMMON_DEVICE_TIERS` stays exactly as-is.

- [ ] **Step 3: Add tests** to `tests/test_devices.py`:

```python
def test_expanded_presets_resolve_and_count():
    assert len(DEVICE_PRESETS) >= 45
    # spot-check new kinds + usable math
    assert usable_memory_gb(DEVICE_PRESETS["rtx-3090-24gb"]) == 20.4
    assert usable_memory_gb(DEVICE_PRESETS["8x-h100-80gb"]) == round(80 * 0.85 * 8, 2)
    assert usable_memory_gb(DEVICE_PRESETS["mac-96gb"]) == round(96 * 0.72, 2)
    assert usable_memory_gb(DEVICE_PRESETS["server-256gb-cpu"]) == round(256 * 0.5, 2)


def test_common_tiers_all_present():
    from radar.models_radar.devices import COMMON_DEVICE_TIERS
    assert all(k in DEVICE_PRESETS for k in COMMON_DEVICE_TIERS)
```

(Match whatever import style `tests/test_devices.py` already uses.)

- [ ] **Step 4: Run gate** → green. Commit.

---

### Task 3: Comprehensive model catalog (~26 seeds) with metadata

**Files:**
- Modify: `config/model-seed.yaml`
- Test: `tests/test_models_radar_seed.py` (or wherever `load_model_seed` is tested; create a small test if none asserts the catalog)

**Interfaces:**
- Consumes: `load_model_seed`, the `ModelSeed` schema (incl. the new `release_date`/`use_case` from Task 1, and existing `params_total`/`params_active`/`context_length`/`license`/`openness`/`modality`/`backer`).
- Produces: an expanded seed file. Every existing seed stays; new ones added.

- [ ] **Step 1: Keep the 8 existing seeds**, then append the families below. Fill `params_total`, `params_active` (MoE only), `context_length`, `license`, `openness`, `release_date`, `use_case`, `hf_repo`, and `ollama_name` where a real Ollama tag exists. Openness mapping: Apache/MIT → `open-permissive`; Llama/Gemma/Qwen-72B/Yi → `open-restricted`; Cohere CC-BY-NC → `open-restricted`; gated HF → `gated`. Backer types reuse the existing enum (`big_tech`, `startup`, `community`, etc. — match what `Backer` accepts).

```yaml
  - id: llama-3.3-70b
    name: Llama 3.3 70B Instruct
    family: Llama
    hf_repo: meta-llama/Llama-3.3-70B-Instruct
    ollama_name: llama3.3
    backer: {name: "Meta", type: big_tech}
    params_total: 70000000000
    context_length: 131072
    license: llama-3.3
    openness: open-restricted
    release_date: "2024-12"
    use_case: general chat, instruction following

  - id: llama-3.1-70b
    name: Llama 3.1 70B Instruct
    family: Llama
    hf_repo: meta-llama/Llama-3.1-70B-Instruct
    ollama_name: llama3.1
    backer: {name: "Meta", type: big_tech}
    params_total: 70000000000
    context_length: 131072
    license: llama-3.1
    openness: open-restricted
    release_date: "2024-07"
    use_case: general chat

  - id: qwen2.5-7b
    name: Qwen2.5 7B Instruct
    family: Qwen2.5
    hf_repo: Qwen/Qwen2.5-7B-Instruct
    ollama_name: qwen2.5
    backer: {name: "Alibaba", type: big_tech}
    params_total: 7600000000
    context_length: 131072
    license: apache-2.0
    openness: open-permissive
    release_date: "2024-09"
    use_case: general chat

  - id: qwen2.5-14b
    name: Qwen2.5 14B Instruct
    family: Qwen2.5
    hf_repo: Qwen/Qwen2.5-14B-Instruct
    ollama_name: qwen2.5
    backer: {name: "Alibaba", type: big_tech}
    params_total: 14700000000
    context_length: 131072
    license: apache-2.0
    openness: open-permissive
    release_date: "2024-09"
    use_case: general chat

  - id: qwen2.5-32b
    name: Qwen2.5 32B Instruct
    family: Qwen2.5
    hf_repo: Qwen/Qwen2.5-32B-Instruct
    ollama_name: qwen2.5
    backer: {name: "Alibaba", type: big_tech}
    params_total: 32500000000
    context_length: 131072
    license: apache-2.0
    openness: open-permissive
    release_date: "2024-09"
    use_case: general chat

  - id: qwen2.5-72b
    name: Qwen2.5 72B Instruct
    family: Qwen2.5
    hf_repo: Qwen/Qwen2.5-72B-Instruct
    ollama_name: qwen2.5
    backer: {name: "Alibaba", type: big_tech}
    params_total: 72700000000
    context_length: 131072
    license: qwen
    openness: open-restricted
    release_date: "2024-09"
    use_case: general chat, high capability

  - id: qwen2.5-coder-7b
    name: Qwen2.5-Coder 7B
    family: Qwen2.5-Coder
    hf_repo: Qwen/Qwen2.5-Coder-7B-Instruct
    ollama_name: qwen2.5-coder
    backer: {name: "Alibaba", type: big_tech}
    params_total: 7600000000
    context_length: 131072
    license: apache-2.0
    openness: open-permissive
    release_date: "2024-11"
    use_case: coding

  - id: qwen2.5-coder-32b
    name: Qwen2.5-Coder 32B
    family: Qwen2.5-Coder
    hf_repo: Qwen/Qwen2.5-Coder-32B-Instruct
    ollama_name: qwen2.5-coder
    backer: {name: "Alibaba", type: big_tech}
    params_total: 32500000000
    context_length: 131072
    license: apache-2.0
    openness: open-permissive
    release_date: "2024-11"
    use_case: coding

  - id: qwen3-32b
    name: Qwen3 32B
    family: Qwen3
    hf_repo: Qwen/Qwen3-32B
    ollama_name: qwen3
    backer: {name: "Alibaba", type: big_tech}
    params_total: 32800000000
    context_length: 40960
    license: apache-2.0
    openness: open-permissive
    release_date: "2025-04"
    use_case: reasoning, general chat

  - id: qwen3-14b
    name: Qwen3 14B
    family: Qwen3
    hf_repo: Qwen/Qwen3-14B
    ollama_name: qwen3
    backer: {name: "Alibaba", type: big_tech}
    params_total: 14800000000
    context_length: 40960
    license: apache-2.0
    openness: open-permissive
    release_date: "2025-04"
    use_case: reasoning, general chat

  - id: mixtral-8x7b
    name: Mixtral 8x7B Instruct
    family: Mixtral
    hf_repo: mistralai/Mixtral-8x7B-Instruct-v0.1
    ollama_name: mixtral
    backer: {name: "Mistral AI", type: startup}
    params_total: 46700000000
    params_active: 12900000000
    context_length: 32768
    license: apache-2.0
    openness: open-permissive
    release_date: "2023-12"
    use_case: general chat (MoE)

  - id: mixtral-8x22b
    name: Mixtral 8x22B Instruct
    family: Mixtral
    hf_repo: mistralai/Mixtral-8x22B-Instruct-v0.1
    ollama_name: mixtral
    backer: {name: "Mistral AI", type: startup}
    params_total: 141000000000
    params_active: 39000000000
    context_length: 65536
    license: apache-2.0
    openness: open-permissive
    release_date: "2024-04"
    use_case: high capability (MoE)

  - id: mistral-nemo-12b
    name: Mistral Nemo 12B
    family: Mistral
    hf_repo: mistralai/Mistral-Nemo-Instruct-2407
    ollama_name: mistral-nemo
    backer: {name: "Mistral AI", type: startup}
    params_total: 12200000000
    context_length: 131072
    license: apache-2.0
    openness: open-permissive
    release_date: "2024-07"
    use_case: general chat, long context

  - id: deepseek-r1
    name: DeepSeek-R1
    family: DeepSeek
    hf_repo: deepseek-ai/DeepSeek-R1
    ollama_name: deepseek-r1
    backer: {name: "DeepSeek", type: startup}
    params_total: 671000000000
    params_active: 37000000000
    context_length: 163840
    license: mit
    openness: open-permissive
    release_date: "2025-01"
    use_case: reasoning (MoE)

  - id: deepseek-v3
    name: DeepSeek-V3
    family: DeepSeek
    hf_repo: deepseek-ai/DeepSeek-V3
    ollama_name: deepseek-v3
    backer: {name: "DeepSeek", type: startup}
    params_total: 671000000000
    params_active: 37000000000
    context_length: 131072
    license: deepseek
    openness: open-restricted
    release_date: "2024-12"
    use_case: general chat, high capability (MoE)

  - id: command-r-35b
    name: Command R 35B
    family: Command-R
    hf_repo: CohereForAI/c4ai-command-r-v01
    ollama_name: command-r
    backer: {name: "Cohere", type: startup}
    params_total: 35000000000
    context_length: 131072
    license: cc-by-nc-4.0
    openness: open-restricted
    release_date: "2024-03"
    use_case: RAG, tool use

  - id: command-r-plus-104b
    name: Command R+ 104B
    family: Command-R
    hf_repo: CohereForAI/c4ai-command-r-plus
    ollama_name: command-r-plus
    backer: {name: "Cohere", type: startup}
    params_total: 104000000000
    context_length: 131072
    license: cc-by-nc-4.0
    openness: open-restricted
    release_date: "2024-04"
    use_case: RAG, tool use, high capability

  - id: gemma-2-9b
    name: Gemma 2 9B
    family: Gemma
    hf_repo: google/gemma-2-9b-it
    ollama_name: gemma2
    backer: {name: "Google", type: big_tech}
    params_total: 9200000000
    context_length: 8192
    license: gemma
    openness: gated
    release_date: "2024-06"
    use_case: general chat

  - id: gemma-2-27b
    name: Gemma 2 27B
    family: Gemma
    hf_repo: google/gemma-2-27b-it
    ollama_name: gemma2
    backer: {name: "Google", type: big_tech}
    params_total: 27200000000
    context_length: 8192
    license: gemma
    openness: gated
    release_date: "2024-06"
    use_case: general chat

  - id: yi-1.5-34b
    name: Yi 1.5 34B Chat
    family: Yi
    hf_repo: 01-ai/Yi-1.5-34B-Chat
    ollama_name: yi
    backer: {name: "01.AI", type: startup}
    params_total: 34000000000
    context_length: 32768
    license: apache-2.0
    openness: open-permissive
    release_date: "2024-05"
    use_case: general chat

  - id: granite-3-8b
    name: Granite 3.1 8B Instruct
    family: Granite
    hf_repo: ibm-granite/granite-3.1-8b-instruct
    ollama_name: granite3.1-dense
    backer: {name: "IBM", type: big_tech}
    params_total: 8200000000
    context_length: 131072
    license: apache-2.0
    openness: open-permissive
    release_date: "2024-12"
    use_case: enterprise, tool use

  - id: qwq-32b
    name: QwQ 32B
    family: Qwen
    hf_repo: Qwen/QwQ-32B
    ollama_name: qwq
    backer: {name: "Alibaba", type: big_tech}
    params_total: 32500000000
    context_length: 131072
    license: apache-2.0
    openness: open-permissive
    release_date: "2025-03"
    use_case: reasoning

  - id: starcoder2-15b
    name: StarCoder2 15B
    family: StarCoder
    hf_repo: bigcode/starcoder2-15b
    ollama_name: starcoder2
    backer: {name: "BigCode", type: community}
    params_total: 16000000000
    context_length: 16384
    license: bigcode-openrail-m
    openness: open-restricted
    release_date: "2024-02"
    use_case: coding

  - id: phi-3.5-mini
    name: Phi-3.5-mini Instruct
    family: Phi
    hf_repo: microsoft/Phi-3.5-mini-instruct
    ollama_name: phi3.5
    backer: {name: "Microsoft", type: big_tech}
    params_total: 3800000000
    context_length: 131072
    license: mit
    openness: open-permissive
    release_date: "2024-08"
    use_case: small, on-device

  - id: smollm2-1.7b
    name: SmolLM2 1.7B Instruct
    family: SmolLM
    hf_repo: HuggingFaceTB/SmolLM2-1.7B-Instruct
    ollama_name: smollm2
    backer: {name: "Hugging Face", type: community}
    params_total: 1700000000
    context_length: 8192
    license: apache-2.0
    openness: open-permissive
    release_date: "2024-11"
    use_case: small, on-device
```

- [ ] **Step 2: Verify the catalog loads.** Add/extend a test in `tests/test_models_radar_seed.py`:

```python
def test_seed_catalog_is_comprehensive_and_valid():
    from pathlib import Path
    from radar.models_radar.seed import load_model_seed
    seeds = load_model_seed(Path("config/model-seed.yaml"))
    assert len(seeds) >= 26
    ids = [s.id for s in seeds]
    assert len(ids) == len(set(ids)), "seed ids must be unique"
    # MoE seeds carry active params
    moe = {s.id: s for s in seeds if s.id in ("mixtral-8x7b", "deepseek-r1")}
    assert all(s.params_active and s.params_active < s.params_total for s in moe.values())
```

(If `load_model_seed` lives elsewhere, import it from the right module — check `src/radar/models_radar/seed.py`.)

- [ ] **Step 3: Run gate** → green. Then a real smoke: `radar models scan --root .` must succeed (best-effort per model; gated 401s are fine) and `radar models list` shows the larger catalog. Commit.

---

### Task 4: Quant-ladder accuracy (MLX + richer synthesized ladder)

**Files:**
- Modify: `src/radar/models_radar/assemble.py`
- Test: `tests/test_models_radar_assemble.py`

**Interfaces:**
- Consumes: `Platform.APPLE_MLX`, `bits_for_format`, `estimate_memory_gb`, the existing `add(fmt, bits, platform, source, size_gb=None)` closure.
- Produces: a broader synthesized quant ladder so a model with no collected quants still surfaces realistic GGUF *and* Apple MLX options.

- [ ] **Step 1: Write the failing test:**

```python
def test_synthesized_ladder_includes_mlx_and_q6():
    seed = ModelSeed(id="x", name="X", family="F", params_total=8_000_000_000,
                     num_layers=32, hidden_size=4096, context_length=4096)
    m = build_model_entry(seed, None, [])
    formats = {q.format for q in m.quants}
    assert {"Q4_K_M", "Q6_K", "Q8_0", "FP16"} <= formats
    assert any(q.platform == Platform.APPLE_MLX for q in m.quants)
    assert {"MLX-4bit", "MLX-8bit"} <= formats
```

(Add `Platform` to the test imports.)

- [ ] **Step 2: Broaden the ladder.** Replace `_DEFAULT_QUANT_LADDER` and its use. Define both a GGUF ladder and an Apple-MLX ladder:

```python
# Synthesized when no quants are collected: realistic GGUF options + Apple MLX.
_DEFAULT_QUANT_LADDER = [("Q4_K_M", 4.5), ("Q5_K_M", 5.5), ("Q6_K", 6.6), ("Q8_0", 8.0), ("FP16", 16.0)]
_DEFAULT_MLX_LADDER = [("MLX-4bit", 4.5), ("MLX-8bit", 8.0)]
```

In `build_model_entry`, where the synthesized fallback runs, add the MLX variants alongside the GGUF ones:

```python
    if not quants and params_total is not None:
        for fmt, bits in _DEFAULT_QUANT_LADDER:
            add(fmt, bits, Platform.GENERIC, "synthesized")
        for fmt, bits in _DEFAULT_MLX_LADDER:
            add(fmt, bits, Platform.APPLE_MLX, "synthesized")
```

- [ ] **Step 3: Run gate** → green. Verify `minimum_viable_quant`/`hardware_tier` still pick the Q4-class entry (lowest viable bits) so tiers don't regress. Commit.

---

### Task 5: Style the model pages + filter/sort UX + surfaced metadata

**Files:**
- Modify: `src/radar/web/templates/static_models.html` (full rewrite to the shell)
- Modify: `src/radar/web/templates/static_model.html` (full rewrite to the shell)
- Modify: `src/radar/web/templates/models.html` (live — match static)
- Modify: `src/radar/web/templates/model.html` (live — match static)
- Modify: `src/radar/web/templates/_model_detail.html` (surface metadata)
- Modify: `src/radar/web/templates/_device_picker.html` (group options by kind)
- Create: `src/radar/web/templates/_models_filter_bar.html`
- Create: `src/radar/web/templates/_models_filter_script.html`
- Modify: `src/radar/web/templates/static_index.html` + `src/radar/web/templates/index.html` (add a "Models" nav link)
- Test: `tests/test_static_site.py`, `tests/test_device_picker.py`, `tests/test_web.py`

**Interfaces:**
- Consumes: `_base_styles.html`, `_hero.html` (needs `page_title`, `tagline`, `nav` set vars + `asset_base` env global — already provided), `_footer.html`, `picker_context()`, `fit_by_tier`, `slug_by_model`, `models`. The dashboard table classes (`ring-pill ring-<ring>`, `.container`, `.filter-bar`) come from `_base_styles.html`.
- Produces: styled `models.html`/`model_*.html`; a reusable models filter; grouped device picker. The fit-coloring CSS already in `_device_picker.html` stays.

- [ ] **Step 1: Create `_models_filter_bar.html`** (mirror `_filter_bar.html`; options derived from `models`):

```html
{# Client-side filter for #models-table. Context: models. Progressive enhancement. #}
<div class="filter-bar">
  <input id="mfilter-text" type="text" placeholder="Search models…"
         oninput="modelsFilter()" aria-label="Search models">
  <select id="mfilter-family" onchange="modelsFilter()" aria-label="Filter by family">
    <option value="">All families</option>
    {% for fam in models | map(attribute='family') | unique | sort %}
    <option value="{{ fam }}">{{ fam }}</option>
    {% endfor %}
  </select>
  <select id="mfilter-ring" onchange="modelsFilter()" aria-label="Filter by ring">
    <option value="">Any ring</option>
    {% for r in models | selectattr('ring') | map(attribute='ring.value') | unique | sort %}
    <option value="{{ r }}">{{ r }}</option>
    {% endfor %}
  </select>
  <select id="mfilter-tier" onchange="modelsFilter()" aria-label="Filter by hardware tier">
    <option value="">Any tier</option>
    {% for t in models | map(attribute='hardware_tier.value') | unique | sort %}
    <option value="{{ t }}">{{ t }}</option>
    {% endfor %}
  </select>
</div>
```

- [ ] **Step 2: Create `_models_filter_script.html`** (mirror `_filter_script.html`, matching on `data-*`):

```html
{# Dependency-free filter for #models-table. Matches on data-* attributes. #}
<script>
  function modelsFilter() {
    var text = (document.getElementById('mfilter-text').value || '').toLowerCase();
    var fam = document.getElementById('mfilter-family').value || '';
    var ring = document.getElementById('mfilter-ring').value || '';
    var tier = document.getElementById('mfilter-tier').value || '';
    var rows = document.querySelectorAll('#models-table tbody tr[data-model]');
    var shown = 0;
    rows.forEach(function (row) {
      var hay = (row.getAttribute('data-model') + ' ' + row.getAttribute('data-family') + ' ' +
                 (row.getAttribute('data-use-case') || '')).toLowerCase();
      var ok = (!text || hay.indexOf(text) !== -1)
        && (!fam || row.getAttribute('data-family') === fam)
        && (!ring || row.getAttribute('data-ring') === ring)
        && (!tier || row.getAttribute('data-tier') === tier);
      row.style.display = ok ? '' : 'none';
      if (ok) shown++;
    });
    var none = document.getElementById('models-no-matches');
    if (none) none.style.display = shown ? 'none' : '';
  }
</script>
```

- [ ] **Step 3: Rewrite `static_models.html`** to the dashboard shell with the richer table (keep the `{% include "_device_picker.html" %}`, keep the per-row `data-min-memory-gb = mems|min` and the Min-mem cell):

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Local Models · On-Prem AI Adoption Radar</title>
    <link rel="icon" type="image/png" href="{{ asset_base }}static/brand/favicon.png" />
    {% include "_base_styles.html" %}
  </head>
  <body>
    {% set page_title = "Local Models" %}
    {% set tagline = "Open models you can run on-prem — sized to your hardware, refreshed daily." %}
    {% set nav = {"Radar": "index.html", "Compare": "compare.html", "History": "history.html"} %}
    {% include "_hero.html" %}
    <main class="container">
      {% if not models %}<p>No models scanned yet.</p>{% endif %}
      {% include "_device_picker.html" %}
      {% include "_models_filter_bar.html" %}
      <table id="models-table">
        <thead>
          <tr><th>Model</th><th>Family</th><th>Ring</th><th>Tier</th><th>Params</th>
              <th>Context</th><th>License</th><th>Use case</th><th>Min mem</th></tr>
        </thead>
        <tbody>
          {% for m in models %}
          {% set mems = m.quants | selectattr('est_memory_gb_4k') | map(attribute='est_memory_gb_4k') | list %}
          <tr data-model="{{ m.name }}" data-family="{{ m.family }}"
              data-ring="{{ m.ring.value if m.ring else '' }}" data-tier="{{ m.hardware_tier.value }}"
              data-use-case="{{ m.use_case or '' }}"{% if mems %} data-min-memory-gb="{{ mems | min }}"{% endif %}>
            <td><a href="model_{{ slug_by_model[m.id] }}.html">{{ m.name }}</a></td>
            <td>{{ m.family }}</td>
            <td>{% if m.ring %}<span class="ring-pill ring-{{ m.ring.value }}">{{ m.ring.value }}</span>{% else %}-{% endif %}</td>
            <td>{{ m.hardware_tier.value }}</td>
            <td>{{ '%.0fB'|format(m.params_total / 1e9) if m.params_total else '?' }}{% if m.params_active %} <small>(A{{ '%.0f'|format(m.params_active / 1e9) }}B)</small>{% endif %}</td>
            <td>{{ '{:,}'.format(m.context_length) if m.context_length else '?' }}</td>
            <td>{{ m.license or '?' }}</td>
            <td>{{ m.use_case or '' }}</td>
            <td>{{ '%.1f GB'|format(mems | min) if mems else '?' }}</td>
          </tr>
          {% else %}
          <tr><td colspan="9">No models yet.</td></tr>
          {% endfor %}
          <tr id="models-no-matches" style="display:none;"><td colspan="9">No models match the current filter.</td></tr>
        </tbody>
      </table>
      {% include "_models_filter_script.html" %}
    </main>
    {% include "_footer.html" %}
  </body>
</html>
```

- [ ] **Step 4: Rewrite `static_model.html`** to the shell:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{{ model.name }} · Models</title>
    <link rel="icon" type="image/png" href="{{ asset_base }}static/brand/favicon.png" />
    {% include "_base_styles.html" %}
  </head>
  <body>
    {% set page_title = model.name %}
    {% set tagline = model.family %}
    {% set nav = {"Models": "models.html", "Radar": "index.html"} %}
    {% include "_hero.html" %}
    <main class="container">
      {% include "_model_detail.html" %}
    </main>
    {% include "_footer.html" %}
  </body>
</html>
```

- [ ] **Step 5: Enrich `_model_detail.html`** — surface release_date + use_case (keep the existing quant + "Runs on" tables). Replace the two top `<p>` lines with:

```html
<p>Ring: <strong>{{ model.ring.value if model.ring else '-' }}</strong> ·
   Hardware: <strong>{{ model.hardware_tier.value }}</strong> ·
   Modality: {{ model.modality.value }}{% if model.license %} · License: {{ model.license }}{% endif %}
   {% if model.use_case %} · Use case: {{ model.use_case }}{% endif %}</p>
<p>Params: {{ '%.1fB'|format(model.params_total / 1e9) if model.params_total else '?' }}{% if model.params_active %} (active {{ '%.1fB'|format(model.params_active / 1e9) }}){% endif %}
   {% if model.context_length %} · Context: {{ '{:,}'.format(model.context_length) }}{% endif %}
   {% if model.release_date %} · Released: {{ model.release_date }}{% endif %}</p>
```

- [ ] **Step 6: Group the device picker** options by kind in `_device_picker.html`. Replace the flat `{% for d in device_picker.device_presets %}…{% endfor %}` option loop with three `<optgroup>`s (GPU / Apple / CPU), each filtering `device_picker.device_presets` by `d.kind`:

```html
      <optgroup label="GPU">
        {% for d in device_picker.device_presets if d.kind == 'gpu' %}
        <option value="{{ d.id }}" data-usable="{{ d.usable_gb }}">{{ d.label }} (~{{ '%.0f'|format(d.usable_gb) }} GB usable)</option>
        {% endfor %}
      </optgroup>
      <optgroup label="Apple">
        {% for d in device_picker.device_presets if d.kind == 'apple' %}
        <option value="{{ d.id }}" data-usable="{{ d.usable_gb }}">{{ d.label }} (~{{ '%.0f'|format(d.usable_gb) }} GB usable)</option>
        {% endfor %}
      </optgroup>
      <optgroup label="CPU / RAM">
        {% for d in device_picker.device_presets if d.kind == 'cpu' %}
        <option value="{{ d.id }}" data-usable="{{ d.usable_gb }}">{{ d.label }} (~{{ '%.0f'|format(d.usable_gb) }} GB usable)</option>
        {% endfor %}
      </optgroup>
```

(Keep the leading `— pick a device —` and trailing `Custom…` options, the `<script>`, and the fit CSS exactly as they are.)

- [ ] **Step 7: Match the live templates.** Make `models.html` (live) mirror `static_models.html` and `model.html` (live) mirror `static_model.html` — same shell, same table, same includes. The live routes already pass `device_picker`/`fit_by_tier`/`models`/`slug_by_model`; the `asset_base` global differs (live uses `/static`) but is already wired. Add a "Models" link to the dashboard nav in `static_index.html` and `index.html` (`{% set nav = {"Models": "models.html", "Compare": ...} %}`).

- [ ] **Step 8: Update/extend tests** in `tests/test_static_site.py` + `tests/test_device_picker.py` + `tests/test_web.py`:

```python
# test_static_site.py — the models page is now styled + filterable + richer
def test_models_page_is_styled_and_filterable(tmp_path):
    # build a model entry (reuse the existing helper/fixture style in this file)
    ...
    html = (out / "models.html").read_text(encoding="utf-8")
    assert "_base_styles" not in html  # included, not literal
    assert "mfilter-family" in html and "models-table" in html
    assert "ring-pill" in html
    assert "Use case" in html and "Context" in html
```

Update the existing `test_static_models_page_has_picker_and_row_data` / `test_static_models_page_injects_tight_fraction` if the markup moved (the picker include + `data-min-memory-gb` + `RADAR_TIGHT_FRACTION` must still be present). Add a `test_device_picker.py` assertion that the picker now contains `<optgroup`. For `test_web.py`, assert the live `/models` response still 200s and contains `models-table` + `mfilter-family`.

- [ ] **Step 9: Run gate** → green. Commit.

---

### Task 6: Phase gate + live smoke + final review + merge + push

- [ ] **Step 1: Full gate** — `ruff check src tests && mypy src && pytest -q` green; report the real full-suite count.
- [ ] **Step 2: Live smoke** — `radar models scan --root .` then `radar export --root . --out /tmp/site-cat`:
  - `models.html` has the hero, `_base_styles` output (a `<style>` block / `.container`), the `mfilter-*` controls, the grouped `<optgroup>` picker, the richer columns (Params/Context/License/Use case), and per-row `data-min-memory-gb`.
  - a `model_*.html` is styled (hero + container) and shows the "Runs on" table + release/use-case line.
  - Spot-check the device count in the picker (≥ 45 options) and the model count in the table (≥ the catalog that resolved).
  - Live app (`TestClient`): `/models` 200 with the new markup; `/model/{id}` 200 styled.
- [ ] **Step 3: Final whole-branch review** (most-capable model) over `git merge-base main HEAD`..HEAD, with this plan's Global Constraints as the lens.
- [ ] **Step 4: Merge** to main `--no-ff`, integrate `origin` (rebase/pull the daily CI history commit first), push, delete branch.

---

## Self-Review

**Spec coverage:** UI "not seen" → Task 5 (shell + styling). More GPUs → Task 2 (~45 presets). More models → Task 3 (~26 seeds). Richer metadata → Task 1 (schema) + Task 3 (data) + Task 5 (surfaced). Models-page UX → Task 5 (filter/sort, grouped picker, columns). Quant accuracy → Task 4 (richer + MLX ladder). GPU auto-detection explicitly dropped per user.

**Placeholder scan:** exact preset dict, exact seed YAML, exact template bodies, exact test code given. The few "(reuse the existing helper/fixture style in this file)" notes point implementers at concrete in-file patterns rather than inventing.

**Type consistency:** new `release_date`/`use_case` are `str | None` on both `ModelSeed` and `ModelEntry`; `_cpu` returns `DeviceProfile` like `_gpu`/`_mac`; `Platform.APPLE_MLX` already exists; filter JS reads only `data-*`; `ring-pill ring-<value>` matches the dashboard's existing classes. `COMMON_DEVICE_TIERS` keys (`rtx-4060-8gb`, `rtx-4080-16gb`, `rtx-4090-24gb`, `rtx-6000-ada-48gb`, `a100-80gb`, `mac-64gb`) all remain in the expanded `DEVICE_PRESETS`.
