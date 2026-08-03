from datetime import UTC, datetime

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
