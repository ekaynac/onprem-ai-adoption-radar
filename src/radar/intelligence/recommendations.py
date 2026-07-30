"""Transparent public and workspace-adjusted recommendations."""

from __future__ import annotations

from typing import Protocol

from pydantic import Field

from radar.intelligence.contracts import (
    Claim,
    ClaimState,
    FrozenModel,
    Qualification,
    Release,
    ReleaseLane,
)
from radar.intelligence.workspaces import Workspace
from radar.models import Ring
from radar.models_radar.devices import resolve_device, usable_memory_gb
from radar.models_radar.memory import estimate_memory_gb


COMPUTATION_VERSION = "workspace-recommendation-v1"


class RecommendationView(FrozenModel):
    release_id: str
    workspace_id: str | None
    public_ring: Ring | None
    ring: Ring | None
    changed_factors: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    computation_version: str = COMPUTATION_VERSION


class RecommendationRepository(Protocol):
    def get_release_required(self, release_id: str) -> Release: ...

    def get_qualification(self, release_id: str) -> Qualification | None: ...

    def list_claims_for_subject(self, subject_id: str) -> list[Claim]: ...

    def get_workspace(self, workspace_id: str) -> Workspace | None: ...


class RecommendationService:
    def __init__(self, repository: RecommendationRepository):
        self.repository = repository

    def public(self, release_id: str) -> RecommendationView:
        release = self.repository.get_release_required(release_id)
        qualification = self.repository.get_qualification(release_id)
        if release.lane is ReleaseLane.MARKET_REFERENCE:
            return RecommendationView(
                release_id=release_id,
                workspace_id=None,
                public_ring=None,
                ring=None,
                reasons=[
                    "Market-reference releases receive comparison context "
                    "without an on-prem adoption ring"
                ],
            )
        qualified = bool(qualification and qualification.qualified)
        ring = Ring.PILOT if qualified else Ring.WATCH
        return RecommendationView(
            release_id=release_id,
            workspace_id=None,
            public_ring=ring,
            ring=ring,
            reasons=(
                list(qualification.reasons)
                if qualification is not None
                else ["Qualification has not completed"]
            ),
            assumptions=(
                list(qualification.assumptions)
                if qualification is not None
                else []
            ),
            evidence_ids=(
                list(qualification.evidence_ids)
                if qualification is not None
                else []
            ),
        )

    def for_workspace(
        self,
        release_id: str,
        workspace_id: str,
    ) -> RecommendationView:
        public = self.public(release_id)
        workspace = self.repository.get_workspace(workspace_id)
        if workspace is None:
            raise KeyError(f"Unknown workspace: {workspace_id}")
        if public.ring is None:
            return public.model_copy(update={"workspace_id": workspace_id})

        claims = _current_claims(
            self.repository.list_claims_for_subject(release_id)
        )
        changed_factors: list[str] = []
        reasons = list(public.reasons)
        ring = public.ring

        license_value = _string_claim(claims, "license")
        allowed_licenses = workspace.policies.get("allowed_licenses")
        if (
            isinstance(allowed_licenses, list)
            and license_value is not None
            and license_value not in allowed_licenses
        ):
            ring = Ring.AVOID
            changed_factors.append("license_policy")
            reasons.append(
                f"License {license_value!r} is not allowed by this workspace"
            )

        required_memory = _required_memory(claims)
        available_memory = sum(
            usable_memory_gb(
                resolve_device(
                    item.device_id
                    if item.device_id is not None
                    else item.custom_device or {}
                )
            )
            * item.count
            for item in workspace.devices
        )
        if required_memory is not None and available_memory < required_memory:
            ring = Ring.AVOID
            changed_factors.append("hardware_capacity")
            reasons.append(
                f"Estimated {required_memory:.2f} GB model footprint exceeds "
                f"{available_memory:.2f} GB usable workspace memory"
            )
        elif required_memory is not None:
            reasons.append(
                f"Estimated {required_memory:.2f} GB model footprint fits "
                f"{available_memory:.2f} GB usable workspace memory"
            )
        else:
            if ring is Ring.PILOT:
                ring = Ring.WATCH
            changed_factors.append("hardware_unknown")
            reasons.append("Verified claims are insufficient for a memory fit")

        return RecommendationView(
            release_id=release_id,
            workspace_id=workspace_id,
            public_ring=public.public_ring,
            ring=ring,
            changed_factors=sorted(set(changed_factors)),
            reasons=reasons,
            assumptions=[
                *public.assumptions,
                "Workspace memory uses device usable-memory safety factors",
            ],
            evidence_ids=public.evidence_ids,
        )


def _current_claims(claims: list[Claim]) -> dict[str, Claim]:
    selected: dict[str, Claim] = {}
    for claim in claims:
        if claim.state not in {ClaimState.CANDIDATE, ClaimState.VERIFIED}:
            continue
        current = selected.get(claim.predicate)
        if current is None or (claim.observed_at, claim.id) > (
            current.observed_at,
            current.id,
        ):
            selected[claim.predicate] = claim
    return selected


def _integer_claim(claims: dict[str, Claim], predicate: str) -> int | None:
    claim = claims.get(predicate)
    if claim is None or isinstance(claim.value, bool):
        return None
    if isinstance(claim.value, int):
        return claim.value
    if isinstance(claim.value, str) and claim.value.isdigit():
        return int(claim.value)
    return None


def _string_claim(claims: dict[str, Claim], predicate: str) -> str | None:
    claim = claims.get(predicate)
    return claim.value if claim is not None and isinstance(claim.value, str) else None


def _required_memory(claims: dict[str, Claim]) -> float | None:
    return estimate_memory_gb(
        _integer_claim(claims, "params_total"),
        bits_per_weight=4.0,
        context=_integer_claim(claims, "context_length") or 4096,
        num_layers=_integer_claim(claims, "num_layers"),
        hidden_size=_integer_claim(claims, "hidden_size"),
    )
