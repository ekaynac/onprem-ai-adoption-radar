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
