"""``radar capacity`` — datacenter capacity planning (memory + throughput + solver)."""

from __future__ import annotations

from pathlib import Path

import typer

from radar.capacity.tco import DEFAULT_AMORTIZATION_MONTHS, DEFAULT_ELECTRICITY_USD_PER_KWH
from radar.cli._shared import console


capacity_app = typer.Typer(
    help="Datacenter capacity planning (memory + throughput + solver).",
    no_args_is_help=True,
)


def _capacity_available_ids(entries: list) -> str:
    """Sorted, comma-joined model ids for an "unknown model" error.

    Truncated to ~20 ids with a "… and N more" tail so a huge seed/scan
    doesn't dump hundreds of lines into the terminal.
    """
    ids = sorted({entry.id for entry in entries})
    if len(ids) > 20:
        return ", ".join(ids[:20]) + f", … and {len(ids) - 20} more"
    return ", ".join(ids)


def _capacity_find_entry(entries: list, model_id: str):
    """Case-insensitive exact-id lookup; ``None`` when nothing matches."""
    low = model_id.lower()
    for entry in entries:
        if entry.id.lower() == low:
            return entry
    return None


def _capacity_load_entries(root: Path) -> tuple[list, bool]:
    """Scan entries first; bundled seed fallback (flagged) on an empty scan.

    Thin re-export of ``radar.mcp_server.capacity_queries._entries_or_seed`` —
    the single source of truth for capacity's model loading, shared with
    ``CapacityQueryService`` so the CLI and MCP surfaces never disagree on
    which entries exist. Returns ``(entries, used_seed_fallback)``.
    """
    from radar.mcp_server.capacity_queries import _entries_or_seed

    return _entries_or_seed(root)


def _capacity_print_memory(memory) -> None:
    from rich.table import Table

    table = Table(title="Per-rank memory (GB)")
    for col in ("weights", "KV", "baseline", "fragmentation", "total", "usable", "headroom %"):
        table.add_column(col)
    r = memory.per_rank
    table.add_row(
        f"{r.weights_gb:.2f}", f"{r.kv_gb:.2f}", f"{r.baseline_gb:.2f}",
        f"{r.fragmentation_gb:.2f}", f"{r.total_gb:.2f}",
        f"{memory.usable_per_gpu_gb:.2f}", f"{memory.headroom_fraction * 100:.1f}%",
    )
    console.print(table)


def _capacity_print_throughput(throughput, meets_target: bool | None) -> None:
    console.print(
        f"Throughput: {throughput.per_user_decode_tps:.1f} t/s/user "
        f"(aggregate {throughput.aggregate_decode_tps:.1f} t/s)"
    )
    if throughput.ttft_seconds is not None and throughput.prefill_tps is not None:
        console.print(
            f"  prefill {throughput.prefill_tps:.1f} t/s, TTFT {throughput.ttft_seconds:.2f}s"
        )
    if meets_target is not None:
        console.print(f"  meets target: {meets_target}")


def _capacity_print_assumptions(lines) -> None:
    console.print("[bold]Assumptions:[/bold]")
    for line in lines:
        console.print(f"  - {line}")


def _capacity_print_recipe(plan, entry, *, engine: str, kv_dtype: str) -> None:
    """Render the launch recipe for ``engine``, or a skip note for llama-cpp.

    ``launch_recipe`` deliberately has no llama-cpp template (single-node
    tool, no multi-GPU launch config to generate) — the CLI shows a dim note
    instead of calling it, rather than letting a ``ValueError`` surface.
    """
    from radar.capacity.recipe import launch_recipe

    if engine == "llama-cpp":
        console.print("[dim](no launch recipe for llama-cpp — single-node tool)[/dim]")
        return
    recipe = launch_recipe(plan, entry, engine=engine, kv_dtype=kv_dtype)
    console.print(f"[bold]Launch recipe ({engine}):[/bold]")
    console.print(recipe, markup=False)


