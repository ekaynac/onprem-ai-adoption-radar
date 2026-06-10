# Agent/Tooling Adoption Radar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build V1 of a laptop-runnable agent/tooling adoption radar that scans curated public sources, scores them deterministically, produces decision cards, and serves a local dashboard.

**Architecture:** Python package with a Typer CLI, Pydantic models, async collectors, file run artifacts, SQLite persistence, deterministic scoring, Markdown/JSON reports, and a minimal FastAPI dashboard. The pipeline is stage-based: initialize config -> collect signals -> dedupe -> score -> build cards -> persist -> report -> serve.

**Tech Stack:** Python 3.12, uv, Typer, Rich, Pydantic 2, PyYAML, httpx, feedparser, FastAPI, Uvicorn, pytest, pytest-asyncio.

---

## File Structure

Create this structure across the tasks:

```txt
onprem-ai-adoption-radar/
  pyproject.toml
  README.md
  .env.example
  config/
    seed-sources.yaml
    scoring.yaml
    category-quotas.yaml
  data/
    .gitkeep
  src/radar/
    __init__.py
    cli.py
    constants.py
    models.py
    orchestrator.py
    init_project.py
    collectors/
      __init__.py
      base.py
      github.py
      manual.py
      registry.py
      rss.py
    pipeline/
      __init__.py
      cards.py
      dedupe.py
      quotas.py
    reports/
      __init__.py
      json_export.py
      markdown.py
    scoring/
      __init__.py
      deterministic.py
      rings.py
    storage/
      __init__.py
      config.py
      database.py
      run_store.py
    web/
      __init__.py
      app.py
      templates/
        index.html
  tests/
    fixtures/
      github_releases.json
      rss_feed.xml
    test_cards.py
    test_cli.py
    test_collectors_github.py
    test_collectors_manual.py
    test_collectors_rss.py
    test_config.py
    test_database.py
    test_dedupe.py
    test_init_project.py
    test_orchestrator.py
    test_quotas.py
    test_reports.py
    test_run_store.py
    test_scoring.py
    test_web.py
```

Boundaries:

- `models.py`: typed domain objects and config objects only.
- `storage/config.py`: YAML loading and `${ENV_VAR}` expansion.
- `collectors/`: source-specific fetchers that return `Signal` objects.
- `pipeline/`: pure transformations with no network access.
- `scoring/`: deterministic score and ring logic.
- `storage/run_store.py`: JSON stage artifacts per run.
- `storage/database.py`: SQLite persistence for signals and cards.
- `reports/`: Markdown and JSON rendering.
- `orchestrator.py`: pipeline composition.
- `cli.py`: user commands only.
- `web/app.py`: local read-only dashboard only.

---

## Task 1: Project Scaffold and CLI Shell

**Files:**
- Create: `pyproject.toml`
- Create: `src/radar/__init__.py`
- Create: `src/radar/constants.py`
- Create: `src/radar/cli.py`
- Create: `tests/test_cli.py`

- [ ] **Step 1: Write the failing CLI tests**

Create `tests/test_cli.py`:

```python
from typer.testing import CliRunner

from radar.cli import app


def test_version_command_prints_version():
    runner = CliRunner()

    result = runner.invoke(app, ["version"])

    assert result.exit_code == 0
    assert "onprem-ai-adoption-radar" in result.stdout
    assert "0.1.0" in result.stdout


def test_app_has_help_text():
    runner = CliRunner()

    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "Agent/tooling adoption radar" in result.stdout
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
uv run pytest tests/test_cli.py -q
```

Expected: failure because `pyproject.toml` and `radar.cli` do not exist.

- [ ] **Step 3: Create the package scaffold**

Create `pyproject.toml`:

```toml
[project]
name = "onprem-ai-adoption-radar"
version = "0.1.0"
description = "Decision-oriented radar for agent/tooling adoption in on-prem AI workflows"
readme = "README.md"
requires-python = ">=3.12"
dependencies = [
  "feedparser>=6.0.11",
  "fastapi>=0.115.0",
  "httpx>=0.27.0",
  "jinja2>=3.1.4",
  "pydantic>=2.9.0",
  "python-dateutil>=2.9.0",
  "pyyaml>=6.0.2",
  "rich>=13.9.0",
  "typer>=0.12.5",
  "uvicorn>=0.32.0"
]

[project.optional-dependencies]
dev = [
  "pytest>=8.0.0",
  "pytest-asyncio>=0.24.0"
]

[project.scripts]
radar = "radar.cli:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/radar"]

[tool.pytest.ini_options]
minversion = "8.0"
addopts = "-q"
testpaths = ["tests"]
asyncio_mode = "auto"
```

Create `src/radar/__init__.py`:

```python
"""On-Prem AI Adoption Radar package."""

__version__ = "0.1.0"
```

Create `src/radar/constants.py`:

```python
"""Application constants."""

APP_NAME = "onprem-ai-adoption-radar"
DEFAULT_DATA_DIR = "data"
```

Create `src/radar/cli.py`:

```python
"""Command line interface for the adoption radar."""

from __future__ import annotations

import typer
from rich.console import Console

from radar import __version__
from radar.constants import APP_NAME


app = typer.Typer(
    help="Agent/tooling adoption radar for on-prem AI workflows.",
    no_args_is_help=True,
)
console = Console()


@app.command()
def version() -> None:
    """Print package version."""
    console.print(f"{APP_NAME} {__version__}")


def main() -> None:
    """Entrypoint for the installed console script."""
    app()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run:

```bash
uv sync --extra dev
uv run pytest tests/test_cli.py -q
```

Expected: `2 passed`.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/radar tests/test_cli.py
git commit -m "chore: scaffold radar package and cli"
```

---

## Task 2: Domain Models and Config Loading

**Files:**
- Create: `src/radar/models.py`
- Create: `src/radar/storage/__init__.py`
- Create: `src/radar/storage/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write the failing config/model tests**

Create `tests/test_config.py`:

```python
from pathlib import Path

import pytest

from radar.models import Config, Ring, SourceType
from radar.storage.config import ConfigError, expand_env_vars, load_config


def test_expand_env_vars_replaces_set_values(monkeypatch):
    monkeypatch.setenv("TOKEN", "abc123")

    value = {"headers": ["Bearer ${TOKEN}"], "plain": "${MISSING}"}

    assert expand_env_vars(value) == {
        "headers": ["Bearer abc123"],
        "plain": "${MISSING}",
    }


