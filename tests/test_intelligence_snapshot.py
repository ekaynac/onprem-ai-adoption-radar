import json
import logging
import shutil
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from intelligence.lifecycle_helpers import lifecycle_repository
from intelligence.test_recommendations import seed_recommendable_release
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
from radar.intelligence.services.container import build_services
from radar.models import Category, DecisionCard, Ring
from radar.storage.database import RadarDatabase
from radar.storage.digest_log import DigestLogEntry, append_digest
from radar.storage.model_candidate_log import (
    ModelCandidateObservation,
    append_model_candidates,
)
from radar.storage.source_health_log import (
    SourceHealthRecord,
    SourceOutcome,
    append_source_health,
)
from radar.web.intelligence_snapshot import (
    PUBLIC_RECENT_RELEASE_LIMIT,
    _select_public_releases,
    build_public_snapshot,
    write_model_index,
    write_public_snapshot,
)


def _public_project_payload() -> dict:
    return {
        "project": "vLLM",
        "category": "model_serving",
        "ring": "adopt",
        "score": 4.7,
        "summary": "High-throughput model serving engine.",
        "workflow_fit": {"serving": "strong"},
        "risk_level": "medium",
        "why_it_matters": "Production-grade throughput.",
        "on_prem_fit": "Strong fit for GPU clusters.",
        "evidence": ["https://github.com/vllm-project/vllm"],
        "try_this_week": ["Run a throughput benchmark."],
        "last_reviewed_at": "2026-07-31T08:00:00Z",
        "repository_url": "https://github.com/vllm-project/vllm",
        "sources": [],
        "history": [],
        "latest_metrics": None,
    }


@pytest.mark.parametrize("predicate", ["published_at", "pushed_at"])
def test_public_release_selection_uses_upstream_dates(predicate: str) -> None:
    discovered_late = _release(1).model_copy(
        update={"first_observed_at": datetime(2026, 8, 3, tzinfo=UTC)}
    )
    released_late = _release(2).model_copy(
        update={"first_observed_at": datetime(2026, 7, 1, tzinfo=UTC)}
    )

    selected = _select_public_releases(
        [discovered_late, released_late],
        recent_limit=1,
        metadata={
            discovered_late.id: {predicate: "2026-06-01T00:00:00Z"},
            released_late.id: {predicate: "2026-08-03T07:59:00Z"},
        },
    )

    assert selected == [released_late]


def test_public_projects_fall_back_to_tracked_snapshot_without_database(
    tmp_path,
) -> None:
    from radar.web.public_context import (
        load_public_project_bundle,
        load_public_projects,
    )

    snapshot = tmp_path / "data" / "intelligence" / "public-snapshot.v1.json"
    snapshot.parent.mkdir(parents=True)
    raw_project = {
        **_public_project_payload(),
        "workspace_id": "workspace:private",
        "internal_notes": "must not be republished",
    }
    snapshot.write_text(
        json.dumps(
            {
                "generated_at": "2026-07-30T06:00:00Z",
                "projects": [raw_project],
            }
        ),
        encoding="utf-8",
    )

    projects = load_public_projects(tmp_path)
    bundle = load_public_project_bundle(tmp_path)

    assert len(projects) == 1
    for key, value in _public_project_payload().items():
        assert projects[0][key] == value
    assert bundle.mode == "last_published_baseline"
    assert bundle.generated_at == datetime(2026, 7, 30, 6, tzinfo=UTC)
    assert "workspace_id" not in projects[0]
    assert "internal_notes" not in projects[0]

    repository = lifecycle_repository(tmp_path)
    public_snapshot = build_public_snapshot(
        build_services(repository),
        datetime(2026, 7, 31, 10, tzinfo=UTC),
        root=tmp_path,
    ).model_dump(mode="json")
    assert public_snapshot["project_data"] == {
        "mode": "last_published_baseline",
        "generated_at": "2026-07-30T06:00:00Z",
    }
    assert "workspace_id" not in public_snapshot["projects"][0]
    assert "internal_notes" not in public_snapshot["projects"][0]


def test_public_projects_ignore_non_object_snapshot(tmp_path) -> None:
    from radar.web.public_context import load_public_projects

    snapshot = tmp_path / "data" / "intelligence" / "public-snapshot.v1.json"
    snapshot.parent.mkdir(parents=True)
    snapshot.write_text("[]", encoding="utf-8")

    assert load_public_projects(tmp_path) == []


