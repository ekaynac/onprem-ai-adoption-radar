"""Typed domain and configuration models."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


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
    MODEL_SERVING = "model_serving"
    AI_INFRASTRUCTURE = "ai_infrastructure"
    PHYSICAL_AI_INFRASTRUCTURE = "physical_ai_infrastructure"
    # Playful / creative local-AI projects (image gen, voice, LLM toys) —
    # tracked through the same pipeline but kept in their own lane.
    FUN_EXPERIMENTAL = "fun_experimental"


class Ring(str, Enum):
    """Radar rings."""

    ADOPT = "adopt"
    PILOT = "pilot"
    WATCH = "watch"
    AVOID = "avoid"


class SourceConfig(BaseModel):
    """A configured information source."""

    model_config = ConfigDict(extra="forbid")

    id: str
    type: SourceType
    enabled: bool = True
    project: str
    category: Category
    url: HttpUrl
    tags: list[str] = Field(default_factory=list)
    poll_interval_hours: int = Field(default=24, ge=1)
    # When true, this source is a high-volume "firehose" (e.g. a broad vendor
    # blog) whose entries are re-attributed to tracked projects by the
    # classification layer instead of collapsing into one project card.
    firehose: bool = False
    # Optional extra match strings (beyond the project name) the firehose
    # classifier uses to attribute entries to this project.
    aliases: list[str] = Field(default_factory=list)


class ScoringConfig(BaseModel):
    """Scoring configuration."""

    model_config = ConfigDict(extra="forbid")

    default_ring: Ring = Ring.WATCH
    security_penalty_tags: list[str] = Field(
        default_factory=lambda: [
            "terminal-access",
            "file-write-access",
            "persistent-agent",
            "browser-access",
        ]
    )


class LLMConfig(BaseModel):
    """Optional LLM analyst configuration (firehose tail only).

    Disabled by default — the whole pipeline runs offline and deterministic
    unless this is explicitly turned on. Defaults target a local, OpenAI-
    compatible endpoint (e.g. Ollama) to keep on-prem. The API key, if any, is
    read from the environment, never stored here.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    base_url: str = "http://localhost:11434/v1"
    model: str = "qwen2.5:3b"
    api_key_env: str = "RADAR_LLM_API_KEY"
    timeout_seconds: int = Field(default=20, ge=1)


class Config(BaseModel):
    """Application configuration."""

    model_config = ConfigDict(extra="forbid")

    version: str = "1.0"
    sources: list[SourceConfig] = Field(min_length=1)
    quotas: dict[Category, int] = Field(default_factory=dict)
    scoring: ScoringConfig = Field(default_factory=ScoringConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)


class Signal(BaseModel):
    """Raw normalized signal collected from a source."""

    id: str
    source_id: str
    project: str
    category: Category
    title: str
    url: HttpUrl
    published_at: datetime
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    raw_summary: str = ""
    signal_type: str
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Advisory(BaseModel):
    """A known security advisory affecting a project (e.g. from OSV.dev)."""

    id: str
    severity: str = "UNKNOWN"
    summary: str = ""


class ProjectEvidence(BaseModel):
    """Observed, per-project evidence assembled before scoring.

    Every field is optional: absent evidence means "no adjustment", so projects
    without metrics history score exactly as they did before this existed.
    Evidence is collected input — the scoring math over it stays deterministic.
    """

    model_config = ConfigDict(frozen=True)

    star_growth: int | None = None
    star_growth_pct: float | None = None
    releases_in_window: int = 0
    days_since_push: int | None = None
    advisories: list[Advisory] = Field(default_factory=list)
    hn_mentions: int | None = None
    downloads_weekly: int | None = None
    license: str | None = None
    license_changed_from: str | None = None


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


class OnPremAssessment(BaseModel):
    """One deterministic on-prem adoption rubric assessment."""

    score: int = Field(ge=1, le=5)
    reason: str


class ScoredSignal(BaseModel):
    """Signal with deterministic scoring results."""

    signal: Signal
    scores: ScoreBreakdown
    reason_codes: list[str] = Field(default_factory=list)
    recommended_ring: Ring
    on_prem_rubric: dict[str, OnPremAssessment] = Field(default_factory=dict)


class DecisionCard(BaseModel):
    """Project-level decision card generated from scored signals."""

    project: str
    category: Category
    ring: Ring
    score: float = 0.0  # representative average score (for transparency/sorting)
    summary: str
    workflow_fit: dict[str, str]
    risk_level: str
    what_changed: list[str] = Field(default_factory=list)
    why_it_matters: str = ""
    on_prem_fit: str = ""
    on_prem_rubric: dict[str, OnPremAssessment] = Field(default_factory=dict)
    risk_reasons: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    try_this_week: list[str] = Field(default_factory=list)
    try_next: list[str] = Field(default_factory=list)
    company_demo: dict[str, str | bool] = Field(default_factory=dict)
    evidence: list[str] = Field(default_factory=list)
    # Human-readable observed-data lines ("stars +1,240 (+3.1%) since last
    # scan"), distinct from `evidence` which holds source URLs.
    evidence_notes: list[str] = Field(default_factory=list)
    # Whether upgrading to the releases in this window is routine:
    # none | low (deprecations) | high (breaking changes, security fixes).
    upgrade_risk: str = "none"
    upgrade_risk_notes: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    last_reviewed_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC)
    )

    @field_validator("risk_level")
    @classmethod
    def validate_risk_level(cls, value: str) -> str:
        allowed = {"low", "medium", "high"}
        if value not in allowed:
            raise ValueError(f"risk_level must be one of {sorted(allowed)}")
        return value
