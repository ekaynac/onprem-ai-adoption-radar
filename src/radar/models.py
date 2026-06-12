"""Typed domain and configuration models."""

from __future__ import annotations

from datetime import datetime, timezone
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


class Config(BaseModel):
    """Application configuration."""

    model_config = ConfigDict(extra="forbid")

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
    tags: list[str] = Field(default_factory=list)
    last_reviewed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @field_validator("risk_level")
    @classmethod
    def validate_risk_level(cls, value: str) -> str:
        allowed = {"low", "medium", "high"}
        if value not in allowed:
            raise ValueError(f"risk_level must be one of {sorted(allowed)}")
        return value