def test_public_snapshot_is_deterministic_and_has_no_workspace_data(
    tmp_path,
) -> None:
    repository = lifecycle_repository(tmp_path)
    seed_recommendable_release(repository)
    repository.import_platform(
        platform_id="platform:vllm",
        name="vLLM",
        repo_url="https://github.com/vllm-project/vllm",
        verified_at="2026-07-30",
        payload={"features": {"tensor_parallel": True}},
    )
    generated_at = datetime(2026, 7, 30, 10, 0, tzinfo=UTC)
    snapshot = build_public_snapshot(build_services(repository), generated_at)

    path = write_public_snapshot(snapshot, tmp_path / "_site")
    first = path.read_bytes()
    write_public_snapshot(snapshot, tmp_path / "_site")

    assert path.read_bytes() == first
    payload = json.loads(first)
    assert payload["schema_version"] == "1.0"
    assert payload["releases"]
    assert set(payload) == {
        "schema_version",
        "generated_at",
        "releases",
        "models",
        "projects",
        "model_candidates",
        "platforms",
        "hardware",
        "research",
        "events",
        "source_health",
        "latest_digest",
        "project_data",
        "model_index",
        "quality",
        "source_coverage",
        "briefing",
        "planner",
        "trending",
        "advisor",
        "desk",
        "newsroom",
        "stack_demo",
    }
    assert payload["platforms"][0]["name"] == "vLLM"
    assert payload["platforms"][0]["hardware"] == {}
    assert payload["platforms"][0]["sources"] == [
        "https://github.com/vllm-project/vllm"
    ]
    assert payload["platforms"][0]["verification_status"] == "stale"
    assert payload["source_health"]["stale_claim_count"] >= 1
    assert payload["hardware"]
    assert payload["quality"]["models"]["total"] == len(payload["models"])
    assert payload["quality"]["hardware"]["total"] == len(payload["hardware"])
    assert "workspace" not in first.decode().casefold()


def _release(index: int, *, legacy: bool = False) -> Release:
    identifier = (
        f"release:legacy:model-{index}"
        if legacy
        else f"release:hf:publisher/model-{index}"
    )
    return Release(
        id=identifier,
        family_id=f"family:{index}",
        publisher_id="publisher:test",
        name=f"Model {index}",
        category=ModelCategory.TEXT_REASONING,
        lane=ReleaseLane.DEPLOYABLE,
        lifecycle=LifecycleState.DETECTED,
        first_observed_at=datetime(2026, 1, 1, tzinfo=UTC)
        + timedelta(minutes=index),
        discovery_evidence_strength=EvidenceStrength.TRUSTED_REGISTRY,
    )


def test_public_snapshot_bounds_expensive_detail_projection() -> None:
    legacy = [_release(index, legacy=True) for index in range(5)]
    discovered = [_release(index) for index in range(315)]
    canonical = [*legacy, *discovered]
    release_calls: list[str] = []
    catalog_calls: list[str] = []

    class Repository:
        def list_all_releases(self):
            return canonical

        def list_platforms(self):
            return []

        def list_events(self, *, limit, public_only):
            return []

    def release_detail(release_id, *, now):
        release_calls.append(release_id)
        return SimpleNamespace(
            model_dump=lambda mode: {
                "release_id": release_id,
                "first_observed_at": next(
                    row.first_observed_at.isoformat()
                    for row in canonical
                    if row.id == release_id
                ),
            }
        )

    def catalog_detail(release_id):
        catalog_calls.append(release_id)
        release = next(row for row in canonical if row.id == release_id)
        return SimpleNamespace(
            release_id=release.id,
            name=release.name,
            category=release.category,
            lane=release.lane.value,
            lifecycle=release.lifecycle,
            first_observed_at=release.first_observed_at.isoformat(),
            public_recommendation=SimpleNamespace(
                ring=None, reasons=[], evidence_ids=[]
            ),
        )

    services = SimpleNamespace(
        catalog=SimpleNamespace(
            repository=Repository(),
            get=catalog_detail,
        ),
        releases=SimpleNamespace(get=release_detail),
        operations=SimpleNamespace(
            snapshot=lambda: SimpleNamespace(
                model_dump=lambda mode: {
                    "source_health": [],
                    "stale_claim_count": 0,
                }
            )
        ),
    )

    snapshot = build_public_snapshot(
        services,
        datetime(2026, 8, 3, tzinfo=UTC),
    )

    assert len(release_calls) == len(legacy) + PUBLIC_RECENT_RELEASE_LIMIT
    assert catalog_calls == release_calls
    assert {row.id for row in legacy}.issubset(release_calls)
    assert discovered[-1].id in release_calls
    assert discovered[0].id not in release_calls
    assert snapshot.model_index.total == len(canonical)


def test_model_index_shards_every_release_once_and_is_deterministic(tmp_path) -> None:
    canonical = [_release(index) for index in range(20_001)]
    generated_at = datetime(2026, 8, 3, tzinfo=UTC)

    first = write_model_index(
        canonical,
        tmp_path / "_site",
        generated_at,
        shard_size=2_000,
    )
    first_bytes = {
        path.relative_to(tmp_path / "_site").as_posix(): path.read_bytes()
        for path in sorted((tmp_path / "_site" / "data").rglob("*.json"))
    }
    second = write_model_index(
        list(reversed(canonical)),
        tmp_path / "_site",
        generated_at,
        shard_size=2_000,
    )
    second_bytes = {
        path.relative_to(tmp_path / "_site").as_posix(): path.read_bytes()
        for path in sorted((tmp_path / "_site" / "data").rglob("*.json"))
    }

    assert first == second
    assert first.total == len(canonical)
    assert [shard.count for shard in first.shards] == [2_000] * 10 + [1]
    assert first_bytes == second_bytes
    rows = []
    for shard in first.shards:
        payload = json.loads((tmp_path / "_site" / shard.path).read_text())
        assert len(payload["items"]) == shard.count
        rows.extend(payload["items"])
    assert len(rows) == len(canonical)
    assert len({row["release_id"] for row in rows}) == len(canonical)
    assert rows[0]["release_id"] == canonical[-1].id
    assert rows[0]["source_url"].startswith("https://huggingface.co/")


