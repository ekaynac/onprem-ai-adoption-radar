# Model Discovery — HF-Trending Local-Model Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** `radar models discover` queries Hugging Face for trending local-runnable models, drops those already in `config/model-seed.yaml`, and writes proposals to `data/proposed-model-seeds.yaml` for human review (never auto-adds).

**Architecture:** Mirror the tool discovery (`discovery/proposals.py` + `discovery/hf_papers.py` + the `radar discover` CLI). A `ModelProposal` review model + atomic I/O, an HF list-endpoint discovery function, and a `models discover` sub-command.

**Tech Stack:** Python 3.12, pydantic v2, httpx (async), PyYAML, typer, pytest + ruff + mypy.

## Global Constraints

- Python ≥ 3.12; new modules begin with `from __future__ import annotations`.
- No new third-party dependencies; no API key (public HF); deterministic core, no LLM.
- Immutability (frozen `ModelProposal`); proposals only ever written to the review file — never auto-added to `model-seed.yaml`.
- Best-effort: HF failure → empty proposals + a logged warning, never crash.
- ruff + mypy clean; coverage ≥ 80%. Full-gate (`ruff check src tests`, `mypy src`, `pytest -q`) before EVERY commit (not just the touched file).
- Commit on the CURRENT branch only — never create/switch branches.

---

### Task 1: ModelProposal model + review-file I/O

**Files:**
- Create: `src/radar/discovery/model_proposals.py`
- Test: `tests/test_model_proposals.py`

**Interfaces:**
- Produces: frozen `ModelProposal(model_id, name, family, hf_repo, downloads, likes, modality, reason="", suggested_id)`;
  `write_model_proposals(path: Path, proposals: list[ModelProposal]) -> None`;
  `load_model_proposals(path: Path) -> list[ModelProposal]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_model_proposals.py
from __future__ import annotations

from pathlib import Path

from radar.discovery.model_proposals import (
    ModelProposal, load_model_proposals, write_model_proposals,
)


def _p(model_id: str) -> ModelProposal:
    return ModelProposal(
        model_id=model_id, name=model_id, family="Qwen",
        hf_repo=f"Qwen/{model_id}", downloads=123456, likes=789,
        modality="text", reason="trending: 123456 downloads", suggested_id=f"hf-{model_id.lower()}",
    )


def test_round_trip(tmp_path: Path):
    path = tmp_path / "proposed-model-seeds.yaml"
    write_model_proposals(path, [_p("Qwen3-32B"), _p("Qwen3-14B")])
    loaded = load_model_proposals(path)
    assert [m.model_id for m in loaded] == ["Qwen3-32B", "Qwen3-14B"]
    assert loaded[0].hf_repo == "Qwen/Qwen3-32B" and loaded[0].downloads == 123456


def test_load_missing_is_empty(tmp_path: Path):
    assert load_model_proposals(tmp_path / "nope.yaml") == []


def test_write_is_atomic_and_overwrites(tmp_path: Path):
    path = tmp_path / "proposed-model-seeds.yaml"
    write_model_proposals(path, [_p("A")])
    write_model_proposals(path, [_p("B")])
    assert [m.model_id for m in load_model_proposals(path)] == ["B"]
    assert not (tmp_path / "proposed-model-seeds.tmp").exists()


def test_model_proposal_is_frozen():
    import pytest
    p = _p("X")
    with pytest.raises(Exception):
        p.model_id = "y"
```

- [ ] **Step 2: Run test → fails** (`pytest tests/test_model_proposals.py -v` → `ModuleNotFoundError`).

- [ ] **Step 3: Implement** (mirror `discovery/proposals.py`)

```python
# src/radar/discovery/model_proposals.py
"""Candidate MODEL proposals — written for human review, never auto-applied.

Model discovery writes suggestions to ``data/proposed-model-seeds.yaml``. A human
reviews them and promotes the good ones into ``config/model-seed.yaml``. The radar
never adds a model to its own seed automatically.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict


class ModelProposal(BaseModel):
    """A discovered model proposed as a possible new seed entry."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model_id: str
    name: str
    family: str
    hf_repo: str
    downloads: int
    likes: int
    modality: str
    reason: str = ""
    suggested_id: str


def write_model_proposals(path: Path, proposals: list[ModelProposal]) -> None:
    """Write model proposals to YAML (atomic). Overwrites any prior file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"proposals": [p.model_dump(mode="json") for p in proposals]}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    tmp.replace(path)


def load_model_proposals(path: Path) -> list[ModelProposal]:
    """Load model proposals; a missing file is an empty list."""
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [ModelProposal.model_validate(item) for item in raw.get("proposals") or []]
```

