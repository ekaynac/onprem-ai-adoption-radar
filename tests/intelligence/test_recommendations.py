from __future__ import annotations

from radar.intelligence.contracts import (
    Claim,
    ClaimState,
    EvidenceObservation,
    EvidenceStrength,
    Qualification,
)
from radar.intelligence.recommendations import RecommendationService
from radar.intelligence.workspaces import WorkspaceInput, WorkspaceService
from radar.models import Ring

from .lifecycle_helpers import NOW, RELEASE_ID, lifecycle_repository


def seed_recommendable_release(repository) -> None:
    evidence = EvidenceObservation(
        id="evidence:qualification",
        source_url="https://moonshot.ai/kimi-k3",
        strength=EvidenceStrength.OFFICIAL_DOCUMENTATION,
        retrieved_at=NOW,
        checksum="sha256:qualification",
        extractor_version="test-v1",
    )
    repository.append_evidence(evidence)
    for predicate, value in (
        ("params_total", 1_000_000_000_000),
        ("context_length", 262_144),
        ("license", "kimi-k3"),
    ):
        repository.append_claim(
            Claim(
                id=f"claim:{predicate}",
                subject_id=RELEASE_ID,
                predicate=predicate,
                value=value,
                state=ClaimState.VERIFIED,
                observed_at=NOW,
                evidence_ids=[evidence.id],
            )
        )
    release = repository.get_release_required(RELEASE_ID)
    repository.save_qualification(
        Qualification(
            release_id=RELEASE_ID,
            qualified=True,
            category=release.category,
            reasons=["Verified deployable artifact"],
            assumptions=[],
            evidence_ids=[evidence.id],
        ),
        NOW,
    )


def test_multiple_workspaces_change_fit_without_users(tmp_path) -> None:
    repository = lifecycle_repository(tmp_path)
    seed_recommendable_release(repository)
    workspaces = WorkspaceService(repository)
    laptop = workspaces.create(
        WorkspaceInput(
            name="Laptop Lab",
            devices=[{"device_id": "rtx-4090-24gb", "count": 1}],
            policies={"allowed_licenses": ["apache-2.0", "mit"]},
        )
    )
    datacenter = workspaces.create(
        WorkspaceInput(
            name="H200 Cluster",
            devices=[{"device_id": "hgx-h200-8", "count": 2}],
            policies={
                "allowed_licenses": ["apache-2.0", "mit", "kimi-k3"]
            },
        )
    )
    service = RecommendationService(repository)

    laptop_result = service.for_workspace(RELEASE_ID, laptop.id)
    dc_result = service.for_workspace(RELEASE_ID, datacenter.id)

    assert laptop_result.ring is Ring.AVOID
    assert dc_result.ring is Ring.PILOT
    assert laptop_result.workspace_id == laptop.id
    assert dc_result.workspace_id == datacenter.id
    assert service.public(RELEASE_ID).ring is Ring.PILOT
