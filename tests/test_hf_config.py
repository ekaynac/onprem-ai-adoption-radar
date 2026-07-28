"""Pure parsers for HF config.json → ArchitectureSpec / quant format."""

from radar.models_radar.entities import AttentionKind
from radar.models_radar.hf_config import parse_architecture, parse_quant_format


LLAMA_31_8B = {  # meta-llama/Llama-3.1-8B-Instruct
    # Verified live 2026-07-28 via unsloth/Meta-Llama-3.1-8B-Instruct and
    # NousResearch/Meta-Llama-3.1-8B-Instruct (the meta-llama repo itself is
    # gated). Exact match, no correction needed.
    "num_hidden_layers": 32, "hidden_size": 4096,
    "num_attention_heads": 32, "num_key_value_heads": 8,
    "vocab_size": 128256, "max_position_embeddings": 131072,
}

DEEPSEEK_V3 = {  # deepseek-ai/DeepSeek-V3
    # Verified live 2026-07-28 directly. Exact match, no correction needed.
    # (Live config additionally carries num_key_value_heads=128, equal to
    # num_attention_heads=128 — irrelevant here since kv_lora_rank presence
    # forces MLA regardless of head-count comparison. Live quantization_config
    # is quant_method="fp8", confirming the FP8 mapping too.)
    "num_hidden_layers": 61, "hidden_size": 7168,
    "num_attention_heads": 128, "kv_lora_rank": 512, "qk_rope_head_dim": 64,
    "n_routed_experts": 256, "num_experts_per_tok": 8, "vocab_size": 129280,
}

MIXTRAL_8X7B = {  # mistralai/Mixtral-8x7B-Instruct-v0.1
    # Verified live 2026-07-28 directly. Exact match, no correction needed.
    "num_hidden_layers": 32, "hidden_size": 4096,
    "num_attention_heads": 32, "num_key_value_heads": 8,
    "num_local_experts": 8, "num_experts_per_tok": 2, "sliding_window": None,
}

GLM_STYLE = {  # zai-org/glm-4-9b-chat (classic ChatGLM lineage)
    # Verified live 2026-07-28: zai-org/glm-4-9b-chat carries exactly
    # num_attention_heads=32, multi_query_group_num=2. Note the newer
    # GLM-MoE family (e.g. zai-org/GLM-4.5-Air) has moved to a standard
    # num_key_value_heads key instead — multi_query_group_num is specific
    # to the classic ChatGLM-style configs, not GLM generally.
    "num_attention_heads": 32, "multi_query_group_num": 2, "hidden_size": 4096,
}

GEMMA3_HYBRID = {  # alternating sliding/full attention layout
    # Verified live 2026-07-28: `layer_types` (a list of per-layer attention
    # kinds) is real and exactly this shape on openai/gpt-oss-20b and the
    # nested text_config of nvidia/Qwen3.6-27B-NVFP4. It is NOT what Gemma 3
    # itself emits, though — google/gemma-3-1b-it and the gemma-3-12b-it
    # mirror (unsloth/gemma-3-12b-it; the official repo is gated) instead
    # ship `sliding_window_pattern: 6` (an integer stride, no explicit list).
    # Kept as GEMMA3_HYBRID for continuity with the brief; it exercises the
    # layer_types→HYBRID path shared by gpt-oss/Qwen3-Next-style configs.
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


def test_quant_format_modelopt_mixed_precision_resolves_nvfp4():
    """nvidia/Qwen3.6-27B-NVFP4 (verified live 2026-07-28): the repo's own
    top-level quant_algo is "MIXED_PRECISION", not "NVFP4" — modelopt keeps
    some layers (attention, embeddings) at FP8 for stability and only the
    bulk of MLP weights at NVFP4. The per-layer signal lives nested under
    config_groups. The repo is still an NVFP4 release in every practical
    sense, so the parser must look past the top-level algo label."""
    assert parse_quant_format({
        "quantization_config": {
            "quant_method": "modelopt",
            "quant_algo": "MIXED_PRECISION",
            "config_groups": {
                "group_0": {"weights": {"num_bits": 8, "type": "float"}},
                "group_1": {"weights": {"quant_algo": "W4A16_NVFP4"}},
            },
        }
    }) == "NVFP4"
