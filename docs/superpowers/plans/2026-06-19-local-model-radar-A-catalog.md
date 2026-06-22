# Local-Model Radar — Plan A: Catalog Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a spec-rich local-model catalog — `radar models scan` collects model specs from Hugging Face + Ollama + a manual seed, computes per-quantization memory footprints and a hardware-tier badge deterministically, and `radar models list` shows them.

**Architecture:** A new `src/radar/models_radar/` package, parallel to the tool radar and reusing its idioms (pydantic frozen models, httpx async collectors with best-effort degradation, a YAML seed loaded like `seed-sources.yaml`, a typer sub-app like `seed`, run dirs via `RunStore`). No model flows through the tool `DecisionCard`. This plan delivers the catalog + memory/tier data; adoption ring, momentum, history, and the web/MCP surface are Plan B.

**Tech Stack:** Python 3.12, pydantic v2, httpx (async), PyYAML, typer, `RunStore` (existing), pytest + ruff + mypy.

## Global Constraints

- Python ≥ 3.12; every new module begins with `from __future__ import annotations`.
- No new third-party dependencies.
- No API keys (HF + Ollama public endpoints); deterministic core, no LLM.
- Every network call is best-effort: failures degrade to partial/empty data + a warning, never raise out of a scan.
- Immutability: pydantic models frozen; never mutate inputs; use `model_copy(update=...)`.
- Memory estimator is a pure function; KV-cache term is a non-GQA upper bound (prefer over- to under-estimating). OVERHEAD ≈ 1.2.
- Minimum-viable-quant quality floor: ≥ ~4 effective bits (Q4-class); sub-4-bit quants are recorded but never the "viable minimum".
- Hardware-tier thresholds (min-viable-quant `est_memory_gb_4k`): `laptop ≤16` · `apple_high_ram ≤32` · `single_gpu ≤48` · `workstation ≤180` · `datacenter >180`.
- ruff + mypy clean; coverage ≥ 80%.

---

### Task 1: Entities & enums

**Files:**
- Create: `src/radar/models_radar/__init__.py` (empty)
- Create: `src/radar/models_radar/entities.py`
- Test: `tests/test_models_radar_entities.py`

**Interfaces:**
- Produces: enums `Modality`, `Openness`, `Platform`, `HardwareTier`; frozen models
  `QuantVariant`, `ModelEntry`, `ModelSeed`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_models_radar_entities.py
from __future__ import annotations

import pytest

from radar.models_radar.entities import (
    HardwareTier, Modality, ModelEntry, ModelSeed, Openness, Platform, QuantVariant,
)


def test_quant_variant_is_frozen_and_defaults():
    q = QuantVariant(format="GGUF Q4_K_M", bits_per_weight=4.5, platform=Platform.GENERIC)
    assert q.file_size_gb is None and q.est_memory_gb_4k is None
    with pytest.raises(Exception):
        q.format = "x"


def test_model_entry_minimal_and_frozen():
    m = ModelEntry(id="qwen3-30b-a3b", name="Qwen3-30B-A3B", family="Qwen3")
    assert m.params_active is None and m.quants == [] and m.modality == Modality.TEXT
    with pytest.raises(Exception):
        m.name = "x"


def test_model_seed_requires_id_and_family():
    s = ModelSeed(id="llama-3.1-8b", name="Llama 3.1 8B", family="Llama",
                  hf_repo="meta-llama/Llama-3.1-8B")
    assert s.ollama_name is None and s.enabled is True


def test_enum_values():
    assert Platform.APPLE_MLX.value == "apple_mlx"
    assert HardwareTier.SINGLE_GPU.value == "single_gpu"
    assert Openness.OPEN_PERMISSIVE.value == "open-permissive"
    assert Modality.MULTIMODAL.value == "multimodal"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_models_radar_entities.py -v`
Expected: FAIL (`ModuleNotFoundError: radar.models_radar.entities`).

- [ ] **Step 3: Implement**

Create `src/radar/models_radar/__init__.py` empty. Create `entities.py`:

```python
# src/radar/models_radar/entities.py
"""Entities for the local-model radar (separate from the tool DecisionCard)."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from radar.models import Backer


class Modality(str, Enum):
    TEXT = "text"
    VISION = "vision"
    AUDIO = "audio"
    MULTIMODAL = "multimodal"


class Openness(str, Enum):
    OPEN_PERMISSIVE = "open-permissive"   # open weights + permissive license
    OPEN_RESTRICTED = "open-restricted"   # open weights, restricted/non-commercial
    GATED = "gated"                       # weights behind acceptance/login
    CLOSED = "closed"                     # no open weights


class Platform(str, Enum):
    GENERIC = "generic"
    APPLE_MLX = "apple_mlx"


class HardwareTier(str, Enum):
    LAPTOP = "laptop"
    APPLE_HIGH_RAM = "apple_high_ram"
    SINGLE_GPU = "single_gpu"
    WORKSTATION = "workstation"
    DATACENTER = "datacenter"
    UNKNOWN = "unknown"


class QuantVariant(BaseModel):
    """One quantization of a model."""

    model_config = ConfigDict(frozen=True)

    format: str                       # e.g. "GGUF Q4_K_M", "MLX-4bit", "AWQ", "FP16"
    bits_per_weight: float
    platform: Platform = Platform.GENERIC
    source: str = ""                  # "hf:<repo>" | "ollama:<tag>" | "manual"
    file_size_gb: float | None = None
    est_memory_gb_4k: float | None = None
    est_memory_gb_32k: float | None = None
    perf_tokens_per_sec: float | None = None
    perf_device: str | None = None


class ModelEntry(BaseModel):
    """A tracked local model with specs and quantizations."""

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    family: str
    backer: Backer | None = None
    hf_repo: str | None = None
    ollama_name: str | None = None
    params_total: int | None = None       # raw count, e.g. 30_000_000_000
    params_active: int | None = None      # < total for MoE; None → treated as dense
    num_layers: int | None = None
    hidden_size: int | None = None
    context_length: int | None = None
    modality: Modality = Modality.TEXT
    license: str | None = None
    openness: Openness | None = None
    hf_downloads: int | None = None
    hf_likes: int | None = None
    last_modified: str | None = None
    hardware_tier: HardwareTier = HardwareTier.UNKNOWN
    quants: list[QuantVariant] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ModelSeed(BaseModel):
    """A seeded model family entry (config/model-seed.yaml)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    family: str
    enabled: bool = True
    hf_repo: str | None = None
    ollama_name: str | None = None
    backer: Backer | None = None
    # Manual spec overrides for what the APIs miss (MoE active params, closed
    # models, MLX perf). Merged over collected data during assembly.
    params_total: int | None = None
    params_active: int | None = None
    num_layers: int | None = None
    hidden_size: int | None = None
    context_length: int | None = None
    modality: Modality | None = None
    license: str | None = None
    openness: Openness | None = None
    manual_quants: list[QuantVariant] = Field(default_factory=list)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_models_radar_entities.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/radar/models_radar/__init__.py src/radar/models_radar/entities.py tests/test_models_radar_entities.py
