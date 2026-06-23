"""Merge a seed + collector data into a fully-specced ModelEntry."""

from __future__ import annotations

from radar.models_radar.collectors.huggingface import HFModelData
from radar.models_radar.collectors.ollama import (
    OllamaQuant,
    param_billions,
    tag_param_billions,
)
from radar.models_radar.entities import (
    Modality,
    ModelEntry,
    ModelSeed,
    Openness,
    Platform,
    QuantVariant,
)
from radar.models_radar.memory import estimate_memory_gb, hardware_tier, minimum_viable_quant


_PERMISSIVE = {"apache-2.0", "mit", "bsd-3-clause", "apache-2", "openrail"}
_BITS_BY_FORMAT = {
    "q2": 2.6, "q3": 3.4, "q4": 4.5, "q5": 5.5, "q6": 6.6,
    "q8": 8.0, "fp16": 16.0, "f16": 16.0, "bf16": 16.0,
    "awq": 4.0, "gptq": 4.0, "mlx-4bit": 4.5, "mlx-8bit": 8.0,
}
_REF_4K = 4096
_REF_32K = 32768
_DEFAULT_QUANT_LADDER = [("Q4_K_M", 4.5), ("Q5_K_M", 5.5), ("Q8_0", 8.0), ("FP16", 16.0)]
# Seeds that share an ``ollama_name`` (e.g. both Qwen3 sizes use "qwen3") pull the
# whole family's tag list; keep only tags whose parameter size (from the API label
# or the tag-name token) is within this fraction of the model's resolved param
# count. Tags with no parseable size are kept (we can't disprove them).
_OLLAMA_SIZE_TOLERANCE = 0.2


def bits_for_format(fmt: str) -> float:
    """Return bits-per-weight for a quant format string (default Q4-class)."""
    low = fmt.lower()
    for key, bits in _BITS_BY_FORMAT.items():
        if key in low:
            return bits
    return 4.5


def openness_from_license(license: str | None) -> Openness | None:
    """Map a license identifier to an Openness enum value, or None if unknown."""
    if not license:
        return None
    low = license.lower()
    if low in _PERMISSIVE:
        return Openness.OPEN_PERMISSIVE
    return Openness.OPEN_RESTRICTED


def _modality(seed: ModelSeed, hf: HFModelData | None) -> Modality:
    if seed.modality is not None:
        return seed.modality
    tag = (hf.modality_tag if hf else None) or ""
    if "image" in tag or "vision" in tag:
        return Modality.VISION
    if "audio" in tag or "speech" in tag:
        return Modality.AUDIO
    return Modality.TEXT


def build_model_entry(
    seed: ModelSeed,
    hf: HFModelData | None,
    ollama_quants: list[OllamaQuant],
) -> ModelEntry:
    """Merge order: manual seed overrides win over collected HF/Ollama data."""
    params_total = seed.params_total or (hf.params_total if hf else None)
    num_layers = seed.num_layers or (hf.num_layers if hf else None)
    hidden = seed.hidden_size or (hf.hidden_size if hf else None)
    context = seed.context_length or (hf.context_length if hf else None)
    license_ = seed.license or (hf.license if hf else None)
    openness = seed.openness or openness_from_license(license_)

    quants: list[QuantVariant] = []
    seen: set[tuple[str, Platform]] = set()

    def add(
        fmt: str,
        bits: float,
        platform: Platform,
        source: str,
        size_gb: float | None = None,
    ) -> None:
        key = (fmt, platform)
        if key in seen:
            return
        seen.add(key)
        ctx = context or _REF_4K
        quants.append(
            QuantVariant(
                format=fmt,
                bits_per_weight=bits,
                platform=platform,
                source=source,
                file_size_gb=size_gb,
                est_memory_gb_4k=estimate_memory_gb(params_total, bits, _REF_4K, num_layers, hidden),
                # Full estimate at 32k context including KV cache when architecture
                # (layers + hidden_size) is known.
                est_memory_gb_32k=estimate_memory_gb(
                    params_total,
                    bits,
                    min(_REF_32K, ctx) if context else _REF_32K,
                    num_layers,
                    hidden,
                ),
            )
        )

    for q in seed.manual_quants:  # manual first (authoritative)
        add(q.format, q.bits_per_weight, q.platform, "manual", q.file_size_gb)
    if hf:
        for fmt in hf.quant_formats:
            add(fmt, bits_for_format(fmt), Platform.GENERIC, f"hf:{seed.hf_repo}")
    for oq in _ollama_quants_for_size(ollama_quants, params_total):
        add(
            f"Ollama {oq.tag}",
            oq.bits_per_weight,
            Platform.GENERIC,
            f"ollama:{seed.ollama_name}",
            oq.size_gb,
        )

    if not quants and params_total is not None:
        for fmt, bits in _DEFAULT_QUANT_LADDER:
            add(fmt, bits, Platform.GENERIC, "synthesized")

    mv = minimum_viable_quant(quants)
    tier = hardware_tier(mv.est_memory_gb_4k if mv else None)

    warnings: list[str] = []
    if params_total is None:
        warnings.append("incomplete: no specs resolved (no params)")

    return ModelEntry(
        id=seed.id,
        name=seed.name,
        family=seed.family,
        backer=seed.backer,
        hf_repo=seed.hf_repo,
        ollama_name=seed.ollama_name,
        params_total=params_total,
        params_active=seed.params_active,
        num_layers=num_layers,
        hidden_size=hidden,
        context_length=context,
        modality=_modality(seed, hf),
        license=license_,
        openness=openness,
        hf_downloads=(hf.downloads if hf else None),
        hf_likes=(hf.likes if hf else None),
        last_modified=(hf.last_modified if hf else None),
        hardware_tier=tier,
        quants=quants,
        warnings=warnings,
    )


def _ollama_quants_for_size(
    quants: list[OllamaQuant],
    params_total: int | None,
) -> list[OllamaQuant]:
    """Drop Ollama tags whose advertised parameter size doesn't match this model.

    Seeds that share an ``ollama_name`` otherwise inherit the whole family's tags
    (e.g. a 8B model picking up ``qwen3:30b-*``). Tags without a parseable size
    label, or any model with no resolved param count, pass through unchanged.
    """
    if params_total is None:
        return quants
    target_b = params_total / 1e9
    kept: list[OllamaQuant] = []
    for q in quants:
        # Prefer the API's parameter-size label; fall back to the size token in the
        # tag name (the label is often empty on the featured /api/tags endpoint).
        size_b = param_billions(q.param_label) or tag_param_billions(q.tag)
        if size_b is None or abs(size_b - target_b) <= _OLLAMA_SIZE_TOLERANCE * target_b:
            kept.append(q)
    return kept
