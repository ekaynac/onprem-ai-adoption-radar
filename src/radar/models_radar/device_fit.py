"""Deterministic model↔device fit evaluation.

Compares each quant's estimated memory (recomputed at the requested context via
the shared estimator, falling back to the stored 4K estimate) against the
device's usable memory. No LLM; identical inputs → identical verdict.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from radar.models_radar.devices import DeviceProfile, usable_memory_gb
from radar.models_radar.entities import ModelEntry, QuantVariant
from radar.models_radar.memory import VIABLE_MIN_BITS, estimate_memory_gb


# Fraction of usable memory above which a fit is "tight". Also injected into the
# dashboard picker JS, so the row-coloring threshold stays a single source of truth.
TIGHT_FRACTION = 0.95


class ModelFit(BaseModel):
    """Whether a model fits a device, and at which quant."""

    model_config = ConfigDict(frozen=True)

    model_id: str
    device_name: str
    usable_gb: float
    verdict: str  # fits | fits_tight | fits_quantized | wont_fit | unknown
    best_quant_format: str | None = None
    best_quant_memory_gb: float | None = None
    context_tokens: int = 4096
    note: str = ""


def _quant_memory(model: ModelEntry, quant: QuantVariant, context_tokens: int) -> float | None:
    """Memory for this quant at the context; estimator, else the stored 4K value."""
    est = estimate_memory_gb(
        model.params_total, quant.bits_per_weight, context_tokens,
        model.num_layers, model.hidden_size, architecture=model.architecture,
    )
    return est if est is not None else quant.est_memory_gb_4k


def evaluate_fit(
    model: ModelEntry, device: DeviceProfile, context_tokens: int = 4096,
) -> ModelFit:
    usable = usable_memory_gb(device)
    base = ModelFit(model_id=model.id, device_name=device.name, usable_gb=usable,
                    verdict="unknown", context_tokens=context_tokens)

    raw = [(q, _quant_memory(model, q, context_tokens)) for q in model.quants]
    sized: list[tuple[QuantVariant, float]] = [(q, m) for q, m in raw if m is not None]
    if not sized:
        return base.model_copy(update={"note": "no sized quants"})

    fitting: list[tuple[QuantVariant, float]] = [(q, m) for q, m in sized if m <= usable]
    if not fitting:
        smallest = min(sized, key=lambda qm: qm[1])
        return base.model_copy(update={
            "verdict": "wont_fit",
            "note": f"smallest quant {smallest[0].format} needs ~{smallest[1]} GB > {usable} GB usable",
        })

    # largest quant that fits = highest bits_per_weight among fitting
    best_q, best_m = max(fitting, key=lambda qm: qm[0].bits_per_weight)
    viable_fits: list[tuple[QuantVariant, float]] = [(q, m) for q, m in fitting if q.bits_per_weight >= VIABLE_MIN_BITS]
    if not viable_fits:
        verdict = "fits_quantized"  # only sub-Q4 quants fit
    elif best_m > usable * TIGHT_FRACTION:
        verdict = "fits_tight"
    else:
        verdict = "fits"
    return base.model_copy(update={
        "verdict": verdict, "best_quant_format": best_q.format,
        "best_quant_memory_gb": best_m,
        "note": f"{best_q.format} ~{best_m} GB ≤ {usable} GB usable",
    })


# Decode throughput is bandwidth-bound: bytes moved per token ≈ active
# params × bits/weight ÷ 8. The efficiency factor absorbs KV-cache traffic,
# kernel overhead, and framework variance; published Spark measurements
# (gpt-oss-120b ≈ 60 t/s at 273 GB/s) land near 0.75 of the naive bound.
BANDWIDTH_EFFICIENCY = 0.75

# Interactive-use thresholds (tokens/sec decode).
TPS_UNUSABLE_BELOW = 2.0   # slower than reading pace — prototyping only
TPS_SLOW_BELOW = 8.0       # tolerable for batch work, painful for chat


def estimate_decode_tps(
    model: ModelEntry,
    device: DeviceProfile,
    quant_bits_per_weight: float | None,
) -> float | None:
    """Estimated decode tokens/sec from memory bandwidth and active params.

    Device-agnostic: any profile with ``memory_bandwidth_gbs`` gets scored.
    Dense models (no ``params_active``) use total params — every param is
    active. MoE models must carry their active-params figure; unknown stays
    unknown rather than inventing one from total params.
    """
    if not device.memory_bandwidth_gbs or not quant_bits_per_weight:
        return None
    active = model.params_active or model.params_total
    if not active:
        return None
    bytes_per_token = active * quant_bits_per_weight / 8.0
    raw_tps = device.memory_bandwidth_gbs * 1e9 / bytes_per_token
    return round(raw_tps * BANDWIDTH_EFFICIENCY, 1)


def performance_note(tps: float | None) -> str | None:
    """Human verdict for an estimated tok/s, or None when unestimated."""
    if tps is None:
        return None
    if tps < TPS_UNUSABLE_BELOW:
        return (
            f"~{tps:g} tok/s est. on this device's memory bandwidth — "
            "unusable for interactive use; fine for overnight batch"
        )
    if tps < TPS_SLOW_BELOW:
        return (
            f"~{tps:g} tok/s est. — slow interactive; prefer a lower "
            "quant or an MoE alternative"
        )
    return f"~{tps:g} tok/s est. decode on this device"


_ORDER = {"fits": 0, "fits_tight": 1, "fits_quantized": 2, "wont_fit": 3, "unknown": 4}


def fit_report(
    models: list[ModelEntry], device: DeviceProfile, context_tokens: int = 4096,
) -> list[ModelFit]:
    fits = [evaluate_fit(m, device, context_tokens) for m in models]
    return sorted(fits, key=lambda f: (_ORDER.get(f.verdict, 9), f.best_quant_memory_gb or 1e9))
