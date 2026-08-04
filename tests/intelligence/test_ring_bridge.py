"""Legacy ring bridge: curated pipeline rings become canonical recommendations."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from radar.intelligence.contracts import (
    EvidenceStrength,
    LifecycleState,
    ModelCategory,
    ProductFamily,
    Publisher,
    Release,
    ReleaseLane,
)
from radar.intelligence.recommendations import (
    LEGACY_BRIDGE_VERSION,
    RecommendationService,
    legacy_ring_bridge,
)
from radar.intelligence.services.container import build_services
from radar.models import Ring
from radar.web.intelligence_snapshot import (
    SnapshotInvariantError,
    build_public_snapshot,
    write_model_index,
)

from .lifecycle_helpers import lifecycle_repository


NOW = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)

PROFILES = {
    "kimi-k3": {
        "id": "kimi-k3",
        "ring": "adopt",
        "score": 4.2,
        "score_breakdown": {
            "openness": 4,
            "local_runnability": 5,
            "capability_tier": 4,
            "ecosystem_support": 4,
            "average": 4.2,
        },
        "hardware_tier": "datacenter",
        "warnings": [],
    },
    "seed-baseline": {
        "id": "seed-baseline",
        "ring": None,
        "score": None,
        "warnings": ["Curated seed baseline; scan enrichment is pending"],
    },
    "bad-ring": {"id": "bad-ring", "ring": "meteoric"},
}


def test_bridge_maps_scored_profiles_and_skips_pending_or_invalid() -> None:
    bridge = legacy_ring_bridge(PROFILES)

    assert set(bridge) == {"release:legacy:kimi-k3"}
    record = bridge["release:legacy:kimi-k3"]
    assert record.ring is Ring.ADOPT
    assert record.score == 4.2
    assert record.evidence_id == "evidence:legacy:model-seed:kimi-k3"
    assert record.hardware_tier == "datacenter"


def seed_legacy_release(repository) -> Release:
    repository.upsert_publisher(
        Publisher(
            id="publisher:legacy:moonshot-ai",
            name="Moonshot AI Legacy",
            official_domains=["moonshot.ai"],
            official_accounts=["moonshotai-legacy"],
        )
    )
    repository.upsert_family(
        ProductFamily(
            id="family:legacy:moonshot-ai:kimi",
            publisher_id="publisher:legacy:moonshot-ai",
            name="Kimi Legacy",
        )
    )
    release = Release(
        id="release:legacy:kimi-k3",
        family_id="family:legacy:moonshot-ai:kimi",
        publisher_id="publisher:legacy:moonshot-ai",
        name="Kimi K3",
        category=ModelCategory.MULTIMODAL,
        lane=ReleaseLane.DEPLOYABLE,
        lifecycle=LifecycleState.DETECTED,
        first_observed_at=NOW,
        discovery_evidence_strength=EvidenceStrength.TRUSTED_REGISTRY,
    )
    repository.upsert_release(release)
    return release


def test_bridged_recommendation_restores_the_adopt_path(tmp_path) -> None:
    repository = lifecycle_repository(tmp_path)
    release = seed_legacy_release(repository)
    service = RecommendationService(
        repository,
        legacy_ring_bridge(PROFILES),
    )

    view = service.public(release.id)

    # DETECTED lifecycle would normally yield no ring at all.
    assert view.public_ring is Ring.ADOPT
    assert view.ring is Ring.ADOPT
    assert view.computation_version == LEGACY_BRIDGE_VERSION
    assert view.evidence_ids == ["evidence:legacy:model-seed:kimi-k3"]
    assert any("4.2/5" in reason for reason in view.reasons)
    assert any("openness 4/5" in reason for reason in view.reasons)

    unbridged = RecommendationService(repository).public(release.id)
    assert unbridged.public_ring is None


def test_snapshot_carries_bridged_rings_and_index_matches(tmp_path) -> None:
    repository = lifecycle_repository(tmp_path)
    release = seed_legacy_release(repository)
    bridge = legacy_ring_bridge(PROFILES)

    snapshot = build_public_snapshot(
        build_services(repository, legacy_rings=bridge),
        NOW,
    ).model_dump(mode="json")
    row = next(
        item
        for item in snapshot["models"]
        if item["release_id"] == release.id
    )
    assert row["public_ring"] == "adopt"
    assert any("4.2/5" in reason for reason in row["reasons"])

    manifest = write_model_index(
        repository.list_all_releases(),
        tmp_path / "_site",
        NOW,
        repository=repository,
        legacy_rings=bridge,
    )
    import json as json_module

    payload = json_module.loads(
        (tmp_path / "_site" / manifest.shards[0].path).read_text()
    )
    index_row = next(
        item for item in payload["items"] if item["release_id"] == release.id
    )
    assert index_row["public_ring"] == "adopt"


def test_briefing_summarizes_rings_picks_and_movers(tmp_path) -> None:
    from radar.web.intelligence_snapshot import _build_briefing

    projects = [
        {
            "project": "vllm",
            "category": "inference_serving",
            "ring": "adopt",
            "backer": "community",
            "trend": "rising",
            "risk_level": "low",
            "score": 4.5,
            "try_this_week": "Serve a quantized model with speculative decoding",
            "evidence_notes": ["note one", "note two", "note three"],
            "history": [
                {
                    "change_type": "promoted",
                    "ring": "adopt",
                    "previous_ring": "pilot",
                    "observed_at": "2026-08-01T10:00:00Z",
                }
            ],
        },
        {
            "project": "old-tool",
            "category": "agent_frameworks",
            "ring": "avoid",
            "score": 1.2,
            "history": [
                {
                    # Outside the mover window: must not appear.
                    "change_type": "demoted",
                    "ring": "avoid",
                    "previous_ring": "watch",
                    "observed_at": "2026-06-01T10:00:00Z",
                }
            ],
        },
    ]
    model_rows = [
        {"release_id": "release:legacy:kimi-k3", "public_ring": "adopt"},
        {"release_id": "release:legacy:pending-model", "public_ring": None},
        {"release_id": "release:hf:acme/thing", "public_ring": None},
    ]

    briefing = _build_briefing(
        projects,
        model_rows,
        datetime(2026, 8, 3, 12, 0, tzinfo=UTC),
        None,
    )

    assert briefing["rings"]["projects"] == {
        "tracked": 2,
        "adopt": 1,
        "avoid": 1,
    }
    assert briefing["rings"]["models"] == {"tracked": 2, "adopt": 1}
    assert [pick["project"] for pick in briefing["try_this_week"]] == ["vllm"]
    pick = briefing["try_this_week"][0]
    assert pick["evidence_notes"] == ["note one", "note two"]
    assert pick["note"] == "Serve a quantized model with speculative decoding"
    # Mover line matches the CLI movers report format.
    assert [mover["line"] for mover in briefing["movers"]] == [
        "vllm: pilot → adopt (promoted)"
    ]


def test_snapshot_invariant_fails_when_curated_ring_is_dropped(tmp_path) -> None:
    repository = lifecycle_repository(tmp_path)
    seed_legacy_release(repository)
    root = tmp_path / "root"
    (root / "data" / "runs" / "run-1").mkdir(parents=True)
    (root / "data" / "runs" / "run-1" / "meta.json").write_text(
        '{"run_id": "run-1", "kind": "models"}'
    )
    (root / "data" / "runs" / "run-1" / "model_cards.json").write_text(
        """[{"id": "kimi-k3", "name": "Kimi K3", "family": "Kimi",
            "ring": "adopt", "score": 4.2}]"""
    )

    with pytest.raises(SnapshotInvariantError, match="release:legacy:kimi-k3"):
        # Services built WITHOUT the bridge: the curated ring would be
        # silently dropped, so the snapshot build must refuse.
        build_public_snapshot(
            build_services(repository),
            NOW,
            root=root,
        )