Note: `ConfigDict(extra="forbid", frozen=True)` — the field `model_id` would normally trip pydantic's
protected-namespace warning for `model_`; add `protected_namespaces=()` to the `ConfigDict` if a warning
appears at import/test time (keep test output pristine). i.e.
`model_config = ConfigDict(extra="forbid", frozen=True, protected_namespaces=())`.

- [ ] **Step 4: Run test → pass**, then full gate. **Step 5: Commit** `git add src/radar/discovery/model_proposals.py tests/test_model_proposals.py && git commit -m "feat(models): ModelProposal review model + atomic I/O"`

---

### Task 2: HF trending-models discovery

**Files:**
- Create: `src/radar/discovery/hf_trending_models.py`
- Test: `tests/test_hf_trending_models.py`

**Interfaces:**
- Consumes: `ModelProposal` (Task 1), `ModelSeed` (`radar.models_radar.entities`), `project_slug` (`radar.web.slugs`).
- Produces: `fetch_trending_models(client, limit=50, pipeline_tag="text-generation", sort="trendingScore", headers=None) -> list[dict]`;
  `discover_trending_models(seeds: list[ModelSeed], client, min_downloads=10000, limit=50, headers=None) -> list[ModelProposal]`.
  Module constant `HF_MODELS_URL = "https://huggingface.co/api/models"`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_hf_trending_models.py
from __future__ import annotations

import pytest

from radar.discovery.hf_trending_models import discover_trending_models, fetch_trending_models
from radar.models_radar.entities import ModelSeed

# HF /api/models returns a list of dicts like this:
MODELS = [
    {"id": "Qwen/Qwen3-32B", "downloads": 900000, "likes": 1200, "pipeline_tag": "text-generation"},
    {"id": "meta-llama/Llama-3.3-70B-Instruct", "downloads": 500000, "likes": 900, "pipeline_tag": "text-generation"},
    {"id": "Qwen/Qwen3-8B", "downloads": 800000, "likes": 1100, "pipeline_tag": "text-generation"},  # already seeded
    {"id": "tiny/obscure-model", "downloads": 50, "likes": 1, "pipeline_tag": "text-generation"},     # below floor
]


class FakeResp:
    def __init__(self, payload): self._p = payload
    def raise_for_status(self): pass
    def json(self): return self._p


class FakeClient:
    def __init__(self, payload): self.payload = payload; self.last_params = None
    async def get(self, url, params=None, **kw):
        self.last_params = params
        return FakeResp(self.payload)


class BoomClient:
    async def get(self, url, **kw): raise RuntimeError("network down")


def _seeds():
    return [ModelSeed(id="qwen3-8b", name="Qwen3 8B", family="Qwen3", hf_repo="Qwen/Qwen3-8B")]


@pytest.mark.asyncio
async def test_fetch_trending_models_passes_params():
    client = FakeClient(MODELS)
    out = await fetch_trending_models(client, limit=10, pipeline_tag="text-generation")
    assert out == MODELS
    assert client.last_params["limit"] == 10
    assert client.last_params["pipeline_tag"] == "text-generation"
    assert client.last_params["sort"] == "trendingScore"


@pytest.mark.asyncio
async def test_discover_dedups_seeded_and_filters_floor_and_ranks():
    proposals = await discover_trending_models(_seeds(), FakeClient(MODELS), min_downloads=10000)
    ids = [p.hf_repo for p in proposals]
    assert "Qwen/Qwen3-8B" not in ids        # already seeded → dropped
    assert "tiny/obscure-model" not in ids    # below floor → dropped
    assert ids == ["Qwen/Qwen3-32B", "meta-llama/Llama-3.3-70B-Instruct"]  # ranked by downloads desc
    top = proposals[0]
    assert top.family == "Qwen" and top.modality == "text" and top.suggested_id == "hf-qwen3-32b"
    assert "900000" in top.reason


@pytest.mark.asyncio
async def test_discover_degrades_to_empty_on_failure():
    assert await discover_trending_models(_seeds(), BoomClient()) == []