def _capacity_print_tco(plan, *, electricity_usd_per_kwh: float, amortization_months: int) -> None:
    """Render the kW-first TCO block, or a dim skip note when it can't be computed.

    ``estimate_tco`` returns ``None`` only when the device's board TDP is
    unpublished or the plan has no throughput estimate — both real, expected
    states (a custom device, a memory-only plan), not errors. Its own
    assumption lines (electricity rate, amortization basis, the TDP/capex
    caveats) print directly under this block rather than folding into the
    plan's main ``Assumptions:`` section above the recipe — they're specific
    to the TCO knobs, not the deployment shape.
    """
    from radar.capacity.tco import estimate_tco
    from radar.models_radar.devices import resolve_device

    tco = estimate_tco(
        plan, electricity_usd_per_kwh=electricity_usd_per_kwh, amortization_months=amortization_months,
    )
    if tco is None:
        console.print("[dim](no TCO estimate — device board TDP is not published)[/dim]")
        return

    capex_excluded = resolve_device(plan.device_id).indicative_price_usd is None
    console.print("[bold]TCO (indicative):[/bold]")
    console.print(f"  fleet power: {tco.fleet_power_kw:.2f} kW")
    if tco.tokens_per_sec_per_kw is not None:
        console.print(f"  {tco.tokens_per_sec_per_kw:.1f} tok/s/kW")
    if tco.usd_per_million_tokens is not None:
        suffix = " (electricity only — no public list price)" if capex_excluded else ""
        console.print(f"  ${tco.usd_per_million_tokens:.4f}/Mtok{suffix}")
    for line in tco.assumptions.lines:
        console.print(f"  - {line}")


@capacity_app.command("plan")
def capacity_plan(
    model: str = typer.Option(..., "--model", help="Model id to plan capacity for."),
    device: str = typer.Option(..., "--device", help="Device/node/cluster preset id."),
    users: int = typer.Option(..., "--users", min=1, help="Concurrent users/requests to serve."),
    context: int = typer.Option(..., "--context", min=1, help="Average context length (tokens)."),
    target_tps: float | None = typer.Option(
        None, "--target-tps", help="Target decode tokens/sec/user (optional)."
    ),
    quant: str | None = typer.Option(None, "--quant", help="Quant format override (e.g. FP8)."),
    kv_dtype: str = typer.Option("fp16", "--kv-dtype", help="KV cache dtype."),
    engine: str = typer.Option("vllm", "--engine", help="Serving engine (vllm, sglang, ...)."),
    electricity_usd_kwh: float = typer.Option(
        DEFAULT_ELECTRICITY_USD_PER_KWH, "--electricity-usd-kwh",
        help="Electricity rate ($/kWh) for the TCO block.",
    ),
    amortization_months: int = typer.Option(
        DEFAULT_AMORTIZATION_MONTHS, "--amortization-months",
        help="Hardware amortization horizon (months) for the TCO block.",
    ),
    root: Path = typer.Option(Path("."), help="Project root."),
) -> None:
    """Smallest GPU count (+ layout) that serves a workload, with its assumption sheet."""
    from radar.capacity.memory import InfeasibleError
    from radar.capacity.solver import plan_capacity
    from radar.capacity.types import Workload
    from radar.models_radar.devices import DeviceError

    entries, used_seed_fallback = _capacity_load_entries(root)
    if used_seed_fallback:
        console.print("[yellow](no scan found — using bundled seed specs)[/yellow]")

    entry = _capacity_find_entry(entries, model)
    if entry is None:
        console.print(
            f"[red]Unknown model {model!r}. Available: {_capacity_available_ids(entries)}[/red]"
        )
        raise typer.Exit(code=1)

    workload = Workload(
        concurrent_requests=users, avg_context_tokens=context,
        target_tokens_per_sec_per_user=target_tps,
    )
    try:
        plan = plan_capacity(
            entry, device, workload,
            quant_format=quant, kv_dtype=kv_dtype, engine=engine,
        )
    except InfeasibleError as exc:
        console.print("[red]Infeasible:[/red]")
        for reason in exc.reasons:
            console.print(f"  [red]- {reason}[/red]")
        raise typer.Exit(code=2) from exc
    except DeviceError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    except ValueError as exc:
        # Bad --kv-dtype or --engine (radar.capacity.kv/throughput raise plain
        # ValueError for these) — surface as a readable error, not a traceback.
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc

    header = (
        f"[bold]{plan.model_id}[/bold] on [bold]{plan.device_id}[/bold]: "
        f"{plan.n_gpus} GPU(s)"
    )
    if plan.n_nodes is not None:
        header += f", {plan.n_nodes} node(s)"
    header += (
        f" — layout TP={plan.parallelism.tensor_parallel} "
        f"PP={plan.parallelism.pipeline_parallel} EP={plan.parallelism.expert_parallel}"
    )
    console.print(header)
    _capacity_print_memory(plan.memory)
    if plan.throughput is not None:
        _capacity_print_throughput(plan.throughput, plan.meets_target)
    _capacity_print_assumptions(plan.assumptions.lines)
    _capacity_print_recipe(plan, entry, engine=engine, kv_dtype=kv_dtype)
    _capacity_print_tco(
        plan, electricity_usd_per_kwh=electricity_usd_kwh, amortization_months=amortization_months,
    )