git commit -m "feat(models): ModelEntry/QuantVariant/ModelSeed entities + enums"
```

---

### Task 2: Memory estimator + hardware tier (pure functions)

**Files:**
- Create: `src/radar/models_radar/memory.py`
- Test: `tests/test_models_radar_memory.py`

**Interfaces:**
- Consumes: `QuantVariant`, `HardwareTier` (Task 1).
- Produces: `estimate_memory_gb(params_total, bits_per_weight, context, num_layers, hidden_size) -> float | None`;
  `minimum_viable_quant(quants: list[QuantVariant]) -> QuantVariant | None`;
  `hardware_tier(min_memory_gb: float | None) -> HardwareTier`;
  constants `OVERHEAD`, `VIABLE_MIN_BITS`, `TIER_THRESHOLDS`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_models_radar_memory.py
from __future__ import annotations

from radar.models_radar.entities import HardwareTier, Platform, QuantVariant
from radar.models_radar.memory import (
    estimate_memory_gb, hardware_tier, minimum_viable_quant,
)


def test_weights_only_when_arch_unknown():
    # 8B params at 4.5 bits ≈ 4.5 GB weights * 1.2 overhead ≈ 5.4 GB.
    gb = estimate_memory_gb(8_000_000_000, 4.5, context=4096, num_layers=None, hidden_size=None)
    assert 5.0 <= gb <= 5.8


def test_kv_cache_grows_with_context():
    small = estimate_memory_gb(8_000_000_000, 4.5, 4096, num_layers=32, hidden_size=4096)
    big = estimate_memory_gb(8_000_000_000, 4.5, 32768, num_layers=32, hidden_size=4096)
    assert big > small


def test_moe_uses_total_params_for_memory():
    # 30B total drives memory even though only 3B active.
    gb = estimate_memory_gb(30_000_000_000, 4.5, 4096, num_layers=None, hidden_size=None)
    assert gb > 15  # ~16.2 GB weights-only; far above a 3B model's ~1.7 GB


def test_estimate_none_without_params():
    assert estimate_memory_gb(None, 4.5, 4096, None, None) is None


def test_minimum_viable_quant_skips_sub_4bit():
    quants = [
        QuantVariant(format="Q2_K", bits_per_weight=2.6, est_memory_gb_4k=3.0),
        QuantVariant(format="Q4_K_M", bits_per_weight=4.5, est_memory_gb_4k=5.4),
        QuantVariant(format="Q8_0", bits_per_weight=8.0, est_memory_gb_4k=9.0),
    ]
    mv = minimum_viable_quant(quants)
    assert mv is not None and mv.format == "Q4_K_M"  # Q2 skipped, Q4 is the smallest viable


def test_minimum_viable_quant_none_when_no_estimates():
    assert minimum_viable_quant([QuantVariant(format="Q4_K_M", bits_per_weight=4.5)]) is None


def test_hardware_tier_boundaries():
    assert hardware_tier(12) == HardwareTier.LAPTOP
    assert hardware_tier(16) == HardwareTier.LAPTOP
    assert hardware_tier(24) == HardwareTier.APPLE_HIGH_RAM
    assert hardware_tier(48) == HardwareTier.SINGLE_GPU
    assert hardware_tier(120) == HardwareTier.WORKSTATION
    assert hardware_tier(400) == HardwareTier.DATACENTER
    assert hardware_tier(None) == HardwareTier.UNKNOWN
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_models_radar_memory.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement**

```python
# src/radar/models_radar/memory.py
"""Deterministic memory estimation and hardware-tier classification.

Pure functions: identical inputs → identical output. The KV-cache term is a
non-GQA upper bound, so estimates lean high rather than low. These numbers are
the substrate the future hardware-device-matching phase compares to a machine.
"""

from __future__ import annotations

from radar.models_radar.entities import HardwareTier, QuantVariant


OVERHEAD = 1.2
VIABLE_MIN_BITS = 4.0
# (max_gb_inclusive, tier) ordered ascending; first match wins.
TIER_THRESHOLDS: list[tuple[float, HardwareTier]] = [
    (16.0, HardwareTier.LAPTOP),
    (32.0, HardwareTier.APPLE_HIGH_RAM),
    (48.0, HardwareTier.SINGLE_GPU),
    (180.0, HardwareTier.WORKSTATION),
]


def estimate_memory_gb(
    params_total: int | None,
    bits_per_weight: float,
    context: int,
    num_layers: int | None,
    hidden_size: int | None,
) -> float | None:
    """Estimated RAM/VRAM (GB) to run the model at ``context`` tokens.

    Weights term always applies. KV-cache term is added only when architecture
    (layers + hidden size) is known; otherwise the estimate is weights-only.
    """
    if params_total is None:
        return None
    weights_gb = params_total * bits_per_weight / 8 / 1e9
    kv_cache_gb = 0.0
    if num_layers and hidden_size:
        # 2 (K and V) * 2 bytes (fp16) * layers * context * hidden.
        kv_cache_gb = 2 * 2 * num_layers * context * hidden_size / 1e9
    return round((weights_gb + kv_cache_gb) * OVERHEAD, 1)


