"""Query service exposing the capacity solver over MCP (spec §6, sub-project D task 7).

Thin adapter over ``radar.capacity.solver`` — never raises across the MCP
boundary. ``InfeasibleError``/``DeviceError``/plain ``ValueError`` (bad
device, quant, kv_dtype, or engine) all fold into a structured
``{"feasible": False, "reasons": [...]}`` dict; only an unrecognized
``model_id`` returns ``None`` (mirrors ``ModelQueryService``'s contract).

``_entries_or_seed`` is the single source of truth for capacity's model
loading: scan-first, bundled-seed fallback on an empty scan. It is shared by
this service and the ``radar capacity`` CLI commands (``radar.cli``
re-exports it as ``_capacity_load_entries``) so both surfaces always agree on
which entries exist.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from radar.capacity.memory import InfeasibleError
from radar.capacity.recipe import launch_recipe
from radar.capacity.solver import max_workload as _solve_max_workload
from radar.capacity.solver import plan_capacity as _solve_plan_capacity
from radar.capacity.tco import estimate_tco
from radar.capacity.types import Workload
from radar.mcp_server.model_queries import _latest_model_cards
from radar.models_radar.devices import DeviceError
from radar.models_radar.entities import ModelEntry


def _entries_or_seed(root: Path) -> tuple[list[ModelEntry], bool]:
    """Scan entries first; bundled seed fallback (flagged) on an empty scan.

    Mirrors ``ModelQueryService._entries()``'s scan read, but capacity
    planning must also work on a fresh clone with no scan at all — the seed
    fallback rehydrates entries the same offline way
    ``tests/test_capacity_solver.py``'s ``_entry`` helper does
    (``load_model_seed`` + ``build_model_entry(seed, None, [])``). Returns
    ``(entries, used_seed_fallback)``.
    """
    cards = _latest_model_cards(root)
    if cards:
        return [ModelEntry.model_validate(c) for c in cards], False

    from radar.models_radar.assemble import build_model_entry
    from radar.models_radar.seed import load_model_seed

    seed_path = Path(__file__).resolve().parents[3] / "config" / "model-seed.yaml"
    seeds = load_model_seed(seed_path)
    return [build_model_entry(seed, None, []) for seed in seeds], True


def _find_entry(entries: list[ModelEntry], model_id: str) -> ModelEntry | None:
    """Case-insensitive exact-id lookup; ``None`` when nothing matches."""
    low = model_id.lower()
    return next((e for e in entries if e.id.lower() == low), None)


def _plan_one(
    entry: ModelEntry,
    device: str,
    concurrent_requests: int,
    avg_context_tokens: int,
    target_tps_per_user: float | None,
    quant: str | None,
    kv_dtype: str,
    engine: str,
) -> dict[str, Any]:
    """Solve one (model, device) pair; folds every failure into a dict.

    On success the dict also carries ``"recipe"``: a copy-pasteable launch
    command for ``engine`` (task 8, spec §6.4) — omitted when ``engine`` is
    ``llama-cpp``, which has no launch recipe (single-node tool). It also
    carries ``"tco"``: the kW-first TCO estimate (task 9, spec §6.5) dumped
    via ``TCOEstimate.model_dump(mode="json")``, or ``None`` when the
    device's board TDP isn't published or the plan has no throughput
    estimate — both real states, not errors, so the key is always present.
    """
    try:
        # Workload construction lives inside the try: a bad concurrent_requests
        # or avg_context_tokens (e.g. 0 or negative) raises pydantic's
        # ValidationError, a ValueError subclass, so it folds into the same
        # readable "feasible: False" response as InfeasibleError/DeviceError
        # instead of escaping as a raw traceback across the MCP boundary.
        workload = Workload(
            concurrent_requests=concurrent_requests,
            avg_context_tokens=avg_context_tokens,
            target_tokens_per_sec_per_user=target_tps_per_user,
        )
        plan = _solve_plan_capacity(
            entry, device, workload,
            quant_format=quant, kv_dtype=kv_dtype, engine=engine,
        )
    except InfeasibleError as exc:
        return {"feasible": False, "model_id": entry.id, "device": device,
                "reasons": exc.reasons}
    except (DeviceError, ValueError) as exc:
        # Bad device preset, kv_dtype, engine, or workload (users/context) —
        # readable, never a raised exception across the MCP boundary.
        return {"feasible": False, "model_id": entry.id, "device": device,
                "reasons": [str(exc)]}
    result: dict[str, Any] = {"feasible": True, **plan.model_dump(mode="json")}
    if engine != "llama-cpp":
        # launch_recipe has no llama-cpp template (single-node tool, no
        # multi-GPU launch config) — omit the key rather than raising or
        # forcing every consumer to special-case a placeholder value.
        result["recipe"] = launch_recipe(plan, entry, engine=engine, kv_dtype=kv_dtype)
    tco = estimate_tco(plan)
    result["tco"] = tco.model_dump(mode="json") if tco is not None else None
    return result


class CapacityQueryService:
    """Transport-agnostic capacity-solver queries (plan / max-workload / compare)."""

    def __init__(self, root: Path):
        self.root = Path(root)

    def _entries(self) -> list[ModelEntry]:
        entries, _used_seed_fallback = _entries_or_seed(self.root)
        return entries

    def plan_capacity(
        self,
        model_id: str,
        device: str,
        concurrent_requests: int,
        avg_context_tokens: int,
        target_tps_per_user: float | None = None,
        quant: str | None = None,
        kv_dtype: str = "fp16",
        engine: str = "vllm",
    ) -> dict[str, Any] | None:
        """Smallest GPU count (+ layout) that serves the workload, or why not.

        ``None`` for an unknown ``model_id``. Otherwise always a dict:
        ``{"feasible": True, "recipe": <launch command>, "tco": <TCOEstimate
        dict or None>, **CapacityPlan.model_dump(mode="json")}`` on success
        (``"recipe"`` omitted for ``engine="llama-cpp"``, which has none;
        ``"tco"`` is ``None`` when the device's board TDP is unpublished or
        the plan has no throughput estimate), or ``{"feasible": False,
        "model_id", "device", "reasons"}`` when infeasible or the inputs
        (device/quant/kv_dtype/engine) are bad.
        """
        entry = _find_entry(self._entries(), model_id)
        if entry is None:
            return None
        return _plan_one(
            entry, device, concurrent_requests, avg_context_tokens,
            target_tps_per_user, quant, kv_dtype, engine,
        )

    def max_workload(
        self,
        model_id: str,
        device: str,
        n_gpus: int,
        avg_context_tokens: int,
        quant: str | None = None,
        kv_dtype: str = "fp16",
        engine: str = "vllm",
    ) -> dict[str, Any] | None:
        """Largest concurrency ``n_gpus`` can serve at ``avg_context_tokens``.

        Mirrors ``plan_capacity``'s contract: ``None`` for an unknown
        ``model_id``, else ``{"feasible": True, **MaxWorkload.model_dump(...)}``
        or a ``{"feasible": False, ..., "reasons": [...]}`` dict — never a
        raised exception.
        """
        entry = _find_entry(self._entries(), model_id)
        if entry is None:
            return None
        try:
            result = _solve_max_workload(
                entry, device, n_gpus,
                avg_context_tokens=avg_context_tokens,
                quant_format=quant, kv_dtype=kv_dtype, engine=engine,
            )
        except InfeasibleError as exc:
            return {"feasible": False, "model_id": entry.id, "device": device,
                    "reasons": exc.reasons}
        except (DeviceError, ValueError) as exc:
            return {"feasible": False, "model_id": entry.id, "device": device,
                    "reasons": [str(exc)]}
        return {"feasible": True, **result.model_dump(mode="json")}

    def compare_devices(
        self,
        model_id: str,
        devices: list[str],
        concurrent_requests: int,
        avg_context_tokens: int,
        target_tps_per_user: float | None = None,
        quant: str | None = None,
        kv_dtype: str = "fp16",
        engine: str = "vllm",
    ) -> list[dict[str, Any]] | None:
        """Plan the same workload across several devices, one row per device.

        ``None`` for an unknown ``model_id``. Otherwise one plan-or-reasons
        dict per requested device id, order preserved, each also carrying
        ``"device": <id>`` — an unrecognized device id gets its own
        ``feasible: False`` row (the ``DeviceError`` message in ``reasons``)
        rather than aborting the whole comparison.
        """
        entry = _find_entry(self._entries(), model_id)
        if entry is None:
            return None
        rows: list[dict[str, Any]] = []
        for device in devices:
            row = _plan_one(
                entry, device, concurrent_requests, avg_context_tokens,
                target_tps_per_user, quant, kv_dtype, engine,
            )
            row["device"] = device
            rows.append(row)
        return rows