def test_load_config_validates_yaml(tmp_path: Path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
version: "1.0"
sources:
  - id: github-openclaw
    type: github_repo
    enabled: true
    project: OpenClaw
    category: general_agents
    url: https://github.com/openclaw/openclaw
    tags: [general-agent, open-source]
quotas:
  coding_agents: 4
scoring:
  default_ring: watch
""",
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert isinstance(config, Config)
    assert config.sources[0].id == "github-openclaw"
    assert config.sources[0].type == SourceType.GITHUB_REPO
    assert config.scoring.default_ring == Ring.WATCH


def test_load_config_reports_yaml_error(tmp_path: Path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("sources: [", encoding="utf-8")

    with pytest.raises(ConfigError) as exc:
        load_config(config_path)

    assert "Invalid YAML" in str(exc.value)


def test_load_config_reports_validation_error(tmp_path: Path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("version: '1.0'\nsources: []\n", encoding="utf-8")

    with pytest.raises(ConfigError) as exc:
        load_config(config_path)

    assert "Configuration validation failed" in str(exc.value)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
uv run pytest tests/test_config.py -q
```

Expected: failure because `radar.models` and `radar.storage.config` do not exist.

- [ ] **Step 3: Implement the models and config loader**

Create `src/radar/models.py`:

```python
"""Typed domain and configuration models."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, HttpUrl, field_validator


class SourceType(str, Enum):
    """Supported source types for V1."""

    GITHUB_REPO = "github_repo"
    RSS = "rss"
    MANUAL = "manual"


class Category(str, Enum):
    """Radar categories."""

    CODING_AGENTS = "coding_agents"
    GENERAL_AGENTS = "general_agents"
    MCP_TOOLING = "mcp_tooling"
    SANDBOX_GOVERNANCE = "sandbox_governance"
    AGENT_FRAMEWORKS = "agent_frameworks"


class Ring(str, Enum):
    """Radar rings."""

    ADOPT = "adopt"
    PILOT = "pilot"
    WATCH = "watch"
    AVOID = "avoid"


class SourceConfig(BaseModel):
    """A configured information source."""

    id: str
    type: SourceType
    enabled: bool = True
    project: str
    category: Category
    url: HttpUrl
    tags: list[str] = Field(default_factory=list)
    poll_interval_hours: int = Field(default=24, ge=1)


class ScoringConfig(BaseModel):
    """Scoring configuration."""

    default_ring: Ring = Ring.WATCH
    security_penalty_tags: list[str] = Field(
        default_factory=lambda: [
            "terminal-access",
            "file-write-access",
            "persistent-agent",
            "browser-access",
        ]
    )


class Config(BaseModel):
    """Application configuration."""

    version: str = "1.0"
    sources: list[SourceConfig] = Field(min_length=1)
    quotas: dict[Category, int] = Field(default_factory=dict)
    scoring: ScoringConfig = Field(default_factory=ScoringConfig)


class Signal(BaseModel):
    """Raw normalized signal collected from a source."""

    id: str
    source_id: str
    project: str
    category: Category
    title: str
    url: HttpUrl
    published_at: datetime
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    raw_summary: str = ""
    signal_type: str
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ScoreBreakdown(BaseModel):
    """Deterministic score dimensions."""

    workflow_impact: int = Field(ge=1, le=5)
    laptop_runnability: int = Field(ge=1, le=5)
    open_source_maturity: int = Field(ge=1, le=5)
    on_prem_relevance: int = Field(ge=1, le=5)
    security_posture: int = Field(ge=1, le=5)
    demo_value: int = Field(ge=1, le=5)
    setup_friction: int = Field(ge=1, le=5)

    @property
    def average(self) -> float:
        total = (
            self.workflow_impact
            + self.laptop_runnability
            + self.open_source_maturity
            + self.on_prem_relevance
            + self.security_posture
            + self.demo_value
            + self.setup_friction
        )
        return round(total / 7, 2)


class ScoredSignal(BaseModel):
    """Signal with deterministic scoring results."""

    signal: Signal
    scores: ScoreBreakdown
    reason_codes: list[str] = Field(default_factory=list)
    recommended_ring: Ring


class DecisionCard(BaseModel):
    """Project-level decision card generated from scored signals."""

    project: str
    category: Category
    ring: Ring
    summary: str
    workflow_fit: dict[str, str]
    risk_level: str
    risk_reasons: list[str] = Field(default_factory=list)
    try_this_week: list[str] = Field(default_factory=list)
    company_demo: dict[str, str | bool] = Field(default_factory=dict)
    evidence: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    last_reviewed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("risk_level")
    @classmethod
    def validate_risk_level(cls, value: str) -> str:
        allowed = {"low", "medium", "high"}
        if value not in allowed:
            raise ValueError(f"risk_level must be one of {sorted(allowed)}")
        return value
```

Create `src/radar/storage/__init__.py`:

```python
"""Storage helpers."""
```

Create `src/radar/storage/config.py`:

```python
"""Configuration loading and environment expansion."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from radar.models import Config


_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class ConfigError(ValueError):
    """Raised when configuration cannot be loaded."""


def expand_env_vars(value: Any) -> Any:
    """Recursively expand ${VAR} references in strings."""
    if isinstance(value, str):
        return _ENV_PATTERN.sub(lambda m: os.environ.get(m.group(1), m.group(0)), value)
    if isinstance(value, dict):
        return {key: expand_env_vars(item) for key, item in value.items()}
    if isinstance(value, list):
        return [expand_env_vars(item) for item in value]
    return value


def load_config(path: Path) -> Config:
    """Load and validate a YAML config file."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {path}: {exc}") from exc
    except FileNotFoundError as exc:
        raise ConfigError(f"Configuration file not found: {path}") from exc

    if raw is None:
        raw = {}

    expanded = expand_env_vars(raw)

    try:
        return Config.model_validate(expanded)
    except ValidationError as exc:
        raise ConfigError(f"Configuration validation failed for {path}: {exc}") from exc
```

- [ ] **Step 4: Run the tests to verify they pass**

Run:

```bash
uv run pytest tests/test_config.py -q
```

Expected: `4 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/radar/models.py src/radar/storage tests/test_config.py
git commit -m "feat: add typed config and domain models"
```

---

## Task 3: Run Artifact Store

**Files:**
- Create: `src/radar/storage/run_store.py`
- Create: `tests/test_run_store.py`

- [ ] **Step 1: Write the failing run store tests**

Create `tests/test_run_store.py`:

```python
import json
from pathlib import Path

import pytest

from radar.storage.run_store import RunStore


def test_create_run_writes_meta(tmp_path: Path):
    store = RunStore(tmp_path)

    run_id = store.create_run("run-test")

    assert run_id == "run-test"
    meta = json.loads((tmp_path / "run-test" / "meta.json").read_text())
    assert meta["run_id"] == "run-test"
    assert "created_at" in meta


def test_save_and_load_stage(tmp_path: Path):
    store = RunStore(tmp_path)
    store.create_run("run-test")

    store.save_stage("run-test", "raw_signals", [{"id": "s1"}])

    assert store.load_stage("run-test", "raw_signals") == [{"id": "s1"}]


def test_rejects_invalid_run_id(tmp_path: Path):
    store = RunStore(tmp_path)

    with pytest.raises(ValueError):
        store.create_run("../escape")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
