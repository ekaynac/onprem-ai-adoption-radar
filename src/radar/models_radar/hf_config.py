"""Pure parsers: HF config.json dict → ArchitectureSpec / quant format.

Family coverage: generic transformer keys (Llama/Qwen/Mistral/Gemma/Phi),
DeepSeek MLA (kv_lora_rank), MoE (DeepSeek/Mixtral/Qwen-MoE key variants),
GLM (multi_query_group_num). Unknown layouts degrade to UNKNOWN, never raise.

Key mappings verified against live `config.json` files 2026-07-28 (see
tests/test_hf_config.py fixture comments for the exact repos checked):
meta-llama/Llama-3.1-8B-Instruct (via ungated mirrors — the original is
gated), deepseek-ai/DeepSeek-V3, mistralai/Mixtral-8x7B-Instruct-v0.1,
zai-org/glm-4-9b-chat (multi_query_group_num), openai/gpt-oss-20b and
nvidia/Qwen3.6-27B-NVFP4 (layer_types), TheBloke AWQ/GPTQ examples, and
nvidia/Qwen3.6-27B-NVFP4's quantization_config (modelopt MIXED_PRECISION).
"""

from __future__ import annotations

import json

from radar.models_radar.entities import ArchitectureSpec, AttentionKind


_QUANT_METHOD_FORMATS = {
    "fp8": "FP8",
    "mxfp4": "MXFP4",
    "awq": "AWQ",
    "gptq": "GPTQ",
}


def parse_architecture(cfg: dict) -> ArchitectureSpec:
    """Extract attention/MoE geometry. Missing keys stay None — never guess.

    `cfg` is expected to be a dict, but this is the boundary where a live
    HF fetch (Task 3) lands raw JSON — a malformed response (empty body,
    a JSON array/string/null instead of an object) must degrade to
    ArchitectureSpec(), never raise.
    """
    if not isinstance(cfg, dict):
        return ArchitectureSpec()
    heads = _int(cfg.get("num_attention_heads"))
    kv_heads = _int(cfg.get("num_key_value_heads")) or _int(cfg.get("multi_query_group_num"))
    hidden = _int(cfg.get("hidden_size"))
    head_dim = _int(cfg.get("head_dim"))
    if head_dim is None and heads and hidden:
        head_dim = hidden // heads
    kv_lora_rank = _int(cfg.get("kv_lora_rank"))
    num_experts = (
        _int(cfg.get("n_routed_experts"))
        or _int(cfg.get("num_local_experts"))
        or _int(cfg.get("num_experts"))
    )
    return ArchitectureSpec(
        attention_kind=_attention_kind(cfg, heads, kv_heads, kv_lora_rank),
        num_attention_heads=heads,
        num_key_value_heads=kv_heads,
        head_dim=head_dim,
        kv_lora_rank=kv_lora_rank,
        qk_rope_head_dim=_int(cfg.get("qk_rope_head_dim")),
        num_experts=num_experts,
        experts_per_token=_int(cfg.get("num_experts_per_tok")),
        sliding_window=_int(cfg.get("sliding_window")),
        vocab_size=_int(cfg.get("vocab_size")),
    )


def parse_quant_format(cfg: dict) -> str | None:
    """Canonical quant label when the repo's weights are themselves quantized.

    Most repos declare a single `quant_method` (fp8/mxfp4/awq/gptq) or a
    `quant_algo` that directly names NVFP4. Some NVIDIA ModelOpt NVFP4
    releases (verified live: nvidia/Qwen3.6-27B-NVFP4) instead report a
    top-level `quant_algo` of "MIXED_PRECISION" — a handful of layers (attention,
    embeddings) stay FP8 for numerical stability while the bulk of the MLP
    weights are NVFP4, and that per-layer detail is nested under
    `config_groups`. Such repos are still NVFP4 releases in every practical
    sense, so we look past the top-level label when it says MIXED_PRECISION.
    """
    if not isinstance(cfg, dict):
        return None
    qc = cfg.get("quantization_config")
    if not isinstance(qc, dict):
        return None
    method = str(qc.get("quant_method") or "").lower()
    algo = str(qc.get("quant_algo") or "").upper()
    if "NVFP4" in algo or method == "nvfp4":
        return "NVFP4"
    direct = _QUANT_METHOD_FORMATS.get(method)
    if direct:
        return direct
    if algo == "MIXED_PRECISION" and _nested_contains_nvfp4(qc):
        return "NVFP4"
    return None


def _nested_contains_nvfp4(qc: dict) -> bool:
    """True if any per-layer entry under quantization_config names NVFP4."""
    try:
        return "NVFP4" in json.dumps(qc).upper()
    except (TypeError, ValueError):
        return False


def _attention_kind(
    cfg: dict, heads: int | None, kv_heads: int | None, kv_lora_rank: int | None
) -> AttentionKind:
    if kv_lora_rank:
        return AttentionKind.MLA
    layer_types = cfg.get("layer_types")
    if isinstance(layer_types, list) and len(set(layer_types)) > 1:
        return AttentionKind.HYBRID
    if heads and kv_heads:
        return AttentionKind.GQA if kv_heads < heads else AttentionKind.MHA
    return AttentionKind.UNKNOWN


def _int(value: object) -> int | None:
    """Best-effort int: config values may be int, float, numeric str, or junk."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None
