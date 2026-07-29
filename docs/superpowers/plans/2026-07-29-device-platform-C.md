# Sub-project C: Device & Platform Knowledge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Device schema v2 (bandwidth/TFLOPS/interconnect/TDP/indicative price + provenance) seeded from YAML, an expanded cited catalog with Node/Cluster entities, the datacenter hardware-tier split with a `datacenter-first` model-scoring view, datacenter "Runs on" rows, and the engine platform-capability matrix — spec §5.3–5.5 of `docs/superpowers/specs/2026-07-27-capacity-planning-radar-v3-design.md`.

**Architecture:** Devices move from imperative Python (`devices.py:49-106`) into `config/device-seed.yaml` loaded by a new `device_seed.py` (same loader pattern as technique-seed), while `devices.py` keeps its exact public API (`DEVICE_PRESETS`, `resolve_device`, `usable_memory_gb`, `COMMON_DEVICE_TIERS`) so all six consumers are untouched by the migration. Nodes/clusters are separate seed lists flattened into `DeviceProfile`s (no new `kind` — the `Literal["gpu","apple","cpu"]` is load-bearing in 4 places) and resolvable by id. The tier split adds enum members (only 4 code sites can break; templates/filter-JS are data-driven). The platform matrix is a new cited YAML + loader + `/platforms` page + MCP tool.

**Tech Stack:** Python 3.12, pydantic v2, PyYAML, FastAPI + Jinja2, pytest. Run everything with `uv run`. Network available for live spec verification (curl).

## Global Constraints

- **Cardinal data rule (from sub-project B): never invent a number.** Every bandwidth/TFLOPS/TDP/price/matrix claim is live-verified during implementation and cited (`spec_url` + `verified: 2026-07-29` in YAML, or a `# not published as of 2026-07-29` omission comment). Prices are indicative public list figures only (spec D3 — no private cost data).
- **Public API freeze on `devices.py`:** `DEVICE_PRESETS: dict[str, DeviceProfile]`, `COMMON_DEVICE_TIERS: list[str]`, `USABLE_FRACTION`, `usable_memory_gb(device)`, `resolve_device(spec)` keep their exact names/shapes. All 48 existing preset ids keep identical `(kind, total_memory_gb, gpu_count)` — a golden migration test pins this.
- **`DeviceProfile.kind` stays `Literal["gpu","apple","cpu"]`** (load-bearing: `USABLE_FRACTION` keys, 3 optgroup filters + custom-kind select in `_device_picker.html:8-27`, JS fallback).
- **`HardwareTier.DATACENTER` remains a valid enum member** — persisted entries/metrics carry `"datacenter"` and must keep validating. New computations never emit it.
- Persisted model rings are NEVER changed by the `datacenter-first` profile — it is a view (mirrors tool-radar `reweight_cards` philosophy); static export publishes the default lens only.
- memory.py's `OVERHEAD`/`estimate_memory_gb` math untouched (sub-project D owns it) — only `TIER_THRESHOLDS`/`hardware_tier()` change here.
- Static/live parity; every new `render_static_site` kwarg optional + paired back-compat test; new pages join the sweep loops (`tests/test_web.py:1375,1536`; `tests/test_static_site.py:1036`).
- Deterministic; gates before every commit: `uv run pytest -q && uv run ruff check . && uv run mypy src` (suite starts at 1162 passed).
- Commit format `<type>: <description>`, NO Co-Authored-By. Never commit `data/` files.
- Branch: `feature/capacity-radar/device-platform-C` (checked out).

**Context map (recon facts used throughout — exact, verified 2026-07-29):**
- `devices.py` (133 lines): presets via `_gpu/_mac/_cpu` factories; consumers: `device_fit.py:12`, `picker_context.py:8-13`, `mcp_server/model_queries.py:12`, `cli.py:723,741,758` (local imports in `models devices`/`models fit`).
- Pinned tests: `test_devices.py:54` (`len >= 45` floor), `:63` (`COMMON_DEVICE_TIERS ⊆ DEVICE_PRESETS`), preset-id pins listed at `test_devices.py:28-31,56-59`, `test_device_picker.py:14-51`, `test_model_queries.py:144,151`, `test_models_radar_cli.py:61-62,91-93`, `test_static_site.py:362,457-466`.
- Tier consumers that can break on new members: `models_radar/scoring.py:20-27` `_TIER_SCORE` (bare `[]` lookup at `:56`), `memory.py:16-21` `TIER_THRESHOLDS` (+ fallthrough at `:68`). Templates/JS are data-driven (`_models_filter_bar.html:17-22` builds options from data).
- Tier boundary tests: `test_models_radar_memory.py:47-54`.
- Model scoring: 4 equal-weight dims (`scoring.py:53-63`); ring gate `model_ring` (`:66-74`); NO profile mechanism exists in models_radar (tool profiles: `scoring/profiles.py`, config `Config.profiles`).
- Seed loader pattern to copy: `research_radar/seed.py` (3 try-blocks + mapping guard + `_check_ids`); path idiom: `root/"config"/X` with `Path(__file__).resolve().parents[2]/"config"/X` fallback (`cli.py:304-307`, 8 occurrences, no shared helper).
- Device dict shape divergence to preserve: `picker_context` uses `label`, MCP `list_devices` uses `name` (both pinned by tests).
- New-page precedent: route `app.py:429-434` (/research); static writer `_write_technique_pages` (`static_site.py:521+`) behind `if technique_entries:` guard; nav = `{% set nav = {...7 items...} %}` in 19 templates (10 live incl. project.html/model.html etc., 9 static); page tests `test_web.py:796-816` + `test_static_site.py:542-599`.
- "Runs on" table: `picker_context.fit_by_tier` (`picker_context.py:30-38`), rendered `_model_detail.html:50-57`; `test_static_site.py:362` pins literal `"RTX 4090 (24GB)"`.
- `models devices` CLI column `{key:<20}` already overflows on 22-char ids — widen to `<26` while touched.

---

### Task 1: Device seed YAML + loader + schema v2 fields (faithful migration)

