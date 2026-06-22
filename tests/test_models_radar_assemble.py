from __future__ import annotations

from radar.models_radar.assemble import build_model_entry, openness_from_license
from radar.models_radar.collectors.huggingface import HFModelData
from radar.models_radar.collectors.ollama import OllamaQuant
from radar.models_radar.entities import HardwareTier, ModelSeed, Openness


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
    assert 7.0 <= q4.est_memory_gb_4k <= 9.0
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