def minimum_viable_quant(quants: list[QuantVariant]) -> QuantVariant | None:
    """Smallest-memory quant at or above the quality floor, or None.

    Only considers quants with a computed ``est_memory_gb_4k`` and
    ``bits_per_weight >= VIABLE_MIN_BITS``.
    """
    viable = [
        q for q in quants
        if q.est_memory_gb_4k is not None and q.bits_per_weight >= VIABLE_MIN_BITS
    ]
    if not viable:
        return None
    return min(viable, key=lambda q: q.est_memory_gb_4k)  # type: ignore[arg-type,return-value]


def hardware_tier(min_memory_gb: float | None) -> HardwareTier:
    """Classify a model by its minimum-viable-quant memory."""
    if min_memory_gb is None:
        return HardwareTier.UNKNOWN
    for ceiling, tier in TIER_THRESHOLDS:
        if min_memory_gb <= ceiling:
            return tier
    return HardwareTier.DATACENTER
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_models_radar_memory.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add src/radar/models_radar/memory.py tests/test_models_radar_memory.py
git commit -m "feat(models): deterministic memory estimator + hardware-tier classifier"
```

---

### Task 3: Model seed config + loader

**Files:**
- Create: `config/model-seed.yaml`
- Create: `src/radar/models_radar/seed.py`
- Test: `tests/test_models_radar_seed.py`

**Interfaces:**
- Consumes: `ModelSeed` (Task 1).
- Produces: `load_model_seed(path: Path) -> list[ModelSeed]`; raises `ModelSeedError` on invalid YAML.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_models_radar_seed.py
from __future__ import annotations

from pathlib import Path

import pytest

from radar.models_radar.seed import ModelSeedError, load_model_seed


def test_loads_bundled_seed_with_known_families():
    seeds = load_model_seed(Path("config/model-seed.yaml"))
    assert len(seeds) >= 6
    families = {s.family for s in seeds}
    assert {"Llama", "Qwen3"} <= families
    # MoE entry carries active params from the manual override.
    moe = next((s for s in seeds if s.params_active and s.params_total
                and s.params_active < s.params_total), None)
    assert moe is not None


def test_missing_file_raises(tmp_path: Path):
    with pytest.raises(ModelSeedError):
        load_model_seed(tmp_path / "nope.yaml")


def test_invalid_yaml_raises(tmp_path: Path):
    p = tmp_path / "bad.yaml"
    p.write_text("models: [::::]", encoding="utf-8")
    with pytest.raises(ModelSeedError):
        load_model_seed(p)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_models_radar_seed.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement the loader**

```python
# src/radar/models_radar/seed.py
"""Load the bundled model seed (config/model-seed.yaml)."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from radar.models_radar.entities import ModelSeed


class ModelSeedError(ValueError):
    """Raised when the model seed cannot be loaded."""


def load_model_seed(path: Path) -> list[ModelSeed]:
    try:
        contents = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ModelSeedError(f"Model seed not found: {path}") from exc
    try:
        raw = yaml.safe_load(contents) or {}
    except yaml.YAMLError as exc:
        raise ModelSeedError(f"Invalid YAML in {path}: {exc}") from exc
    try:
        return [ModelSeed.model_validate(item) for item in raw.get("models") or []]
    except ValidationError as exc:
        raise ModelSeedError(f"Model seed validation failed for {path}: {exc}") from exc
```

- [ ] **Step 4: Create the seed file**

Create `config/model-seed.yaml` with a starter set. Specs the HF collector can
fill (params, layers, hidden, context, license) may be omitted; supply
`params_active`/`manual_quants` only where the APIs miss them (MoE, MLX). The
implementer should sanity-check each `hf_repo`/`ollama_name` resolves.

```yaml
version: "1.0"
models:
  - id: llama-3.1-8b
    name: Llama 3.1 8B Instruct
    family: Llama
    hf_repo: meta-llama/Llama-3.1-8B-Instruct
    ollama_name: llama3.1
    backer: {name: "Meta", type: big_tech}
  - id: qwen3-30b-a3b
    name: Qwen3-30B-A3B
    family: Qwen3
    hf_repo: Qwen/Qwen3-30B-A3B
    ollama_name: qwen3
    backer: {name: "Alibaba", type: big_tech}
    params_total: 30000000000
    params_active: 3000000000   # MoE: APIs don't expose active params
  - id: qwen3-8b
    name: Qwen3 8B
    family: Qwen3
    hf_repo: Qwen/Qwen3-8B
    ollama_name: qwen3
    backer: {name: "Alibaba", type: big_tech}
  - id: deepseek-r1-distill-qwen-7b
    name: DeepSeek-R1-Distill-Qwen-7B
    family: DeepSeek
    hf_repo: deepseek-ai/DeepSeek-R1-Distill-Qwen-7B
    ollama_name: deepseek-r1
    backer: {name: "DeepSeek", type: startup}
  - id: mistral-small-3
    name: Mistral Small 3
    family: Mistral
    hf_repo: mistralai/Mistral-Small-24B-Instruct-2501
    ollama_name: mistral-small
    backer: {name: "Mistral AI", type: startup}
  - id: gemma-3-12b
    name: Gemma 3 12B
    family: Gemma
    hf_repo: google/gemma-3-12b-it
    ollama_name: gemma3
    backer: {name: "Google", type: big_tech}
  - id: phi-4
    name: Phi-4
    family: Phi
    hf_repo: microsoft/phi-4
    ollama_name: phi4
    backer: {name: "Microsoft", type: big_tech}
  - id: gpt-oss-20b
    name: gpt-oss-20b
    family: gpt-oss
    hf_repo: openai/gpt-oss-20b
    ollama_name: gpt-oss
    backer: {name: "OpenAI", type: startup}
```

> **Note for the implementer:** model specs are date-sensitive. Verify each
> `hf_repo` and `ollama_name` resolves (HTTP 200) before finalizing; if a repo
> 404s, correct the slug or mark `enabled: false` with a note. This is the
> "research the seed" step — accuracy of repos matters more than list length.

- [ ] **Step 5: Run test + commit**

Run: `pytest tests/test_models_radar_seed.py -v`  → PASS (3 tests).

```bash
git add config/model-seed.yaml src/radar/models_radar/seed.py tests/test_models_radar_seed.py
git commit -m "feat(models): model-seed.yaml + loader"
```

---

### Task 4: Hugging Face collector

**Files:**
- Create: `src/radar/models_radar/collectors/__init__.py` (empty)
- Create: `src/radar/models_radar/collectors/huggingface.py`
- Test: `tests/test_models_radar_hf.py`

**Interfaces:**
- Consumes: `Platform`, `QuantVariant` (Task 1).
- Produces: `HFModelData` (frozen: `params_total, num_layers, hidden_size, context_length, license, modality_tag, downloads, likes, last_modified, quant_formats: list[str]`);
  `async fetch_hf_model(hf_repo: str, client) -> HFModelData | None` (None on failure).
  Quant-format detection helper `quant_formats_from_siblings(filenames: list[str]) -> list[str]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_models_radar_hf.py
from __future__ import annotations

import pytest

from radar.models_radar.collectors.huggingface import (
    fetch_hf_model, quant_formats_from_siblings,
)

MODEL_JSON = {
    "downloads": 123456, "likes": 789, "lastModified": "2026-06-01T00:00:00.000Z",
    "pipeline_tag": "text-generation",
    "cardData": {"license": "apache-2.0"},
    "safetensors": {"total": 8030000000},
    "siblings": [
        {"rfilename": "model-00001-of-00002.safetensors"},
        {"rfilename": "config.json"},
    ],
}
CONFIG_JSON = {"num_hidden_layers": 32, "hidden_size": 4096, "max_position_embeddings": 131072}


class FakeResp:
    def __init__(self, payload): self._p = payload
    def raise_for_status(self): pass
    def json(self): return self._p


class FakeClient:
    def __init__(self, routes): self.routes = routes
    async def get(self, url, **kw):
        for frag, payload in self.routes.items():
            if frag in url:
                return FakeResp(payload)
        raise AssertionError(f"unexpected url {url}")


def test_quant_formats_from_siblings_detects_gguf_and_mlx():
    fmts = quant_formats_from_siblings([
        "model.Q4_K_M.gguf", "model.Q8_0.gguf", "model.safetensors",
        "model.fp16.gguf", "mlx-4bit/weights.npz",
    ])
    assert "GGUF Q4_K_M" in fmts and "GGUF Q8_0" in fmts


@pytest.mark.asyncio
async def test_fetch_hf_model_parses_specs():
    client = FakeClient({
        "api/models/meta-llama/Llama-3.1-8B": MODEL_JSON,
        "raw/main/config.json": CONFIG_JSON,
    })
    data = await fetch_hf_model("meta-llama/Llama-3.1-8B", client)
    assert data is not None
    assert data.params_total == 8030000000
    assert data.num_layers == 32 and data.hidden_size == 4096
    assert data.context_length == 131072
    assert data.license == "apache-2.0"
    assert data.downloads == 123456 and data.likes == 789


@pytest.mark.asyncio
async def test_fetch_hf_model_degrades_to_none_on_error():
    class Boom:
        async def get(self, url, **kw): raise RuntimeError("network down")
    assert await fetch_hf_model("x/y", Boom()) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_models_radar_hf.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement**

```python
# src/radar/models_radar/collectors/huggingface.py
"""Hugging Face Hub collector: model specs, popularity, quant detection."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Protocol


