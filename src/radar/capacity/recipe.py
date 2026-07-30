"""Copy-pasteable launch configs from a solved CapacityPlan (spec §6.4, task 8).

``launch_recipe`` turns a solved ``CapacityPlan`` + its ``ModelEntry`` into a
ready-to-paste serving-engine launch command: vLLM first (the radar's
default target engine), then SGLang, then a cautious 3-line TensorRT-LLM
pointer (its engine-build step differs per version, so it gets a note + a
repo link rather than a full command). Pure string formatting — no I/O, no
subprocess, nothing here ever touches a GPU or the filesystem.

``llama-cpp`` is deliberately out of scope: it is spec'd elsewhere as a
single-node tool, so there is no multi-GPU launch recipe worth generating
for it. Callers (the CLI, the MCP capacity queries) special-case it rather
than calling this function.
"""

from __future__ import annotations

from radar.capacity.solver import CapacityPlan
from radar.models_radar.entities import ModelEntry


SUPPORTED_ENGINES: tuple[str, ...] = ("vllm", "sglang", "tensorrt-llm")

_GPU_MEMORY_UTILIZATION = 0.85  # radar's fixed usable-memory planning assumption


def launch_recipe(
    plan: CapacityPlan,
    entry: ModelEntry,
    *,
    engine: str = "vllm",
    kv_dtype: str = "fp16",
) -> str:
    """Render a copy-pasteable launch command for ``engine`` from ``plan``.

    ``engine`` must be one of ``SUPPORTED_ENGINES`` (``vllm``, ``sglang``,
    ``tensorrt-llm``) — anything else, including ``llama-cpp``, raises
    ``ValueError`` naming the supported engines.
    """
    if engine == "vllm":
        return _vllm_recipe(plan, entry, kv_dtype=kv_dtype)
    if engine == "sglang":
        return _sglang_recipe(plan, entry, kv_dtype=kv_dtype)
    if engine == "tensorrt-llm":
        return _tensorrt_llm_recipe(plan, entry)
    raise ValueError(
        f"launch_recipe: unsupported engine {engine!r} — supported: "
        f"{', '.join(SUPPORTED_ENGINES)} (llama-cpp is a single-node tool, "
        "not in launch-recipe scope)"
    )


def _model_ref_and_note(entry: ModelEntry) -> tuple[str, str]:
    """The repo/path token for the launch command, plus its trailing comment."""
    if entry.hf_repo:
        return entry.hf_repo, f"# model: https://huggingface.co/{entry.hf_repo}"
    return "<model-path>", "# replace <model-path> with your local weights path"


def _kv_dtype_note(kv_dtype: str, flag_emitted: bool) -> str | None:
    """A disclosure comment for kv-dtypes with no known engine flag mapping.

    ``fp16`` needs no flag (engine default) and no note; ``fp8`` gets a real
    flag (``flag_emitted`` is True) so no note either. Anything else (bf16,
    int8, fp4, ...) is the only value the radar doesn't map to a concrete
    flag today — disclose the gap instead of guessing one.
    """
    if flag_emitted or kv_dtype == "fp16":
        return None
    return f"# kv-dtype {kv_dtype}: check engine support"


def _headroom_comment(plan: CapacityPlan, *, reduce_flag: str) -> str:
    headroom_pct = plan.memory.headroom_fraction * 100
    return (
        f"# headroom {headroom_pct:.1f}% at {plan.workload.concurrent_requests} users "
        f"× {plan.workload.avg_context_tokens} ctx — reduce {reduce_flag} if OOM"
    )


def _command_lines(head: str, flags: list[str]) -> list[str]:
    """``head`` on its own line, then one ``    --flag value`` line per flag,
    each continued with `` \\`` except the last."""
    if not flags:
        return [head]
    lines = [f"{head} \\"]
    last = len(flags) - 1
    for i, flag in enumerate(flags):
        lines.append(f"    {flag}" + (" \\" if i < last else ""))
    return lines


def _vllm_recipe(plan: CapacityPlan, entry: ModelEntry, *, kv_dtype: str) -> str:
    repo, model_note = _model_ref_and_note(entry)
    tp = plan.parallelism.tensor_parallel
    pp = plan.parallelism.pipeline_parallel

    flags = [f"--tensor-parallel-size {tp}"]
    if pp > 1:
        flags.append(f"--pipeline-parallel-size {pp}")
    flags.append(f"--max-model-len {plan.workload.avg_context_tokens}")
    flags.append(f"--max-num-seqs {plan.workload.concurrent_requests}")

    kv_flag_emitted = kv_dtype == "fp8"
    if kv_flag_emitted:
        flags.append("--kv-cache-dtype fp8")
    if "fp8" in plan.quant_format.lower():
        flags.append("--quantization fp8")
    flags.append(f"--gpu-memory-utilization {_GPU_MEMORY_UTILIZATION}")

    lines = _command_lines(f"vllm serve {repo}", flags)
    kv_note = _kv_dtype_note(kv_dtype, kv_flag_emitted)
    if kv_note is not None:
        lines.append(kv_note)
    lines.append("# usable-memory fraction matches the radar's 0.85 planning assumption")
    lines.append(_headroom_comment(plan, reduce_flag="--max-num-seqs"))
    lines.append(model_note)
    return "\n".join(lines)


def _sglang_recipe(plan: CapacityPlan, entry: ModelEntry, *, kv_dtype: str) -> str:
    repo, model_note = _model_ref_and_note(entry)
    tp = plan.parallelism.tensor_parallel
    pp = plan.parallelism.pipeline_parallel

    flags = []
    if pp > 1:
        flags.append(f"--pp {pp}")
    flags.append(f"--context-length {plan.workload.avg_context_tokens}")
    flags.append(f"--max-running-requests {plan.workload.concurrent_requests}")

    kv_flag_emitted = kv_dtype == "fp8"
    if kv_flag_emitted:
        flags.append("--kv-cache-dtype fp8_e4m3")

    head = f"python -m sglang.launch_server --model-path {repo} --tp {tp}"
    lines = _command_lines(head, flags)
    kv_note = _kv_dtype_note(kv_dtype, kv_flag_emitted)
    if kv_note is not None:
        lines.append(kv_note)
    lines.append(_headroom_comment(plan, reduce_flag="--max-running-requests"))
    lines.append(model_note)
    return "\n".join(lines)


def _tensorrt_llm_recipe(plan: CapacityPlan, entry: ModelEntry) -> str:
    repo, model_note = _model_ref_and_note(entry)
    tp = plan.parallelism.tensor_parallel
    pp = plan.parallelism.pipeline_parallel

    flags = [f"--pp_size {pp}"] if pp > 1 else []
    lines = _command_lines(f"trtllm-serve {repo} --tp_size {tp}", flags)
    lines.append(
        "# NOTE: TensorRT-LLM requires an engine-build step that differs per "
        "version — see https://github.com/NVIDIA/TensorRT-LLM"
    )
    lines.append(model_note)
    return "\n".join(lines)
