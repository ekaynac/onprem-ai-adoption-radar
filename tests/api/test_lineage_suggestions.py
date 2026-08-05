"""Operator flow: list/accept/reject Tier-3 lineage suggestions."""

from __future__ import annotations

from datetime import UTC, datetime


def _seed_suggestion(repository) -> str:
    from radar.intelligence.contracts import (
        EvidenceStrength,
        LifecycleState,
        LineageRelation,
        ModelCategory,
        Release,
        ReleaseLane,
    )
    from radar.intelligence.lineage import build_inferred_edge

    release = repository.list_all_releases()[0]
    child = Release(
        id="release:child:gguf",
        family_id=release.family_id,
        publisher_id=release.publisher_id,
        name="Child GGUF",
        category=ModelCategory.TEXT_REASONING,
        lane=ReleaseLane.DEPLOYABLE,
        lifecycle=LifecycleState.DETECTED,
        first_observed_at=datetime(2026, 8, 5, tzinfo=UTC),
        discovery_evidence_strength=EvidenceStrength.TRUSTED_REGISTRY,
    )
    repository.upsert_release(child)
    edge = build_inferred_edge(
        child.id,
        "quantco/Model-X-GGUF",
        "acme/Model-X",
        LineageRelation.QUANTIZED,
        resolve_parent=lambda repo: None,
        observed_at=datetime(2026, 8, 5, tzinfo=UTC),
    )
    repository.upsert_lineage_edge(edge)
    return edge.id


def test_suggestions_are_listed_and_acceptable(api_client, api_repository):
    edge_id = _seed_suggestion(api_repository)

    listed = api_client.get("/api/v1/operations/lineage-suggestions")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [edge_id]

    accepted = api_client.post(
        f"/api/v1/operations/lineage-suggestions/{edge_id}/accept"
    )
    assert accepted.status_code == 200
    payload = accepted.json()
    assert payload["declared"] is True
    assert payload["confidence"] == 0.9
    assert payload["evidence_ids"]
    # No longer a suggestion.
    assert api_client.get("/api/v1/operations/lineage-suggestions").json() == []
    assert (
        api_client.post(
            f"/api/v1/operations/lineage-suggestions/{edge_id}/accept"
        ).status_code
        == 404
    )


def test_suggestions_can_be_rejected(api_client, api_repository):
    edge_id = _seed_suggestion(api_repository)

    rejected = api_client.post(
        f"/api/v1/operations/lineage-suggestions/{edge_id}/reject"
    )
    assert rejected.status_code == 204
    assert api_repository.get_lineage_edge(edge_id) is None
    assert (
        api_client.post(
            f"/api/v1/operations/lineage-suggestions/{edge_id}/reject"
        ).status_code
        == 404
    )


def test_public_mode_rejects_suggestion_mutations(
    public_api_client, api_repository
):
    edge_id = _seed_suggestion(api_repository)
    assert (
        public_api_client.post(
            f"/api/v1/operations/lineage-suggestions/{edge_id}/accept"
        ).status_code
        == 403
    )
    assert (
        public_api_client.post(
            f"/api/v1/operations/lineage-suggestions/{edge_id}/reject"
        ).status_code
        == 403
    )