def test_model_index_uses_claim_metadata_for_release_time_rank_and_facets(
    tmp_path,
) -> None:
    repository = lifecycle_repository(tmp_path)
    seed_recommendable_release(repository)
    release = repository.list_all_releases()[0]
    evidence = EvidenceObservation(
        id="evidence:index-metadata",
        source_url="https://huggingface.co/moonshotai/Kimi-K3",
        strength=EvidenceStrength.TRUSTED_REGISTRY,
        retrieved_at=datetime(2026, 8, 3, 8, tzinfo=UTC),
        checksum="index-metadata",
        extractor_version="test",
    )
    repository.append_evidence(evidence)
    for predicate, value in (
        ("hf_repo", "moonshotai/Kimi-K3"),
        ("last_modified", "2026-08-03T07:55:00Z"),
        ("downloads", 12_345),
        ("likes", 678),
        ("license", "modified-mit"),
        ("hardware_tier", "4x H100 80GB"),
        ("pipeline_tag", "image-text-to-text"),
    ):
        repository.append_claim(
            Claim(
                id=f"claim:index:{predicate}",
                subject_id=release.id,
                predicate=predicate,
                value=value,
                state=ClaimState.CANDIDATE,
                observed_at=evidence.retrieved_at,
                evidence_ids=[evidence.id],
            )
        )

    manifest = write_model_index(
        repository.list_all_releases(),
        tmp_path / "_site",
        datetime(2026, 8, 3, 8, 15, tzinfo=UTC),
        repository=repository,
    )
    payload = json.loads((tmp_path / "_site" / manifest.shards[0].path).read_text())
    item = payload["items"][0]

    assert item["released_at"] == "2026-08-03T07:55:00Z"
    assert item["profile"]["publisher"] == release.publisher_id
    assert item["profile"]["license"] == "modified-mit"
    assert item["profile"]["hardware_tier"] == "4x H100 80GB"
    assert item["profile"]["modality"] == "image-text-to-text"
    assert item["profile"]["hf_downloads"] == 12_345
    assert item["confidence"] > 0.8

    snapshot = build_public_snapshot(
        build_services(repository),
        datetime(2026, 8, 3, 8, 15, tzinfo=UTC),
    ).model_dump(mode="json")
    release_row = next(
        row for row in snapshot["releases"] if row["release_id"] == release.id
    )
    assert release_row["released_at"] == "2026-08-03T07:55:00Z"
    assert release_row["confidence"] > 0.8