uv run pytest tests/test_run_store.py -q
```

Expected: failure because `radar.storage.run_store` does not exist.

- [ ] **Step 3: Implement the run store**

Create `src/radar/storage/run_store.py`:

```python
"""File-based staged run artifact storage."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
STAGE_NAMES = {
    "raw_signals",
    "scored_signals",
    "filtered_signals",
    "decision_cards",
}


@dataclass
class RunStore:
    """Persist scan artifacts under data/runs/<run_id>."""

    root: Path

    def __post_init__(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def create_run(self, run_id: str | None = None) -> str:
        """Create a run directory and meta file."""
        resolved = run_id or self._make_run_id()
        run_dir = self._run_dir(resolved, must_exist=False)
        run_dir.mkdir(parents=True, exist_ok=True)
        meta_path = run_dir / "meta.json"
        if not meta_path.exists():
            meta_path.write_text(
                json.dumps(
                    {"run_id": resolved, "created_at": self._now()},
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        return resolved

    def save_stage(self, run_id: str, stage: str, payload: list[dict[str, Any]]) -> Path:
        """Save a JSON stage artifact."""
        if stage not in STAGE_NAMES:
            raise ValueError(f"Unsupported stage: {stage}")
        path = self._run_dir(run_id) / f"{stage}.json"
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        self.update_meta(run_id, {"last_stage": stage})
        return path

    def load_stage(self, run_id: str, stage: str) -> list[dict[str, Any]]:
        """Load a JSON stage artifact."""
        if stage not in STAGE_NAMES:
            raise ValueError(f"Unsupported stage: {stage}")
        path = self._run_dir(run_id) / f"{stage}.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def save_report(self, run_id: str, markdown: str) -> Path:
        """Save a Markdown report artifact."""
        path = self._run_dir(run_id) / "report.md"
        path.write_text(markdown, encoding="utf-8")
        self.update_meta(run_id, {"report": "report.md"})
        return path

    def update_meta(self, run_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        """Merge values into meta.json."""
        path = self._run_dir(run_id) / "meta.json"
        meta = json.loads(path.read_text(encoding="utf-8"))
        meta.update(updates)
        meta["updated_at"] = self._now()
        path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
        return meta

    def _run_dir(self, run_id: str, must_exist: bool = True) -> Path:
        if not RUN_ID_RE.fullmatch(run_id) or ".." in run_id:
            raise ValueError("Invalid run_id")
        root = self.root.resolve()
        path = (self.root / run_id).resolve()
        if not path.is_relative_to(root):
            raise ValueError("Invalid run_id")
        if must_exist and not path.exists():
            raise FileNotFoundError(f"Run not found: {run_id}")
        return path

    @staticmethod
    def _make_run_id() -> str:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        return f"run-{stamp}-{uuid4().hex[:8]}"

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run:

```bash
uv run pytest tests/test_run_store.py -q
```

Expected: `3 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/radar/storage/run_store.py tests/test_run_store.py
git commit -m "feat: add staged run artifact store"
```

---

## Task 4: Seed Config and `radar init`

**Files:**
- Create: `.env.example`
- Create: `config/seed-sources.yaml`
- Create: `config/scoring.yaml`
- Create: `config/category-quotas.yaml`
- Create: `src/radar/init_project.py`
- Modify: `src/radar/cli.py`
- Create: `tests/test_init_project.py`

- [ ] **Step 1: Write the failing init tests**

Create `tests/test_init_project.py`:

```python
from pathlib import Path

from radar.init_project import initialize_project


def test_initialize_project_writes_config_and_env(tmp_path: Path):
    result = initialize_project(tmp_path)

    assert result.config_path == tmp_path / "data" / "config.yaml"
    assert result.config_path.exists()
    assert (tmp_path / ".env.example").exists()
    assert (tmp_path / "data" / "runs").is_dir()

    config_text = result.config_path.read_text(encoding="utf-8")
    assert "github-openclaw" in config_text
    assert "github-nvidia-nemoclaw" in config_text
    assert "github-cline" in config_text


def test_initialize_project_does_not_overwrite_existing_config(tmp_path: Path):
    config_path = tmp_path / "data" / "config.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text("version: custom\n", encoding="utf-8")

    initialize_project(tmp_path)

    assert config_path.read_text(encoding="utf-8") == "version: custom\n"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
uv run pytest tests/test_init_project.py -q
```

Expected: failure because `radar.init_project` does not exist.

- [ ] **Step 3: Add seed files**

Create `.env.example`:

```bash
# Optional: raises GitHub API rate limits from 60/hour to 5000/hour.
GITHUB_TOKEN=

# Optional: reserved for future LLM-assisted analysis.
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
```

Create `config/category-quotas.yaml`:

```yaml
coding_agents: 4
general_agents: 3
mcp_tooling: 4
sandbox_governance: 4
agent_frameworks: 3
```

Create `config/scoring.yaml`:

```yaml
default_ring: watch
security_penalty_tags:
  - terminal-access
  - file-write-access
  - persistent-agent
  - browser-access
```

Create `config/seed-sources.yaml`:

```yaml
version: "1.0"
sources:
  - id: github-openclaw
    type: github_repo
    enabled: true
    project: OpenClaw
    category: general_agents
    url: https://github.com/openclaw/openclaw
    tags: [general-agent, open-source, persistent-agent, workflow-automation, file-write-access]
  - id: github-nvidia-nemoclaw
    type: github_repo
    enabled: true
    project: NVIDIA NemoClaw
    category: sandbox_governance
    url: https://github.com/NVIDIA/NemoClaw
    tags: [sandbox, governance, open-source, on-prem-relevant]
  - id: github-hermes-agent
    type: github_repo
    enabled: true
    project: Hermes Agent
    category: general_agents
    url: https://github.com/NousResearch/hermes-agent
    tags: [general-agent, persistent-agent, memory, open-source]
  - id: github-cline
    type: github_repo
    enabled: true
    project: Cline
    category: coding_agents
    url: https://github.com/cline/cline
    tags: [coding-agent, mcp, file-write-access, terminal-access]
  - id: github-openhands
    type: github_repo
    enabled: true
    project: OpenHands
    category: coding_agents
    url: https://github.com/OpenHands/OpenHands
    tags: [coding-agent, software-agent-sdk, open-source]
  - id: github-aider
    type: github_repo
    enabled: true
    project: Aider
    category: coding_agents
    url: https://github.com/Aider-AI/aider
    tags: [coding-agent, terminal, open-source]
  - id: github-goose
    type: github_repo
    enabled: true
    project: Goose
    category: general_agents
    url: https://github.com/aaif-goose/goose
    tags: [general-agent, mcp, desktop, cli]
  - id: github-langgraph
    type: github_repo
    enabled: true
    project: LangGraph
    category: agent_frameworks
    url: https://github.com/langchain-ai/langgraph
    tags: [agent-framework, orchestration, open-source]
  - id: github-autogen
    type: github_repo
    enabled: true
    project: AutoGen
    category: agent_frameworks
    url: https://github.com/microsoft/autogen
    tags: [agent-framework, multi-agent, open-source]
  - id: mcp-docs
    type: manual
    enabled: true
    project: Model Context Protocol
    category: mcp_tooling
    url: https://modelcontextprotocol.io/docs/getting-started/intro
    tags: [mcp, protocol, tooling]
quotas:
  coding_agents: 4
  general_agents: 3
  mcp_tooling: 4
  sandbox_governance: 4
  agent_frameworks: 3
scoring:
  default_ring: watch
  security_penalty_tags:
    - terminal-access
    - file-write-access
    - persistent-agent
    - browser-access
```

- [ ] **Step 4: Implement `initialize_project` and CLI command**

Create `src/radar/init_project.py`:

```python
"""Project initialization helpers."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class InitResult:
    """Paths created or reused by init."""

    config_path: Path
    env_example_path: Path
    runs_path: Path


def initialize_project(root: Path) -> InitResult:
    """Create local config and data directories without overwriting config."""
    root = root.resolve()
    data_dir = root / "data"
    runs_dir = data_dir / "runs"
    config_path = data_dir / "config.yaml"
    env_example_path = root / ".env.example"

    data_dir.mkdir(parents=True, exist_ok=True)
    runs_dir.mkdir(parents=True, exist_ok=True)

    package_root = Path(__file__).resolve().parents[2]
    seed_config = package_root / "config" / "seed-sources.yaml"
    env_example = package_root / ".env.example"

    if not config_path.exists():
        shutil.copy2(seed_config, config_path)
    if not env_example_path.exists():
        shutil.copy2(env_example, env_example_path)

    return InitResult(
        config_path=config_path,
        env_example_path=env_example_path,
        runs_path=runs_dir,
    )
```

Modify `src/radar/cli.py` to add the command:

```python
from pathlib import Path

from radar.init_project import initialize_project
```

Add below `version()`:

```python
@app.command()
def init(root: Path = typer.Option(Path("."), help="Project root to initialize.")) -> None:
    """Create starter config and data directories."""
    result = initialize_project(root)
    console.print(f"Config: {result.config_path}")
    console.print(f"Env example: {result.env_example_path}")
    console.print(f"Runs: {result.runs_path}")
```

- [ ] **Step 5: Run the tests to verify they pass**

Run:

```bash
uv run pytest tests/test_init_project.py tests/test_cli.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add .env.example config src/radar/init_project.py src/radar/cli.py tests/test_init_project.py tests/test_cli.py
git commit -m "feat: add starter config initialization"
```

---

## Task 5: Collector Interface and Manual Collector

**Files:**
- Create: `src/radar/collectors/__init__.py`
- Create: `src/radar/collectors/base.py`
- Create: `src/radar/collectors/manual.py`
- Create: `tests/test_collectors_manual.py`

- [ ] **Step 1: Write the failing manual collector test**

Create `tests/test_collectors_manual.py`:

```python
from datetime import datetime, timezone

import pytest

from radar.collectors.manual import ManualCollector
from radar.models import Category, SourceConfig, SourceType


@pytest.mark.asyncio
async def test_manual_collector_emits_one_signal():
    source = SourceConfig(
        id="mcp-docs",
        type=SourceType.MANUAL,
        enabled=True,
        project="Model Context Protocol",
        category=Category.MCP_TOOLING,
        url="https://modelcontextprotocol.io/docs/getting-started/intro",
        tags=["mcp", "protocol"],
    )
    collector = ManualCollector([source])

    signals = await collector.fetch(datetime(2026, 6, 10, tzinfo=timezone.utc))

    assert len(signals) == 1
    assert signals[0].id == "manual:mcp-docs"
    assert signals[0].project == "Model Context Protocol"
    assert signals[0].signal_type == "manual_reference"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
