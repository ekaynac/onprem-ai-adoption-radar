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
    # v2: no architecture -> legacy MHA KV bound from hidden_size.
    # weights = 8B*4.5/8/1e9 = 4.5 GB; *FRAGMENTATION(1.05) = 4.725
    # kv = 2*hidden_size(4096)*2bytes*layers(32) = 524288 bytes/token;
    #      kv_gb at 4096 tokens = 524288*4096/1e9 = 2.147... -> rounds to 2.15
    # total = 4.725 + 2.15 + 1.5 = 8.375 -> rounds to 8.38 (band [7.5, 9.0])
    q4 = next(q for q in m.quants if q.bits_per_weight == 4.5 and q.est_memory_gb_4k)
    assert 7.5 <= q4.est_memory_gb_4k <= 9.0
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


def test_ollama_tags_filtered_to_model_size():
    # Seeds sharing ollama_name="qwen3" pull the whole family's tags; an 8B model
    # must keep only the 8B tags, not the 30B ones.
    seed = ModelSeed(id="qwen3-8b", name="Qwen3 8B", family="Qwen3",
                     params_total=8_000_000_000, ollama_name="qwen3")
    ollama = [
        OllamaQuant(tag="qwen3:8b-q4_K_M", size_gb=4.9, bits_per_weight=4.5, param_label="8B"),
        OllamaQuant(tag="qwen3:30b-a3b-q4_K_M", size_gb=17.5, bits_per_weight=4.5, param_label="30B"),
    ]
    m = build_model_entry(seed, None, ollama)
    ollama_formats = [q.format for q in m.quants if q.source.startswith("ollama")]
    assert "Ollama qwen3:8b-q4_K_M" in ollama_formats
    assert "Ollama qwen3:30b-a3b-q4_K_M" not in ollama_formats


def test_ollama_tags_filtered_by_name_token_when_label_empty():
    # The featured /api/tags endpoint leaves parameter_size empty; size is then only
    # in the tag name. A 12B model must drop the 4B and 27B family tags.
    seed = ModelSeed(id="gemma-3-12b", name="Gemma 3 12B", family="Gemma",
                     params_total=12_000_000_000, ollama_name="gemma3")
    ollama = [
        OllamaQuant(tag="gemma3:4b", size_gb=3.3, bits_per_weight=4.5, param_label=""),
        OllamaQuant(tag="gemma3:12b", size_gb=8.1, bits_per_weight=4.5, param_label=""),
        OllamaQuant(tag="gemma3:27b", size_gb=17.0, bits_per_weight=4.5, param_label=""),
    ]
    m = build_model_entry(seed, None, ollama)
    ollama_formats = [q.format for q in m.quants if q.source.startswith("ollama")]
    assert ollama_formats == ["Ollama gemma3:12b"]


def test_ollama_tags_without_label_or_params_are_kept():
    # No resolvable param count → cannot disprove any tag, so keep them all.
    seed = ModelSeed(id="x", name="X", family="F", ollama_name="x")
    ollama = [OllamaQuant(tag="x:q4_K_M", size_gb=4.9, bits_per_weight=4.5, param_label=None)]
    m = build_model_entry(seed, None, ollama)
    assert any(q.format == "Ollama x:q4_K_M" for q in m.quants)


def test_synthesizes_default_quants_when_none_collected():
    seed = ModelSeed(
        id="x",
        name="X",
        family="F",
        params_total=8_000_000_000,
        num_layers=32,
        hidden_size=4096,
        context_length=4096,
    )
    m = build_model_entry(seed, None, [])
    assert m.quants, "expected synthesized quants"
    q4 = next((q for q in m.quants if q.format == "Q4_K_M"), None)
    assert q4 is not None, "Q4_K_M should be in synthesized ladder"
    assert q4.source == "synthesized"
    assert q4.est_memory_gb_4k is not None and q4.est_memory_gb_4k > 0
    assert m.hardware_tier == HardwareTier.LAPTOP


def test_build_carries_release_date_and_use_case():
    seed = ModelSeed(id="x", name="X", family="F", params_total=8_000_000_000,
                     release_date="2025-01", use_case="reasoning")
    m = build_model_entry(seed, None, [])
    assert m.release_date == "2025-01" and m.use_case == "reasoning"


def test_synthesized_ladder_includes_mlx_and_q6():
    seed = ModelSeed(id="x", name="X", family="F", params_total=8_000_000_000,
                     num_layers=32, hidden_size=4096, context_length=4096)
    m = build_model_entry(seed, None, [])
    formats = {q.format for q in m.quants}
    assert {"Q4_K_M", "Q6_K", "Q8_0", "FP16"} <= formats
    assert any(q.platform == Platform.APPLE_MLX for q in m.quants)
    assert {"MLX-4bit", "MLX-8bit"} <= formats


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

    # v2: NVFP4 uses E4M3 scales per 16 elements (+0.5 bit -> 4.5), distinct
    # from MXFP4's coarser E8M0 scales per 32 elements (+0.25 bit -> 4.25).
    assert bits_for_format("NVFP4") == 4.5
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


def test_gated_flag_sets_openness_gated_when_seed_silent():
    from radar.models_radar.collectors.huggingface import HFModelData

    seed = ModelSeed(id="m-g", name="M-G", family="M", hf_repo="org/m-g")
    hf = HFModelData(params_total=8_000_000_000, license="llama3.1", gated=True)
    entry = build_model_entry(seed, hf, [])
    assert entry.openness == Openness.GATED


def test_seed_openness_wins_over_gated_flag():
    from radar.models_radar.collectors.huggingface import HFModelData

    seed = ModelSeed(
        id="m-g2", name="M-G2", family="M", hf_repo="org/m-g2",
        openness=Openness.OPEN_RESTRICTED,
    )
    hf = HFModelData(params_total=8_000_000_000, license="llama3.1", gated=True)
    entry = build_model_entry(seed, hf, [])
    assert entry.openness == Openness.OPEN_RESTRICTED
