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
    weights are NVFP4, and that per-layer detail lives nested under
    `quantized_layers.<layer path>.quant_algo` (values like "W4A16_NVFP4",
    "FP8") and/or `config_groups.<group>.quant_algo`. Such repos are still
    NVFP4 releases in every practical sense, so we look past the top-level
    label when it says MIXED_PRECISION — but only at those two known
    sub-trees' `quant_algo` values, never a blind scan of the whole
    quantization_config (an unrelated free-text field or a boolean flag
    mentioning "nvfp4" must not cause a false positive).
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
    if algo == "MIXED_PRECISION" and any(
        "NVFP4" in a.upper() for a in _mixed_precision_quant_algos(qc)
    ):
        return "NVFP4"
    return None


def _mixed_precision_quant_algos(qc: dict) -> list[str]:
    """Per-layer/per-group `quant_algo` strings from ModelOpt's mixed-precision
    sub-trees only — `config_groups` and `quantized_layers` — verified against
    the live nvidia/Qwen3.6-27B-NVFP4 shape, where
    `quantized_layers.<layer>.quant_algo` carries values like "W4A16_NVFP4"
    and "FP8" (config_groups itself only carries bit-width/type there, but
    other ModelOpt schema versions may put a `quant_algo` per group, so both
    sub-trees are walked). Deliberately scoped: no other key of
    quantization_config (e.g. "ignore", "producer", a hypothetical
    "description") is inspected.
    """
    algos: list[str] = []
    for section_key in ("config_groups", "quantized_layers"):
        section = qc.get(section_key)
        if isinstance(section, dict):
            for entry in section.values():
                algos.extend(_collect_quant_algo_values(entry))
    return algos


def _collect_quant_algo_values(node: object) -> list[str]:
    """Recursively pull string values found under a `quant_algo` key."""
    values: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "quant_algo" and isinstance(value, str):
                values.append(value)
            else:
                values.extend(_collect_quant_algo_values(value))
    elif isinstance(node, list):
        for item in node:
            values.extend(_collect_quant_algo_values(item))
    return values


def _attention_kind(
    cfg: dict, heads: int | None, kv_heads: int | None, kv_lora_rank: int | None
) -> AttentionKind:
    if kv_lora_rank:
        return AttentionKind.MLA
    layer_types = cfg.get("layer_types")
    if isinstance(layer_types, list) and _distinct_count(layer_types) > 1:
        return AttentionKind.HYBRID
    if heads and kv_heads:
        return AttentionKind.GQA if kv_heads < heads else AttentionKind.MHA
    return AttentionKind.UNKNOWN


def _distinct_count(values: list) -> int:
    """len(set(values)) that tolerates unhashable junk entries (e.g. dicts)."""
    try:
        return len(set(values))
    except TypeError:
        seen: list = []
        for v in values:
            if v not in seen:
                seen.append(v)
        return len(seen)


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