uv run pytest tests/test_collectors_manual.py -q
```

Expected: failure because `radar.collectors.manual` does not exist.

- [ ] **Step 3: Implement the collector interface and manual collector**

Create `src/radar/collectors/__init__.py`:

```python
"""Signal collectors."""
```

Create `src/radar/collectors/base.py`:

```python
"""Base collector interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from radar.models import Signal


class BaseCollector(ABC):
    """Fetch signals published after a point in time."""

    @abstractmethod
    async def fetch(self, since: datetime) -> list[Signal]:
        """Return normalized signals."""
```

Create `src/radar/collectors/manual.py`:

```python
"""Collector for manually configured references."""

from __future__ import annotations

from datetime import datetime, timezone

from radar.collectors.base import BaseCollector
from radar.models import Signal, SourceConfig


class ManualCollector(BaseCollector):
    """Emit one stable signal per manual source."""

    def __init__(self, sources: list[SourceConfig]):
        self.sources = sources

    async def fetch(self, since: datetime) -> list[Signal]:
        """Return configured manual references."""
        now = datetime.now(timezone.utc)
        return [
            Signal(
                id=f"manual:{source.id}",
                source_id=source.id,
                project=source.project,
                category=source.category,
                title=f"{source.project} reference",
                url=source.url,
                published_at=now,
                raw_summary=f"Manual reference for {source.project}",
                signal_type="manual_reference",
                tags=source.tags,
            )
            for source in self.sources
            if source.enabled
        ]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run:

```bash
uv run pytest tests/test_collectors_manual.py -q
```

Expected: `1 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/radar/collectors tests/test_collectors_manual.py
git commit -m "feat: add collector interface and manual collector"
```

---

## Task 6: GitHub Collector

**Files:**
- Create: `src/radar/collectors/github.py`
- Create: `tests/fixtures/github_releases.json`
- Create: `tests/test_collectors_github.py`

- [ ] **Step 1: Add GitHub fixture and failing tests**

Create `tests/fixtures/github_releases.json`:

```json
[
  {
    "id": 101,
    "tag_name": "v1.2.3",
    "html_url": "https://github.com/openclaw/openclaw/releases/tag/v1.2.3",
    "body": "CLI onboarding and plugin list improvements.",
    "published_at": "2026-06-10T08:00:00Z",
    "prerelease": false,
    "author": {"login": "maintainer"}
  }
]
```

Create `tests/test_collectors_github.py`:

```python
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from radar.collectors.github import GitHubCollector
from radar.models import Category, SourceConfig, SourceType


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeClient:
    def __init__(self, payload):
        self.payload = payload
        self.urls = []

    async def get(self, url, headers=None, follow_redirects=True):
        self.urls.append(url)
        return FakeResponse(self.payload)


@pytest.mark.asyncio
async def test_github_collector_fetches_repo_releases():
    payload = json.loads(Path("tests/fixtures/github_releases.json").read_text())
    source = SourceConfig(
        id="github-openclaw",
        type=SourceType.GITHUB_REPO,
        enabled=True,
        project="OpenClaw",
        category=Category.GENERAL_AGENTS,
        url="https://github.com/openclaw/openclaw",
        tags=["general-agent"],
    )
    client = FakeClient(payload)
    collector = GitHubCollector([source], client=client)

    signals = await collector.fetch(datetime(2026, 6, 9, tzinfo=timezone.utc))

    assert len(signals) == 1
    assert signals[0].id == "github:github-openclaw:release:101"
    assert signals[0].project == "OpenClaw"
    assert signals[0].title == "OpenClaw released v1.2.3"
    assert signals[0].metadata["tag"] == "v1.2.3"
    assert client.urls == ["https://api.github.com/repos/openclaw/openclaw/releases?per_page=10"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
uv run pytest tests/test_collectors_github.py -q
```

Expected: failure because `radar.collectors.github` does not exist.

- [ ] **Step 3: Implement GitHub collector**

Create `src/radar/collectors/github.py`:

```python
"""GitHub repository release collector."""

from __future__ import annotations

import logging
import os
from datetime import datetime
from urllib.parse import urlparse

import httpx

from radar.collectors.base import BaseCollector
from radar.models import Signal, SourceConfig


logger = logging.getLogger(__name__)


class GitHubCollector(BaseCollector):
    """Collect release signals from configured GitHub repositories."""

    def __init__(self, sources: list[SourceConfig], client: httpx.AsyncClient):
        self.sources = sources
        self.client = client
        self.base_url = "https://api.github.com"

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "onprem-ai-adoption-radar",
        }
        token = os.getenv("GITHUB_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    async def fetch(self, since: datetime) -> list[Signal]:
        """Fetch releases for all enabled GitHub repo sources."""
        signals: list[Signal] = []
        for source in self.sources:
            if not source.enabled:
                continue
            owner_repo = self._owner_repo(str(source.url))
            if owner_repo is None:
                logger.warning("Skipping invalid GitHub URL for source %s", source.id)
                continue
            owner, repo = owner_repo
            signals.extend(await self._fetch_releases(source, owner, repo, since))
        return signals

    async def _fetch_releases(
        self,
        source: SourceConfig,
        owner: str,
        repo: str,
        since: datetime,
    ) -> list[Signal]:
        url = f"{self.base_url}/repos/{owner}/{repo}/releases?per_page=10"
        try:
            response = await self.client.get(
                url,
                headers=self._headers(),
                follow_redirects=True,
            )
            response.raise_for_status()
            releases = response.json()
        except httpx.HTTPError as exc:
            logger.warning("GitHub source %s failed: %s", source.id, exc)
            return []

        signals: list[Signal] = []
        for release in releases:
            published_at = datetime.fromisoformat(
                release["published_at"].replace("Z", "+00:00")
            )
            if published_at < since:
                continue
            tag = release["tag_name"]
            signals.append(
                Signal(
                    id=f"github:{source.id}:release:{release['id']}",
                    source_id=source.id,
                    project=source.project,
                    category=source.category,
                    title=f"{source.project} released {tag}",
                    url=release["html_url"],
                    published_at=published_at,
                    raw_summary=release.get("body") or "",
                    signal_type="github_release",
                    tags=source.tags,
                    metadata={
                        "repo": f"{owner}/{repo}",
                        "tag": tag,
                        "prerelease": release.get("prerelease", False),
                        "author": release.get("author", {}).get("login", ""),
                    },
                )
            )
        return signals

    @staticmethod
    def _owner_repo(url: str) -> tuple[str, str] | None:
        parsed = urlparse(url)
        parts = [part for part in parsed.path.split("/") if part]
        if parsed.netloc != "github.com" or len(parts) < 2:
            return None
        return parts[0], parts[1]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run:

```bash
uv run pytest tests/test_collectors_github.py -q
```

Expected: `1 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/radar/collectors/github.py tests/fixtures/github_releases.json tests/test_collectors_github.py
git commit -m "feat: add github release collector"
```

---

## Task 7: RSS Collector and Collector Registry

**Files:**
- Create: `src/radar/collectors/rss.py`
- Create: `src/radar/collectors/registry.py`
- Create: `tests/fixtures/rss_feed.xml`
- Create: `tests/test_collectors_rss.py`

- [ ] **Step 1: Add RSS fixture and failing tests**

Create `tests/fixtures/rss_feed.xml`:

```xml
<?xml version="1.0" encoding="UTF-8" ?>
<rss version="2.0">
  <channel>
    <title>Agent Tooling Blog</title>
    <item>
      <title>MCP server approval patterns</title>
      <link>https://example.com/mcp-approval</link>
      <description>New guidance for human approval flows in tool-using agents.</description>
      <pubDate>Wed, 10 Jun 2026 10:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
```

Create `tests/test_collectors_rss.py`:

```python
from datetime import datetime, timezone
from pathlib import Path

import pytest

from radar.collectors.registry import build_collectors
from radar.collectors.rss import RSSCollector
from radar.models import Category, Config, SourceConfig, SourceType


class FakeResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        return None


class FakeClient:
    def __init__(self, text):
        self.text = text

    async def get(self, url, follow_redirects=True):
        return FakeResponse(self.text)


@pytest.mark.asyncio
async def test_rss_collector_fetches_feed_items():
    source = SourceConfig(
        id="rss-agent-blog",
        type=SourceType.RSS,
        enabled=True,
        project="Agent Blog",
        category=Category.MCP_TOOLING,
        url="https://example.com/feed.xml",
        tags=["mcp"],
    )
    feed = Path("tests/fixtures/rss_feed.xml").read_text(encoding="utf-8")
    collector = RSSCollector([source], client=FakeClient(feed))

    signals = await collector.fetch(datetime(2026, 6, 9, tzinfo=timezone.utc))

    assert len(signals) == 1
    assert signals[0].id == "rss:rss-agent-blog:https://example.com/mcp-approval"
    assert signals[0].title == "MCP server approval patterns"


def test_registry_builds_enabled_collectors():
    config = Config(
        sources=[
            SourceConfig(
                id="rss-agent-blog",
                type=SourceType.RSS,
                enabled=True,
                project="Agent Blog",
                category=Category.MCP_TOOLING,
                url="https://example.com/feed.xml",
            )
        ]
    )

    collectors = build_collectors(config, client=object())

    assert len(collectors) == 1
    assert collectors[0].__class__.__name__ == "RSSCollector"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
uv run pytest tests/test_collectors_rss.py -q
```

Expected: failure because `radar.collectors.rss` and `registry` do not exist.

- [ ] **Step 3: Implement RSS collector and registry**

Create `src/radar/collectors/rss.py`:

```python
"""RSS and Atom feed collector."""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone

import feedparser
import httpx
from dateutil import parser as date_parser

from radar.collectors.base import BaseCollector
from radar.models import Signal, SourceConfig


logger = logging.getLogger(__name__)


class RSSCollector(BaseCollector):
    """Collect signals from RSS or Atom feeds."""

    def __init__(self, sources: list[SourceConfig], client: httpx.AsyncClient):
        self.sources = sources
        self.client = client

    async def fetch(self, since: datetime) -> list[Signal]:
        signals: list[Signal] = []
        for source in self.sources:
            if not source.enabled:
                continue
            signals.extend(await self._fetch_source(source, since))
        return signals

    async def _fetch_source(self, source: SourceConfig, since: datetime) -> list[Signal]:
        try:
            response = await self.client.get(str(source.url), follow_redirects=True)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("RSS source %s failed: %s", source.id, exc)
            return []

        feed = feedparser.parse(response.text)
        signals: list[Signal] = []
        for entry in feed.entries:
            published_at = self._published_at(entry)
            if published_at < since:
                continue
            link = entry.get("link") or str(source.url)
            title = entry.get("title") or source.project
            summary = entry.get("summary") or entry.get("description") or ""
            signals.append(
                Signal(
                    id=f"rss:{source.id}:{self._stable_key(link)}",
                    source_id=source.id,
                    project=source.project,
                    category=source.category,
                    title=title,
                    url=link,
                    published_at=published_at,
                    raw_summary=summary,
                    signal_type="rss_entry",
                    tags=source.tags,
                    metadata={"feed": source.id},
                )
            )
        return signals

    @staticmethod
    def _stable_key(value: str) -> str:
        if value.startswith("http"):
            return value
        return hashlib.sha1(value.encode("utf-8")).hexdigest()

    @staticmethod
    def _published_at(entry) -> datetime:
        raw = entry.get("published") or entry.get("updated") or entry.get("created")
        if raw:
            parsed = date_parser.parse(raw)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed
        return datetime.now(timezone.utc)
```

Create `src/radar/collectors/registry.py`:

```python
"""Collector construction from config."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from radar.collectors.base import BaseCollector
from radar.collectors.github import GitHubCollector
from radar.collectors.manual import ManualCollector
from radar.collectors.rss import RSSCollector
from radar.models import Config, SourceConfig, SourceType