logger = logging.getLogger(__name__)

HF_MODEL_URL = "https://huggingface.co/api/models/{repo}"
HF_CONFIG_URL = "https://huggingface.co/{repo}/raw/main/config.json"
_GGUF_RE = re.compile(r"(Q\d[\w]*|F16|BF16|F32)\.gguf$", re.IGNORECASE)


class _AsyncClient(Protocol):
    async def get(self, url: str, **kwargs: Any) -> Any: ...


@dataclass(frozen=True)
class HFModelData:
    params_total: int | None = None
    num_layers: int | None = None
    hidden_size: int | None = None
    context_length: int | None = None
    license: str | None = None
    modality_tag: str | None = None
    downloads: int | None = None
    likes: int | None = None
    last_modified: str | None = None
    quant_formats: list[str] = field(default_factory=list)


def quant_formats_from_siblings(filenames: list[str]) -> list[str]:
    """Map GGUF filenames to canonical quant format labels."""
    formats: list[str] = []
    for name in filenames:
        m = _GGUF_RE.search(name)
        if m:
            label = f"GGUF {m.group(1).upper().replace('F16', 'F16')}"
            if label not in formats:
                formats.append(label)
    return formats


async def fetch_hf_model(hf_repo: str, client: _AsyncClient) -> HFModelData | None:
    """Fetch model metadata + config. Returns None on any failure."""
    try:
        meta_resp = await client.get(HF_MODEL_URL.format(repo=hf_repo))
        meta_resp.raise_for_status()
        meta = meta_resp.json()
    except Exception as exc:
        logger.warning("HF model fetch failed (%s): %s", hf_repo, exc)
        return None

    siblings = [s.get("rfilename", "") for s in meta.get("siblings") or []]
    card = meta.get("cardData") or {}
    safet = meta.get("safetensors") or {}

    num_layers = hidden = context = None
    try:
        cfg_resp = await client.get(HF_CONFIG_URL.format(repo=hf_repo))
        cfg_resp.raise_for_status()
        cfg = cfg_resp.json()
        num_layers = cfg.get("num_hidden_layers")
        hidden = cfg.get("hidden_size")
        context = cfg.get("max_position_embeddings")
    except Exception as exc:
        logger.warning("HF config fetch failed (%s): %s", hf_repo, exc)

    return HFModelData(
        params_total=safet.get("total"),
        num_layers=num_layers,
        hidden_size=hidden,
        context_length=context,
        license=card.get("license") or meta.get("license"),
        modality_tag=meta.get("pipeline_tag"),
        downloads=meta.get("downloads"),
        likes=meta.get("likes"),
        last_modified=meta.get("lastModified"),
        quant_formats=quant_formats_from_siblings(siblings),
    )
