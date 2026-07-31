import json
import logging
from datetime import UTC, datetime

from intelligence.lifecycle_helpers import lifecycle_repository
from intelligence.test_recommendations import seed_recommendable_release
from radar.intelligence.contracts import (
    Claim,
    ClaimState,
    EvidenceObservation,
    EvidenceStrength,
)
from radar.intelligence.services.container import build_services
from radar.models import Category, DecisionCard, Ring
from radar.storage.database import RadarDatabase
from radar.storage.digest_log import DigestLogEntry, append_digest
from radar.storage.model_candidate_log import (
    ModelCandidateObservation,
    append_model_candidates,
)
from radar.web.intelligence_snapshot import (
    build_public_snapshot,
    write_public_snapshot,
)


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
    }
    assert payload["platforms"][0]["name"] == "vLLM"
    assert payload["platforms"][0]["hardware"] == {}
    assert payload["platforms"][0]["sources"] == [
        "https://github.com/vllm-project/vllm"
    ]
    assert payload["platforms"][0]["verification_status"] == "stale"
    assert payload["source_health"]["stale_claim_count"] >= 1
    assert payload["hardware"]
    assert "workspace" not in first.decode().casefold()


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