**Files:**
- Create: `config/device-seed.yaml`, `src/radar/models_radar/device_seed.py`
- Modify: `src/radar/models_radar/devices.py` (presets loaded from YAML; API unchanged)
- Test: `tests/test_device_seed.py` (new), `tests/test_devices.py` (append golden migration test; existing tests unchanged)

**Interfaces:**
- Consumes: existing `DeviceProfile`, loader pattern from `research_radar/seed.py`.
- Produces:
  - `DeviceProfile` gains optional frozen fields (defaults keep old constructors valid): `memory_bandwidth_gbs: float | None = None`, `tflops_fp16: float | None = None`, `tflops_fp8: float | None = None`, `tflops_fp4: float | None = None`, `interconnect: str | None = None`, `tdp_watts: int | None = None`, `indicative_price_usd: int | None = None`, `spec_url: str | None = None`, `verified: str | None = None` (ISO date), `datacenter: bool = False` (drives picker grouping + Task 6 tier rows).
  - `device_seed.py`: `class DeviceSeedError(ValueError)`; `class DeviceSeed(BaseModel, extra="forbid")` with `id: str` + every `DeviceProfile` field above (name/kind/total_memory_gb/gpu_count + v2 optionals); `def load_device_seed(path: Path) -> list[DeviceSeed]` — 3-try-block shape, mapping guard, top-level key `devices:`, `_check_ids` (unique ids, non-empty).
  - `devices.py`: `def _bundled_seed_path() -> Path` (root `config/device-seed.yaml` via the parents[2] idiom); `DEVICE_PRESETS` built at import from the seed (`{s.id: DeviceProfile(**s.model_dump(exclude={"id"})) for s in load_device_seed(...)}`); factories `_gpu/_mac/_cpu` and the imperative dict DELETED. `COMMON_DEVICE_TIERS`/`resolve_device`/`usable_memory_gb`/`USABLE_FRACTION` byte-identical.
  - Task 2/3 write into the same YAML; Task 6 consumes `datacenter`.

- [ ] **Step 1: Write the failing loader tests** (`tests/test_device_seed.py`):

```python
"""Device seed loading (config/device-seed.yaml)."""

from __future__ import annotations

from pathlib import Path

import pytest

from radar.models_radar.device_seed import DeviceSeed, DeviceSeedError, load_device_seed

_REPO_ROOT = Path(__file__).resolve().parents[1]


def test_bundled_seed_loads_and_covers_legacy_presets():
    seeds = load_device_seed(_REPO_ROOT / "config" / "device-seed.yaml")
    by_id = {s.id: s for s in seeds}
    assert len(seeds) >= 48
    assert by_id["rtx-4090-24gb"].total_memory_gb == 24
    assert by_id["mac-64gb"].kind == "apple"
    assert by_id["8x-h100-80gb"].gpu_count == 8
    assert by_id["server-256gb-cpu"].kind == "cpu"


def test_duplicate_ids_rejected(tmp_path: Path):
    p = tmp_path / "d.yaml"
    p.write_text(
        "devices:\n"
        "  - {id: a, name: A, kind: gpu, total_memory_gb: 8}\n"
        "  - {id: a, name: A2, kind: gpu, total_memory_gb: 16}\n",
        encoding="utf-8",
    )
    with pytest.raises(DeviceSeedError, match="Duplicate"):
        load_device_seed(p)


def test_missing_file_and_bad_yaml_raise(tmp_path: Path):
    with pytest.raises(DeviceSeedError, match="not found"):
        load_device_seed(tmp_path / "missing.yaml")
    bad = tmp_path / "bad.yaml"
    bad.write_text("devices: [:::", encoding="utf-8")
    with pytest.raises(DeviceSeedError, match="Invalid YAML"):
        load_device_seed(bad)


def test_unknown_field_rejected(tmp_path: Path):
    p = tmp_path / "d.yaml"
    p.write_text(
        "devices:\n  - {id: a, name: A, kind: gpu, total_memory_gb: 8, bogus: 1}\n",
        encoding="utf-8",
    )
    with pytest.raises(DeviceSeedError, match="validation failed"):
        load_device_seed(p)
```

And the golden migration test (append to `tests/test_devices.py`):

```python
def test_yaml_migration_preserves_every_legacy_preset():
    """The YAML seed must reproduce the pre-migration catalog exactly."""
    legacy = {
        "rtx-3060-12gb": ("gpu", 12, 1), "rtx-3080-10gb": ("gpu", 10, 1),
        "rtx-3090-24gb": ("gpu", 24, 1), "rtx-4060-8gb": ("gpu", 8, 1),
        "rtx-4060-ti-16gb": ("gpu", 16, 1), "rtx-4070-12gb": ("gpu", 12, 1),
        "rtx-4070-ti-super-16gb": ("gpu", 16, 1), "rtx-4080-16gb": ("gpu", 16, 1),
        "rtx-4090-24gb": ("gpu", 24, 1), "rtx-5070-12gb": ("gpu", 12, 1),
        "rtx-5070-ti-16gb": ("gpu", 16, 1), "rtx-5080-16gb": ("gpu", 16, 1),
        "rtx-5090-32gb": ("gpu", 32, 1), "rtx-a6000-48gb": ("gpu", 48, 1),
        "rtx-6000-ada-48gb": ("gpu", 48, 1), "a10-24gb": ("gpu", 24, 1),
        "a40-48gb": ("gpu", 48, 1), "l4-24gb": ("gpu", 24, 1),
        "l40s-48gb": ("gpu", 48, 1), "t4-16gb": ("gpu", 16, 1),
        "v100-32gb": ("gpu", 32, 1), "a100-40gb": ("gpu", 40, 1),
        "a100-80gb": ("gpu", 80, 1), "h100-80gb": ("gpu", 80, 1),
        "h100-nvl-94gb": ("gpu", 94, 1), "h200-141gb": ("gpu", 141, 1),
        "gh200-96gb": ("gpu", 96, 1), "b200-192gb": ("gpu", 192, 1),
        "mi210-64gb": ("gpu", 64, 1), "mi250-128gb": ("gpu", 128, 1),
        "mi300x-192gb": ("gpu", 192, 1), "2x-rtx-4090-24gb": ("gpu", 24, 2),
        "4x-rtx-4090-24gb": ("gpu", 24, 4), "2x-a100-80gb": ("gpu", 80, 2),
        "4x-a100-80gb": ("gpu", 80, 4), "8x-h100-80gb": ("gpu", 80, 8),
        "mac-16gb": ("apple", 16, 1), "mac-24gb": ("apple", 24, 1),
        "mac-32gb": ("apple", 32, 1), "mac-48gb": ("apple", 48, 1),
        "mac-64gb": ("apple", 64, 1), "mac-96gb": ("apple", 96, 1),
        "mac-128gb": ("apple", 128, 1), "mac-192gb": ("apple", 192, 1),
        "mac-256gb": ("apple", 256, 1), "mac-512gb": ("apple", 512, 1),
        "laptop-16gb-cpu": ("cpu", 16, 1), "workstation-64gb-cpu": ("cpu", 64, 1),
        "server-256gb-cpu": ("cpu", 256, 1),
    }
    for key, (kind, gb, count) in legacy.items():
        d = DEVICE_PRESETS[key]
        assert (d.kind, d.total_memory_gb, d.gpu_count) == (kind, gb, count), key
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_device_seed.py -q` → ImportError.