```

- [ ] **Step 4: Run test + commit**

Run: `pytest tests/test_models_radar_hf.py -v` → PASS (3 tests).

```bash
git add src/radar/models_radar/collectors/__init__.py src/radar/models_radar/collectors/huggingface.py tests/test_models_radar_hf.py
git commit -m "feat(models): Hugging Face collector (specs, popularity, quant detection)"
```

---

### Task 5: Ollama collector

**Files:**
- Create: `src/radar/models_radar/collectors/ollama.py`
- Test: `tests/test_models_radar_ollama.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `OllamaQuant` (frozen: `tag: str, size_gb: float | None, bits_per_weight: float`);
  `async fetch_ollama_quants(ollama_name: str, client) -> list[OllamaQuant]` (empty on failure);
  `bits_for_tag(tag: str) -> float` mapping an Ollama quant tag to effective bits.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_models_radar_ollama.py
from __future__ import annotations

import pytest

from radar.models_radar.collectors.ollama import bits_for_tag, fetch_ollama_quants

TAGS_JSON = {"models": [
    {"tag": "8b-instruct-q4_K_M", "size": 4_900_000_000},
    {"tag": "8b-instruct-q8_0", "size": 8_500_000_000},
    {"tag": "latest", "size": 4_900_000_000},
]}


class FakeResp:
    def __init__(self, p): self._p = p
    def raise_for_status(self): pass
    def json(self): return self._p


class FakeClient:
    def __init__(self, payload): self.payload = payload
    async def get(self, url, **kw): return FakeResp(self.payload)


def test_bits_for_tag_known_quants():
    assert bits_for_tag("8b-q4_K_M") == 4.5
    assert bits_for_tag("8b-q8_0") == 8.0
    assert bits_for_tag("fp16") == 16.0
    assert bits_for_tag("weird-unknown") == 4.5  # default to Q4-class


@pytest.mark.asyncio
async def test_fetch_ollama_quants_parses_tags_and_sizes():
    quants = await fetch_ollama_quants("llama3.1", FakeClient(TAGS_JSON))
    by_tag = {q.tag: q for q in quants}
    assert by_tag["8b-instruct-q4_K_M"].size_gb == pytest.approx(4.9, abs=0.1)
    assert by_tag["8b-instruct-q4_K_M"].bits_per_weight == 4.5
    assert by_tag["8b-instruct-q8_0"].bits_per_weight == 8.0


@pytest.mark.asyncio
async def test_fetch_ollama_quants_degrades_to_empty():
    class Boom:
        async def get(self, url, **kw): raise RuntimeError("down")
    assert await fetch_ollama_quants("x", Boom()) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_models_radar_ollama.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement**

```python
# src/radar/models_radar/collectors/ollama.py
"""Ollama library collector: local-runnable quant tags + sizes."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol


logger = logging.getLogger(__name__)

OLLAMA_TAGS_URL = "https://ollama.com/api/tags/{name}"
_BITS_BY_QUANT = {
    "q2": 2.6, "q3": 3.4, "q4": 4.5, "q5": 5.5, "q6": 6.6, "q8": 8.0,
    "fp16": 16.0, "f16": 16.0,
}


class _AsyncClient(Protocol):
    async def get(self, url: str, **kwargs: Any) -> Any: ...


@dataclass(frozen=True)
class OllamaQuant:
    tag: str
    size_gb: float | None
    bits_per_weight: float


def bits_for_tag(tag: str) -> float:
    """Effective bits-per-weight for an Ollama quant tag (default Q4-class)."""
    low = tag.lower()
    for key, bits in _BITS_BY_QUANT.items():
        if key in low:
            return bits
    return 4.5


async def fetch_ollama_quants(ollama_name: str, client: _AsyncClient) -> list[OllamaQuant]:
    """Quant tags for an Ollama model. Empty list on failure or no tags."""
    try:
        resp = await client.get(OLLAMA_TAGS_URL.format(name=ollama_name))
        resp.raise_for_status()
        items = resp.json().get("models") or []
    except Exception as exc:
        logger.warning("Ollama tags fetch failed (%s): %s", ollama_name, exc)
        return []
    quants: list[OllamaQuant] = []
    for item in items:
        tag = item.get("tag") or ""
        if not tag or tag == "latest":
            continue
        size = item.get("size")
        quants.append(OllamaQuant(
            tag=tag,
            size_gb=round(size / 1e9, 1) if isinstance(size, (int, float)) else None,
            bits_per_weight=bits_for_tag(tag),
        ))
    return quants
```

> **Implementer note:** confirm the real Ollama tags endpoint shape with a live
> smoke (the registry path/JSON may differ from the fixture); adjust the URL/parse
> to match what the live service returns, keeping the function contract identical.
> Keep the degrade-to-empty behavior.

- [ ] **Step 4: Run test + commit**

Run: `pytest tests/test_models_radar_ollama.py -v` → PASS (3 tests).

```bash
git add src/radar/models_radar/collectors/ollama.py tests/test_models_radar_ollama.py
git commit -m "feat(models): Ollama collector (quant tags + sizes)"
```

---

### Task 6: Assemble a ModelEntry from seed + collectors

**Files:**
- Create: `src/radar/models_radar/assemble.py`
- Test: `tests/test_models_radar_assemble.py`

**Interfaces:**
- Consumes: `ModelSeed`, `ModelEntry`, `QuantVariant`, `Platform`, `Modality`, `Openness` (Task 1);
  `estimate_memory_gb`, `minimum_viable_quant`, `hardware_tier` (Task 2);
  `HFModelData` (Task 4); `OllamaQuant` (Task 5).
- Produces: `build_model_entry(seed, hf, ollama_quants) -> ModelEntry` where
  `hf: HFModelData | None`, `ollama_quants: list[OllamaQuant]`. Also
  `bits_for_format(fmt: str) -> float` and `openness_from_license(license) -> Openness`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_models_radar_assemble.py
from __future__ import annotations

from radar.models_radar.assemble import build_model_entry, openness_from_license
from radar.models_radar.collectors.huggingface import HFModelData
from radar.models_radar.collectors.ollama import OllamaQuant
from radar.models_radar.entities import HardwareTier, ModelSeed, Openness, Platform


def test_openness_mapping():
    assert openness_from_license("apache-2.0") == Openness.OPEN_PERMISSIVE
    assert openness_from_license("llama3.1") == Openness.OPEN_RESTRICTED
    assert openness_from_license(None) is None