def build_collectors(config: Config, client: Any) -> list[BaseCollector]:
    """Build one collector per enabled source type."""
    grouped: dict[SourceType, list[SourceConfig]] = defaultdict(list)
    for source in config.sources:
        if source.enabled:
            grouped[source.type].append(source)

    collectors: list[BaseCollector] = []
    if grouped[SourceType.GITHUB_REPO]:
        collectors.append(GitHubCollector(grouped[SourceType.GITHUB_REPO], client))
    if grouped[SourceType.RSS]:
        collectors.append(RSSCollector(grouped[SourceType.RSS], client))
    if grouped[SourceType.MANUAL]:
        collectors.append(ManualCollector(grouped[SourceType.MANUAL]))
    return collectors
```

- [ ] **Step 4: Run the tests to verify they pass**

Run:

```bash
uv run pytest tests/test_collectors_rss.py tests/test_collectors_github.py tests/test_collectors_manual.py -q
```

Expected: collector tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/radar/collectors/rss.py src/radar/collectors/registry.py tests/fixtures/rss_feed.xml tests/test_collectors_rss.py
git commit -m "feat: add rss collector and registry"
```

---

## Task 8: Deduplication, Scoring, and Rings

**Files:**
- Create: `src/radar/pipeline/__init__.py`
- Create: `src/radar/pipeline/dedupe.py`
- Create: `src/radar/scoring/__init__.py`
- Create: `src/radar/scoring/rings.py`
- Create: `src/radar/scoring/deterministic.py`
- Create: `tests/test_dedupe.py`
- Create: `tests/test_scoring.py`

- [ ] **Step 1: Write failing pure-function tests**

Create `tests/test_dedupe.py`:

```python
from datetime import datetime, timezone

from radar.models import Category, Signal
from radar.pipeline.dedupe import dedupe_signals


def make_signal(signal_id: str, url: str, summary: str) -> Signal:
    return Signal(
        id=signal_id,
        source_id="source",
        project="Cline",
        category=Category.CODING_AGENTS,
        title="Release",
        url=url,
        published_at=datetime(2026, 6, 10, tzinfo=timezone.utc),
        raw_summary=summary,
        signal_type="github_release",
    )


def test_dedupe_keeps_richer_signal_for_same_url():
    short = make_signal("short", "https://example.com/a", "short")
    rich = make_signal("rich", "https://example.com/a/", "longer summary")

    result = dedupe_signals([short, rich])

    assert [signal.id for signal in result] == ["rich"]
```

Create `tests/test_scoring.py`:

```python
from datetime import datetime, timezone

from radar.models import Category, Ring, ScoringConfig, Signal
from radar.scoring.deterministic import score_signal
from radar.scoring.rings import ring_from_score


def test_ring_from_score_accounts_for_security_posture():
    assert ring_from_score(4.5, security_posture=4) == Ring.ADOPT
    assert ring_from_score(4.2, security_posture=2) == Ring.PILOT
    assert ring_from_score(2.0, security_posture=1) == Ring.AVOID


def test_score_signal_marks_file_write_access_as_risk():
    signal = Signal(
        id="s1",
        source_id="github-cline",
        project="Cline",
        category=Category.CODING_AGENTS,
        title="Cline released v1",
        url="https://github.com/cline/cline/releases/tag/v1",
        published_at=datetime(2026, 6, 10, tzinfo=timezone.utc),
        raw_summary="MCP approval improvements",
        signal_type="github_release",
        tags=["coding-agent", "file-write-access", "terminal-access", "mcp"],
    )

    scored = score_signal(signal, ScoringConfig())

    assert scored.scores.workflow_impact >= 4
    assert scored.scores.security_posture == 2
    assert "needs_sandbox_review" in scored.reason_codes
    assert scored.recommended_ring == Ring.PILOT
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/test_dedupe.py tests/test_scoring.py -q
```

Expected: failure because pipeline/scoring modules do not exist.

- [ ] **Step 3: Implement dedupe and deterministic scoring**

Create `src/radar/pipeline/__init__.py`:

```python
"""Pure pipeline transformations."""
```

Create `src/radar/pipeline/dedupe.py`:

```python
"""Signal deduplication."""

from __future__ import annotations

from urllib.parse import urlparse

from radar.models import Signal


def dedupe_signals(signals: list[Signal]) -> list[Signal]:
    """Deduplicate signals by normalized URL, keeping the richest summary."""
    groups: dict[str, Signal] = {}
    for signal in signals:
        key = _normalize_url(str(signal.url))
        current = groups.get(key)
        if current is None or len(signal.raw_summary) > len(current.raw_summary):
            groups[key] = signal
    return list(groups.values())


def _normalize_url(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if host.startswith("www."):
        host = host[4:]
    path = parsed.path.rstrip("/")
    return f"{host}{path}"
```

Create `src/radar/scoring/__init__.py`:

```python
"""Deterministic scoring helpers."""
```

Create `src/radar/scoring/rings.py`:

```python
"""Ring assignment rules."""

from __future__ import annotations

from radar.models import Ring


def ring_from_score(average: float, security_posture: int) -> Ring:
    """Map an average score and security posture to a radar ring."""
    if average < 2.5 or security_posture <= 1:
        return Ring.AVOID
    if average >= 4.3 and security_posture >= 3:
        return Ring.ADOPT
    if average >= 3.4:
        return Ring.PILOT
    return Ring.WATCH
```

Create `src/radar/scoring/deterministic.py`:

```python
"""Deterministic signal scoring."""

from __future__ import annotations

from radar.models import Category, ScoredSignal, ScoreBreakdown, ScoringConfig, Signal
from radar.scoring.rings import ring_from_score


def score_signal(signal: Signal, config: ScoringConfig) -> ScoredSignal:
    """Score a signal using explainable rules."""
    tags = set(signal.tags)
    reason_codes: list[str] = []

    workflow_impact = 4 if signal.category in {Category.CODING_AGENTS, Category.GENERAL_AGENTS} else 3
    if "mcp" in tags:
        workflow_impact += 1
        reason_codes.append("mcp_relevant")

    laptop_runnability = 5 if not {"kubernetes", "gpu-required"} & tags else 2
    open_source_maturity = 4 if "open-source" in tags else 3
    on_prem_relevance = 4 if {"on-prem-relevant", "sandbox", "mcp"} & tags else 3
    demo_value = 4 if signal.category != Category.AGENT_FRAMEWORKS else 3
    setup_friction = 4 if "kubernetes" not in tags else 2

    risky_tags = set(config.security_penalty_tags) & tags
    if risky_tags:
        security_posture = 2
        reason_codes.append("needs_sandbox_review")
    else:
        security_posture = 4

    scores = ScoreBreakdown(
        workflow_impact=min(workflow_impact, 5),
        laptop_runnability=laptop_runnability,
        open_source_maturity=open_source_maturity,
        on_prem_relevance=on_prem_relevance,
        security_posture=security_posture,
        demo_value=demo_value,
        setup_friction=setup_friction,
    )
    ring = ring_from_score(scores.average, scores.security_posture)
    return ScoredSignal(
        signal=signal,
        scores=scores,
        reason_codes=reason_codes,
        recommended_ring=ring,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
uv run pytest tests/test_dedupe.py tests/test_scoring.py -q
```

