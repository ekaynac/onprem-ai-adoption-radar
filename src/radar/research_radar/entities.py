"""Entities for the academic research radar (techniques, not papers)."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from radar.models import Category, Ring


class TechniqueDomain(str, Enum):
    """Research-native grouping, orthogonal to the radar Category."""

    INFERENCE = "inference"
    FINE_TUNING = "fine_tuning"
    RAG = "rag"
    AGENT_ARCHITECTURE = "agent_architecture"
    SAFETY_SANDBOXING = "safety_sandboxing"
    ORCHESTRATION = "orchestration"
    EMBODIED = "embodied"


class PaperRole(str, Enum):
    CANONICAL = "canonical"
    FOLLOWUP = "followup"
    SURVEY = "survey"


class OnPremImpact(str, Enum):
    """What adopting the technique buys an on-prem deployment."""

    REDUCES_MEMORY = "reduces_memory"
    REDUCES_LATENCY = "reduces_latency"
    ENABLES_SCALE = "enables_scale"
    IMPROVES_SAFETY = "improves_safety"
    IMPROVES_QUALITY = "improves_quality"


class ImplKind(str, Enum):
    TOOL = "tool"    # ref = a source id in data/config.yaml
    MODEL = "model"  # ref = a model id in config/model-seed.yaml


class PaperLink(BaseModel):
    """A paper attached to a technique (papers are attributes, never entities)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    arxiv_id: str
    title: str
    role: PaperRole = PaperRole.CANONICAL
    published: str | None = None  # ISO "YYYY-MM"


class ImplementationLink(BaseModel):
    """A typed link into the radar's own tool/model catalogs."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: ImplKind
    ref: str
    note: str | None = None


class ResolvedImplementation(BaseModel):
    """An implementation link resolved against the catalogs at assembly time."""

    model_config = ConfigDict(frozen=True)

    kind: ImplKind
    ref: str
    ring: Ring | None = None  # referenced entity's current ring (None = no ring yet)
    note: str | None = None


class TechniqueSeed(BaseModel):
    """A curated technique entry (config/technique-seed.yaml)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    category: Category
    domain: TechniqueDomain
    aliases: list[str] = Field(default_factory=list)
    papers: list[PaperLink] = Field(default_factory=list)
    implementations: list[ImplementationLink] = Field(default_factory=list)
    open_code: bool = False
    onprem_impact: OnPremImpact
    superseded_by: str | None = None
    enabled: bool = True
    notes: str | None = None


class TechniqueScore(BaseModel):
    """Deterministic technique-adoption score dimensions (1-5)."""

    model_config = ConfigDict(frozen=True)

    implementation_breadth: int = Field(ge=1, le=5)
    implementation_maturity: int = Field(ge=1, le=5)
    validation: int = Field(ge=1, le=5)
    reproducibility: int = Field(ge=1, le=5)
    momentum: int = Field(ge=1, le=5)
    onprem_impact: int = Field(ge=1, le=5)
    average: float


class TechniqueEntry(BaseModel):
    """A tracked technique with resolved evidence and (after scoring) a ring."""

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    category: Category
    domain: TechniqueDomain
    aliases: list[str] = Field(default_factory=list)
    papers: list[PaperLink] = Field(default_factory=list)
    resolved_implementations: list[ResolvedImplementation] = Field(default_factory=list)
    open_code: bool = False
    onprem_impact: OnPremImpact
    superseded_by: str | None = None
    notes: str | None = None
    citation_count: int | None = None
    citation_source: str | None = None  # "s2" | "openalex" (velocity is same-source only)
    peer_reviewed: bool | None = None
    score: float | None = None
    score_breakdown: TechniqueScore | None = None
    ring: Ring | None = None
    warnings: list[str] = Field(default_factory=list)