def test_build_merges_specs_computes_memory_and_tier():
    seed = ModelSeed(id="llama-3.1-8b", name="Llama 3.1 8B", family="Llama",
                     hf_repo="meta-llama/Llama-3.1-8B", ollama_name="llama3.1")
    hf = HFModelData(params_total=8_000_000_000, num_layers=32, hidden_size=4096,
                     context_length=131072, license="apache-2.0",
                     modality_tag="text-generation", downloads=1000, likes=10,
                     quant_formats=["GGUF Q4_K_M", "GGUF Q8_0"])
    ollama = [OllamaQuant(tag="8b-q4_K_M", size_gb=4.9, bits_per_weight=4.5)]
    m = build_model_entry(seed, hf, ollama)

    assert m.params_total == 8_000_000_000 and m.context_length == 131072
    assert m.openness == Openness.OPEN_PERMISSIVE
    # quants from HF formats + ollama tag, each with a computed 4k memory estimate
    q4 = next(q for q in m.quants if q.bits_per_weight == 4.5 and q.est_memory_gb_4k)
    assert 4.5 <= q4.est_memory_gb_4k <= 7.0
    # 8B Q4 → laptop tier
    assert m.hardware_tier == HardwareTier.LAPTOP


def test_manual_overrides_win_and_moe_active_preserved():
    seed = ModelSeed(id="qwen3-30b-a3b", name="Qwen3-30B-A3B", family="Qwen3",
                     params_total=30_000_000_000, params_active=3_000_000_000,
                     manual_quants=[])
    m = build_model_entry(seed, None, [])
    assert m.params_total == 30_000_000_000 and m.params_active == 3_000_000_000


def test_no_data_yields_incomplete_entry_with_warning():
    seed = ModelSeed(id="x", name="X", family="Fam", hf_repo="a/b")
    m = build_model_entry(seed, None, [])
    assert m.hardware_tier == HardwareTier.UNKNOWN
    assert any("no specs" in w.lower() or "incomplete" in w.lower() for w in m.warnings)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_models_radar_assemble.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement**

```python
# src/radar/models_radar/assemble.py
"""Merge a seed + collector data into a fully-specced ModelEntry."""

from __future__ import annotations

from radar.models_radar.collectors.huggingface import HFModelData
from radar.models_radar.collectors.ollama import OllamaQuant
from radar.models_radar.entities import (
    HardwareTier, Modality, ModelEntry, ModelSeed, Openness, Platform, QuantVariant,
)
from radar.models_radar.memory import estimate_memory_gb, hardware_tier, minimum_viable_quant


_PERMISSIVE = {"apache-2.0", "mit", "bsd-3-clause", "apache-2", "openrail"}
_BITS_BY_FORMAT = {"q2": 2.6, "q3": 3.4, "q4": 4.5, "q5": 5.5, "q6": 6.6,
                   "q8": 8.0, "fp16": 16.0, "f16": 16.0, "bf16": 16.0,
                   "awq": 4.0, "gptq": 4.0, "mlx-4bit": 4.5, "mlx-8bit": 8.0}
_REF_4K = 4096
_REF_32K = 32768


def bits_for_format(fmt: str) -> float:
    low = fmt.lower()
    for key, bits in _BITS_BY_FORMAT.items():
        if key in low:
            return bits
    return 4.5


def openness_from_license(license: str | None) -> Openness | None:
    if not license:
        return None
    low = license.lower()
    if low in _PERMISSIVE:
        return Openness.OPEN_PERMISSIVE
    return Openness.OPEN_RESTRICTED


def _modality(seed: ModelSeed, hf: HFModelData | None) -> Modality:
    if seed.modality is not None:
        return seed.modality
    tag = (hf.modality_tag if hf else None) or ""
    if "image" in tag or "vision" in tag:
        return Modality.VISION
    if "audio" in tag or "speech" in tag:
        return Modality.AUDIO
    return Modality.TEXT


def build_model_entry(
    seed: ModelSeed, hf: HFModelData | None, ollama_quants: list[OllamaQuant],
) -> ModelEntry:
    """Merge order: manual seed overrides win over collected HF/Ollama data."""
    params_total = seed.params_total or (hf.params_total if hf else None)
    num_layers = seed.num_layers or (hf.num_layers if hf else None)
    hidden = seed.hidden_size or (hf.hidden_size if hf else None)
    context = seed.context_length or (hf.context_length if hf else None)
    license_ = seed.license or (hf.license if hf else None)
    openness = seed.openness or openness_from_license(license_)

    quants: list[QuantVariant] = []
    seen: set[tuple[str, Platform]] = set()

    def add(fmt: str, bits: float, platform: Platform, source: str,
            size_gb: float | None = None) -> None:
        key = (fmt, platform)
        if key in seen:
            return
        seen.add(key)
        ctx = context or _REF_4K
        quants.append(QuantVariant(
            format=fmt, bits_per_weight=bits, platform=platform, source=source,
            file_size_gb=size_gb,
            est_memory_gb_4k=estimate_memory_gb(params_total, bits, _REF_4K, num_layers, hidden),
            est_memory_gb_32k=estimate_memory_gb(
                params_total, bits, min(_REF_32K, ctx) if context else _REF_32K,
                num_layers, hidden),
        ))

    for q in seed.manual_quants:                       # manual first (authoritative)
        add(q.format, q.bits_per_weight, q.platform, "manual", q.file_size_gb)
    if hf:
        for fmt in hf.quant_formats:
            add(fmt, bits_for_format(fmt), Platform.GENERIC, f"hf:{seed.hf_repo}")
    for oq in ollama_quants:
        add(f"Ollama {oq.tag}", oq.bits_per_weight, Platform.GENERIC,
            f"ollama:{seed.ollama_name}", oq.size_gb)

    mv = minimum_viable_quant(quants)
    tier = hardware_tier(mv.est_memory_gb_4k if mv else None)

    warnings: list[str] = []
    if params_total is None:
        warnings.append("incomplete: no specs resolved (no params)")

    return ModelEntry(
        id=seed.id, name=seed.name, family=seed.family, backer=seed.backer,
        hf_repo=seed.hf_repo, ollama_name=seed.ollama_name,
        params_total=params_total, params_active=seed.params_active,
        num_layers=num_layers, hidden_size=hidden, context_length=context,
        modality=_modality(seed, hf), license=license_, openness=openness,
        hf_downloads=(hf.downloads if hf else None),
        hf_likes=(hf.likes if hf else None),
        last_modified=(hf.last_modified if hf else None),
        hardware_tier=tier, quants=quants, warnings=warnings,
    )
```