- [ ] **Step 3: Implement.** `device_seed.py` (mirror `research_radar/seed.py` exactly):

```python
"""Load the bundled device seed (config/device-seed.yaml)."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from radar.models_radar.devices import DeviceProfile


class DeviceSeedError(ValueError):
    """Raised when the device seed cannot be loaded."""


class DeviceSeed(BaseModel):
    """One device entry in config/device-seed.yaml."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    name: str
    kind: str  # validated by DeviceProfile's Literal on conversion
    total_memory_gb: float
    gpu_count: int = 1
    memory_bandwidth_gbs: float | None = None
    tflops_fp16: float | None = None
    tflops_fp8: float | None = None
    tflops_fp4: float | None = None
    interconnect: str | None = None
    tdp_watts: int | None = None
    indicative_price_usd: int | None = None
    spec_url: str | None = None
    verified: str | None = None
    datacenter: bool = False

    def to_profile(self) -> DeviceProfile:
        return DeviceProfile(**self.model_dump(exclude={"id"}))


def load_device_seed(path: Path) -> list[DeviceSeed]:
    try:
        contents = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise DeviceSeedError(f"Device seed not found: {path}") from exc
    try:
        raw = yaml.safe_load(contents) or {}
    except yaml.YAMLError as exc:
        raise DeviceSeedError(f"Invalid YAML in {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise DeviceSeedError(f"Device seed {path} must be a mapping with a 'devices' list")
    try:
        seeds = [DeviceSeed.model_validate(item) for item in raw.get("devices") or []]
    except ValidationError as exc:
        raise DeviceSeedError(f"Device seed validation failed for {path}: {exc}") from exc
    ids = [s.id for s in seeds]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise DeviceSeedError(f"Duplicate device ids in {path}: {', '.join(duplicates)}")
    return seeds
```

`devices.py`: add the v2 optional fields to `DeviceProfile` (after `gpu_count`, same order as `DeviceSeed`); replace lines 37-106 (factories + dict) with:

```python
def _bundled_seed_path() -> Path:
    # Repo-root config; same resolution idiom as the model/technique seeds.
    return Path(__file__).resolve().parents[3] / "config" / "device-seed.yaml"


def _load_presets() -> dict[str, DeviceProfile]:
    from radar.models_radar.device_seed import load_device_seed  # local: avoid cycle

    return {s.id: s.to_profile() for s in load_device_seed(_bundled_seed_path())}


DEVICE_PRESETS: dict[str, DeviceProfile] = _load_presets()
```

(**Path caution:** `devices.py` sits at `src/radar/models_radar/devices.py` → repo root is `parents[3]`, NOT the `parents[2]` used from `cli.py`. Verify with a quick REPL check.) `config/device-seed.yaml`: header comment + all 48 legacy entries in the same comment-grouped order, e.g.:

```yaml
# Device catalog — schema v2 (capacity radar sub-project C).
# Numbers policy: every v2 spec number carries spec_url + verified date;
# unpublished values are omitted with a dated comment. Prices are indicative
# public list figures only (spec D3). Memory/kind/count for legacy entries
# are a faithful migration from the pre-2026-07-29 devices.py.
version: "1.0"
devices:
  # --- Consumer NVIDIA ---
  - {id: rtx-3060-12gb, name: "RTX 3060 (12GB)", kind: gpu, total_memory_gb: 12}
  # ... (all 48, faithfully)
```

- [ ] **Step 4: Run** — `uv run pytest tests/test_device_seed.py tests/test_devices.py tests/test_device_picker.py tests/test_model_queries.py -q` → PASS (existing pins prove API freeze).
- [ ] **Step 5: Full gates; commit** — `git commit -am "feat: device catalog seeded from config/device-seed.yaml with schema v2 fields"`

---

### Task 2: Catalog expansion + cited v2 spec data

**Files:**
- Modify: `config/device-seed.yaml`
- Test: `tests/test_device_seed.py` (append)

**Interfaces:** data-only; Task 6 consumes `datacenter: true` flags.