Expected: `3 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/radar/pipeline src/radar/scoring tests/test_dedupe.py tests/test_scoring.py
git commit -m "feat: add deterministic dedupe and scoring"
```

---

## Task 9: Decision Cards, Quotas, and SQLite Persistence

**Files:**
- Create: `src/radar/pipeline/cards.py`
- Create: `src/radar/pipeline/quotas.py`
- Create: `src/radar/storage/database.py`
- Create: `tests/test_cards.py`
- Create: `tests/test_quotas.py`
- Create: `tests/test_database.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_cards.py`:

```python
from datetime import datetime, timezone

from radar.models import Category, Ring, ScoredSignal, ScoreBreakdown, Signal
from radar.pipeline.cards import build_decision_cards


def test_build_decision_cards_groups_by_project():
    signal = Signal(
        id="s1",
        source_id="github-cline",
        project="Cline",
        category=Category.CODING_AGENTS,
        title="Cline released v1",
        url="https://github.com/cline/cline/releases/tag/v1",
        published_at=datetime(2026, 6, 10, tzinfo=timezone.utc),
        raw_summary="MCP approval improvements",
        signal_type="github_release",
        tags=["file-write-access"],
    )
    scored = ScoredSignal(
        signal=signal,
        scores=ScoreBreakdown(
            workflow_impact=5,
            laptop_runnability=5,
            open_source_maturity=4,
            on_prem_relevance=3,
            security_posture=2,
            demo_value=4,
            setup_friction=4,
        ),
        reason_codes=["needs_sandbox_review"],
        recommended_ring=Ring.PILOT,
    )

    cards = build_decision_cards([scored])

    assert len(cards) == 1
    assert cards[0].project == "Cline"
    assert cards[0].ring == Ring.PILOT
    assert cards[0].risk_level == "high"
    assert "https://github.com/cline/cline/releases/tag/v1" in cards[0].evidence
```

Create `tests/test_quotas.py`:

```python
from radar.models import Category, DecisionCard, Ring
from radar.pipeline.quotas import apply_category_quotas


def card(project: str, category: Category) -> DecisionCard:
    return DecisionCard(
        project=project,
        category=category,
        ring=Ring.PILOT,
        summary=project,
        workflow_fit={"personal_dev": "high"},
        risk_level="medium",
    )


def test_apply_category_quotas_limits_each_category():
    cards = [
        card("A", Category.CODING_AGENTS),
        card("B", Category.CODING_AGENTS),
        card("C", Category.MCP_TOOLING),
    ]

    selected = apply_category_quotas(cards, {Category.CODING_AGENTS: 1})

    assert [item.project for item in selected] == ["A", "C"]
```

Create `tests/test_database.py`:

```python
from pathlib import Path

from radar.models import Category, DecisionCard, Ring
from radar.storage.database import RadarDatabase


def test_database_persists_decision_cards(tmp_path: Path):
    db = RadarDatabase(tmp_path / "radar.db")
    db.initialize()
    card = DecisionCard(
        project="Cline",
        category=Category.CODING_AGENTS,
        ring=Ring.PILOT,
        summary="Coding agent",
        workflow_fit={"personal_dev": "high"},
        risk_level="medium",
        evidence=["https://example.com"],
    )

    db.upsert_cards([card])

    cards = db.list_cards()
    assert len(cards) == 1
    assert cards[0].project == "Cline"
    assert cards[0].ring == Ring.PILOT
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/test_cards.py tests/test_quotas.py tests/test_database.py -q
```

Expected: failure because card, quota, and database modules do not exist.

- [ ] **Step 3: Implement cards, quotas, and database**

Create `src/radar/pipeline/cards.py`:

```python
"""Decision card generation."""

from __future__ import annotations

from collections import defaultdict

from radar.models import DecisionCard, Ring, ScoredSignal


def build_decision_cards(scored_signals: list[ScoredSignal]) -> list[DecisionCard]:
    """Build one decision card per project."""
    grouped: dict[str, list[ScoredSignal]] = defaultdict(list)
    for scored in scored_signals:
        grouped[scored.signal.project].append(scored)

    cards: list[DecisionCard] = []
    for project, items in grouped.items():
        best = sorted(items, key=lambda item: item.scores.average, reverse=True)[0]
        risk_level = _risk_level(best)
        risk_reasons = _risk_reasons(best)
        cards.append(
            DecisionCard(
                project=project,
                category=best.signal.category,
                ring=best.recommended_ring,
                summary=best.signal.raw_summary or best.signal.title,
                workflow_fit={
                    "personal_dev": "high" if best.scores.workflow_impact >= 4 else "medium",
                    "company_demo": "high" if best.scores.demo_value >= 4 else "medium",
                    "enterprise_onprem": "high" if best.scores.on_prem_relevance >= 4 else "medium",
                },
                risk_level=risk_level,
                risk_reasons=risk_reasons,
                try_this_week=_try_steps(best),
                company_demo={
                    "suitable": best.recommended_ring in {Ring.ADOPT, Ring.PILOT},
                    "angle": f"{project} adoption review with workflow and safety notes",
                },
                evidence=sorted({str(item.signal.url) for item in items}),
                tags=sorted({tag for item in items for tag in item.signal.tags}),
            )
        )
    return sorted(cards, key=lambda card: (card.category.value, card.project.lower()))


def _risk_level(scored: ScoredSignal) -> str:
    if scored.scores.security_posture <= 2:
        return "high"
    if scored.scores.security_posture == 3:
        return "medium"
    return "low"


def _risk_reasons(scored: ScoredSignal) -> list[str]:
    if "needs_sandbox_review" in scored.reason_codes:
        return ["Requires sandbox or approval review before serious use."]
    return ["No major local execution risk detected from configured tags."]


def _try_steps(scored: ScoredSignal) -> list[str]:
    if scored.recommended_ring == Ring.AVOID:
        return []
    return [
        "Read official docs and release notes.",
        "Try on a disposable repository or low-risk workflow.",
        "Record setup friction, permissions needed, and workflow value.",
    ]
```

Create `src/radar/pipeline/quotas.py`:

```python
"""Balanced report selection."""

from __future__ import annotations

from collections import defaultdict

from radar.models import Category, DecisionCard


def apply_category_quotas(
    cards: list[DecisionCard],
    quotas: dict[Category, int],
) -> list[DecisionCard]:
    """Limit cards per category while preserving input order."""
    counts: dict[Category, int] = defaultdict(int)
    selected: list[DecisionCard] = []
    for card in cards:
        limit = quotas.get(card.category)
        if limit is not None and counts[card.category] >= limit:
            continue
        selected.append(card)
        counts[card.category] += 1
    return selected
```

Create `src/radar/storage/database.py`:

```python
"""SQLite persistence for decision cards."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from radar.models import DecisionCard


class RadarDatabase:
    """Small SQLite wrapper for local persistence."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def initialize(self) -> None:
        """Create tables."""
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS decision_cards (
                    project TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    ring TEXT NOT NULL,
                    category TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def upsert_cards(self, cards: list[DecisionCard]) -> None:
        """Insert or update cards by project."""
        with sqlite3.connect(self.path) as conn:
            for card in cards:
                conn.execute(
                    """
                    INSERT INTO decision_cards(project, payload, ring, category, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(project) DO UPDATE SET
                        payload=excluded.payload,
                        ring=excluded.ring,
                        category=excluded.category,
                        updated_at=excluded.updated_at
                    """,
                    (
                        card.project,
                        card.model_dump_json(),
                        card.ring.value,
                        card.category.value,
                        card.last_reviewed_at.isoformat(),
                    ),
                )

    def list_cards(self) -> list[DecisionCard]:
        """Return all cards ordered by category and project."""
        with sqlite3.connect(self.path) as conn:
            rows = conn.execute(
                "SELECT payload FROM decision_cards ORDER BY category, project"
            ).fetchall()
        return [DecisionCard.model_validate_json(row[0]) for row in rows]
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
uv run pytest tests/test_cards.py tests/test_quotas.py tests/test_database.py -q
```

Expected: `3 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/radar/pipeline/cards.py src/radar/pipeline/quotas.py src/radar/storage/database.py tests/test_cards.py tests/test_quotas.py tests/test_database.py
git commit -m "feat: add decision cards and persistence"
```

---

## Task 10: Markdown and JSON Reports

