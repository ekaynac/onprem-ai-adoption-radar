from datetime import UTC, datetime

from radar.intelligence.contracts import LineageEdge, LineageRelation
from radar.storage.model_candidate_log import (
    ModelCandidateObservation,
    append_model_candidates,
)


def test_release_stream_supports_since_and_workspace(api_client) -> None:
    response = api_client.get(
        "/api/v1/releases",
        params={
            "since": "2026-07-30T08:00:00Z",
            "workspace_id": "workspace:dc",
        },
    )

    assert response.status_code == 200
    assert response.json()["items"][0]["citations"]


def test_unknown_release_is_404(api_client) -> None:
    response = api_client.get("/api/v1/releases/release:missing")

    assert response.status_code == 404


def test_release_stream_includes_fresh_hf_candidates_by_default(
    api_client,
    tmp_path,
) -> None:
    append_model_candidates(
        tmp_path / "data" / "model-candidate-observations.jsonl",
        [
            ModelCandidateObservation(
                hf_repo="moonshotai/Kimi-K3",
                name="Kimi-K3",
                family="moonshotai",
                downloads=1,
                pipeline_tag="image-text-to-text",
                observed_at=datetime.now(UTC),
            )
        ],
    )

    response = api_client.get("/api/v1/releases")

    assert response.status_code == 200
    assert any(item["name"] == "Kimi-K3" for item in response.json()["items"])


def test_priority_release_filter_runs_before_limit(api_client, tmp_path) -> None:
    observations = [
        ModelCandidateObservation(
            hf_repo=f"community/model-{index}",
            name=f"Low {index}",
            family=f"community-{index}",
            downloads=0,
            likes=0,
            last_modified="2026-08-03T09:00:00Z",
            observed_at=datetime.now(UTC),
        )
        for index in range(50)
    ]
    observations.append(
        ModelCandidateObservation(
            hf_repo="moonshotai/Authority",
            name="Authoritative release",
            family="moonshotai",
            downloads=10_000,
            likes=500,
            pipeline_tag="text-generation",
            last_modified="2026-08-02T09:00:00Z",
            observed_at=datetime.now(UTC),
        )
    )
    append_model_candidates(
        tmp_path / "data" / "model-candidate-observations.jsonl",
        observations,
    )

    response = api_client.get(
        "/api/v1/releases",
        params={"priority_only": "true", "limit": 1},
    )

    assert response.status_code == 200
    assert response.json()["items"][0]["name"] == "Authoritative release"


def test_priority_stream_excludes_declared_derivatives(
    api_client,
    api_repository,
) -> None:
    from datetime import datetime as dt

    from radar.intelligence.contracts import (
        Claim,
        ClaimState,
        EvidenceObservation,
        EvidenceStrength,
        LifecycleState,
        ModelCategory,
        Release,
        ReleaseLane,
    )

    root_release = api_repository.list_all_releases()[0]
    derivative = Release(
        id="release:moonshot-ai:kimi:k3:gguf",
        family_id=root_release.family_id,
        publisher_id=root_release.publisher_id,
        name="Kimi K3 GGUF",
        category=ModelCategory.MULTIMODAL,
        lane=ReleaseLane.DEPLOYABLE,
        lifecycle=LifecycleState.VERIFIED,
        first_observed_at=dt(2026, 8, 3, 7, tzinfo=UTC),
        discovery_evidence_strength=EvidenceStrength.TRUSTED_REGISTRY,
    )
    api_repository.upsert_release(derivative)
    evidence = EvidenceObservation(
        id="evidence:priority-derivative",
        source_url="https://huggingface.co/grearl/Kimi-K3-GGUF",
        strength=EvidenceStrength.TRUSTED_REGISTRY,
        retrieved_at=dt(2026, 8, 3, 8, tzinfo=UTC),
        checksum="priority-derivative",
        extractor_version="test",
    )
    api_repository.append_evidence(evidence)
    for index, (predicate, value) in enumerate(
        (
            ("hf_repo", "grearl/Kimi-K3-GGUF"),
            ("last_modified", "2026-08-03T07:55:00Z"),
            ("downloads", 5_000_000),
            ("likes", 4_000),
            ("license", "modified-mit"),
            ("pipeline_tag", "image-text-to-text"),
        )
    ):
        api_repository.append_claim(
            Claim(
                id=f"claim:priority-derivative:{index}",
                subject_id=derivative.id,
                predicate=predicate,
                value=value,
                state=ClaimState.CANDIDATE,
                observed_at=evidence.retrieved_at,
                evidence_ids=[evidence.id],
            )
        )
    api_repository.upsert_lineage_edge(
        LineageEdge(
            id=f"lineage:{derivative.id}:quantized:hf:moonshotai/kimi-k3",
            child_release_id=derivative.id,
            parent_external_ref="hf:moonshotai/Kimi-K3",
            parent_release_id=root_release.id,
            root_release_id=root_release.id,
            relation=LineageRelation.QUANTIZED,
            declared=True,
            confidence=0.95,
            evidence_ids=[evidence.id],
            extractor_version="test",
            observed_at=evidence.retrieved_at,
        )
    )

    everything = api_client.get("/api/v1/releases", params={"limit": 100})
    assert any(
        item["release_id"] == derivative.id
        for item in everything.json()["items"]
    )

    priority = api_client.get(
        "/api/v1/releases",
        params={"priority_only": "true", "limit": 100},
    )
    priority_ids = [item["release_id"] for item in priority.json()["items"]]
    assert derivative.id not in priority_ids
