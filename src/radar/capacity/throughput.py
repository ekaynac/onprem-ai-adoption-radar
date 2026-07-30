"""Roofline throughput model — decode from memory bandwidth, prefill from TFLOPS (spec §6).

This is a *roofline* model: decode throughput is bandwidth-bound (every step
re-reads the weights plus the KV cache once per token), and prefill
throughput is compute-bound (a dense matmul over the whole prompt). Neither
half claims to be a measurement — both are documented estimates gated by a
per-engine efficiency constant, disclosed verbatim in the returned
``AssumptionSheet`` so callers can see exactly which numbers drove the
result.

Decode math, per step, batch ``B = workload.concurrent_requests``:

- ``active = params_active or params_total`` — dense models fall back to
  their total parameter count; MoE models pass ``params_active`` (the
  per-token expert-routed weight count) because decode only ever reads the
  active experts' weights, not the whole checkpoint. An assumption note
  discloses this whenever ``params_active`` is used.
- ``bytes_per_step = active * bits_per_weight / 8 + B * avg_context_tokens *
  kv_bytes_per_token`` — one read of the active weights, plus one read of
  every request's KV cache for the token being generated. When
  ``kv_bytes_per_token`` is ``None`` (no architecture data — see
  ``radar.capacity.kv``), the KV term is dropped to 0 with an assumption
  note; the result is a weights-only lower bound on bytes moved.
- ``aggregate_bw = n_gpus * device.memory_bandwidth_gbs * 1e9 * decode_mbu``
  — peak fleet HBM bandwidth in bytes/sec, scaled by the engine's realized
  fraction (``decode_mbu``, memory-bandwidth utilization).
- ``aggregate_decode_tps = aggregate_bw * B / bytes_per_step``;
  ``per_user_decode_tps = aggregate_decode_tps / B``. Batching amortizes the
  fixed weight-read cost across more requests, so aggregate throughput rises
  with ``B`` (up to the KV-term's own growth) while per-user throughput falls
  — the classic decode-batching trade-off.

``device.memory_bandwidth_gbs is None`` (custom devices built from bare
``{kind, total_memory_gb, gpu_count}`` specs publish no bandwidth figure) is
the ONE condition under which this function returns ``None`` outright: there
is no honest way to roofline decode without a bandwidth number, so the
caller degrades to a memory-only plan (``radar.capacity.memory``) instead.
Missing TFLOPS is different — it degrades only the prefill half of the
result (``prefill_tps``/``ttft_seconds`` become ``None`` with a note) because
decode is fully computable from bandwidth alone.

Prefill math, over the whole batch's prompt tokens:

- ``dtype = weight_dtype_for_bits(bits_per_weight)`` picks the TFLOPS figure
  that matches the weight quantization (``tflops_fp16``/``tflops_fp8``/
  ``tflops_fp4`` on ``DeviceProfile``).
- If the device does not publish that dtype's TFLOPS, fall back to
  ``tflops_fp16`` with a note ("prefill computed at fp16 TFLOPS (no {dtype}
  figure published)"). If fp16 is unpublished too, ``prefill_tps`` (and
  ``ttft_seconds``) are ``None`` with a note — decode is still returned.
- ``prefill_tps = n_gpus * tflops * 1e12 * prefill_mfu / (2 * active)`` — the
  standard 2*params FLOPs/token roofline, scaled by the engine's realized
  fraction of dense peak TFLOPS (``prefill_mfu``, model-FLOPS utilization).
- ``ttft_seconds = avg_context_tokens / prefill_tps`` — time to first token,
  treating prefill as a single batched pass over the average prompt length.

Reported ``aggregate_decode_tps``/``per_user_decode_tps``/``prefill_tps`` are
rounded to 1 decimal; ``ttft_seconds`` to 2 decimals — all rounding happens
once, at the end, on the full-precision intermediate values above.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from radar.capacity.types import AssumptionSheet, Workload
from radar.models_radar.devices import DeviceProfile


ENGINE_EFFICIENCY: dict[str, dict[str, float]] = {
    # DOCUMENTED ESTIMATES (spec 6.2), calibrated by sub-project E's measured
    # benchmarks. decode_mbu = fraction of peak HBM bandwidth realized during
    # decode; prefill_mfu = fraction of peak dense TFLOPS realized in prefill.
    "vllm": {"decode_mbu": 0.60, "prefill_mfu": 0.50},
    "sglang": {"decode_mbu": 0.60, "prefill_mfu": 0.50},
    "tensorrt-llm": {"decode_mbu": 0.65, "prefill_mfu": 0.55},
    "llama-cpp": {"decode_mbu": 0.50, "prefill_mfu": 0.30},
}


class ThroughputEstimate(BaseModel):
    """A roofline decode/prefill throughput estimate for one deployment shape."""

    model_config = ConfigDict(frozen=True)

    aggregate_decode_tps: float  # tokens/sec across the fleet at this batch
    per_user_decode_tps: float  # aggregate / concurrent_requests
    prefill_tps: float | None  # None when TFLOPS for the dtype unavailable
    ttft_seconds: float | None  # avg_context / prefill_tps
    assumptions: AssumptionSheet


def weight_dtype_for_bits(bits_per_weight: float) -> str:
    """Map a weight quantization's bit width to the matching TFLOPS dtype key.

    ``>= 12`` bits/weight -> ``"fp16"``; ``>= 6`` -> ``"fp8"`` (int8-class byte
    width); anything narrower -> ``"fp4"``.
    """
    if bits_per_weight >= 12:
        return "fp16"
    if bits_per_weight >= 6:
        return "fp8"
    return "fp4"


def _resolve_prefill_tflops(
    device: DeviceProfile, dtype: str
) -> tuple[float | None, list[str]]:
    """Pick the TFLOPS figure for ``dtype``, falling back to fp16, then giving up.

    Returns the TFLOPS value (or ``None`` if nothing usable is published) plus
    any assumption notes describing the fallback that was taken.
    """
    tflops_by_dtype: dict[str, float | None] = {
        "fp16": device.tflops_fp16,
        "fp8": device.tflops_fp8,
        "fp4": device.tflops_fp4,
    }
    tflops = tflops_by_dtype[dtype]
    if tflops is not None:
        return tflops, []

    if dtype != "fp16" and device.tflops_fp16 is not None:
        return device.tflops_fp16, [
            f"prefill computed at fp16 TFLOPS (no {dtype} figure published)"
        ]

    return None, [f"prefill_tps unavailable — no {dtype} or fp16 TFLOPS published for this device"]


def estimate_throughput(
    *,
    params_active: int | None,
    params_total: int,
    bits_per_weight: float,
    kv_bytes_per_token: float | None,
    workload: Workload,
    device: DeviceProfile,
    n_gpus: int,
    engine: str = "vllm",
) -> ThroughputEstimate | None:
    """Roofline decode (bandwidth) + prefill (TFLOPS) throughput for one shape.

    See the module docstring for the full math. Returns ``None`` only when
    ``device.memory_bandwidth_gbs`` is unpublished — the caller should
    degrade to a memory-only plan in that case. Raises ``ValueError`` for an
    unknown ``engine``.
    """
    if engine not in ENGINE_EFFICIENCY:
        raise ValueError(
            f"Unknown engine {engine!r}. Known engines: {', '.join(ENGINE_EFFICIENCY)}"
        )

    if device.memory_bandwidth_gbs is None:
        return None

    constants = ENGINE_EFFICIENCY[engine]
    decode_mbu = constants["decode_mbu"]
    prefill_mfu = constants["prefill_mfu"]

    assumptions = AssumptionSheet().plus(
        f"{engine} decode MBU {decode_mbu:.2f}, prefill MFU {prefill_mfu:.2f} — "
        "documented estimates, not measurements; calibrated by sub-project E"
    )

    active = params_active or params_total
    if params_active:
        assumptions = assumptions.plus("MoE: decode reads active expert weights only")

    batch = workload.concurrent_requests
    weights_bytes = active * bits_per_weight / 8
    if kv_bytes_per_token is None:
        kv_bytes = 0.0
        assumptions = assumptions.plus("KV read not modeled — no architecture data")
    else:
        kv_bytes = batch * workload.avg_context_tokens * kv_bytes_per_token
    bytes_per_step = weights_bytes + kv_bytes

    aggregate_bw = n_gpus * device.memory_bandwidth_gbs * 1e9 * decode_mbu
    aggregate_decode_tps = aggregate_bw * batch / bytes_per_step
    per_user_decode_tps = aggregate_decode_tps / batch

    dtype = weight_dtype_for_bits(bits_per_weight)
    tflops, prefill_notes = _resolve_prefill_tflops(device, dtype)
    assumptions = assumptions.plus(*prefill_notes)

    prefill_tps: float | None
    ttft_seconds: float | None
    if tflops is None:
        prefill_tps = None
        ttft_seconds = None
    else:
        prefill_tps = n_gpus * tflops * 1e12 * prefill_mfu / (2 * active)
        ttft_seconds = workload.avg_context_tokens / prefill_tps

    return ThroughputEstimate(
        aggregate_decode_tps=round(aggregate_decode_tps, 1),
        per_user_decode_tps=round(per_user_decode_tps, 1),
        prefill_tps=round(prefill_tps, 1) if prefill_tps is not None else None,
        ttft_seconds=round(ttft_seconds, 2) if ttft_seconds is not None else None,
        assumptions=assumptions,
    )
