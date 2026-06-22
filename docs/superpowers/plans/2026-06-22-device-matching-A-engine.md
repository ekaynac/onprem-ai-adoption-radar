# Device Matching — Phase A: Engine + MCP + CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Tell a user which tracked models run on their machine and at which quantization — a deterministic device-fit evaluator over the existing per-quant memory estimates, exposed via MCP + CLI.

**Architecture:** A `DeviceProfile` + curated presets (`models_radar/devices.py`) and a `ModelFit` evaluator (`models_radar/device_fit.py`) that compares a device's *usable* memory to per-quant model memory (reusing `estimate_memory_gb` / `minimum_viable_quant`). Surfaced via MCP tools and `radar models fit`/`devices`. Web surfaces are Phase B.

**Tech Stack:** Python 3.12, pydantic v2, FastMCP, typer, pytest + ruff + mypy.

## Global Constraints

- Python ≥ 3.12; new modules begin with `from __future__ import annotations`.
- No new third-party dependencies; deterministic core, no LLM.
- Reuse `estimate_memory_gb` / `minimum_viable_quant` (`models_radar/memory.py`), `ModelEntry`/`QuantVariant` (`models_radar/entities.py`) — do NOT re-derive model memory differently.
- Immutability (frozen `DeviceProfile`/`ModelFit`); graceful (no model run → empty report; unknown arch → weights-only via the estimator's own fallback; never crash).
- Usable-memory fractions (verified ecosystem standard): GPU 0.85, Apple unified 0.72, CPU 0.50.
- ruff + mypy clean; coverage ≥ 80%. Full-gate (`ruff check src tests`, `mypy src`, `pytest -q`) before EVERY commit. Commit on the CURRENT branch only — never create/switch branches.

---

### Task 1: Device model + presets + usable memory

**Files:**
- Create: `src/radar/models_radar/devices.py`
- Test: `tests/test_devices.py`

**Interfaces:**
- Produces: frozen `DeviceProfile(name, kind, total_memory_gb, gpu_count=1)` (kind ∈ "gpu"|"apple"|"cpu");
  `USABLE_FRACTION: dict[str, float]`; `usable_memory_gb(device) -> float`;
  `DEVICE_PRESETS: dict[str, DeviceProfile]`; `resolve_device(spec: str | dict) -> DeviceProfile` (preset name or `{kind,total_memory_gb,gpu_count}`); raises `DeviceError` on bad spec.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_devices.py
from __future__ import annotations

import pytest

from radar.models_radar.devices import (
    DEVICE_PRESETS, DeviceError, DeviceProfile, resolve_device, usable_memory_gb,
)


def test_usable_memory_by_kind():
    assert usable_memory_gb(DeviceProfile(name="g", kind="gpu", total_memory_gb=24)) == pytest.approx(20.4)
    assert usable_memory_gb(DeviceProfile(name="m", kind="apple", total_memory_gb=64)) == pytest.approx(46.08)
    assert usable_memory_gb(DeviceProfile(name="c", kind="cpu", total_memory_gb=32)) == pytest.approx(16.0)


def test_usable_memory_multi_gpu():
    d = DeviceProfile(name="2xa100", kind="gpu", total_memory_gb=80, gpu_count=2)
    assert usable_memory_gb(d) == pytest.approx(136.0)  # 80 * 0.85 * 2


def test_presets_include_common_devices():
    assert "rtx-4090-24gb" in DEVICE_PRESETS
    assert "mac-64gb" in DEVICE_PRESETS and DEVICE_PRESETS["mac-64gb"].kind == "apple"
    assert DEVICE_PRESETS["a100-80gb"].total_memory_gb == 80
    assert DEVICE_PRESETS["2x-a100-80gb"].gpu_count == 2


def test_resolve_preset_and_custom():
    assert resolve_device("rtx-4090-24gb").total_memory_gb == 24
    custom = resolve_device({"kind": "gpu", "total_memory_gb": 12})
    assert custom.kind == "gpu" and custom.total_memory_gb == 12 and custom.gpu_count == 1


def test_resolve_bad_spec_raises():
    with pytest.raises(DeviceError):
        resolve_device("no-such-preset")
    with pytest.raises(DeviceError):
        resolve_device({"kind": "gpu"})  # missing total_memory_gb


def test_device_profile_is_frozen():
    d = DeviceProfile(name="g", kind="gpu", total_memory_gb=24)
    with pytest.raises(Exception):
        d.total_memory_gb = 48
```

- [ ] **Step 2: Run test → fails** (`pytest tests/test_devices.py -v` → `ModuleNotFoundError`).

- [ ] **Step 3: Implement**

```python
# src/radar/models_radar/devices.py
"""Device profiles + usable-memory model for hardware-fit checks.

Usable fractions are the ecosystem-standard fudge factors (dedicated GPU 0.85,
Apple unified memory 0.72, CPU 0.50) that account for OS/runtime/CUDA overhead.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class DeviceError(ValueError):
    """Raised when a device spec cannot be resolved."""


USABLE_FRACTION: dict[str, float] = {"gpu": 0.85, "apple": 0.72, "cpu": 0.50}


class DeviceProfile(BaseModel):
    """A machine the user might run models on."""

    model_config = ConfigDict(frozen=True)

    name: str
    kind: Literal["gpu", "apple", "cpu"]
    total_memory_gb: float
    gpu_count: int = 1


def usable_memory_gb(device: DeviceProfile) -> float:
    """Memory actually available to the model (GB), after the kind's fraction."""
    return round(device.total_memory_gb * USABLE_FRACTION[device.kind] * device.gpu_count, 2)


def _gpu(name: str, gb: float, count: int = 1) -> DeviceProfile:
    return DeviceProfile(name=name, kind="gpu", total_memory_gb=gb, gpu_count=count)


def _mac(name: str, gb: float) -> DeviceProfile:
    return DeviceProfile(name=name, kind="apple", total_memory_gb=gb)


DEVICE_PRESETS: dict[str, DeviceProfile] = {
    "rtx-4060-8gb": _gpu("RTX 4060 (8GB)", 8),
    "rtx-4070-12gb": _gpu("RTX 4070 (12GB)", 12),
    "rtx-4080-16gb": _gpu("RTX 4080 (16GB)", 16),
    "rtx-4090-24gb": _gpu("RTX 4090 (24GB)", 24),
    "rtx-5090-32gb": _gpu("RTX 5090 (32GB)", 32),
    "rtx-6000-ada-48gb": _gpu("RTX 6000 Ada (48GB)", 48),
    "a100-40gb": _gpu("A100 (40GB)", 40),
    "a100-80gb": _gpu("A100 (80GB)", 80),
    "h100-80gb": _gpu("H100 (80GB)", 80),
    "h200-141gb": _gpu("H200 (141GB)", 141),
    "mi300x-192gb": _gpu("MI300X (192GB)", 192),
    "2x-a100-80gb": _gpu("2x A100 (80GB)", 80, count=2),
    "mac-16gb": _mac("Mac (16GB unified)", 16),
    "mac-32gb": _mac("Mac (32GB unified)", 32),
    "mac-64gb": _mac("Mac (64GB unified)", 64),
    "mac-128gb": _mac("Mac (128GB unified)", 128),
    "mac-192gb": _mac("Mac (192GB unified)", 192),
    "mac-512gb": _mac("Mac Studio (512GB unified)", 512),
    "laptop-16gb-cpu": DeviceProfile(name="Laptop (16GB, no GPU)", kind="cpu", total_memory_gb=16),
}


def resolve_device(spec: str | dict[str, Any]) -> DeviceProfile:
    """A preset name, or a custom dict {kind, total_memory_gb, gpu_count?}."""
    if isinstance(spec, str):
        preset = DEVICE_PRESETS.get(spec)
        if preset is None:
            raise DeviceError(
                f"Unknown device preset '{spec}'. Known: {', '.join(sorted(DEVICE_PRESETS))}"
            )
        return preset
    try:
        return DeviceProfile(
            name=str(spec.get("name") or "custom"),
            kind=spec["kind"],
            total_memory_gb=float(spec["total_memory_gb"]),
            gpu_count=int(spec.get("gpu_count", 1)),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise DeviceError(f"Invalid device spec {spec!r}: {exc}") from exc
```

- [ ] **Step 4: Run test → pass**, full gate. **Step 5: Commit** `feat(models): device profiles + presets + usable memory`.

---

### Task 2: Fit evaluator

**Files:**
- Create: `src/radar/models_radar/device_fit.py`
- Test: `tests/test_device_fit.py`

**Interfaces:**
- Consumes: `DeviceProfile`, `usable_memory_gb` (Task 1); `ModelEntry`, `QuantVariant` (entities); `estimate_memory_gb`, `VIABLE_MIN_BITS` (memory).
- Produces: frozen `ModelFit(model_id, device_name, usable_gb, verdict, best_quant_format, best_quant_memory_gb, context_tokens, note)`;
  `evaluate_fit(model: ModelEntry, device: DeviceProfile, context_tokens: int = 4096) -> ModelFit`;
  `fit_report(models: list[ModelEntry], device: DeviceProfile, context_tokens: int = 4096) -> list[ModelFit]`.
  Verdict values: `"fits"`, `"fits_tight"`, `"fits_quantized"`, `"wont_fit"`, `"unknown"`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_device_fit.py
from __future__ import annotations

from radar.models_radar.devices import DeviceProfile
from radar.models_radar.device_fit import evaluate_fit, fit_report
from radar.models_radar.entities import HardwareTier, ModelEntry, Platform, QuantVariant


def _model(mid: str, params: int, quants: list[tuple[str, float]]) -> ModelEntry:
    # quants: list of (format, bits); est_memory computed weights-only here for clarity
    qs = [
        QuantVariant(format=f, bits_per_weight=b, platform=Platform.GENERIC, source="x",
                     est_memory_gb_4k=round(params * b / 8 / 1e9 * 1.2, 1))
        for f, b in quants
    ]
    return ModelEntry(id=mid, name=mid, family="F", params_total=params, quants=qs)


def test_8b_q4_fits_24gb_gpu():
    m = _model("qwen3-8b", 8_000_000_000, [("Q4_K_M", 4.5), ("Q8_0", 8.0)])
    dev = DeviceProfile(name="4090", kind="gpu", total_memory_gb=24)  # usable 20.4
    fit = evaluate_fit(m, dev)
    assert fit.verdict == "fits"
    assert fit.best_quant_format == "Q8_0"  # largest that fits (8B Q8 ~9.6GB ≤ 20.4)


def test_70b_wont_fit_16gb_gpu():
    m = _model("llama-70b", 70_000_000_000, [("Q4_K_M", 4.5), ("Q8_0", 8.0)])
    dev = DeviceProfile(name="4080", kind="gpu", total_memory_gb=16)  # usable 13.6
    fit = evaluate_fit(m, dev)
    assert fit.verdict == "wont_fit" and fit.best_quant_format is None


def test_only_smaller_quant_fits():
    # 24B: Q8 ~28.8GB (won't fit 24GB→20.4), Q4 ~16.2GB (fits)
    m = _model("mistral-24b", 24_000_000_000, [("Q4_K_M", 4.5), ("Q8_0", 8.0)])
    dev = DeviceProfile(name="4090", kind="gpu", total_memory_gb=24)
    fit = evaluate_fit(m, dev)
    assert fit.verdict == "fits" and fit.best_quant_format == "Q4_K_M"


def test_apple_fraction_is_lower():
    m = _model("q", 32_000_000_000, [("Q8_0", 8.0)])  # ~38.4GB
    # 48GB Mac → usable 34.56 (won't fit Q8); 48GB GPU → usable 40.8 (fits Q8)
    assert evaluate_fit(m, DeviceProfile(name="mac", kind="apple", total_memory_gb=48)).verdict == "wont_fit"
    assert evaluate_fit(m, DeviceProfile(name="gpu", kind="gpu", total_memory_gb=48)).verdict == "fits"


def test_multi_gpu_sums():
    m = _model("big", 120_000_000_000, [("Q4_K_M", 4.5)])  # ~81GB
    dev = DeviceProfile(name="2xa100", kind="gpu", total_memory_gb=80, gpu_count=2)  # usable 136
    assert evaluate_fit(m, dev).verdict == "fits"


def test_no_params_is_unknown():
    m = ModelEntry(id="x", name="x", family="F")  # no params, no quants
    assert evaluate_fit(m, DeviceProfile(name="g", kind="gpu", total_memory_gb=24)).verdict == "unknown"


def test_fit_report_sorts_fits_first():
    fits = _model("small", 3_000_000_000, [("Q4_K_M", 4.5)])
    nofit = _model("huge", 200_000_000_000, [("Q4_K_M", 4.5)])
    report = fit_report([nofit, fits], DeviceProfile(name="g", kind="gpu", total_memory_gb=24))
    assert report[0].model_id == "small"
```

- [ ] **Step 2: Run test → fails** (`ModuleNotFoundError`).

- [ ] **Step 3: Implement**

```python
# src/radar/models_radar/device_fit.py
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


_TIGHT_FRACTION = 0.95


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
        model.num_layers, model.hidden_size,
    )
    return est if est is not None else quant.est_memory_gb_4k


def evaluate_fit(
    model: ModelEntry, device: DeviceProfile, context_tokens: int = 4096,
) -> ModelFit:
    usable = usable_memory_gb(device)
    base = ModelFit(model_id=model.id, device_name=device.name, usable_gb=usable,
                    verdict="unknown", context_tokens=context_tokens)

    sized = [(q, _quant_memory(model, q, context_tokens)) for q in model.quants]
    sized = [(q, m) for q, m in sized if m is not None]
    if not sized:
        return base.model_copy(update={"note": "no sized quants"})

    fitting = [(q, m) for q, m in sized if m <= usable]
    if not fitting:
        smallest = min(sized, key=lambda qm: qm[1])
        return base.model_copy(update={
            "verdict": "wont_fit",
            "note": f"smallest quant {smallest[0].format} needs ~{smallest[1]} GB > {usable} GB usable",
        })

    # largest quant that fits = highest bits_per_weight among fitting
    best_q, best_m = max(fitting, key=lambda qm: qm[0].bits_per_weight)
    viable_fits = [(q, m) for q, m in fitting if q.bits_per_weight >= VIABLE_MIN_BITS]
    if not viable_fits:
        verdict = "fits_quantized"  # only sub-Q4 quants fit
    elif best_m > usable * _TIGHT_FRACTION:
        verdict = "fits_tight"
    else:
        verdict = "fits"
    return base.model_copy(update={
        "verdict": verdict, "best_quant_format": best_q.format,
        "best_quant_memory_gb": best_m,
        "note": f"{best_q.format} ~{best_m} GB ≤ {usable} GB usable",
    })


_ORDER = {"fits": 0, "fits_tight": 1, "fits_quantized": 2, "wont_fit": 3, "unknown": 4}


def fit_report(
    models: list[ModelEntry], device: DeviceProfile, context_tokens: int = 4096,
) -> list[ModelFit]:
    fits = [evaluate_fit(m, device, context_tokens) for m in models]
    return sorted(fits, key=lambda f: (_ORDER.get(f.verdict, 9), f.best_quant_memory_gb or 1e9))
```

- [ ] **Step 4: Run test → pass**, full gate. **Step 5: Commit** `feat(models): device-fit evaluator (verdict + largest-fitting quant)`.

---

### Task 3: MCP tools (list_devices, can_run, fit_report)

**Files:**
- Modify: `src/radar/mcp_server/model_queries.py` (add device methods to `ModelQueryService`)
- Modify: `src/radar/mcp_server/server.py` (register 3 tools)
- Test: `tests/test_mcp_server.py` + `tests/test_model_queries.py` (add)

**Interfaces:**
- Consumes: `resolve_device`/`DEVICE_PRESETS` (Task 1), `evaluate_fit`/`fit_report` (Task 2), the existing `_entries()` + `ModelEntry`.
- Produces: `ModelQueryService.list_devices() -> list[dict]`, `.can_run(model_id, device, context_tokens=4096) -> dict | None`, `.device_fit_report(device, context_tokens=4096) -> list[dict]`; MCP tools `list_devices`, `can_run`, `fit_report`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_model_queries.py — add (reuses the _seed() helper that writes a model run)
def test_can_run_and_fit_report(tmp_path):
    _seed(tmp_path)  # existing helper: writes qwen3-8b/qwen3-30b-a3b/big-405b model_cards run
    from radar.mcp_server.model_queries import ModelQueryService
    svc = ModelQueryService(tmp_path)

    devices = svc.list_devices()
    assert any(d["id"] == "rtx-4090-24gb" for d in devices)

    one = svc.can_run("qwen3-8b", "rtx-4090-24gb")
    assert one is not None and one["verdict"] in ("fits", "fits_tight", "fits_quantized")
    assert svc.can_run("nope", "rtx-4090-24gb") is None

    report = svc.device_fit_report("laptop-16gb-cpu")
    assert {r["model_id"] for r in report} == {"qwen3-8b", "qwen3-30b-a3b", "big-405b"}
    # custom device dict
    custom = svc.device_fit_report({"kind": "gpu", "total_memory_gb": 8})
    assert all("verdict" in r for r in custom)
```
```python
# tests/test_mcp_server.py — add (reuses _seed_models)
def test_server_registers_device_tools(tmp_path):
    _seed_models(tmp_path)
    import asyncio
    from radar.mcp_server.server import build_mcp_server
    names = {t.name for t in asyncio.run(build_mcp_server(tmp_path).list_tools())}
    assert {"list_devices", "can_run", "fit_report"} <= names
```

- [ ] **Step 2: Run → fails.**

- [ ] **Step 3: Implement** — `ModelQueryService` methods:

```python
# in model_queries.py — imports
from radar.models_radar.devices import DEVICE_PRESETS, resolve_device, usable_memory_gb
from radar.models_radar.device_fit import evaluate_fit, fit_report
```
```python
    def list_devices(self) -> list[dict[str, Any]]:
        return [
            {"id": key, "name": d.name, "kind": d.kind,
             "total_memory_gb": d.total_memory_gb, "gpu_count": d.gpu_count,
             "usable_gb": usable_memory_gb(d)}
            for key, d in DEVICE_PRESETS.items()
        ]

    def can_run(self, model_id: str, device: str | dict[str, Any],
                context_tokens: int = 4096) -> dict[str, Any] | None:
        entry = next((e for e in self._entries() if e.id == model_id), None)
        if entry is None:
            return None
        return evaluate_fit(entry, resolve_device(device), context_tokens).model_dump(mode="json")

    def device_fit_report(self, device: str | dict[str, Any],
                          context_tokens: int = 4096) -> list[dict[str, Any]]:
        dev = resolve_device(device)
        return [f.model_dump(mode="json") for f in fit_report(self._entries(), dev, context_tokens)]
```
Register in `server.py` (mirror existing `@mcp.tool()` model tools, delegating to `models`):

```python
    @mcp.tool()
    def list_devices() -> list[dict]:
        """List built-in device presets (GPU/Apple/CPU) with usable memory."""
        return models.list_devices()

    @mcp.tool()
    def can_run(model_id: str, device: str | dict, context_tokens: int = 4096) -> dict | None:
        """Whether a model fits a device (preset id or {kind,total_memory_gb,gpu_count}) + best quant."""
        return models.can_run(model_id, device, context_tokens)

    @mcp.tool()
    def fit_report(device: str | dict, context_tokens: int = 4096) -> list[dict]:
        """Per-model fit verdicts for a device (preset id or custom spec)."""
        return models.fit_report(device, context_tokens)
```
(`fit_report` MCP tool delegates to `models.device_fit_report` to avoid a name clash with the service method — keep the tool named `fit_report` per the plan, service method `device_fit_report`.)

- [ ] **Step 4: Run → pass**, full gate. **Step 5: Commit** `feat(models): MCP list_devices/can_run/fit_report`.

---

### Task 4: CLI — `radar models devices` + `radar models fit`

**Files:**
- Modify: `src/radar/cli.py` (add to `models_app`)
- Test: `tests/test_models_radar_cli.py` (add)

**Interfaces:**
- Consumes: `DEVICE_PRESETS`/`resolve_device` (Task 1), `fit_report` (Task 2), `_latest_model_cards` (`mcp_server/model_queries`), `ModelEntry`.
- Produces: `radar models devices`; `radar models fit --device <preset> [--memory GB --kind gpu|apple|cpu --gpus N] [--context N] --root .`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_models_radar_cli.py — add (reuses the model-run seeding helper)
def test_models_devices_lists_presets(tmp_path):
    from typer.testing import CliRunner
    from radar.cli import app
    r = CliRunner().invoke(app, ["models", "devices"])
    assert r.exit_code == 0 and "rtx-4090-24gb" in r.stdout


def test_models_fit_reports_verdicts(tmp_path, monkeypatch):
    from typer.testing import CliRunner
    from radar.cli import app
    from radar.models_radar.entities import HardwareTier, Modality, ModelEntry, Openness, Platform, QuantVariant
    from radar.models import Ring
    from radar.storage.run_store import RunStore
    runner = CliRunner()
    runner.invoke(app, ["init", "--root", str(tmp_path)])
    rs = RunStore(tmp_path / "data" / "runs")
    rid = rs.create_run()
    e = ModelEntry(id="qwen3-8b", name="Qwen3 8B", family="Qwen3", params_total=8_000_000_000,
                   openness=Openness.OPEN_PERMISSIVE, hardware_tier=HardwareTier.LAPTOP,
                   ring=Ring.ADOPT, modality=Modality.TEXT,
                   quants=[QuantVariant(format="Q4_K_M", bits_per_weight=4.5, est_memory_gb_4k=8.4,
                                        platform=Platform.GENERIC, source="hf:x")])
    rs.save_stage(rid, "model_cards", [e.model_dump(mode="json")])
    rs.update_meta(rid, {"kind": "models", "model_count": 1})

    r = runner.invoke(app, ["models", "fit", "--device", "rtx-4090-24gb", "--root", str(tmp_path)])
    assert r.exit_code == 0, r.stdout
    assert "qwen3-8b" in r.stdout and "fits" in r.stdout
```

- [ ] **Step 2: Run → fails.**

- [ ] **Step 3: Implement** — add to `models_app`:

```python
@models_app.command("devices")
def models_devices() -> None:
    """List built-in device presets for the fit check."""
    from radar.models_radar.devices import DEVICE_PRESETS, usable_memory_gb
    for key, d in DEVICE_PRESETS.items():
        console.print(f"  {key:<20} {d.name:<28} ~{usable_memory_gb(d):>6.1f} GB usable",
                      highlight=False)


@models_app.command("fit")
def models_fit(
    device: str = typer.Option("", help="Preset id (see `radar models devices`)."),
    memory: float = typer.Option(0.0, help="Custom: total memory GB (with --kind)."),
    kind: str = typer.Option("gpu", help="Custom device kind: gpu|apple|cpu."),
    gpus: int = typer.Option(1, help="Custom: number of GPUs."),
    context: int = typer.Option(4096, help="Context length (tokens) for the estimate."),
    root: Path = typer.Option(Path("."), help="Project root."),
) -> None:
    """Show which tracked models fit a device, and at which quant."""
    from radar.mcp_server.model_queries import _latest_model_cards
    from radar.models_radar.device_fit import fit_report
    from radar.models_radar.devices import DeviceError, resolve_device
    from radar.models_radar.entities import ModelEntry

    try:
        spec: str | dict = device or {"kind": kind, "total_memory_gb": memory, "gpu_count": gpus}
        if not device and memory <= 0:
            console.print("[red]Provide --device <preset> or --memory <GB>.[/red]")
            raise typer.Exit(code=1)
        dev = resolve_device(spec)
    except DeviceError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc

    entries = [ModelEntry.model_validate(c) for c in _latest_model_cards(root)]
    if not entries:
        console.print("[yellow]No model scan yet. Run [bold]radar models scan[/bold] first.[/yellow]")
        return
    from radar.models_radar.devices import usable_memory_gb
    console.print(f"{dev.name} — ~{usable_memory_gb(dev):.1f} GB usable @ {context} ctx:")
    for f in fit_report(entries, dev, context):
        q = f.best_quant_format or "-"
        console.print(f"  {f.model_id:<28} {f.verdict:<15} {q}", highlight=False)
```

- [ ] **Step 4: Run → pass**, full gate. **Step 5: Commit** `feat(models): radar models devices + fit CLI`.

---

### Task 5: Full-gate + live smoke + final review + merge

**Files:** none.

- [ ] **Step 1: Gates** — `ruff check src tests && mypy src && pytest -q` green.
- [ ] **Step 2: Live smoke** — `radar models scan --root .` (refresh), then:
  - `radar models devices` lists presets;
  - `radar models fit --device rtx-4090-24gb --root .` → 8–32B models `fits` (Q4–Q8), the 30B-A3B MoE around the line; `--device mac-64gb` shifts verdicts lower (0.72 usable); `--memory 12 --kind gpu` → only small models fit; `--device laptop-16gb-cpu` → mostly `wont_fit`/`fits_quantized`.
  - MCP: build the server on `.` and call `can_run("qwen3-8b","rtx-4090-24gb")` → `fits` + a best quant; `list_devices()` non-empty.
- [ ] **Step 3: Final whole-branch review** (most-capable model) over branch base..HEAD.
- [ ] **Step 4: Merge** to main `--no-ff`, delete branch (KEEP `feature/device-matching`? No — Phase B continues on a fresh branch), integrate `origin`, push.

```bash
git checkout main && git merge --no-ff feature/device-matching \
  -m "Merge feature/device-matching (Phase A): device-fit engine + MCP + CLI"
git branch -d feature/device-matching
```

---

## Self-Review

**Spec coverage (Phase A):** device model + presets + usable → Task 1; fit evaluator (verdict ladder, largest-fitting quant, context-aware, Apple/multi-GPU) → Task 2; MCP `list_devices`/`can_run`/`fit_report` → Task 3; CLI `devices`/`fit` → Task 4; live verification → Task 5. Phase B (dashboard picker, per-model badge) intentionally separate.

**Placeholder scan:** Every code step has complete code. The MCP note clarifies the tool `fit_report` delegates to the service `device_fit_report` (avoids a method/tool name clash) — concrete, not a placeholder.

**Type consistency:** `DeviceProfile`/`usable_memory_gb`/`resolve_device`/`DEVICE_PRESETS` (Task 1) consumed by Tasks 2-4. `evaluate_fit(model, device, context_tokens)` / `fit_report(models, device, context_tokens)` / `ModelFit` (Task 2) consumed by Tasks 3-4. `_latest_model_cards` + `ModelEntry.model_validate` reused (Task 4) as in the existing models CLI. Verdict strings (`fits`/`fits_tight`/`fits_quantized`/`wont_fit`/`unknown`) consistent across Tasks 2-4. Reuses `estimate_memory_gb`/`VIABLE_MIN_BITS` from memory.py unchanged.
