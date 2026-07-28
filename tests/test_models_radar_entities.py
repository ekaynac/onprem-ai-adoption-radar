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


def test_architecture_spec_defaults_and_frozen():
    from radar.models_radar.entities import ArchitectureSpec, AttentionKind

    arch = ArchitectureSpec()
    assert arch.attention_kind is AttentionKind.UNKNOWN
    assert arch.num_key_value_heads is None

    with pytest.raises(ValidationError):
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