def test_significance_ranks_official_root_above_fresh_popular_derivative(
    tmp_path,
) -> None:
    from radar.intelligence.contracts import (
        LineageEdge,
        LineageRelation,
        ProductFamily,
        Publisher,
    )

    repository = lifecycle_repository(tmp_path)
    root_release = repository.list_all_releases()[0]
    repository.upsert_publisher(
        Publisher(
            id="publisher:provisional:grearl",
            name="grearl",
            official_domains=[],
            official_accounts=["grearl"],
        )
    )
    repository.upsert_family(
        ProductFamily(
            id="family:provisional:grearl:kimi",
            publisher_id="publisher:provisional:grearl",
            name="Kimi",
        )
    )
    derivative = Release(
        id="release:provisional:grearl:kimi:k3:gguf",
        family_id="family:provisional:grearl:kimi",
        publisher_id="publisher:provisional:grearl",
        name="Kimi K3 GGUF",
        category=ModelCategory.MULTIMODAL,
        lane=ReleaseLane.DEPLOYABLE,
        lifecycle=LifecycleState.VERIFIED,
        first_observed_at=datetime(2026, 8, 3, 7, tzinfo=UTC),
        discovery_evidence_strength=EvidenceStrength.TRUSTED_REGISTRY,
    )
    repository.upsert_release(derivative)
    evidence = EvidenceObservation(
        id="evidence:lineage-metadata",
        source_url="https://huggingface.co/moonshotai/Kimi-K3",
        strength=EvidenceStrength.TRUSTED_REGISTRY,
        retrieved_at=datetime(2026, 8, 3, 8, tzinfo=UTC),
        checksum="lineage-metadata",
        extractor_version="test",
    )
    repository.append_evidence(evidence)
    claims = (
        # Root: checked base, older, modest downloads.
        (root_release.id, "hf_repo", "moonshotai/Kimi-K3"),
        (root_release.id, "last_modified", "2026-06-01T00:00:00Z"),
        (root_release.id, "downloads", 950_000),
        (root_release.id, "lineage_declared", []),
        # Derivative: freshly touched, far more downloads.
        (derivative.id, "hf_repo", "grearl/Kimi-K3-GGUF"),
        (derivative.id, "last_modified", "2026-08-03T07:55:00Z"),
        (derivative.id, "downloads", 5_000_000),
    )
    for index, (subject_id, predicate, value) in enumerate(claims):
        repository.append_claim(
            Claim(
                id=f"claim:lineage-rank:{index}",
                subject_id=subject_id,
                predicate=predicate,
                value=value,
                state=ClaimState.CANDIDATE,
                observed_at=evidence.retrieved_at,
                evidence_ids=[evidence.id],
            )
        )
    repository.upsert_lineage_edge(
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

    generated_at = datetime(2026, 8, 3, 9, tzinfo=UTC)
    manifest = write_model_index(
        repository.list_all_releases(),
        tmp_path / "_site",
        generated_at,
        repository=repository,
    )
    payload = json.loads((tmp_path / "_site" / manifest.shards[0].path).read_text())
    ordered_ids = [item["release_id"] for item in payload["items"]]
    assert ordered_ids.index(root_release.id) < ordered_ids.index(derivative.id)

    root_item = payload["items"][ordered_ids.index(root_release.id)]
    derived_item = payload["items"][ordered_ids.index(derivative.id)]
    assert root_item["significance"]["class"] == "official_root"
    assert root_item["is_official"] is True
    assert root_item["lineage"]["root_release"] == root_release.id
    assert root_item["lineage"]["derivative_counts"] == {"quantized": 1}
    assert derived_item["significance"]["class"] == "declared_derivative"
    assert derived_item["is_official"] is False
    assert derived_item["lineage"] == {
        "base_release": root_release.id,
        "relation": "quantized",
        "root_release": root_release.id,
        "derivative_counts": None,
    }
    assert any(
        factor.startswith("class ")
        for factor in root_item["significance"]["factors"]
    )

    snapshot = build_public_snapshot(
        build_services(repository),
        generated_at,
    ).model_dump(mode="json")
    model_ids = [row["release_id"] for row in snapshot["models"]]
    assert model_ids.index(root_release.id) < model_ids.index(derivative.id)
    derivative_row = next(
        row
        for row in snapshot["releases"]
        if row["release_id"] == derivative.id
    )
    assert derivative_row["lineage"]["relation"] == "quantized"
    assert derivative_row["lineage"]["root_release"] == root_release.id


def test_public_snapshot_exposes_latest_valid_digest(tmp_path, caplog) -> None:
    repository = lifecycle_repository(tmp_path)
    digest_path = tmp_path / "data" / "digest-log.jsonl"
    append_digest(
        digest_path,
        [
            DigestLogEntry(
                label="2026-W30",
                generated_at=datetime(2026, 7, 24, 8, tzinfo=UTC),
                url="digests/digest_2026-W30.html",
                summary="Week 30",
            ),
            DigestLogEntry(
                label="2026-W31",
                generated_at=datetime(2026, 7, 31, 8, tzinfo=UTC),
                url="digests/digest_2026-W31.html",
                summary="Week 31",
            ),
        ],
    )
    with digest_path.open("a", encoding="utf-8") as handle:
        handle.write("{malformed trailing record\n")
    card = tmp_path / "digests" / "cards" / "trending_og.png"
    card.parent.mkdir(parents=True)
    card.write_bytes(b"png")

    with caplog.at_level(logging.WARNING):
        snapshot = build_public_snapshot(
            build_services(repository),
            datetime(2026, 7, 31, 9, tzinfo=UTC),
            root=tmp_path,
        )

    assert snapshot.latest_digest == {
        "generated_at": "2026-07-31T08:00:00Z",
        "html_url": "digests/digest_2026-W31.html",
        "card_url": "digests/cards/trending_og.png",
    }
    assert "Skipping corrupt digest-log line" in caplog.text


def test_public_snapshot_restores_projects_and_fresh_hf_candidates(
    tmp_path,
) -> None:
    repository = lifecycle_repository(tmp_path)
    database = RadarDatabase(tmp_path / "data" / "radar.db")
    database.initialize()
    database.upsert_cards(
        [
            DecisionCard(
                project="vLLM",
                category=Category.MODEL_SERVING,
                ring=Ring.ADOPT,
                score=4.7,
                summary="High-throughput model serving engine.",
                workflow_fit={"serving": "strong"},
                risk_level="medium",
                why_it_matters="Production-grade throughput and broad model support.",
                on_prem_fit="Strong fit for GPU clusters.",
                evidence=["https://github.com/vllm-project/vllm"],
                try_this_week=["Run a representative throughput benchmark."],
                last_reviewed_at=datetime(2026, 7, 31, 8, 0, tzinfo=UTC),
            )
        ]
    )
    append_model_candidates(
        tmp_path / "data" / "model-candidate-observations.jsonl",
        [
            ModelCandidateObservation(
                hf_repo="moonshotai/Kimi-K3",
                name="Kimi-K3",
                family="moonshotai",
                downloads=2_000,
                likes=4_000,
                pipeline_tag="image-text-to-text",
                created_at="2026-07-28T08:00:00Z",
                last_modified="2026-07-31T02:00:00Z",
                observed_at=datetime(2026, 7, 31, 3, 0, tzinfo=UTC),
            ),
            ModelCandidateObservation(
                hf_repo="moonshotai/Kimi-K3",
                name="Kimi-K3",
                family="moonshotai",
                downloads=2_850,
                likes=4_860,
                pipeline_tag="image-text-to-text",
                created_at="2026-07-28T08:00:00Z",
                last_modified="2026-07-31T07:58:00Z",
                observed_at=datetime(2026, 7, 31, 8, 0, tzinfo=UTC),
            )
        ],
    )

    snapshot = build_public_snapshot(
        build_services(repository),
        datetime(2026, 7, 31, 8, 15, tzinfo=UTC),
        root=tmp_path,
    ).model_dump(mode="json")

    assert snapshot["projects"][0]["project"] == "vLLM"
    assert snapshot["projects"][0]["repository_url"] == (
        "https://github.com/vllm-project/vllm"
    )
    assert snapshot["model_candidates"][0]["hf_repo"] == "moonshotai/Kimi-K3"
    kimi = next(item for item in snapshot["models"] if item["name"] == "Kimi-K3")
    assert kimi["lifecycle"] == "detected"
    assert kimi["category"] == "multimodal"
    assert kimi["source_url"] == "https://huggingface.co/moonshotai/Kimi-K3"
    assert any(item["name"] == "Kimi-K3" for item in snapshot["releases"])
    assert next(
        item for item in snapshot["releases"] if item["name"] == "Kimi-K3"
    )["freshness"] == "fresh"
    kimi_release = next(
        item for item in snapshot["releases"] if item["name"] == "Kimi-K3"
    )
    assert kimi_release["released_at"] == "2026-07-31T07:58:00Z"
    assert kimi_release["age_hours"] == pytest.approx(17 / 60)
    assert kimi_release["confidence"] > 0.8


def test_public_source_health_treats_recent_empty_fetch_as_success(tmp_path) -> None:
    observed_at = datetime(2026, 8, 3, 8, tzinfo=UTC)
    append_source_health(
        tmp_path / "data" / "source-health.jsonl",
        SourceHealthRecord(
            run_id="run:empty",
            observed_at=observed_at,
            sources={
                "rss-ollama-blog": SourceOutcome(count=0, status="empty"),
            },
        ),
    )

    from radar.web.public_context import load_public_source_health

    health = load_public_source_health(
        tmp_path,
        now=observed_at + timedelta(hours=3),
    )[0]

    assert health["status"] == "empty"
    assert health["consecutive_failures"] == 0
    assert health["last_success_at"] == observed_at.isoformat()


def test_candidate_projection_reserves_space_for_new_low_download_releases(
    tmp_path,
) -> None:
    observed_at = datetime(2026, 7, 31, 8, 0, tzinfo=UTC)
    rows = [
        ModelCandidateObservation(
            hf_repo=f"popular/model-{index}",
            name=f"model-{index}",
            family="popular",
            downloads=1_000_000 - index,
            observed_at=observed_at,
            last_modified="2026-07-30T08:00:00Z",
        )
        for index in range(230)
    ]
    rows.append(
        ModelCandidateObservation(
            hf_repo="moonshotai/Kimi-K3",
            name="Kimi-K3",
            family="moonshotai",
            downloads=1,
            pipeline_tag="image-text-to-text",
            observed_at=observed_at,
            last_modified="2026-07-31T07:59:00Z",
        )
    )
    append_model_candidates(
        tmp_path / "data" / "model-candidate-observations.jsonl",
        rows,
    )

    from radar.web.public_context import load_public_model_candidates

    projected = load_public_model_candidates(
        tmp_path,
        datetime(2026, 7, 31, 8, 15, tzinfo=UTC),
    )

    assert any(item["hf_repo"] == "moonshotai/Kimi-K3" for item in projected)


def test_curated_model_fallback_is_explicitly_labeled(tmp_path) -> None:
    from radar.web.public_context import load_public_model_profiles

    config = tmp_path / "config"
    config.mkdir()
    shutil.copy2("config/model-seed.yaml", config / "model-seed.yaml")

    profiles = load_public_model_profiles(tmp_path)

    assert profiles
    assert all(
        "Curated seed baseline; scan enrichment is pending"
        in profile["warnings"]
        for profile in profiles.values()
    )


def test_profiles_carry_tenure_and_download_series_from_metrics(tmp_path) -> None:
    from radar.storage.model_metrics_store import ModelMetrics, ModelMetricsStore
    from radar.web.public_context import load_public_model_profiles

    (tmp_path / "data" / "runs" / "run-1").mkdir(parents=True)
    (tmp_path / "data" / "runs" / "run-1" / "meta.json").write_text(
        '{"run_id": "run-1", "kind": "models"}'
    )
    (tmp_path / "data" / "runs" / "run-1" / "model_cards.json").write_text(
        '[{"id": "kimi-k3", "name": "Kimi K3", "family": "Kimi", "ring": "adopt"}]'
    )
    store = ModelMetricsStore(tmp_path / "data" / "radar.db")
    store.initialize()
    store.record(
        [
            ModelMetrics(
                model_id="kimi-k3",
                run_id=f"run-{day}",
                observed_at=datetime(2026, 7, day, 8, tzinfo=UTC),
                downloads=downloads,
            )
            for day, downloads in ((1, 1000), (2, 1500), (3, None), (4, 2400))
        ]
    )

    profiles = load_public_model_profiles(tmp_path)

    profile = profiles["kimi-k3"]
    assert profile["first_tracked_at"].startswith("2026-07-01")
    assert [point["downloads"] for point in profile["downloads_history"]] == [
        1000,
        1500,
        2400,
    ]


def test_planner_grid_matches_the_fit_engine_verbatim(tmp_path) -> None:
    from radar.mcp_server.model_queries import ModelQueryService

    (tmp_path / "data" / "runs" / "run-1").mkdir(parents=True)
    (tmp_path / "data" / "runs" / "run-1" / "meta.json").write_text(
        '{"run_id": "run-1", "kind": "models"}'
    )
    (tmp_path / "data" / "runs" / "run-1" / "model_cards.json").write_text(
        json.dumps(
            [
                {
                    "id": "kimi-k3-mini",
                    "name": "Kimi K3 Mini",
                    "family": "Kimi",
                    "params_total": 8_000_000_000,
                    "num_layers": 32,
                    "hidden_size": 4096,
                    "context_length": 32768,
                    "quants": [
                        {
                            "format": "GGUF Q4_K_M",
                            "bits_per_weight": 4.5,
                            "source": "manual",
                        }
                    ],
                }
            ]
        )
    )
    repository = lifecycle_repository(tmp_path)

    snapshot = build_public_snapshot(
        build_services(repository),
        datetime(2026, 8, 4, 10, tzinfo=UTC),
        root=tmp_path,
    ).model_dump(mode="json")

    planner = snapshot["planner"]
    assert planner["context_tokens"] == 4096
    assert set(planner["devices"]) >= {"rtx-4090-24gb", "h100-80gb"}
    row = next(
        fit
        for fit in planner["fits"]
        if fit["device"] == "rtx-4090-24gb"
        and fit["model_id"] == "kimi-k3-mini"
    )
    # Golden parity: the grid is a projection of the same engine the CLI
    # and MCP answer from — byte-for-byte identical verdicts.
    golden = ModelQueryService(tmp_path).can_run(
        "kimi-k3-mini",
        "rtx-4090-24gb",
        4096,
    )
    assert golden is not None
    assert {key: row[key] for key in golden} == golden
    assert row["verdict"] in {
        "fits",
        "fits_tight",
        "fits_quantized",
        "wont_fit",
        "unknown",
    }


def test_trending_section_builds_windows_and_star_series(tmp_path) -> None:
    lines = []
    for day, stars in ((1, 100), (5, 400), (9, 900), (12, 1600)):
        lines.append(
            json.dumps(
                {
                    "repo": "acme/fast-llm",
                    "lane": "onprem",
                    "stars": stars,
                    "observed_at": f"2026-08-{day:02d}T08:00:00Z",
                    "repo_created_at": "2026-08-01T00:00:00Z",
                    "description": "Fast local inference",
                    "topics": ["llm", "inference"],
                    "license": "MIT",
                }
            )
        )
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "trending-observations.jsonl").write_text(
        "\n".join(lines) + "\n"
    )
    repository = lifecycle_repository(tmp_path)

    snapshot = build_public_snapshot(
        build_services(repository),
        datetime(2026, 8, 12, 12, tzinfo=UTC),
        root=tmp_path,
    ).model_dump(mode="json")

    trending = snapshot["trending"]
    assert set(trending["windows"]) == {"7d", "30d", "90d"}
    row = trending["windows"]["7d"][0]
    assert row["repo"] == "acme/fast-llm"
    assert row["url"] == "https://github.com/acme/fast-llm"
    assert row["velocity_per_day"] is not None and row["velocity_per_day"] > 0
    assert row["is_new"] is True
    series = trending["series"]["acme/fast-llm"]
    # 14-day sparkline window: the day-1 point (11 days before generated_at
    # is inside; all four observations qualify).
    assert [point["stars"] for point in series] == [100, 400, 900, 1600]


