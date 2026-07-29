"""Load the bundled platform capability matrix (config/platform-matrix.yaml).

Every hardware/feature cell is a cited claim about a serving engine (vLLM,
SGLang, TensorRT-LLM, ...): does it support this GPU/NPU family, or this
serving feature (MLA, FP8 KV cache, disaggregated prefill, ...)? ``unknown``
is the honest default when a claim couldn't be confirmed from the engine's
own docs/release notes — this seed never guesses "yes".
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


Support = Literal["yes", "partial", "no", "unknown"]

_HARDWARE_KEYS = ("nvidia", "amd", "intel_gaudi", "apple", "ascend", "cpu")
_FEATURE_KEYS = (
    "tensor_parallel", "pipeline_parallel", "expert_parallel",
    "mla", "hybrid_attention", "fp8", "nvfp4", "awq", "gptq", "gguf",
    "kv_cache_fp8", "speculative_decoding", "prefix_caching",
    "disaggregated_prefill",
)


class PlatformMatrixError(ValueError):
    """Raised when the platform matrix seed cannot be loaded."""


def _coerce_support_map(raw: object, valid_keys: tuple[str, ...], field: str) -> dict[str, object]:
    """YAML-1.1 boolean-trap defense + key-subset validation.

    Bare ``yes``/``no`` in YAML 1.1 parse as Python ``True``/``False``, not
    strings — a hand-edited, unquoted ``nvidia: yes`` would otherwise crash
    the ``Support`` literal instead of degrading gracefully. This coerces
    ``True -> "yes"`` and ``False -> "no"`` before the field's real type
    validation runs. It also rejects any key outside the recognized
    hardware/feature set, so a typo'd column fails loudly at load time
    instead of silently seeding an ignored cell.
    """
    if not isinstance(raw, dict):
        raise ValueError(f"{field} must be a mapping, got {type(raw).__name__}")
    coerced: dict[str, object] = {}
    for key, value in raw.items():
        if key not in valid_keys:
            raise ValueError(
                f"Unknown {field} key {key!r} (expected one of {', '.join(valid_keys)})"
            )
        if value is True:
            coerced[key] = "yes"
        elif value is False:
            coerced[key] = "no"
        else:
            coerced[key] = value
    return coerced


class PlatformSeed(BaseModel):
    """One serving-engine entry in config/platform-matrix.yaml."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    name: str
    repo_url: str
    hardware: dict[str, Support]
    features: dict[str, Support]
    sources: list[str] = Field(min_length=1)
    verified: str  # ISO date
    notes: str = ""

    @field_validator("hardware", mode="before")
    @classmethod
    def _coerce_hardware(cls, v: object) -> dict[str, object]:
        return _coerce_support_map(v, _HARDWARE_KEYS, "hardware")

    @field_validator("features", mode="before")
    @classmethod
    def _coerce_features(cls, v: object) -> dict[str, object]:
        return _coerce_support_map(v, _FEATURE_KEYS, "features")


def load_platform_matrix(path: Path) -> list[PlatformSeed]:
    """Load + validate config/platform-matrix.yaml (or a custom path)."""
    try:
        contents = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PlatformMatrixError(f"Platform matrix not found: {path}") from exc
    try:
        raw = yaml.safe_load(contents) or {}
    except yaml.YAMLError as exc:
        raise PlatformMatrixError(f"Invalid YAML in {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise PlatformMatrixError(
            f"Platform matrix {path} must be a mapping with a 'platforms' list"
        )
    try:
        platforms = [PlatformSeed.model_validate(item) for item in raw.get("platforms") or []]
    except ValidationError as exc:
        raise PlatformMatrixError(f"Platform matrix validation failed for {path}: {exc}") from exc
    _check_ids(platforms, path)
    return platforms


def _check_ids(platforms: list[PlatformSeed], path: Path) -> None:
    """Unique, non-empty ids."""
    ids = [p.id for p in platforms]
    if any(not i for i in ids):
        raise PlatformMatrixError(f"Platform matrix {path} has an empty id")
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise PlatformMatrixError(f"Duplicate platform ids in {path}: {', '.join(duplicates)}")