```

- [ ] **Step 2: Run test → fails** (`ModuleNotFoundError`).

- [ ] **Step 3: Implement** (mirror `discovery/hf_papers.py` best-effort shape)

```python
# src/radar/discovery/hf_trending_models.py
"""Discover trending local-runnable models from the Hugging Face Hub.

Queries the HF models list endpoint, drops models already in the seed and those
below a download floor, and returns proposals ranked by downloads. Best-effort:
a network failure degrades to no proposals. Results are only ever written to the
review file (see model_proposals.py) — never auto-added to the seed.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from radar.discovery.model_proposals import ModelProposal
from radar.models_radar.entities import ModelSeed
from radar.web.slugs import project_slug


logger = logging.getLogger(__name__)

HF_MODELS_URL = "https://huggingface.co/api/models"
_MODALITY_BY_TAG = {
    "text-generation": "text",
    "image-text-to-text": "multimodal",
    "automatic-speech-recognition": "audio",
    "text-to-image": "vision",
}


class _AsyncClient(Protocol):
    async def get(self, url: str, **kwargs: Any) -> Any: ...


async def fetch_trending_models(
    client: _AsyncClient,
    limit: int = 50,
    pipeline_tag: str = "text-generation",
    sort: str = "trendingScore",
    headers: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """HF models list (best-effort → [])."""
    try:
        response = await client.get(
            HF_MODELS_URL,
            params={"sort": sort, "direction": -1, "limit": limit,
                    "pipeline_tag": pipeline_tag},
            headers=headers or {},
        )
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, list) else []
    except Exception as exc:
        logger.warning("HF trending-models fetch failed: %s", exc)
        return []


async def discover_trending_models(
    seeds: list[ModelSeed],
    client: _AsyncClient,
    min_downloads: int = 10000,
    limit: int = 50,
    headers: dict[str, str] | None = None,
) -> list[ModelProposal]:
    """Trending models not already seeded, above the download floor, ranked by downloads."""
    seeded = {(s.hf_repo or "").lower() for s in seeds if s.hf_repo}
    items = await fetch_trending_models(client, limit=limit, headers=headers)
    proposals: list[ModelProposal] = []
    for item in items:
        repo = item.get("id") or ""
        if not repo or repo.lower() in seeded:
            continue
        downloads = int(item.get("downloads") or 0)
        if downloads < min_downloads:
            continue
        likes = int(item.get("likes") or 0)
        name = repo.split("/")[-1]
        family = repo.split("/")[0] if "/" in repo else name
        modality = _MODALITY_BY_TAG.get(item.get("pipeline_tag") or "", "text")
        proposals.append(ModelProposal(
            model_id=name, name=name, family=family, hf_repo=repo,
            downloads=downloads, likes=likes, modality=modality,
            reason=f"trending: {downloads} downloads, {likes} likes",
            suggested_id=f"hf-{project_slug(name)}",
        ))
    return sorted(proposals, key=lambda p: p.downloads, reverse=True)[:limit]
```

- [ ] **Step 4: Run test → pass**, full gate. **Step 5: Commit** `feat(models): HF trending-models discovery`.

---

### Task 3: `radar models discover` CLI

**Files:**
- Modify: `src/radar/cli.py` (add a `discover` command to the existing `models_app`)
- Test: `tests/test_models_radar_cli.py` (add)

**Interfaces:**
- Consumes: `discover_trending_models` (Task 2), `write_model_proposals` (Task 1), `load_model_seed`, packaged-seed fallback (same as `models scan`).
- Produces: CLI `radar models discover --root . [--min-downloads N] [--limit N]` writing `data/proposed-model-seeds.yaml`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_models_radar_cli.py — add
def test_models_discover_writes_proposals(tmp_path, monkeypatch):
    from typer.testing import CliRunner
    from radar.cli import app
    from radar.discovery.model_proposals import ModelProposal, load_model_proposals

    runner = CliRunner()
    runner.invoke(app, ["init", "--root", str(tmp_path)])

    async def fake_discover(seeds, client, min_downloads=10000, limit=50, headers=None):
        return [ModelProposal(model_id="Qwen3-32B", name="Qwen3-32B", family="Qwen",
                              hf_repo="Qwen/Qwen3-32B", downloads=900000, likes=1200,
                              modality="text", reason="trending", suggested_id="hf-qwen3-32b")]
    monkeypatch.setattr("radar.discovery.hf_trending_models.discover_trending_models", fake_discover)

    result = runner.invoke(app, ["models", "discover", "--root", str(tmp_path)])
    assert result.exit_code == 0, result.stdout
    proposals = load_model_proposals(tmp_path / "data" / "proposed-model-seeds.yaml")
    assert any(p.hf_repo == "Qwen/Qwen3-32B" for p in proposals)
    assert "Qwen3-32B" in result.stdout
```

- [ ] **Step 2: Run test → fails** (no `discover` command).

- [ ] **Step 3: Implement** — add to `cli.py` (place near the other `@models_app.command` defs). Match the
packaged-seed fallback used by `models_scan` (`config/model-seed.yaml`, else the packaged one):

```python
@models_app.command("discover")
def models_discover(
    min_downloads: int = typer.Option(10000, help="Minimum HF downloads for a candidate."),
    limit: int = typer.Option(50, help="Max candidates to fetch/propose."),
    root: Path = typer.Option(Path("."), help="Project root."),
) -> None:
    """Find trending HF models and write proposals for review (never auto-adds)."""
    import asyncio

    import httpx

    from radar.discovery.hf_trending_models import discover_trending_models
    from radar.discovery.model_proposals import write_model_proposals
    from radar.models_radar.seed import load_model_seed

    seed_path = root / "config" / "model-seed.yaml"
    if not seed_path.exists():
        seed_path = Path(__file__).resolve().parents[2] / "config" / "model-seed.yaml"
    seeds = load_model_seed(seed_path)

    async def _run():
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            return await discover_trending_models(
                seeds, client, min_downloads=min_downloads, limit=limit
            )

    proposals = asyncio.run(_run())
    out_path = root / "data" / "proposed-model-seeds.yaml"
    write_model_proposals(out_path, proposals)
    console.print(f"Found {len(proposals)} model candidate(s) → {out_path}")
    for p in proposals[:15]:
        console.print(
            f"  {p.downloads:>9,}↓  {p.model_id:<32} {p.family:<14} {p.hf_repo}",
            highlight=False,
        )
```

The test monkeypatches `radar.discovery.hf_trending_models.discover_trending_models`; the command imports
it inside the function body at call time, so the patch on the source module attribute takes effect (same
pattern as the tool `discover` test). Keep that import style.

- [ ] **Step 4: Run test → pass**, full gate. **Step 5: Commit** `feat(models): radar models discover CLI`.

---

### Task 4: Full-gate + live smoke + final review + merge

**Files:** none.

- [ ] **Step 1: Gates** — `ruff check src tests && mypy src && pytest -q` green.
- [ ] **Step 2: Live smoke** — `radar models discover --root .` (real HF API) → `data/proposed-model-seeds.yaml`
  lists trending text-generation models; confirm NONE of the 8 already-seeded repos appear (e.g. `Qwen/Qwen3-8B`,
  `meta-llama/Llama-3.1-8B-Instruct`); confirm `load_model_proposals` reads it back. Then force-degrade
  (point at an unreachable host via a quick Python snippet, or trust the BoomClient unit test) — the command
  must write an empty proposals file and exit 0. If the HF `/api/models` param shape differs from the fixture
  (e.g. `sort` value), adjust `fetch_trending_models` and re-run the unit tests. **Do not skip the live run —
  the SP1 arXiv bug was exactly an endpoint/param mismatch unit tests missed.**
- [ ] **Step 3: Final whole-branch review** (most-capable model) over branch base..HEAD.
- [ ] **Step 4: Merge** to main `--no-ff`, delete branch, integrate `origin`, push.

```bash
git checkout main && git merge --no-ff feature/model-discovery \
  -m "Merge feature/model-discovery: HF-trending local-model discovery"
git branch -d feature/model-discovery
```

---

## Self-Review

**Spec coverage:** §5 model discovery (HF-trending → proposed-model-seeds.yaml, dedup vs seed, review-only) →
Tasks 1 (proposal model + I/O), 2 (HF discovery + dedup + floor + rank), 3 (CLI). Live verification → Task 4.
Fully covers the deferred §5 item; no scope creep (no auto-add, no daily-CI step — manual command like the
tool `discover`).

**Placeholder scan:** Every code step has complete code. Task 1 notes the `protected_namespaces=()` ConfigDict
fix as a concrete conditional instruction (pydantic protects `model_` prefixes), not a placeholder.

**Type consistency:** `ModelProposal` fields (Task 1) consumed identically by Task 2 + the Task 3 test.
`discover_trending_models(seeds, client, min_downloads, limit, headers)` signature matches Task 2 ↔ Task 3 call
+ the Task 3 monkeypatch target (`radar.discovery.hf_trending_models.discover_trending_models`).
`fetch_trending_models(client, limit, pipeline_tag, sort, headers)` matches Task 2 def ↔ its caller in
`discover_trending_models`. `write_model_proposals`/`load_model_proposals` (Task 1) used by Task 3 + Task 4.
`ModelSeed.hf_repo` (existing) used for dedup. `project_slug` (existing) for `suggested_id`.