- [ ] **Step 1: Live-fetch and record.** For each device below, curl the vendor spec page (NVIDIA datasheets/product pages, AMD product pages, Intel/Habana, and reputable secondary sources only when the vendor page lacks a number — cite whichever you used). Capture in your report: memory, bandwidth, dense FP16/FP8/FP4 TFLOPS (dense, not sparse — note if only sparse is published and halve with a comment), TDP, indicative list price if credibly public. **Do not invent; omit + dated comment when unpublished.**
  - New single GPUs: `h200-nvl-141gb`, `b300-288gb`, `rtx-pro-6000-blackwell-96gb`, `mi325x-256gb`, `mi355x-288gb`, `gaudi3-128gb`, `ascend-910b-64gb`, `ascend-910c` (memory per published figures — verify; Huawei publishes sparsely: if even the memory figure can't be sourced, drop the entry with a dated YAML comment). GB300 NVL72: include as a Task 3 cluster/node ONLY if citable; otherwise a dated omission comment next to gb200-nvl72.
  - v2 fields for existing datacenter/pro devices: `a100-40gb`, `a100-80gb`, `h100-80gb`, `h100-nvl-94gb`, `h200-141gb`, `gh200-96gb`, `b200-192gb`, `mi210-64gb`, `mi250-128gb`, `mi300x-192gb`, `l40s-48gb`, `rtx-6000-ada-48gb`, `rtx-4090-24gb`, `rtx-5090-32gb`.
  - Mark `datacenter: true` on: a100-*, h100-*, h200-141gb, gh200-96gb, b200/b300, mi210/mi250/mi300x/mi325x/mi355x, gaudi3, ascend-910b, l40s-48gb, plus the multi-GPU a100/h100 rigs.
  - New multi-GPU rigs (memory/count only, datacenter: true): `4x-h100-80gb`, `8x-h200-141gb`, `8x-b200-192gb`, `8x-mi300x-192gb`.

Example target shape (values ILLUSTRATIVE — use only live-verified numbers):

```yaml
  - id: h200-141gb
    name: "H200 (141GB)"
    kind: gpu
    total_memory_gb: 141
    memory_bandwidth_gbs: 4800        # nvidia.com H200 datasheet (verified 2026-07-29)
    tflops_fp16: 989                  # dense; datasheet lists 1979 sparse
    tflops_fp8: 1979
    tdp_watts: 700
    interconnect: "NVLink 4 900 GB/s"
    spec_url: https://www.nvidia.com/en-us/data-center/h200/
    verified: "2026-07-29"
    datacenter: true
    # indicative_price_usd omitted: NVIDIA publishes no list price as of 2026-07-29
```

- [ ] **Step 2: Write the failing validation tests** (append to `tests/test_device_seed.py`):

```python
def test_new_datacenter_devices_present_with_cited_specs():
    seeds = {s.id: s for s in load_device_seed(_REPO_ROOT / "config" / "device-seed.yaml")}
    for did in ("b300-288gb", "mi325x-256gb", "mi355x-288gb", "gaudi3-128gb",
                "ascend-910b-64gb", "rtx-pro-6000-blackwell-96gb",
                "8x-h200-141gb", "8x-b200-192gb", "8x-mi300x-192gb", "4x-h100-80gb"):
        assert did in seeds, did
        assert seeds[did].datacenter is True, did
    h200 = seeds["h200-141gb"]
    assert h200.memory_bandwidth_gbs and h200.memory_bandwidth_gbs > 1000
    assert h200.spec_url and h200.verified


def test_every_v2_number_is_cited():
    seeds = load_device_seed(_REPO_ROOT / "config" / "device-seed.yaml")
    v2_fields = ("memory_bandwidth_gbs", "tflops_fp16", "tflops_fp8", "tflops_fp4",
                 "tdp_watts", "indicative_price_usd")
    for s in seeds:
        if any(getattr(s, f) is not None for f in v2_fields):
            assert s.spec_url, f"{s.id} has v2 numbers but no spec_url"
            assert s.verified, f"{s.id} has v2 numbers but no verified date"
        for f in v2_fields:
            value = getattr(s, f)
            assert value is None or value > 0, f"{s.id}.{f} must be positive"
```

- [ ] **Step 3: Edit the YAML with the verified data; run the tests → PASS.** (Multi-GPU rigs inherit no per-GPU v2 numbers — keep them memory/count-only unless you cite node-level figures.)
- [ ] **Step 4: Full gates; commit** — `git commit -am "feat: expanded device catalog — Blackwell/MI3xx/Gaudi/Ascend + cited bandwidth/TFLOPS/TDP specs"`

---

### Task 3: Node + Cluster entities

**Files:**
- Modify: `src/radar/models_radar/device_seed.py` (NodeSeed/ClusterSeed + loader keys), `config/device-seed.yaml` (nodes/clusters sections), `src/radar/models_radar/devices.py` (NODE_PRESETS/CLUSTER_PRESETS + resolve fallback)
- Test: `tests/test_device_seed.py` (append), `tests/test_devices.py` (append)

**Interfaces:**
- Produces:
  - `class NodeSeed(BaseModel, extra="forbid", frozen)`: `id, name, device: str` (ref into devices), `gpus_per_node: int`, `interconnect: str | None = None`, `spec_url: str | None = None`, `verified: str | None = None`.
  - `class ClusterSeed(...)`: `id, name, node: str` (ref into nodes), `node_count: int`, `fabric: str | None = None`, `spec_url/verified`.
  - `load_device_seed` return becomes `DeviceCatalog` (frozen BaseModel): `devices: list[DeviceSeed]`, `nodes: list[NodeSeed]`, `clusters: list[ClusterSeed]` — **breaking change to Task 1's return**; update Task 1's tests mechanically (`load_device_seed(p).devices`). Ref-integrity checks: node.device must exist in devices; cluster.node in nodes (DeviceSeedError otherwise).
  - `devices.py`: `NODE_PRESETS: dict[str, DeviceProfile]` — node flattened over its base device: `base.model_copy(update={"name": node.name, "gpu_count": node.gpus_per_node, "interconnect": node.interconnect or base.interconnect, "datacenter": True})`; `CLUSTER_PRESETS` similarly with `gpu_count = gpus_per_node * node_count` and `interconnect = fabric`. `resolve_device` falls back DEVICE → NODE → CLUSTER before raising (error message now says `Known devices/nodes/clusters: ...`).
  - Seeded nodes (memory derives from the base device — only interconnect/urls need citing): `hgx-h100-8` (8× h100-80gb, "NVLink 4 900 GB/s"), `hgx-h200-8` (8× h200-141gb), `hgx-b200-8` (8× b200-192gb), `mi300x-oam-8` (8× mi300x-192gb, "Infinity Fabric"), `gb200-nvl72` (72× b200-192gb, "NVLink 5 single domain" — with a YAML comment stating the approximation: B200-die HBM only, Grace LPDDR excluded, cite the NVIDIA NVL72 page).
  - Seeded clusters: `2x-hgx-h200-8` and `4x-hgx-h200-8` (fabric: "InfiniBand NDR 400 Gb/s", cite the DGX SuperPOD reference architecture URL).

- [ ] **Step 1: Failing tests** (append to `tests/test_device_seed.py`):

```python
def test_nodes_and_clusters_load_and_resolve():
    catalog = load_device_seed(_REPO_ROOT / "config" / "device-seed.yaml")
    nodes = {n.id: n for n in catalog.nodes}
    assert nodes["hgx-h200-8"].gpus_per_node == 8
    assert nodes["hgx-h200-8"].device == "h200-141gb"
    assert nodes["gb200-nvl72"].gpus_per_node == 72
    clusters = {c.id: c for c in catalog.clusters}
    assert clusters["2x-hgx-h200-8"].node == "hgx-h200-8"


def test_node_ref_integrity(tmp_path: Path):
    p = tmp_path / "d.yaml"
    p.write_text(
        "devices:\n  - {id: g, name: G, kind: gpu, total_memory_gb: 80}\n"
        "nodes:\n  - {id: n, name: N, device: missing, gpus_per_node: 8}\n",
        encoding="utf-8",
    )
    with pytest.raises(DeviceSeedError, match="unknown device"):
        load_device_seed(p)
```

and (append to `tests/test_devices.py`):

```python
def test_node_and_cluster_presets_resolve_as_devices():
    from radar.models_radar.devices import CLUSTER_PRESETS, NODE_PRESETS

    node = resolve_device("hgx-h200-8")
    assert node.gpu_count == 8 and node.total_memory_gb == 141
    assert usable_memory_gb(node) == round(141 * 0.85 * 8, 2)
    assert NODE_PRESETS["gb200-nvl72"].gpu_count == 72

    cluster = resolve_device("2x-hgx-h200-8")
    assert cluster.gpu_count == 16
    assert "2x-hgx-h200-8" in CLUSTER_PRESETS

    with pytest.raises(DeviceError):
        resolve_device("no-such-anything")
```

- [ ] **Step 2: Verify failure → implement → targeted tests PASS** (update Task 1's `.devices` accessors deliberately; check `tests/test_model_seed_validation.py` and any other `load_device_seed` caller).
- [ ] **Step 3: Full gates; commit** — `git commit -am "feat: node and cluster entities — HGX/OAM/NVL72 presets resolvable as devices"`

---

### Task 4: Datacenter tier split

**Files:**
- Modify: `src/radar/models_radar/entities.py:31-37` (enum), `src/radar/models_radar/memory.py:16-21,61-68`, `src/radar/models_radar/scoring.py:20-27`
- Test: `tests/test_models_radar_memory.py:47-54` (update deliberately + extend), `tests/test_models_radar_scoring.py` (append)

**Interfaces:**
- `HardwareTier` += `SINGLE_GPU_DC = "single_gpu_dc"`, `SINGLE_NODE = "single_node"`, `MULTI_NODE = "multi_node"` (DATACENTER kept, documented as legacy-persisted-only).
- `TIER_THRESHOLDS` becomes:

```python
TIER_THRESHOLDS: list[tuple[float, HardwareTier]] = [
    (16.0, HardwareTier.LAPTOP),
    (32.0, HardwareTier.APPLE_HIGH_RAM),
    (48.0, HardwareTier.SINGLE_GPU),
    (120.0, HardwareTier.WORKSTATION),
    # 163.2 = usable GB of one B200/MI300X (192 * 0.85): the largest single
    # datacenter accelerator. 950 ≈ usable GB of one 8xH200 HGX node.
    (163.0, HardwareTier.SINGLE_GPU_DC),
    (950.0, HardwareTier.SINGLE_NODE),
]
```

  and the fallthrough in `hardware_tier()` returns `HardwareTier.MULTI_NODE` (was DATACENTER). **Boundary shift note (deliberate, documented):** the workstation ceiling moves 180→120; models with min-memory 120–163 (previously "workstation") now read "single_gpu_dc" — a more actionable label in the H200 era. Grep run artifacts are unaffected (persisted strings stay valid).
- `_TIER_SCORE` += `SINGLE_GPU_DC: 2, SINGLE_NODE: 1, MULTI_NODE: 1` (homelab default keeps the datacenter penalty; DATACENTER: 1 stays for legacy entries).

- [ ] **Step 1: Update/extend the boundary tests deliberately** (`tests/test_models_radar_memory.py:47-54` — keep every old assert that still holds, change the two that must change, add the new boundaries):

```python
def test_hardware_tier_boundaries():
    assert hardware_tier(12) == HardwareTier.LAPTOP
    assert hardware_tier(16) == HardwareTier.LAPTOP
    assert hardware_tier(24) == HardwareTier.APPLE_HIGH_RAM
    assert hardware_tier(48) == HardwareTier.SINGLE_GPU
    assert hardware_tier(120) == HardwareTier.WORKSTATION
    assert hardware_tier(150) == HardwareTier.SINGLE_GPU_DC   # was workstation
    assert hardware_tier(163) == HardwareTier.SINGLE_GPU_DC
    assert hardware_tier(400) == HardwareTier.SINGLE_NODE     # was datacenter
    assert hardware_tier(950) == HardwareTier.SINGLE_NODE
    assert hardware_tier(1000) == HardwareTier.MULTI_NODE
    assert hardware_tier(None) == HardwareTier.UNKNOWN
```

and (append to `tests/test_models_radar_scoring.py`):

```python
def test_new_tier_members_score_without_keyerror():
    from radar.models_radar.scoring import _TIER_SCORE

    for tier in HardwareTier:
        assert tier in _TIER_SCORE, tier  # bare [] lookup at scoring.py:56
```

- [ ] **Step 2: RED → implement → GREEN.** Then run the FULL suite and triage fallout deliberately: `test_models_radar_scoring.py:33` (`gated_datacenter_model_scores_low` constructs DATACENTER explicitly — still valid); seed-driven tiers may shift for large models (e.g. entries with min-memory 120-163) — check `tests/test_model_queries.py`/`test_models_radar_scan.py` fixtures for tier expectations and update ONLY where the new ladder genuinely relabels.
- [ ] **Step 3: Full gates; commit** — `git commit -am "feat: datacenter tier split — single_gpu_dc / single_node / multi_node"`

---

### Task 5: `datacenter-first` model-scoring view

**Files:**
- Modify: `src/radar/models_radar/scoring.py`, `src/radar/web/app.py` (/models route param), `src/radar/web/templates/models.html` (active-profile note + toggle link), `src/radar/mcp_server/model_queries.py` + `mcp_server/server.py` (list_models profile param)
- Test: `tests/test_models_radar_scoring.py` (append), `tests/test_web.py` (append), `tests/test_model_queries.py` (append)

**Interfaces:**
- `scoring.py`:

```python
class ModelProfileError(ValueError):
    """Raised for an unknown model-scoring profile."""


MODEL_PROFILES: dict[str, dict[HardwareTier, int]] = {
    "default": _TIER_SCORE,
    # Datacenter lens: single-node/multi-node deployability is the point,
    # not a penalty. Laptop-class models still score fine on capability.
    "datacenter-first": {
        HardwareTier.LAPTOP: 2, HardwareTier.APPLE_HIGH_RAM: 2,
        HardwareTier.SINGLE_GPU: 3, HardwareTier.WORKSTATION: 4,
        HardwareTier.SINGLE_GPU_DC: 5, HardwareTier.SINGLE_NODE: 5,
        HardwareTier.MULTI_NODE: 4, HardwareTier.DATACENTER: 4,
        HardwareTier.UNKNOWN: 2,
    },
}
```

  `score_model(entry, profile: str = "default")` looks up `MODEL_PROFILES` (unknown → `ModelProfileError` listing available names) and uses that tier map at the `:56` lookup; everything else identical. New pure `rescore_entries(entries: list[ModelEntry], profile: str) -> list[ModelEntry]` — recomputes breakdown+ring per entry via `model_copy(update={"score":..., "score_breakdown":..., "ring":...})`; `"default"` returns the input list unchanged. **Persisted rings untouched** — callers use this as a view only.
- `/models?profile=datacenter-first`: route gains `profile: str = ""`; invalid/unknown → fall back to default with the note suppressed (no 500); template shows `{% if active_profile %}<p class="profile-note">Viewing through the <strong>{{ active_profile }}</strong> lens — rings recomputed, not persisted. <a href="/models">default view</a></p>{% endif %}` plus a link to `?profile=datacenter-first` when in default view. Static export: default lens only (unchanged, documented).
- MCP `list_models(..., profile: str | None = None)` → applies `rescore_entries` before filtering/shaping; server.py tool signature updated.

- [ ] **Step 1: Failing pure tests** (append to `tests/test_models_radar_scoring.py`):

```python
def _dc_entry():
    from radar.models_radar.entities import ModelEntry, Openness, QuantVariant

    return ModelEntry.model_validate({
        "id": "big-moe", "name": "Big-MoE-1T", "family": "Big",
        "params_total": 1_000_000_000_000, "openness": Openness.OPEN_PERMISSIVE,
        "hardware_tier": "single_node",
        "quants": [QuantVariant(format="FP8", bits_per_weight=8.0,
                                est_memory_gb_4k=600.0)],
    })


def test_datacenter_first_lifts_single_node_model_to_adopt():
    from radar.models_radar.scoring import model_ring, score_model

    default = score_model(_dc_entry())
    dc = score_model(_dc_entry(), profile="datacenter-first")
    assert default.local_runnability == 1
    assert dc.local_runnability == 5
    assert model_ring(dc).value == "adopt"
    assert model_ring(default).value != "adopt"


def test_unknown_profile_raises_with_names():
    import pytest

    from radar.models_radar.scoring import ModelProfileError, score_model

    with pytest.raises(ModelProfileError, match="datacenter-first"):
        score_model(_dc_entry(), profile="nope")


def test_rescore_entries_is_a_view():
    from radar.models_radar.pipeline import score_entries
    from radar.models_radar.scoring import rescore_entries

    scored = score_entries([_dc_entry()])
    rescored = rescore_entries(scored, "datacenter-first")
    assert scored[0].ring != rescored[0].ring
    assert scored[0].ring is not None  # input untouched (frozen copies)
```

(Sanity math for the first test: openness 5 + runnability 1 + capability 5 (1T ≥ 100B) + ecosystem 2 (1 format, no ollama) = 13/4 = 3.25 → PILOT default; dc-first: (5+5+5+2)/4 = 4.25 and openness ≥ 3 → ADOPT.)

- [ ] **Step 2: RED → implement scoring.py → GREEN.** Then wire the surfaces (web test: `/models?profile=datacenter-first` shows the note + a ring-pill change for a seeded single_node entry; unknown profile → 200 with no note; MCP test: `list_models(profile="datacenter-first")` returns lifted ring for the fixture).
- [ ] **Step 3: Full gates; commit** — `git commit -am "feat: datacenter-first model scoring view on /models and MCP (persisted rings untouched)"`

---

### Task 6: Datacenter "Runs on" rows + picker group + MCP/CLI device surfacing

**Files:**
- Modify: `src/radar/models_radar/devices.py` (DATACENTER_DEVICE_TIERS), `src/radar/web/picker_context.py`, `src/radar/web/templates/_model_detail.html`, `_device_picker.html`, `src/radar/mcp_server/model_queries.py` (list_devices includes nodes/clusters), `src/radar/cli.py:719-726` (`models devices` prints nodes/clusters; widen column to `<26`)
- Test: `tests/test_devices.py` (append), `tests/test_static_site.py` (append), `tests/test_device_picker.py` (append), `tests/test_model_queries.py` (append)

**Interfaces:**
- `devices.py`: `DATACENTER_DEVICE_TIERS: list[str] = ["h100-80gb", "h200-141gb", "b200-192gb", "mi300x-192gb", "hgx-h200-8", "gb200-nvl72"]` + invariant test (all resolvable via `resolve_device`).
- `picker_context.py`: `def datacenter_fit_rows(model: ModelEntry) -> list[dict[str, Any]]` — same 3-key row shape as `fit_by_tier` but iterating `DATACENTER_DEVICE_TIERS` through `resolve_device` (handles nodes). `picker_context()`'s `device_presets` list now appends node/cluster entries (`{"id", "label", "total_memory_gb", "kind", "gpu_count", "usable_gb", "datacenter": True}`) and every device dict gains `"datacenter": d.datacenter` (additive key — pinned picker tests keep passing).
- `_model_detail.html`: after the existing "Runs on" block, a second table gated on size:

```jinja
{% if datacenter_fit and model.hardware_tier.value in ("workstation", "single_gpu_dc", "single_node", "multi_node", "datacenter") %}
<h3>Runs on — datacenter</h3>
<div class="table-wrap">
<table><thead><tr><th>Device / node</th><th>Fit</th><th>Largest quant that fits</th></tr></thead><tbody>
{% for r in datacenter_fit %}<tr><td>{{ r.device }}</td><td>{% if r.verdict == "fits" %}<span class="ring-pill fit-yes">Fits</span>{% elif r.verdict == "fits_tight" %}<span class="ring-pill fit-tight">Fits (tight)</span>{% elif r.verdict == "fits_quantized" %}<span class="ring-pill fit-tight">Fits (quantized)</span>{% elif r.verdict == "wont_fit" %}<span class="ring-pill fit-no">Won't fit</span>{% else %}<span class="ring-pill">Unknown</span>{% endif %}</td><td>{{ r.best_quant }}</td></tr>{% endfor %}
</tbody></table>
</div>
{% endif %}
```

  Context var `datacenter_fit` threaded from `app.py` model route (`:415` area) and `static_site.py` `_write_model_pages` (`:492` area) via `datacenter_fit_rows(entry)`.
- `_device_picker.html`: 4th optgroup BEFORE the custom option: `<optgroup label="Datacenter / nodes">{% for d in device_picker.device_presets if d.datacenter %}...{% endfor %}</optgroup>`, and the three existing optgroups exclude datacenter entries (`if d.kind == 'gpu' and not d.datacenter`).
- MCP `list_devices()` appends node/cluster entries (same 6-key shape, `name` key preserved); CLI `models devices` prints three sections (Devices/Nodes/Clusters).

- [ ] **Step 1: Failing tests** (sketches — adapt to file conventions):

```python
# tests/test_devices.py
def test_datacenter_tiers_all_resolvable():
    from radar.models_radar.devices import DATACENTER_DEVICE_TIERS

    for key in DATACENTER_DEVICE_TIERS:
        assert resolve_device(key) is not None

# tests/test_static_site.py — big model gets the datacenter table; small model doesn't
def test_model_page_datacenter_runs_on_table(tmp_path: Path):
    big = _model_entry_with(hardware_tier="single_node", params_total=671_000_000_000)  # adapt to the file's model factory
    render_static_site([], tmp_path / "_site", datetime(2026, 7, 29, tzinfo=UTC), model_entries=[big])
    page = (tmp_path / "_site" / f"model_{big.id}.html").read_text(encoding="utf-8")
    assert "Runs on — datacenter" in page
    assert "H200 (141GB)" in page

# tests/test_device_picker.py
def test_picker_has_datacenter_optgroup():
    ctx = picker_context()
    assert any(d.get("datacenter") for d in ctx["device_presets"])
    # render the partial via the models page as the existing tests do; assert
    # 'label="Datacenter / nodes"' in html and "hgx-h200-8" in html

# tests/test_model_queries.py
def test_list_devices_includes_nodes():
    assert any(d["id"] == "hgx-h200-8" and d["gpu_count"] == 8 for d in svc.list_devices())
```

- [ ] **Step 2: RED → implement → GREEN; full gates.** (Watch `test_device_picker.py:16-18` — additive keys only; `test_static_site.py:463` row-count is length-relative and unaffected.)
- [ ] **Step 3: Commit** — `git commit -am "feat: datacenter runs-on rows, picker node group, nodes in MCP/CLI device lists"`

---

### Task 7: Platform capability matrix (+ docs/CHANGELOG)

**Files:**
- Create: `config/platform-matrix.yaml`, `src/radar/models_radar/platform_matrix.py`, `src/radar/web/templates/platforms.html`, `static_platforms.html`
- Modify: `src/radar/web/app.py` (route), `src/radar/web/static_site.py` (writer + kwarg), `src/radar/cli.py` (export wiring ~line 2160), `src/radar/mcp_server/model_queries.py` + `server.py` (get_platform_support tool), the 19 nav templates (+1 "Platforms" item), `README.md` (highlights bullet), `docs/architecture.md` (module map row), `CHANGELOG.md`
- Test: `tests/test_platform_matrix.py` (new), `tests/test_web.py` (append + sweep loops at `:1375,:1536`), `tests/test_static_site.py` (append + sweep list at `:1036`), `tests/test_model_queries.py` (append)

**Interfaces:**
- `platform_matrix.py`:

```python
Support = Literal["yes", "partial", "no", "unknown"]

_HARDWARE_KEYS = ("nvidia", "amd", "intel_gaudi", "apple", "ascend", "cpu")
_FEATURE_KEYS = (
    "tensor_parallel", "pipeline_parallel", "expert_parallel",
    "mla", "hybrid_attention", "fp8", "nvfp4", "awq", "gptq", "gguf",
    "kv_cache_fp8", "speculative_decoding", "prefix_caching",
    "disaggregated_prefill",
)


class PlatformSeed(BaseModel):  # extra="forbid", frozen
    id: str
    name: str
    repo_url: str
    hardware: dict[str, Support]   # keys validated ⊆ _HARDWARE_KEYS
    features: dict[str, Support]   # keys validated ⊆ _FEATURE_KEYS
    sources: list[str]             # citation URLs, min_length=1
    verified: str                  # ISO date
    notes: str = ""


class PlatformMatrixError(ValueError): ...
def load_platform_matrix(path: Path) -> list[PlatformSeed]: ...  # same 3-try shape + unique ids + key-subset validation
```

  **YAML 1.1 boolean trap (must handle):** unquoted `yes`/`no` in YAML parse as `True`/`False`, not strings — a bare `nvidia: yes` would fail the `Support` literal. Two-layer defense: (1) all values in the seed YAML are QUOTED (`nvidia: "yes"`); (2) `PlatformSeed` carries a `field_validator(mode="before")` on `hardware`/`features` coercing `True → "yes"` and `False → "no"` so a hand-edited unquoted cell degrades gracefully instead of crashing the loader. Add a dedicated test: a YAML with bare `yes`/`no` loads with the coerced string values.

  **Documented scope deferrals (spec §5.4):** the spec's "kept current semi-automatically by cross-linking release notes the radar already collects" currency mechanism is NOT built here — citations + verified dates ship now; the release-note cross-linker is a follow-up (record in CHANGELOG + PR body). Likewise Task 6 implements "a datacenter row set joins COMMON_DEVICE_TIERS" as a separate `DATACENTER_DEVICE_TIERS` second table rather than growing the homelab list — deliberate interpretation, flagged for the final reviewer.

- Seed content — engines in priority order (spec D2): `vllm`, `sglang`, `tensorrt-llm`, then `llama-cpp`, `ollama`, `mlx-lm`, `tgi`, `lmdeploy`. **Every cell live-verified against the engine's docs/release notes (curl); `unknown` is the honest default — never guess a `yes`.** Each engine's `sources` lists the doc URLs actually consulted.
- Page `/platforms`: matrix table — rows = engines, column groups Hardware then Features, cells render `{% if v == "yes" %}✓{% elif v == "partial" %}◐{% elif v == "no" %}✗{% else %}?{% endif %}` with `title="{{ key }}: {{ v }}"`; per-engine sources footnotes; legend line explaining ✓◐✗? and the verified dates. Empty state: "No platform matrix seeded." Static twin writes `platforms.html` behind `if platform_entries:` guard; CLI export loads the seed with the parents[2] fallback idiom and passes `platform_entries=... or None`.
- Nav: `"Platforms": "/platforms"` (live) / `"platforms.html"` (static) inserted after "Models" in all 19 nav-bearing templates (recon list in Context map).
- MCP: `get_platform_support(platform: str | None = None, feature: str | None = None) -> list[dict]` — filters the seed; feature filter returns `{platform, feature, support, sources}` rows.
- Docs: README Highlights gains a `🧰 **Platform capability matrix**` bullet; `docs/architecture.md` module map row for `platform_matrix`; CHANGELOG `### Device & platform knowledge (sub-project C)` block covering all seven tasks.

- [ ] **Step 1: Failing loader tests** (`tests/test_platform_matrix.py`):

```python
"""Platform capability matrix seed."""

from __future__ import annotations

from pathlib import Path

import pytest

from radar.models_radar.platform_matrix import (
    PlatformMatrixError,
    load_platform_matrix,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SEED = _REPO_ROOT / "config" / "platform-matrix.yaml"


def test_bundled_matrix_loads_with_priority_engines():
    platforms = {p.id: p for p in load_platform_matrix(_SEED)}
    for pid in ("vllm", "sglang", "tensorrt-llm", "llama-cpp", "ollama"):
        assert pid in platforms, pid
    vllm = platforms["vllm"]
    assert vllm.features["mla"] == "yes"          # vLLM ships DeepSeek MLA
    assert vllm.hardware["nvidia"] == "yes"
    assert vllm.sources and vllm.verified


def test_every_engine_cites_sources_and_no_stray_keys():
    for p in load_platform_matrix(_SEED):
        assert p.sources, p.id
        assert p.verified, p.id


def test_unknown_feature_key_rejected(tmp_path: Path):
    bad = tmp_path / "m.yaml"
    bad.write_text(
        "platforms:\n"
        "  - id: x\n    name: X\n    repo_url: https://x\n"
        '    hardware: {nvidia: "yes"}\n'
        '    features: {warp_drive: "yes"}\n'
        "    sources: [https://x/docs]\n    verified: '2026-07-29'\n",
        encoding="utf-8",
    )
    with pytest.raises(PlatformMatrixError, match="warp_drive"):
        load_platform_matrix(bad)


def test_bare_yaml_booleans_are_coerced_not_fatal(tmp_path: Path):
    hand_edited = tmp_path / "m.yaml"
    hand_edited.write_text(
        "platforms:\n"
        "  - id: x\n    name: X\n    repo_url: https://x\n"
        "    hardware: {nvidia: yes, amd: no}\n"   # YAML 1.1 booleans
        '    features: {fp8: "partial"}\n'
        "    sources: [https://x/docs]\n    verified: '2026-07-29'\n",
        encoding="utf-8",
    )
    (platform,) = load_platform_matrix(hand_edited)
    assert platform.hardware["nvidia"] == "yes"
    assert platform.hardware["amd"] == "no"
```

- [ ] **Step 2: RED → implement loader → live-verify and write the seed → GREEN.** (If a claim can't be verified from docs, the cell is `unknown` — the reviewer will spot-check cells against your cited sources.)
- [ ] **Step 3: Page + nav + MCP wiring (tests first per the §6d precedent: populated + empty web tests, static + back-compat tests, sweep-loop additions, MCP filter test).** Follow `techniques.html`'s skeleton; heading OUTSIDE table-wrap; tagline: `{% set tagline = "Which serving engines support which hardware and features — every claim cited." %}`.
- [ ] **Step 4: Docs + CHANGELOG steps; full gates.**
- [ ] **Step 5: Commit** — `git commit -am "feat: platform capability matrix — cited engine support for hardware and features"`

---

## Final verification (whole sub-project)

- [ ] `uv run pytest -q && uv run ruff check . && uv run mypy src` — all green.
- [ ] Live smoke: `uv run radar models devices` shows devices+nodes+clusters; `uv run radar models fit --device hgx-h200-8 --root .` produces verdicts against real scan data; `/models?profile=datacenter-first` lifts DeepSeek-class rings (view only); `/platforms` renders the matrix; static export writes `platforms.html` + datacenter runs-on tables.
- [ ] Spot-check three platform-matrix cells and two device spec numbers against their cited URLs.
- [ ] Subagent-driven per-task reviews + final whole-branch review; PR per repo convention — **checks verified green BEFORE merge**.
