from __future__ import annotations

import pytest
from pydantic import ValidationError

from radar.models_radar.entities import (
    HardwareTier,
    Modality,
    ModelEntry,
    ModelSeed,
    Openness,
    Platform,
    QuantVariant,
)


def test_quant_variant_is_frozen_and_defaults():
    q = QuantVariant(format="GGUF Q4_K_M", bits_per_weight=4.5, platform=Platform.GENERIC)
    assert q.file_size_gb is None and q.est_memory_gb_4k is None
    with pytest.raises(ValidationError):
        q.format = "x"  # type: ignore[misc]


def test_model_entry_minimal_and_frozen():
    m = ModelEntry(id="qwen3-30b-a3b", name="Qwen3-30B-A3B", family="Qwen3")
    assert m.params_active is None and m.quants == [] and m.modality == Modality.TEXT
    with pytest.raises(ValidationError):
        m.name = "x"  # type: ignore[misc]


def test_model_seed_requires_id_and_family():
    s = ModelSeed(id="llama-3.1-8b", name="Llama 3.1 8B", family="Llama",
                  hf_repo="meta-llama/Llama-3.1-8B")
    assert s.ollama_name is None and s.enabled is True


def test_enum_values():
    assert Platform.APPLE_MLX.value == "apple_mlx"
    assert HardwareTier.SINGLE_GPU.value == "single_gpu"
    assert Openness.OPEN_PERMISSIVE.value == "open-permissive"
    assert Modality.MULTIMODAL.value == "multimodal"