**Files:**
- Create: `src/radar/reports/__init__.py`
- Create: `src/radar/reports/markdown.py`
- Create: `src/radar/reports/json_export.py`
- Create: `tests/test_reports.py`

- [ ] **Step 1: Write failing report tests**

Create `tests/test_reports.py`:

```python
import json

from radar.models import Category, DecisionCard, Ring
from radar.reports.json_export import cards_to_json
from radar.reports.markdown import render_markdown_report


def test_render_markdown_report_contains_sections():
    card = DecisionCard(
        project="Cline",
        category=Category.CODING_AGENTS,
        ring=Ring.PILOT,
        summary="Coding agent",
        workflow_fit={"personal_dev": "high"},
        risk_level="high",
        risk_reasons=["Needs sandbox review."],
        evidence=["https://example.com"],
    )

    markdown = render_markdown_report([card], title="Weekly Agent Radar")

    assert "# Weekly Agent Radar" in markdown
    assert "## Try This Week" in markdown
    assert "Cline" in markdown
    assert "Needs sandbox review." in markdown


def test_cards_to_json_returns_valid_json():
    card = DecisionCard(
        project="Cline",
        category=Category.CODING_AGENTS,
        ring=Ring.PILOT,
        summary="Coding agent",
        workflow_fit={"personal_dev": "high"},
        risk_level="medium",
    )

    payload = json.loads(cards_to_json([card]))

    assert payload[0]["project"] == "Cline"
    assert payload[0]["ring"] == "pilot"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/test_reports.py -q
```

Expected: failure because report modules do not exist.

- [ ] **Step 3: Implement reports**

Create `src/radar/reports/__init__.py`:

```python
"""Report renderers."""
```

Create `src/radar/reports/json_export.py`:

```python
"""JSON export renderer."""

from __future__ import annotations

import json

from radar.models import DecisionCard


def cards_to_json(cards: list[DecisionCard]) -> str:
    """Serialize cards to pretty JSON."""
    payload = [card.model_dump(mode="json") for card in cards]
    return json.dumps(payload, indent=2, ensure_ascii=False)
```

Create `src/radar/reports/markdown.py`:

```python
"""Markdown report renderer."""

from __future__ import annotations

from collections import defaultdict

from radar.models import DecisionCard, Ring


def render_markdown_report(cards: list[DecisionCard], title: str) -> str:
    """Render decision cards as a decision-oriented Markdown report."""
    lines = [f"# {title}", ""]
    lines.extend(_section("Try This Week", [c for c in cards if c.ring in {Ring.ADOPT, Ring.PILOT}]))
    lines.extend(_section("Watch", [c for c in cards if c.ring == Ring.WATCH]))
    lines.extend(_section("Avoid", [c for c in cards if c.ring == Ring.AVOID]))
    return "\n".join(lines).rstrip() + "\n"


def _section(title: str, cards: list[DecisionCard]) -> list[str]:
    lines = [f"## {title}", ""]
    if not cards:
        lines.extend(["No items in this section.", ""])
        return lines

    grouped: dict[str, list[DecisionCard]] = defaultdict(list)
    for card in cards:
        grouped[card.category.value].append(card)

    for category, category_cards in grouped.items():
        lines.extend([f"### {category}", ""])
        for card in category_cards:
            evidence = ", ".join(card.evidence) if card.evidence else "No evidence link recorded"
            risks = " ".join(card.risk_reasons) if card.risk_reasons else "No risk notes recorded."
            lines.extend(
                [
                    f"- **{card.project}** (`{card.ring.value}`, risk: `{card.risk_level}`)",
                    f"  - {card.summary}",
                    f"  - Risk: {risks}",
                    f"  - Evidence: {evidence}",
                ]
            )
        lines.append("")
    return lines
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
uv run pytest tests/test_reports.py -q
```

Expected: `2 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/radar/reports tests/test_reports.py
git commit -m "feat: add markdown and json reports"
```

---

## Task 11: Scan Orchestrator and `radar scan/report`

**Files:**
- Create: `src/radar/orchestrator.py`
- Modify: `src/radar/cli.py`
- Create: `tests/test_orchestrator.py`
- Update: `tests/test_cli.py`

- [ ] **Step 1: Write failing orchestrator tests**

Create `tests/test_orchestrator.py`:

```python
from pathlib import Path

from radar.init_project import initialize_project
from radar.orchestrator import RadarOrchestrator


def test_orchestrator_scan_with_manual_source_creates_artifacts(tmp_path: Path):
    initialize_project(tmp_path)
    config_path = tmp_path / "data" / "config.yaml"
    config_path.write_text(
        """
version: "1.0"
sources:
  - id: mcp-docs
    type: manual
    enabled: true
    project: Model Context Protocol
    category: mcp_tooling
    url: https://modelcontextprotocol.io/docs/getting-started/intro
    tags: [mcp, protocol]
quotas:
  mcp_tooling: 4
scoring:
  default_ring: watch
""",
        encoding="utf-8",
    )

    orchestrator = RadarOrchestrator(root=tmp_path)
    result = orchestrator.scan(days=2)

    assert result.run_id.startswith("run-")
    assert (tmp_path / "data" / "runs" / result.run_id / "raw_signals.json").exists()
    assert (tmp_path / "data" / "runs" / result.run_id / "decision_cards.json").exists()
    assert (tmp_path / "data" / "runs" / result.run_id / "report.md").exists()
    assert result.cards[0].project == "Model Context Protocol"
```

Append to `tests/test_cli.py`:

```python
def test_init_command_writes_config(tmp_path):
    runner = CliRunner()

    result = runner.invoke(app, ["init", "--root", str(tmp_path)])

    assert result.exit_code == 0
    assert (tmp_path / "data" / "config.yaml").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/test_orchestrator.py tests/test_cli.py -q
```

Expected: failure because orchestrator and CLI scan/report commands do not exist.

- [ ] **Step 3: Implement orchestrator**

Create `src/radar/orchestrator.py`:

```python
"""Pipeline orchestration."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from radar.collectors.registry import build_collectors
from radar.models import DecisionCard, ScoredSignal
from radar.pipeline.cards import build_decision_cards
from radar.pipeline.dedupe import dedupe_signals
from radar.pipeline.quotas import apply_category_quotas
from radar.reports.markdown import render_markdown_report
from radar.scoring.deterministic import score_signal
from radar.storage.config import load_config
from radar.storage.database import RadarDatabase
from radar.storage.run_store import RunStore


@dataclass(frozen=True)
class ScanResult:
    """Result returned by a scan."""

    run_id: str
    cards: list[DecisionCard]
    report_path: Path


class RadarOrchestrator:
    """Compose collectors, scoring, storage, and reports."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.data_dir = self.root / "data"
        self.config_path = self.data_dir / "config.yaml"
        self.run_store = RunStore(self.data_dir / "runs")
        self.database = RadarDatabase(self.data_dir / "radar.db")

    def scan(self, days: int) -> ScanResult:
        """Run the scan pipeline synchronously for CLI callers."""
        return asyncio.run(self._scan(days))

    async def _scan(self, days: int) -> ScanResult:
        config = load_config(self.config_path)
        self.database.initialize()
        run_id = self.run_store.create_run()
        since = datetime.now(timezone.utc) - timedelta(days=days)

        async with httpx.AsyncClient(timeout=30.0) as client:
            collectors = build_collectors(config, client)
            raw = []
            for collector in collectors:
                try:
                    raw.extend(await collector.fetch(since))
                except Exception as exc:
                    self.run_store.update_meta(run_id, {"collector_warning": str(exc)})

        self.run_store.save_stage(
            run_id,
            "raw_signals",
            [signal.model_dump(mode="json") for signal in raw],
        )
        deduped = dedupe_signals(raw)
        scored: list[ScoredSignal] = [
            score_signal(signal, config.scoring) for signal in deduped
        ]
        self.run_store.save_stage(
            run_id,
            "scored_signals",
            [item.model_dump(mode="json") for item in scored],
        )
        cards = build_decision_cards(scored)
        filtered_cards = apply_category_quotas(cards, config.quotas)
        self.run_store.save_stage(
            run_id,
            "filtered_signals",
            [item.model_dump(mode="json") for item in scored if item.signal.project in {card.project for card in filtered_cards}],
        )
        self.run_store.save_stage(
            run_id,
            "decision_cards",
            [card.model_dump(mode="json") for card in filtered_cards],
        )
        self.database.upsert_cards(filtered_cards)
        report = render_markdown_report(filtered_cards, "Agent/Tooling Adoption Radar")
        report_path = self.run_store.save_report(run_id, report)
        return ScanResult(run_id=run_id, cards=filtered_cards, report_path=report_path)

    def latest_cards(self) -> list[DecisionCard]:
        """Return cards from SQLite."""
        self.database.initialize()
        return self.database.list_cards()
```