def test_newsroom_joins_classifications_and_counts_impacts(tmp_path) -> None:
    (tmp_path / "data").mkdir()
    items = [
        {
            "id": "news:aaaa",
            "source_id": "vllm-blog",
            "title": "vLLM v0.10 released",
            "url": "https://blog.vllm.ai/v0-10",
            "summary": "Release notes",
            "published_at": "2026-08-10T08:00:00Z",
            "observed_at": "2026-08-10T09:00:00Z",
        },
        {
            "id": "news:bbbb",
            "source_id": "hn-ollama",
            "title": "Random consumer story",
            "url": "https://example.com/noise",
            "summary": None,
            "published_at": "2026-08-11T08:00:00Z",
            "observed_at": "2026-08-11T09:00:00Z",
        },
        {
            "id": "news:cccc",
            "source_id": "hn-ollama",
            "title": "Not yet classified",
            "url": "https://example.com/pending",
            "summary": None,
            "published_at": "2026-08-12T08:00:00Z",
            "observed_at": "2026-08-12T09:00:00Z",
        },
    ]
    (tmp_path / "data" / "news-observations.jsonl").write_text(
        "\n".join(json.dumps(item) for item in items) + "\n"
    )
    classifications = [
        {
            "news_id": "news:aaaa",
            "relevant": True,
            "event_type": "release",
            "components": ["vllm"],
            "operational_impact": "breaking",
            "summary": "V1 engine default changed; operators must repin.",
            "citation": "https://blog.vllm.ai/v0-10",
            "model": "claude-opus-5",
            "classified_at": "2026-08-12T10:00:00Z",
        },
        {
            "news_id": "news:bbbb",
            "relevant": False,
            "event_type": "other",
            "components": [],
            "operational_impact": "informational",
            "summary": "Consumer noise.",
            "citation": "https://example.com/noise",
            "model": "claude-opus-5",
            "classified_at": "2026-08-12T10:00:00Z",
        },
    ]
    (tmp_path / "data" / "news-classified.jsonl").write_text(
        "\n".join(json.dumps(row) for row in classifications) + "\n"
    )
    repository = lifecycle_repository(tmp_path)

    snapshot = build_public_snapshot(
        build_services(repository),
        datetime(2026, 8, 12, 12, tzinfo=UTC),
        root=tmp_path,
    ).model_dump(mode="json")

    newsroom = snapshot["newsroom"]
    # Newest first; irrelevant + pending items carry no classification.
    assert [row["id"] for row in newsroom["items"]] == [
        "news:cccc",
        "news:bbbb",
        "news:aaaa",
    ]
    assert newsroom["items"][0]["classification"] is None
    assert newsroom["items"][1]["classification"] is None
    classified = newsroom["items"][2]["classification"]
    assert classified["operational_impact"] == "breaking"
    assert classified["components"] == ["vllm"]
    assert newsroom["counts"] == {
        "total": 3,
        "classified": 1,
        "unclassified": 2,
        "breaking": 1,
        "improvement": 0,
        "informational": 0,
    }
    assert "release" in newsroom["event_types"]


