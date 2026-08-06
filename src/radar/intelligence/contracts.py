"""Immutable contracts shared by intelligence ingestion and delivery."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from radar.models import Ring


class FrozenModel(BaseModel):
    """Strict immutable value object."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class LifecycleState(StrEnum):
    DETECTED = "detected"
    VERIFIED = "verified"
    QUALIFIED = "qualified"
    RECOMMENDED = "recommended"


class ModelCategory(StrEnum):
    TEXT_REASONING = "text_reasoning"
    MULTIMODAL = "multimodal"
    EMBEDDING_RERANKING = "embedding_reranking"
    SPEECH_AUDIO = "speech_audio"
    IMAGE_VIDEO = "image_video"
    VISION_DOCUMENT = "vision_document"


class ReleaseLane(StrEnum):
    DEPLOYABLE = "deployable_onprem"
    ADJACENT = "onprem_adjacent"
    MARKET_REFERENCE = "market_reference"


class EvidenceStrength(StrEnum):
    OFFICIAL_ARTIFACT = "official_artifact"
    OFFICIAL_DOCUMENTATION = "official_documentation"
    OFFICIAL_REPOSITORY = "official_repository"
    OFFICIAL_ANNOUNCEMENT = "official_announcement"
    TRUSTED_REGISTRY = "trusted_registry"
    BENCHMARK_MAINTAINER = "benchmark_maintainer"
    AGGREGATOR = "aggregator"
    COMMUNITY = "community"


PUBLIC_DISCOVERY_STRENGTHS = frozenset(
    {
        EvidenceStrength.OFFICIAL_ARTIFACT,
        EvidenceStrength.OFFICIAL_DOCUMENTATION,
        EvidenceStrength.OFFICIAL_REPOSITORY,
        EvidenceStrength.OFFICIAL_ANNOUNCEMENT,
        EvidenceStrength.TRUSTED_REGISTRY,
    }
)


class ClaimState(StrEnum):
    CANDIDATE = "candidate"
    VERIFIED = "verified"
    CONFLICTING = "conflicting"
    STALE = "stale"
    REJECTED = "rejected"


class ClaimFreshness(StrEnum):
    FRESH = "fresh"
    STALE = "stale"


class SupportStatus(StrEnum):
    YES = "yes"
    PARTIAL = "partial"
    NO = "no"
    UNKNOWN = "unknown"


class EvidenceLevel(StrEnum):
    DOCUMENTED = "documented"
    TESTED = "tested"
    INFERRED = "inferred"


class Publisher(FrozenModel):
    id: str
    name: str
    official_domains: list[str]
    official_accounts: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)


class ProductFamily(FrozenModel):
    id: str
    publisher_id: str
    name: str
    aliases: list[str] = Field(default_factory=list)


class Release(FrozenModel):
    id: str
    family_id: str
    publisher_id: str
    name: str
    category: ModelCategory
    lane: ReleaseLane
    lifecycle: LifecycleState
    first_observed_at: datetime
    discovery_evidence_strength: EvidenceStrength

    @model_validator(mode="after")
    def validate_public_detection(self) -> Release:
        if (
            self.lifecycle is LifecycleState.DETECTED
            and self.discovery_evidence_strength not in PUBLIC_DISCOVERY_STRENGTHS
        ):
            raise ValueError("Detected releases require official or trusted evidence")
        return self


class Artifact(FrozenModel):
    id: str
    release_id: str
    kind: str
    url: str
    checksum: str | None = None
    accessible: bool


class Claim(FrozenModel):
    id: str
    subject_id: str
    predicate: str
    value: Any
    state: ClaimState
    observed_at: datetime
    evidence_ids: list[str] = Field(default_factory=list)
    unit: str | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    supersedes_claim_id: str | None = None

    @model_validator(mode="after")
    def validate_verified_evidence(self) -> Claim:
        if self.state is ClaimState.VERIFIED and not self.evidence_ids:
            raise ValueError("Verified claims require evidence")
        return self


class EvidenceObservation(FrozenModel):
    id: str
    source_url: str
    strength: EvidenceStrength
    retrieved_at: datetime
    checksum: str
    extractor_version: str
    raw_snapshot_path: str | None = None


class CompatibilityAssertion(FrozenModel):
    id: str
    release_id: str
    platform_id: str
    platform_version: str
    feature: str
    support: SupportStatus
    evidence_level: EvidenceLevel
    evidence_ids: list[str]
    hardware_scope: list[str] = Field(default_factory=list)


class Qualification(FrozenModel):
    release_id: str
    qualified: bool
    category: ModelCategory
    reasons: list[str]
    assumptions: list[str]
    evidence_ids: list[str]


class Recommendation(FrozenModel):
    release_id: str
    workspace_id: str | None
    ring: Ring
    score: float
    reasons: list[str]
    assumptions: list[str]
    evidence_ids: list[str]
    computation_version: str


class LifecycleTransition(FrozenModel):
    release_id: str
    from_state: LifecycleState | None
    to_state: LifecycleState
    observed_at: datetime
    reason: str
    evidence_ids: list[str]


class LineageRelation(StrEnum):
    BASE = "base"
    FINETUNE = "finetune"
    ADAPTER = "adapter"
    MERGE = "merge"
    QUANTIZED = "quantized"
    CONVERTED = "converted"
    DISTILLED = "distilled"
    PRUNED = "pruned"
    CHECKPOINT = "checkpoint"


class LineageReviewStatus(StrEnum):
    CLEAR = "clear"
    OPEN = "open"
    RESOLVED = "resolved"


class LineageEdge(FrozenModel):
    """A parent relationship between a release and its upstream model.

    ``parent_external_ref`` carries the declared identity as observed at the
    source (e.g. ``hf:moonshotai/Kimi-K3``); ``parent_release_id`` and
    ``root_release_id`` are filled once identity resolution maps the ref into
    the canonical release namespace, which may happen later than discovery.
    """

    id: str
    child_release_id: str
    parent_external_ref: str
    parent_release_id: str | None = None
    root_release_id: str | None = None
    relation: LineageRelation
    declared: bool
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_ids: list[str] = Field(default_factory=list)
    extractor_version: str
    review_status: LineageReviewStatus = LineageReviewStatus.CLEAR
    observed_at: datetime

    @model_validator(mode="after")
    def validate_edge(self) -> LineageEdge:
        if self.declared and not self.evidence_ids:
            raise ValueError("Declared lineage edges require evidence")
        if (
            self.parent_release_id is not None
            and self.parent_release_id == self.child_release_id
        ):
            raise ValueError("A release cannot be its own lineage parent")
        return self


# Observations, not facts: these predicates are time-series metrics whose
# values legitimately drift between authoritative fetches (every HF scan
# sees new download counts and a moving repo sha). They are latest-wins by
# definition and must never open conflicting-authoritative-claims reviews —
# doing so flooded the queue with ~750 false conflicts (2026-08-03..05).
VOLATILE_PREDICATES = frozenset({"downloads", "likes", "last_modified", "sha"})

# Registry hosts serve ONE mutable record per subject: a list sweep and a
# detail endpoint (or two fetches a day apart) are versions of the same
# record, so disagreement between them is temporal drift — latest wins,
# never a dispute. Evidence from any other host keeps exact-URL identity
# (two different official pages CAN genuinely conflict).
REGISTRY_HOSTS = frozenset({"huggingface.co"})


class ReviewException(FrozenModel):
    id: str
    subject_id: str
    code: str
    message: str
    evidence_ids: list[str]
    opened_at: datetime
    resolved_at: datetime | None = None