- [ ] **Step 4: Add CLI commands**

Modify `src/radar/cli.py` imports:

```python
from radar.orchestrator import RadarOrchestrator
from radar.reports.markdown import render_markdown_report
```

Add commands:

```python
@app.command()
def scan(
    days: int = typer.Option(2, min=1, help="Look back this many days."),
    root: Path = typer.Option(Path("."), help="Project root."),
) -> None:
    """Collect signals, score them, and write run artifacts."""
    result = RadarOrchestrator(root).scan(days=days)
    console.print(f"Run: {result.run_id}")
    console.print(f"Cards: {len(result.cards)}")
    console.print(f"Report: {result.report_path}")


@app.command()
def report(root: Path = typer.Option(Path("."), help="Project root.")) -> None:
    """Print a report from persisted cards."""
    cards = RadarOrchestrator(root).latest_cards()
    console.print(render_markdown_report(cards, "Agent/Tooling Adoption Radar"))
```

- [ ] **Step 5: Run tests to verify they pass**

Run:

```bash
uv run pytest tests/test_orchestrator.py tests/test_cli.py -q
```

Expected: tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/radar/orchestrator.py src/radar/cli.py tests/test_orchestrator.py tests/test_cli.py
git commit -m "feat: add scan and report pipeline"
```

---

## Task 12: Local Dashboard

**Files:**
- Create: `src/radar/web/__init__.py`
- Create: `src/radar/web/app.py`
- Create: `src/radar/web/templates/index.html`
- Modify: `src/radar/cli.py`
- Create: `tests/test_web.py`

- [ ] **Step 1: Write failing dashboard tests**

Create `tests/test_web.py`:

```python
from pathlib import Path

from fastapi.testclient import TestClient

from radar.models import Category, DecisionCard, Ring
from radar.storage.database import RadarDatabase
from radar.web.app import create_app


def test_dashboard_lists_cards(tmp_path: Path):
    db_path = tmp_path / "data" / "radar.db"
    db = RadarDatabase(db_path)
    db.initialize()
    db.upsert_cards(
        [
            DecisionCard(
                project="Cline",
                category=Category.CODING_AGENTS,
                ring=Ring.PILOT,
                summary="Coding agent",
                workflow_fit={"personal_dev": "high"},
                risk_level="medium",
            )
        ]
    )

    client = TestClient(create_app(tmp_path))
    response = client.get("/")

    assert response.status_code == 200
    assert "Cline" in response.text
    assert "pilot" in response.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/test_web.py -q
```

Expected: failure because dashboard files do not exist.

- [ ] **Step 3: Implement FastAPI dashboard**

Create `src/radar/web/__init__.py`:

```python
"""Local dashboard."""
```

Create `src/radar/web/app.py`:

```python
"""FastAPI dashboard app."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from radar.storage.database import RadarDatabase


TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def create_app(root: Path) -> FastAPI:
    """Create a read-only local dashboard app."""
    app = FastAPI(title="Agent/Tooling Adoption Radar")
    db = RadarDatabase(root / "data" / "radar.db")

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        db.initialize()
        cards = db.list_cards()
        return TEMPLATES.TemplateResponse(
            request,
            "index.html",
            {"cards": cards},
        )

    return app
```

Create `src/radar/web/templates/index.html`:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Agent/Tooling Adoption Radar</title>
    <style>
      body { font-family: system-ui, sans-serif; margin: 2rem; color: #1f2937; }
      table { border-collapse: collapse; width: 100%; }
      th, td { border-bottom: 1px solid #e5e7eb; padding: 0.75rem; text-align: left; vertical-align: top; }
      th { background: #f9fafb; }
      .ring { font-family: ui-monospace, monospace; }
    </style>
  </head>
  <body>
    <h1>Agent/Tooling Adoption Radar</h1>
    <table>
      <thead>
        <tr>
          <th>Project</th>
          <th>Category</th>
          <th>Ring</th>
          <th>Risk</th>
          <th>Summary</th>
        </tr>
      </thead>
      <tbody>
        {% for card in cards %}
        <tr>
          <td>{{ card.project }}</td>
          <td>{{ card.category.value }}</td>
          <td class="ring">{{ card.ring.value }}</td>
          <td>{{ card.risk_level }}</td>
          <td>{{ card.summary }}</td>
        </tr>
        {% else %}
        <tr>
          <td colspan="5">No cards yet. Run radar scan first.</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </body>
</html>
```

- [ ] **Step 4: Add CLI serve command**

Modify `src/radar/cli.py` imports:

```python
import uvicorn

from radar.web.app import create_app
```

Add command:

```python
@app.command()
def serve(
    root: Path = typer.Option(Path("."), help="Project root."),
    host: str = typer.Option("127.0.0.1", help="Bind host."),
    port: int = typer.Option(8765, help="Bind port."),
) -> None:
    """Serve the local dashboard."""
    uvicorn.run(create_app(root), host=host, port=port)
```

- [ ] **Step 5: Run tests to verify they pass**

Run:

```bash
uv run pytest tests/test_web.py tests/test_cli.py -q
```

Expected: tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/radar/web src/radar/cli.py tests/test_web.py
git commit -m "feat: add local dashboard"
```

---

## Task 13: README and End-to-End Verification

**Files:**
- Create: `README.md`
- Create: `data/.gitkeep`

- [ ] **Step 1: Write README**

Create `README.md`:

````markdown
# On-Prem AI Adoption Radar

A laptop-runnable radar for deciding which AI agent and tooling technologies are worth trying, watching, demoing, or avoiding.

This is not a generic AI news digest. Tools like Horizon and agents-radar already do broad collection and summarization well. This project focuses on agent/tooling adoption judgment for on-prem and enterprise AI workflows.

## V1 Scope

- Coding agents
- General-purpose agents
- MCP and tool servers
- Sandbox and governance tools
- Agent frameworks

## Quick Start

```bash
uv sync --extra dev
uv run radar init
uv run radar scan --days 2
uv run radar report
uv run radar serve
```

The dashboard runs at `http://127.0.0.1:8765`.

## Safety

The radar observes public sources and generates decision cards. It does not install, execute, or operate third-party agents.

## Outputs

Each scan creates inspectable artifacts under:

```txt
data/runs/<run_id>/
  meta.json
  raw_signals.json
  scored_signals.json
  filtered_signals.json
  decision_cards.json
  report.md
```
````

Create `data/.gitkeep`:

```txt
```

- [ ] **Step 2: Run all tests**

Run:

```bash
uv run pytest -q
```

Expected: all tests pass.

- [ ] **Step 3: Run local smoke workflow**

Run:

```bash
rm -rf /tmp/radar-smoke
mkdir -p /tmp/radar-smoke
uv run radar init --root /tmp/radar-smoke
uv run radar scan --root /tmp/radar-smoke --days 2
uv run radar report --root /tmp/radar-smoke
```

Expected:

- `radar init` prints config and run paths.
- `radar scan` prints a run id, card count, and report path.
- `radar report` prints Markdown with `# Agent/Tooling Adoption Radar`.

- [ ] **Step 4: Commit**

```bash
git add README.md data/.gitkeep
git commit -m "docs: add quick start and safety notes"
```

---

## Self-Review Checklist

Spec coverage:

- Public and laptop-runnable: Tasks 1, 4, 11, 12, 13.
- `radar init`, `scan`, `report`, `serve`: Tasks 4, 11, 12.
- Seed watchlist with 10+ agent/tooling projects: Task 4.
- GitHub/RSS/manual public sources: Tasks 5, 6, 7.
- Deterministic scoring without LLM key: Task 8.
- Decision cards: Task 9.
- Balanced category quotas: Task 9.
- SQLite persistence: Task 9.
- Run artifacts: Task 3 and Task 11.
- Markdown and JSON export: Task 10.
- Local dashboard: Task 12.
- Safety: Tasks 10, 12, 13 avoid rendering trusted HTML and avoid third-party execution.

Type/name consistency:

- CLI command names: `init`, `scan`, `report`, `serve`, `version`.
- Stage names: `raw_signals`, `scored_signals`, `filtered_signals`, `decision_cards`.
- Main models: `SourceConfig`, `Signal`, `ScoredSignal`, `DecisionCard`, `Config`.
- Main orchestrator result: `ScanResult`.

Verification commands:

```bash
uv run pytest -q
rm -rf /tmp/radar-smoke
mkdir -p /tmp/radar-smoke
uv run radar init --root /tmp/radar-smoke
uv run radar scan --root /tmp/radar-smoke --days 2
uv run radar report --root /tmp/radar-smoke
```