def test_stack_demo_diffs_events_against_the_demo_profile(tmp_path) -> None:
    (tmp_path / "data").mkdir()
    items = [
        {
            "id": "news:vllm-break",
            "source_id": "vllm-blog",
            "title": "vLLM drops V0 engine",
            "url": "https://blog.vllm.ai/v0-removal",
            "summary": "V0 removed",
            "published_at": "2026-08-10T09:00:00Z",
            "observed_at": "2026-08-10T10:00:00Z",
        },
        {
            "id": "news:sglang-break",
            "source_id": "hn-vllm",
            "title": "SGLang breaking scheduler change",
            "url": "https://example.com/sglang",
            "summary": "Rewrite",
            "published_at": "2026-08-10T09:00:00Z",
            "observed_at": "2026-08-10T10:00:00Z",
        },
    ]
    (tmp_path / "data" / "news-observations.jsonl").write_text(
        "\n".join(json.dumps(item) for item in items) + "\n"
    )
    classifications = [
        {
            "news_id": "news:vllm-break",
            "relevant": True,
            "event_type": "breaking-change",
            "components": ["vllm"],
            "operational_impact": "breaking",
            "summary": "V0 removed; migrate.",
            "citation": "https://blog.vllm.ai/v0-removal",
            "model": "claude-opus-5",
            "classified_at": "2026-08-11T10:00:00Z",
        },
        {
            "news_id": "news:sglang-break",
            "relevant": True,
            "event_type": "breaking-change",
            "components": ["sglang"],
            "operational_impact": "breaking",
            "summary": "Scheduler rewrite.",
            "citation": "https://example.com/sglang",
            "model": "claude-opus-5",
            "classified_at": "2026-08-11T10:00:00Z",
        },
    ]
    (tmp_path / "data" / "news-classified.jsonl").write_text(
        "\n".join(json.dumps(row) for row in classifications) + "\n"
    )
    repository = lifecycle_repository(tmp_path)

    snapshot = build_public_snapshot(
        build_services(repository),
        datetime(2026, 8, 12, 12, tzinfo=UTC),
        root=tmp_path,
    ).model_dump(mode="json")

    demo = snapshot["stack_demo"]
    assert demo["profile"]["name"].startswith("Mega")
    assert demo["profile"]["stack"]["engines"]
    ids = [alert["id"] for alert in demo["alerts"]["alerts"]]
    # vLLM is in the demo stack → Act alert; SGLang is not → silence.
    assert "alert:news:news:vllm-break" in ids
    assert "alert:news:news:sglang-break" not in ids
    assert demo["alerts"]["alerts"][0]["verdict"] == "act"


