"""Entities for the local-model radar (separate from the tool DecisionCard)."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from radar.models import Backer, Ring


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
    SINGLE_GPU_DC = "single_gpu_dc"    # one datacenter accelerator (B200/MI300X class)
    SINGLE_NODE = "single_node"        # one multi-GPU HGX-class node (e.g. 8xH200)
    MULTI_NODE = "multi_node"          # beyond a single node's usable memory
    # Legacy-persisted only: no new computation emits this; kept so entries
    # written before the datacenter tier split still deserialize.
    DATACENTER = "datacenter"
    UNKNOWN = "unknown"


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


class ModelScore(BaseModel):
    """Deterministic model-adoption score dimensions (1-5)."""

    model_config = ConfigDict(frozen=True)

    openness: int = Field(ge=1, le=5)
    local_runnability: int = Field(ge=1, le=5)
    capability_tier: int = Field(ge=1, le=5)
    ecosystem_support: int = Field(ge=1, le=5)
    average: float


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
    architecture: ArchitectureSpec | None = None
    context_length: int | None = None
    modality: Modality = Modality.TEXT
    license: str | None = None
    openness: Openness | None = None
    hf_downloads: int | None = None
    hf_likes: int | None = None
    last_modified: str | None = None
    release_date: str | None = None   # ISO date "YYYY-MM" or "YYYY-MM-DD"
    use_case: str | None = None        # short note, e.g. "reasoning", "coding", "general chat"
    hardware_tier: HardwareTier = HardwareTier.UNKNOWN
    quants: list[QuantVariant] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    provenance: dict[str, SpecProvenance] = Field(default_factory=dict)
    benchmarks: list[BenchmarkScore] = Field(default_factory=list)
    score: float | None = None
    score_breakdown: ModelScore | None = None
    ring: Ring | None = None


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
    architecture: ArchitectureSpec | None = None
    context_length: int | None = None
    modality: Modality | None = None
    license: str | None = None
    openness: Openness | None = None
    release_date: str | None = None   # ISO date "YYYY-MM" or "YYYY-MM-DD"
    use_case: str | None = None        # short note, e.g. "reasoning", "coding", "general chat"
    manual_quants: list[QuantVariant] = Field(default_factory=list)
    benchmarks: list[BenchmarkScore] = Field(default_factory=list)
    spec_verified: bool = False