@capacity_app.command("max")
def capacity_max(
    model: str = typer.Option(..., "--model", help="Model id to plan capacity for."),
    device: str = typer.Option(..., "--device", help="Device/node/cluster preset id."),
    gpus: int = typer.Option(..., "--gpus", min=1, help="Fixed fleet size (number of GPUs)."),
    context: int = typer.Option(..., "--context", min=1, help="Average context length (tokens)."),
    quant: str | None = typer.Option(None, "--quant", help="Quant format override (e.g. FP8)."),
    kv_dtype: str = typer.Option("fp16", "--kv-dtype", help="KV cache dtype."),
    engine: str = typer.Option("vllm", "--engine", help="Serving engine (vllm, sglang, ...)."),
    root: Path = typer.Option(Path("."), help="Project root."),
) -> None:
    """Largest concurrency a fixed fleet can serve at a given context length."""
    from radar.capacity.memory import InfeasibleError
    from radar.capacity.solver import max_workload
    from radar.models_radar.devices import DeviceError

    entries, used_seed_fallback = _capacity_load_entries(root)
    if used_seed_fallback:
        console.print("[yellow](no scan found — using bundled seed specs)[/yellow]")

    entry = _capacity_find_entry(entries, model)
    if entry is None:
        console.print(
            f"[red]Unknown model {model!r}. Available: {_capacity_available_ids(entries)}[/red]"
        )
        raise typer.Exit(code=1)

    try:
        result = max_workload(
            entry, device, gpus,
            avg_context_tokens=context, quant_format=quant, kv_dtype=kv_dtype, engine=engine,
        )
    except InfeasibleError as exc:
        console.print("[red]Infeasible:[/red]")
        for reason in exc.reasons:
            console.print(f"  [red]- {reason}[/red]")
        raise typer.Exit(code=2) from exc
    except DeviceError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    except ValueError as exc:
        # Bad --kv-dtype or --engine (radar.capacity.kv/throughput raise plain
        # ValueError for these) — surface as a readable error, not a traceback.
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc

    console.print(
        f"[bold]{result.model_id}[/bold] on [bold]{result.device_id}[/bold] "
        f"({result.n_gpus} GPU(s)):"
    )
    console.print(
        f"  max concurrent requests @ {context} ctx: {result.max_concurrent_at_context}"
    )
    if result.per_user_decode_tps_at_max is not None:
        console.print(
            f"  per-user decode t/s at max: {result.per_user_decode_tps_at_max:.1f}"
        )
    _capacity_print_assumptions(result.assumptions.lines)