def test_profiles_attach_triangulated_benchmark_aggregates(tmp_path) -> None:
    import shutil as shutil_module

    from radar.storage.benchmark_observations_log import (
        BenchmarkObservation,
        append_benchmark_observations,
    )
    from radar.web.public_context import load_public_model_profiles

    (tmp_path / "config").mkdir()
    shutil_module.copy2(
        "config/model-seed.yaml", tmp_path / "config" / "model-seed.yaml"
    )
    shutil_module.copy2(
        "config/benchmark-sources.yaml",
        tmp_path / "config" / "benchmark-sources.yaml",
    )
    append_benchmark_observations(
        tmp_path / "data" / "benchmark-observations.jsonl",
        [
            BenchmarkObservation(
                model_id="deepseek-r1",
                hf_repo="deepseek-ai/DeepSeek-R1",
                benchmark="mmlu-pro",
                score=75.0,
                source_id="open-llm-leaderboard",
                source_url="https://ollb.example",
                observed_at=datetime(2026, 8, 4, 8, tzinfo=UTC),
            )
        ],
    )

    profiles = load_public_model_profiles(tmp_path)

    aggregates = {
        row["benchmark"]: row
        for row in profiles["deepseek-r1"]["benchmark_aggregates"]
    }
    mmlu_pro = aggregates["mmlu-pro"]
    # Independent 75.0 vs the card's self-reported 84.0 → gap 9.0, flagged.
    assert mmlu_pro["consensus"] == 75.0
    assert mmlu_pro["self_reported_gap"] == 9.0
    assert mmlu_pro["flagged"] is True
    assert {score["source_id"] for score in mmlu_pro["scores"]} == {
        "open-llm-leaderboard",
        "model-card",
    }
    # Card-only benchmarks surface too (self-reported channel).
    assert aggregates["gpqa-diamond"]["scores"][0]["self_reported"] is True
    # A model with no data has no aggregates key at all.
    assert "benchmark_aggregates" not in profiles["qwen3-8b"]