- [ ] **Step 4: Run test + commit**

Run: `pytest tests/test_models_radar_assemble.py -v` → PASS (4 tests).

```bash
git add src/radar/models_radar/assemble.py tests/test_models_radar_assemble.py
git commit -m "feat(models): assemble ModelEntry (merge seed+HF+Ollama, compute memory+tier)"
```

---

### Task 7: Scan orchestration

**Files:**
- Create: `src/radar/models_radar/scan.py`
- Test: `tests/test_models_radar_scan.py`

**Interfaces:**
- Consumes: `load_model_seed` (Task 3), `fetch_hf_model` (Task 4), `fetch_ollama_quants` (Task 5),
  `build_model_entry` (Task 6), `ModelEntry` (Task 1).
- Produces: `async run_model_scan(seed_path, client) -> list[ModelEntry]` — runs collectors
  per enabled seed (HF when `hf_repo` set, Ollama when `ollama_name` set), assembles, returns
  entries sorted by `id`. Best-effort per model.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_models_radar_scan.py
from __future__ import annotations

from pathlib import Path

import pytest

from radar.models_radar.scan import run_model_scan


class FakeResp:
    def __init__(self, p): self._p = p
    def raise_for_status(self): pass
    def json(self): return self._p


class FakeClient:
    def __init__(self, routes): self.routes = routes
    async def get(self, url, **kw):
        for frag, payload in self.routes.items():
            if frag in url:
                return FakeResp(payload)
        raise AssertionError(f"unexpected {url}")


@pytest.mark.asyncio
async def test_scan_assembles_entries_for_seed(tmp_path: Path):
    seed = tmp_path / "model-seed.yaml"
    seed.write_text(
        "models:\n"
        "  - id: llama-3.1-8b\n    name: Llama 3.1 8B\n    family: Llama\n"
        "    hf_repo: meta-llama/Llama-3.1-8B\n",
        encoding="utf-8",
    )
    client = FakeClient({
        "api/models/meta-llama/Llama-3.1-8B": {
            "downloads": 100, "likes": 5, "safetensors": {"total": 8000000000},
            "cardData": {"license": "apache-2.0"}, "pipeline_tag": "text-generation",
            "siblings": [{"rfilename": "model.Q4_K_M.gguf"}],
        },
        "raw/main/config.json": {"num_hidden_layers": 32, "hidden_size": 4096,
                                 "max_position_embeddings": 131072},
    })
    entries = await run_model_scan(seed, client)
    assert len(entries) == 1
    m = entries[0]
    assert m.id == "llama-3.1-8b" and m.params_total == 8000000000
    assert m.quants and m.hardware_tier.value == "laptop"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_models_radar_scan.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement**

```python
# src/radar/models_radar/scan.py
"""Run the model collectors over the seed and assemble ModelEntry list."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from radar.models_radar.assemble import build_model_entry
from radar.models_radar.collectors.huggingface import fetch_hf_model
from radar.models_radar.collectors.ollama import fetch_ollama_quants
from radar.models_radar.entities import ModelEntry
from radar.models_radar.seed import load_model_seed


async def run_model_scan(seed_path: Path, client: Any) -> list[ModelEntry]:
    """Collect + assemble one ModelEntry per enabled seed. Best-effort per model."""
    seeds = load_model_seed(seed_path)
    entries: list[ModelEntry] = []
    for seed in seeds:
        if not seed.enabled:
            continue
        hf = await fetch_hf_model(seed.hf_repo, client) if seed.hf_repo else None
        ollama = await fetch_ollama_quants(seed.ollama_name, client) if seed.ollama_name else []
        entries.append(build_model_entry(seed, hf, ollama))
    return sorted(entries, key=lambda m: m.id)
```

- [ ] **Step 4: Run test + commit**

Run: `pytest tests/test_models_radar_scan.py -v` → PASS.

```bash
git add src/radar/models_radar/scan.py tests/test_models_radar_scan.py
git commit -m "feat(models): scan orchestration over the model seed"
```

---

### Task 8: `radar models` CLI (scan + list)

**Files:**
- Modify: `src/radar/cli.py` (add a `models` sub-app near the `seed` sub-app at lines 27-28)
- Test: `tests/test_models_radar_cli.py`