def test_platform_reverification_is_repeatable_and_failure_marks_current_claim_stale(
    tmp_path,
) -> None:
    repository = lifecycle_repository(tmp_path)
    platform_id = "platform:legacy:vllm"
    payload = {"hardware": {"nvidia": "yes"}}
    repository.import_platform(
        platform_id=platform_id,
        name="vLLM",
        repo_url="https://github.com/vllm-project/vllm",
        verified_at="2026-07-29",
        payload=payload,
    )
    initial = EvidenceObservation(
        id="evidence:platform:initial",
        source_url="https://docs.vllm.ai/",
        strength=EvidenceStrength.OFFICIAL_DOCUMENTATION,
        retrieved_at=datetime(2026, 7, 29, tzinfo=UTC),
        checksum="initial",
        extractor_version="test",
    )
    repository.append_evidence(initial)
    repository.append_claim(
        Claim(
            id="claim:platform:nvidia",
            subject_id=platform_id,
            predicate="hardware.nvidia",
            value="yes",
            state=ClaimState.VERIFIED,
            observed_at=initial.retrieved_at,
            evidence_ids=[initial.id],
        )
    )
    refreshed = EvidenceObservation(
        id="evidence:platform:refresh",
        source_url="https://docs.vllm.ai/",
        strength=EvidenceStrength.OFFICIAL_DOCUMENTATION,
        retrieved_at=datetime(2026, 7, 31, 8, tzinfo=UTC),
        checksum="fresh",
        extractor_version="test",
    )
    repository.append_evidence(refreshed)
    repository.record_platform_verification(
        platform_id,
        refreshed.retrieved_at,
        evidence_id=refreshed.id,
        success=True,
    )

    assert repository.count_stale_claims() == 0
    assert repository.import_platform(
        platform_id=platform_id,
        name="vLLM",
        repo_url="https://github.com/vllm-project/vllm",
        verified_at="2026-07-29",
        payload=payload,
    ) is False
    repository.record_platform_verification(
        platform_id,
        datetime(2026, 7, 31, 10, tzinfo=UTC),
        evidence_id=refreshed.id,
        success=True,
    )
    assert repository.count_stale_claims() == 0
    repository.record_platform_verification(
        platform_id,
        datetime(2026, 7, 31, 12, tzinfo=UTC),
        evidence_id=None,
        success=False,
    )
    assert repository.count_stale_claims() == 1