**Interfaces:**
- Consumes: `run_model_scan` (Task 7), `RunStore` (existing, `create_run`/`save_stage`/`list_runs`/`read_meta`/`_run_dir`).
- Produces: CLI `radar models scan --root .` (writes `model_cards.json` to a new run dir via RunStore) and
  `radar models list --root .` (reads the latest run's `model_cards.json`, prints id · tier · min-memory · ring-not-yet).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_models_radar_cli.py
from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from radar.cli import app


def test_models_list_reads_latest_scan(tmp_path: Path, monkeypatch):
    runner = CliRunner()
    runner.invoke(app, ["init", "--root", str(tmp_path)])

    # Stub the scan so the CLI test stays offline.
    from radar.models_radar.entities import HardwareTier, ModelEntry, QuantVariant

    async def fake_scan(seed_path, client):
        return [ModelEntry(id="llama-3.1-8b", name="Llama 3.1 8B", family="Llama",
                           hardware_tier=HardwareTier.LAPTOP,
                           quants=[QuantVariant(format="GGUF Q4_K_M", bits_per_weight=4.5,
                                                est_memory_gb_4k=5.4)])]
    monkeypatch.setattr("radar.models_radar.scan.run_model_scan", fake_scan)

    scan_result = runner.invoke(app, ["models", "scan", "--root", str(tmp_path)])
    assert scan_result.exit_code == 0, scan_result.stdout

    list_result = runner.invoke(app, ["models", "list", "--root", str(tmp_path)])
    assert list_result.exit_code == 0, list_result.stdout
    assert "llama-3.1-8b" in list_result.stdout
    assert "laptop" in list_result.stdout
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_models_radar_cli.py -v`
Expected: FAIL (no `models` command).

- [ ] **Step 3: Implement**

In `src/radar/cli.py`, after the `seed_app` registration (line 28), add:

```python
models_app = typer.Typer(help="Local-model radar (catalog + specs).", no_args_is_help=True)
app.add_typer(models_app, name="models")
```

Add the two commands (place near the other command defs):

```python
@models_app.command("scan")
def models_scan(root: Path = typer.Option(Path("."), help="Project root.")) -> None:
    """Collect model specs from HF + Ollama + seed; write a model_cards.json run."""
    import asyncio
    import json as _json

    import httpx

    from radar.models_radar.scan import run_model_scan
    from radar.storage.run_store import RunStore

    seed_path = root / "config" / "model-seed.yaml"
    if not seed_path.exists():
        # fall back to the packaged seed
        seed_path = Path(__file__).resolve().parents[2] / "config" / "model-seed.yaml"

    async def _run():
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            return await run_model_scan(seed_path, client)

    entries = asyncio.run(_run())
    run_store = RunStore(root / "data" / "runs")
    run_id = run_store.create_run()
    run_store.save_stage(run_id, "model_cards", [m.model_dump(mode="json") for m in entries])
    run_store.update_meta(run_id, {"kind": "models", "model_count": len(entries)})
    console.print(f"Scanned {len(entries)} models → run {run_id}")


@models_app.command("list")
def models_list(root: Path = typer.Option(Path("."), help="Project root.")) -> None:
    """List models from the latest model scan."""
    import json as _json

    from radar.storage.run_store import RunStore

    run_store = RunStore(root / "data" / "runs")
    model_run = None
    for rid in reversed(run_store.list_runs()):
        if run_store.read_meta(rid).get("kind") == "models":
            model_run = rid
            break
    if model_run is None:
        console.print("[yellow]No model scan yet. Run [bold]radar models scan[/bold] first.[/yellow]")
        return
    cards_path = run_store._run_dir(model_run) / "model_cards.json"
    entries = _json.loads(cards_path.read_text(encoding="utf-8"))
    console.print(f"{len(entries)} models (run {model_run}):")
    for m in entries:
        quants = m.get("quants") or []
        mems = [q["est_memory_gb_4k"] for q in quants
                if q.get("est_memory_gb_4k") and q.get("bits_per_weight", 0) >= 4.0]
        min_mem = f"{min(mems):.1f}GB" if mems else "?"
        console.print(
            f"  {m['id']:<28} {m.get('hardware_tier','unknown'):<16} "
            f"min~{min_mem:<9} {m.get('family','')}",
            highlight=False,
        )
```

> The `save_stage` call writes `model_cards.json` because `RunStore.save_stage`
> names the file `<stage>.json`. Confirm that against `run_store.py` and adjust
> the read path in `models_list` if the naming differs.

- [ ] **Step 4: Run test + commit**

Run: `pytest tests/test_models_radar_cli.py -v` → PASS.
Run: `ruff check src tests && mypy src` → clean.

```bash
git add src/radar/cli.py tests/test_models_radar_cli.py
git commit -m "feat(models): radar models scan + list CLI"
```

---

### Task 9: Full-gate + live smoke + merge

**Files:** none (verification only).

- [ ] **Step 1: Gates** — `ruff check src tests && mypy src && pytest -q` → all green.
- [ ] **Step 2: Live smoke — HF (no key):** run `fetch_hf_model("Qwen/Qwen3-8B", httpx.AsyncClient(follow_redirects=True))` → confirm non-None with `params_total`, a `context_length`, and ≥1 quant format. If the HF JSON shape differs from the fixtures, fix the parse and re-run the unit tests.
- [ ] **Step 3: Live smoke — Ollama:** run `fetch_ollama_quants("llama3.1", httpx.AsyncClient(follow_redirects=True))` → confirm quant tags + sizes. If the endpoint/JSON differs, fix `OLLAMA_TAGS_URL`/parse and re-run unit tests. **Do not skip — the SP1 arXiv bug was exactly an endpoint/redirect mismatch unit tests missed.**
- [ ] **Step 4: End-to-end:** `radar models scan --root .` then `radar models list --root .` → real models with sane hardware tiers and min-memory; spot-check that an 8B Q4 lands `laptop` and a 30B+ model lands higher.
- [ ] **Step 5: Merge** to main (`--no-ff`) and delete the branch:

```bash
git checkout main && git merge --no-ff feature/local-model-radar \
  -m "Merge feature/local-model-radar (Plan A): local-model catalog core"
git branch -d feature/local-model-radar
```

---

## Self-Review

**Spec coverage (Plan A scope):** Entity & data model (§1) → Task 1. Memory estimator (§2) → Task 2. Hardware tier (§3, tier portion) → Task 2. Sources/collectors (§4: HF, Ollama, manual-via-seed) → Tasks 3-5. Assembly (quant memory, min-viable, tier) → Task 6. Pipeline (§7, scan + CLI portion) → Tasks 7-8. Error handling (best-effort degradation) → Tasks 4,5,6,7. Testing → every task + Task 9 live smoke. **Deferred to Plan B (intentionally, stated in plan header):** adoption ring/scoring (§3 ring portion), model_metrics time-series + model-history + momentum (§5), dashboard/MCP/reports surface (§6), discovery proposals (§5), daily-scan stage integration (§7). No in-scope spec item is unmapped.

**Placeholder scan:** Two implementer notes ask for live-endpoint confirmation of the HF/Ollama JSON shapes and the `save_stage` filename — these are deliberate verification steps with concrete fallbacks, not unfinished code; every code step has complete code. No TBD/TODO/"handle edge cases".

**Type consistency:** `HFModelData`/`OllamaQuant`/`ModelSeed`/`QuantVariant`/`ModelEntry` field names are used identically across Tasks 4→6, 5→6, 1→6→7. `estimate_memory_gb(params_total, bits_per_weight, context, num_layers, hidden_size)` signature matches between Task 2 and its caller in Task 6. `build_model_entry(seed, hf, ollama_quants)` matches Task 6 ↔ Task 7. `run_model_scan(seed_path, client)` matches Task 7 ↔ Task 8 (and the Task 8 monkeypatch targets `radar.models_radar.scan.run_model_scan`). `hardware_tier` values (`laptop`/`single_gpu`/…) consistent across Tasks 2, 6, 8.
