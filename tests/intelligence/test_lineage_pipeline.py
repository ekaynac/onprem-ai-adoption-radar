"""End-to-end lineage: discover → edges → roots, enrichment, and backfill."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest

from radar.intelligence.contracts import (
    EvidenceStrength,
    LifecycleState,
    LineageEdge,
    LineageRelation,
    LineageReviewStatus,
    ModelCategory,
    ProductFamily,
    Publisher,
    Release,
    ReleaseLane,
)
from radar.intelligence.database import Database
from radar.intelligence.jobs import JobKind
from radar.intelligence.lineage import (
    REVIEW_CODE_UNRESOLVED_PARENT,
)
from radar.intelligence.pipeline import (
    IntelligenceJobRunner,
    run_lineage_backfill,
)
from radar.intelligence.repositories import SqlAlchemyIntelligenceRepository
from radar.intelligence.sources.base import DiscoveryCandidate, SourceRecord


NOW = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)


def make_record(url: str, body: bytes) -> SourceRecord:
    return SourceRecord.from_bytes(
        source_id="fixture",
        url=url,
        body=body,
        retrieved_at=NOW,
        strength=EvidenceStrength.TRUSTED_REGISTRY,
        content_type="application/json",
    )


def make_candidate(
    repo: str,
    publisher_hint: str,
    name: str,
    *,
    lineage: list[dict[str, str | None]] | None = None,
) -> DiscoveryCandidate:
    claims: dict[str, object] = {"repo_id": repo, "license": "mit"}
    if lineage is not None:
        claims["lineage_declared"] = lineage
    return DiscoveryCandidate(
        source_record=make_record(
            f"https://huggingface.co/api/models/{repo}",
            b'{"id":"' + repo.encode() + b'"}',
        ),
        external_id=repo,
        publisher_hint=publisher_hint,
        release_name=name,
        category_hint=ModelCategory.MULTIMODAL,
        artifact_urls=[f"https://huggingface.co/{repo}"],
        claims=claims,
    )


class LineageDiscoveryAdapter:
    id = "fixture"

    def __init__(self, candidates: list[DiscoveryCandidate]):
        self.candidates = candidates

    async def discover(self, since: datetime) -> list[DiscoveryCandidate]:
        del since
        return self.candidates

    async def fetch(self, url: str) -> SourceRecord:
        raise NotImplementedError


def repository(tmp_path) -> SqlAlchemyIntelligenceRepository:
    (tmp_path / "data").mkdir(exist_ok=True)
    database = Database(f"sqlite:///{tmp_path / 'data' / 'intelligence.db'}")
    database.create_schema()
    repo = SqlAlchemyIntelligenceRepository(database)
    repo.upsert_publisher(
        Publisher(
            id="publisher:moonshot-ai",
            name="Moonshot AI",
            official_domains=["moonshot.ai"],
            official_accounts=["moonshotai"],
            aliases=["Moonshot"],
        )
    )
    repo.upsert_family(
        ProductFamily(
            id="family:moonshot-ai:kimi",
            publisher_id="publisher:moonshot-ai",
            name="Kimi",
            aliases=["Kimi"],
        )
    )
    return repo


@pytest.mark.asyncio
async def test_discovery_builds_resolved_lineage_edges(tmp_path) -> None:
    repo = repository(tmp_path)
    runner = IntelligenceJobRunner(
        root=tmp_path,
        repository=repo,
        adapters=[
            LineageDiscoveryAdapter(
                [
                    make_candidate(
                        "moonshotai/Kimi-K3",
                        "publisher:moonshot-ai",
                        "Kimi K3",
                    ),
                    make_candidate(
                        "grearl/Kimi-K3-GGUF",
                        "provisional:grearl",
                        "Kimi K3 GGUF",
                        lineage=[
                            {
                                "parent_repo": "moonshotai/Kimi-K3",
                                "relation": "quantized",
                                "via": "tags",
                            }
                        ],
                    ),
                ]
            )
        ],
        clock=lambda: NOW,
    )

    result = await runner.run(JobKind.DISCOVERY, "job:test")

    assert result.created == 2
    releases = {release.name: release for release in repo.list_all_releases()}
    base = releases["Kimi K3"]
    edges = repo.list_all_lineage_edges()
    assert len(edges) == 1
    edge = edges[0]
    assert edge.parent_external_ref == "hf:moonshotai/Kimi-K3"
    assert edge.parent_release_id == base.id
    assert edge.root_release_id == base.id
    assert edge.relation is LineageRelation.QUANTIZED
    assert edge.declared is True
    assert edge.evidence_ids
    assert edge.review_status is LineageReviewStatus.CLEAR


@pytest.mark.asyncio
async def test_discovery_opens_review_for_unresolvable_parent(tmp_path) -> None:
    repo = repository(tmp_path)
    runner = IntelligenceJobRunner(
        root=tmp_path,
        repository=repo,
        adapters=[
            LineageDiscoveryAdapter(
                [
                    make_candidate(
                        "grearl/Kimi-K3-GGUF",
                        "provisional:grearl",
                        "Kimi K3 GGUF",
                        lineage=[
                            {
                                "parent_repo": "ghost/Never-Seen",
                                "relation": "quantized",
                                "via": "tags",
                            }
                        ],
                    ),
                ]
            )
        ],
        clock=lambda: NOW,
    )

    await runner.run(JobKind.DISCOVERY, "job:test")

    edge = repo.list_all_lineage_edges()[0]
    assert edge.parent_release_id is None
    assert edge.root_release_id is None
    assert edge.review_status is LineageReviewStatus.OPEN
    reviews = repo.list_review_exceptions(open_only=True)
    assert [review.code for review in reviews] == [
        REVIEW_CODE_UNRESOLVED_PARENT
    ]

    # A later discovery of the missing parent heals the edge on next sync.
    healing = IntelligenceJobRunner(
        root=tmp_path,
        repository=repo,
        adapters=[
            LineageDiscoveryAdapter(
                [
                    make_candidate(
                        "ghost/Never-Seen",
                        "provisional:ghost",
                        "Never Seen",
                    ),
                    make_candidate(
                        "grearl/Kimi-K3-GGUF",
                        "provisional:grearl",
                        "Kimi K3 GGUF",
                        lineage=[
                            {
                                "parent_repo": "ghost/Never-Seen",
                                "relation": "quantized",
                                "via": "tags",
                            }
                        ],
                    ),
                ]
            )
        ],
        clock=lambda: NOW,
    )
    await healing.run(JobKind.DISCOVERY, "job:heal")

    edge = repo.list_all_lineage_edges()[0]
    assert edge.parent_release_id is not None
    assert edge.root_release_id == edge.parent_release_id
    assert edge.review_status is LineageReviewStatus.CLEAR
    assert repo.list_review_exceptions(open_only=True) == []


@pytest.mark.asyncio
async def test_enrichment_ingests_api_declared_lineage(tmp_path) -> None:
    repo = repository(tmp_path)
    release = Release(
        id="release:provisional-grearl:kimi:k3:gguf",
        family_id="family:moonshot-ai:kimi",
        publisher_id="publisher:moonshot-ai",
        name="Kimi K3 GGUF",
        category=ModelCategory.MULTIMODAL,
        lane=ReleaseLane.DEPLOYABLE,
        lifecycle=LifecycleState.VERIFIED,
        first_observed_at=NOW,
        discovery_evidence_strength=EvidenceStrength.TRUSTED_REGISTRY,
    )
    base = Release(
        id="release:moonshot-ai:kimi:k3",
        family_id="family:moonshot-ai:kimi",
        publisher_id="publisher:moonshot-ai",
        name="Kimi K3",
        category=ModelCategory.MULTIMODAL,
        lane=ReleaseLane.DEPLOYABLE,
        lifecycle=LifecycleState.VERIFIED,
        first_observed_at=NOW,
        discovery_evidence_strength=EvidenceStrength.TRUSTED_REGISTRY,
    )
    repo.upsert_release(base)
    repo.upsert_release(release)

    class EnrichAdapter:
        id = "fixture"

        async def discover(self, since: datetime):
            return []

        async def fetch(self, url: str) -> SourceRecord:
            raise NotImplementedError

        async def enrich(self, repo_id: str):
            record = make_record(
                f"https://huggingface.co/api/models/{repo_id}",
                b"{}",
            )
            return SimpleNamespace(
                records=[SimpleNamespace(source_record=record)],
                claims={
                    "library_name": "transformers",
                    "lineage_declared": [
                        {
                            "parent_repo": "moonshotai/Kimi-K3",
                            "relation": "quantized",
                            "via": "api",
                        }
                    ],
                },
                artifact_urls=[],
            )

    runner = IntelligenceJobRunner(
        root=tmp_path,
        repository=repo,
        adapters=[EnrichAdapter()],
        clock=lambda: NOW,
    )
    evidence = runner._persist_source_record(
        make_record("https://huggingface.co/grearl/Kimi-K3-GGUF", b"{}")
    )
    runner._append_claim(release.id, "hf_repo", "grearl/Kimi-K3-GGUF", evidence)
    runner._append_claim(base.id, "hf_repo", "moonshotai/Kimi-K3", evidence)

    await runner.run(JobKind.ENRICHMENT, "job:enrich")

    edges = repo.list_lineage_for_child(release.id)
    assert len(edges) == 1
    assert edges[0].parent_release_id == base.id
    assert edges[0].root_release_id == base.id
    assert edges[0].confidence == 0.95


@pytest.mark.asyncio
async def test_enrichment_prioritizes_roots_over_their_derivatives(
    tmp_path,
) -> None:
    """Same attempt band, same publisher: the root with descendants leads,
    the declared derivative waits."""
    repo = repository(tmp_path)
    base = Release(
        id="release:moonshot-ai:kimi:k3",
        family_id="family:moonshot-ai:kimi",
        publisher_id="publisher:moonshot-ai",
        name="Kimi K3",
        category=ModelCategory.MULTIMODAL,
        lane=ReleaseLane.DEPLOYABLE,
        lifecycle=LifecycleState.VERIFIED,
        first_observed_at=NOW,
        discovery_evidence_strength=EvidenceStrength.TRUSTED_REGISTRY,
    )
    derivative = base.model_copy(
        update={
            "id": "release:moonshot-ai:kimi:k3:gguf",
            "name": "Kimi K3 GGUF",
            # More recent: would win under pure recency ordering.
            "first_observed_at": NOW.replace(hour=13),
        }
    )
    repo.upsert_release(base)
    repo.upsert_release(derivative)
    runner = IntelligenceJobRunner(root=tmp_path, repository=repo)
    evidence = runner._persist_source_record(
        make_record("https://huggingface.co/moonshotai/Kimi-K3", b"{}")
    )
    runner._append_claim(base.id, "hf_repo", "moonshotai/Kimi-K3", evidence)
    runner._append_claim(
        derivative.id, "hf_repo", "grearl/Kimi-K3-GGUF", evidence
    )
    repo.upsert_lineage_edge(
        LineageEdge(
            id=f"lineage:{derivative.id}:quantized:hf:moonshotai/kimi-k3",
            child_release_id=derivative.id,
            parent_external_ref="hf:moonshotai/Kimi-K3",
            parent_release_id=base.id,
            root_release_id=base.id,
            relation=LineageRelation.QUANTIZED,
            declared=True,
            confidence=0.95,
            evidence_ids=[evidence.id],
            extractor_version="test",
            observed_at=NOW,
        )
    )

    class RecordingAdapter:
        id = "fixture"

        def __init__(self) -> None:
            self.enriched: list[str] = []

        async def discover(self, since):
            return []

        async def fetch(self, url):
            raise NotImplementedError

        async def enrich(self, repo_id: str):
            self.enriched.append(repo_id)
            record = make_record(
                f"https://huggingface.co/api/models/{repo_id}", b"{}"
            )
            return SimpleNamespace(
                records=[SimpleNamespace(source_record=record)],
                claims={},
                artifact_urls=[],
            )

    adapter = RecordingAdapter()
    runner_with_adapter = IntelligenceJobRunner(
        root=tmp_path,
        repository=repo,
        adapters=[adapter],
        clock=lambda: NOW,
        enrichment_batch_size=1,
    )
    await runner_with_adapter.run(JobKind.ENRICHMENT, "job:priority")

    # Batch of one: the root is selected before its fresher derivative.
    assert adapter.enriched == ["moonshotai/Kimi-K3"]


@pytest.mark.asyncio
async def test_backfill_replays_stored_claims_and_fetches_unchecked(
    tmp_path,
) -> None:
    repo = repository(tmp_path)
    base = Release(
        id="release:moonshot-ai:kimi:k3",
        family_id="family:moonshot-ai:kimi",
        publisher_id="publisher:moonshot-ai",
        name="Kimi K3",
        category=ModelCategory.MULTIMODAL,
        lane=ReleaseLane.DEPLOYABLE,
        lifecycle=LifecycleState.VERIFIED,
        first_observed_at=NOW,
        discovery_evidence_strength=EvidenceStrength.TRUSTED_REGISTRY,
    )
    stored = base.model_copy(
        update={"id": "release:moonshot-ai:kimi:k3:awq", "name": "Kimi K3 AWQ"}
    )
    unchecked = base.model_copy(
        update={"id": "release:moonshot-ai:kimi:k3:gguf", "name": "Kimi K3 GGUF"}
    )
    for release in (base, stored, unchecked):
        repo.upsert_release(release)

    runner = IntelligenceJobRunner(root=tmp_path, repository=repo)
    evidence = runner._persist_source_record(
        make_record("https://huggingface.co/api/models/moonshotai/Kimi-K3", b"{}")
    )
    runner._append_claim(base.id, "hf_repo", "moonshotai/Kimi-K3", evidence)
    runner._append_claim(stored.id, "hf_repo", "moonshotai/Kimi-K3-AWQ", evidence)
    runner._append_claim(
        stored.id,
        "lineage_declared",
        [
            {
                "parent_repo": "moonshotai/Kimi-K3",
                "relation": "quantized",
                "via": "card",
            }
        ],
        evidence,
    )
    runner._append_claim(unchecked.id, "hf_repo", "grearl/Kimi-K3-GGUF", evidence)
    runner._append_claim(unchecked.id, "downloads", 120000, evidence)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params.get("expand") == "baseModels"
        if request.url.path.endswith("/grearl/Kimi-K3-GGUF"):
            return httpx.Response(
                200,
                json={
                    "id": "grearl/Kimi-K3-GGUF",
                    "baseModels": {
                        "relation": "quantized",
                        "models": [{"id": "moonshotai/Kimi-K3"}],
                    },
                },
                request=request,
            )
        return httpx.Response(
            200,
            json={"id": "moonshotai/Kimi-K3"},
            request=request,
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as client:
        report = await run_lineage_backfill(
            tmp_path,
            repo,
            fetch_limit=5,
            clock=lambda: NOW,
            client=client,
        )

    assert report["replayed_edges"] == 1
    # Both the derivative and the (parentless) base release get checked; the
    # base stores an empty lineage claim so it is never re-fetched.
    assert report["fetched"] == 2
    assert report["fetched_edges"] == 1
    assert report["edges_total"] == 2
    assert report["roots_resolved"] >= 2
    assert report["review_findings"] == 0
    for child in (stored.id, unchecked.id):
        edges = repo.list_lineage_for_child(child)
        assert edges[0].parent_release_id == base.id
        assert edges[0].root_release_id == base.id
    # The fetched response is now a stored claim: a re-run replays offline.
    rerun = await run_lineage_backfill(
        tmp_path, repo, fetch_limit=0, clock=lambda: NOW
    )
    assert rerun["edges_total"] == 2


@pytest.mark.asyncio
async def test_backfill_registers_out_of_index_parents(tmp_path) -> None:
    """A derivative whose declared parent was never discovered still resolves:

    the backfill fetches the parent repo, ingests it through the normal
    discovery path, and the chain closes — including the grandparent hop.
    """
    repo = repository(tmp_path)
    derivative = Release(
        id="release:provisional-grearl:kimi:k3:gguf",
        family_id="family:moonshot-ai:kimi",
        publisher_id="publisher:moonshot-ai",
        name="Kimi K3 GGUF",
        category=ModelCategory.MULTIMODAL,
        lane=ReleaseLane.DEPLOYABLE,
        lifecycle=LifecycleState.VERIFIED,
        first_observed_at=NOW,
        discovery_evidence_strength=EvidenceStrength.TRUSTED_REGISTRY,
    )
    repo.upsert_release(derivative)
    runner = IntelligenceJobRunner(root=tmp_path, repository=repo)
    evidence = runner._persist_source_record(
        make_record("https://huggingface.co/grearl/Kimi-K3-GGUF", b"{}")
    )
    runner._append_claim(
        derivative.id, "hf_repo", "grearl/Kimi-K3-GGUF", evidence
    )
    runner._append_claim(derivative.id, "downloads", 50000, evidence)

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.url.params.get("expand") == "baseModels":
            if path.endswith("/grearl/Kimi-K3-GGUF"):
                return httpx.Response(
                    200,
                    json={
                        "id": "grearl/Kimi-K3-GGUF",
                        "baseModels": {
                            "relation": "quantized",
                            "models": [{"id": "moonshotai/Kimi-K3"}],
                        },
                    },
                    request=request,
                )
            return httpx.Response(404, request=request)
        if path.endswith("/api/models/moonshotai/Kimi-K3"):
            return httpx.Response(
                200,
                json={
                    "id": "moonshotai/Kimi-K3",
                    "author": "moonshotai",
                    "pipeline_tag": "image-text-to-text",
                    "lastModified": "2026-07-30T08:15:00.000Z",
                    "downloads": 968000,
                    "likes": 9700,
                    "tags": [
                        "base_model:finetune:moonshotai/Kimi-K3-Base",
                    ],
                    "cardData": {"license": "modified-mit"},
                    "siblings": [{"rfilename": "model.safetensors"}],
                },
                request=request,
            )
        if path.endswith("/api/models/moonshotai/Kimi-K3-Base"):
            return httpx.Response(
                200,
                json={
                    "id": "moonshotai/Kimi-K3-Base",
                    "author": "moonshotai",
                    "pipeline_tag": "image-text-to-text",
                    "lastModified": "2026-07-29T08:15:00.000Z",
                    "downloads": 120000,
                    "likes": 800,
                    "tags": [],
                    "cardData": {"license": "modified-mit"},
                    "siblings": [{"rfilename": "model.safetensors"}],
                },
                request=request,
            )
        return httpx.Response(404, request=request)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as client:
        report = await run_lineage_backfill(
            tmp_path,
            repo,
            fetch_limit=5,
            clock=lambda: NOW,
            client=client,
        )

    assert report["parents_registered"] == 2
    assert report["review_findings"] == 0

    releases_by_repo = {}
    values = repo.latest_claim_values(
        [release.id for release in repo.list_all_releases()],
        {"hf_repo"},
    )
    for release_id, claims in values.items():
        releases_by_repo[claims.get("hf_repo")] = release_id
    base_id = releases_by_repo["moonshotai/Kimi-K3-Base"]
    parent_id = releases_by_repo["moonshotai/Kimi-K3"]

    derivative_edge = repo.list_lineage_for_child(derivative.id)[0]
    assert derivative_edge.parent_release_id == parent_id
    assert derivative_edge.root_release_id == base_id
    parent_edge = repo.list_lineage_for_child(parent_id)[0]
    assert parent_edge.parent_release_id == base_id
    assert parent_edge.root_release_id == base_id
    assert repo.list_review_exceptions(open_only=True) == []
    # The parentless grandparent is stamped as checked (confirmed base).
    base_lineage_claims = [
        claim
        for claim in repo.list_claims_for_subject(base_id)
        if claim.predicate == "lineage_declared"
    ]
    assert base_lineage_claims and base_lineage_claims[0].value == []


@pytest.mark.asyncio
async def test_backfill_deadline_stops_fetching_but_replays_and_syncs(
    tmp_path,
) -> None:
    """A rate-limited crawl must never stall publish: with the wall-clock
    budget already spent, network phases are skipped cleanly while stored
    claims still replay and roots still sync."""
    repo = repository(tmp_path)
    base = Release(
        id="release:moonshot-ai:kimi:k3",
        family_id="family:moonshot-ai:kimi",
        publisher_id="publisher:moonshot-ai",
        name="Kimi K3",
        category=ModelCategory.MULTIMODAL,
        lane=ReleaseLane.DEPLOYABLE,
        lifecycle=LifecycleState.VERIFIED,
        first_observed_at=NOW,
        discovery_evidence_strength=EvidenceStrength.TRUSTED_REGISTRY,
    )
    derived = base.model_copy(
        update={"id": "release:moonshot-ai:kimi:k3:awq", "name": "Kimi K3 AWQ"}
    )
    unchecked = base.model_copy(
        update={"id": "release:moonshot-ai:kimi:k3:gguf", "name": "Kimi K3 GGUF"}
    )
    for release in (base, derived, unchecked):
        repo.upsert_release(release)
    runner = IntelligenceJobRunner(root=tmp_path, repository=repo)
    evidence = runner._persist_source_record(
        make_record("https://huggingface.co/api/models/moonshotai/Kimi-K3", b"{}")
    )
    runner._append_claim(base.id, "hf_repo", "moonshotai/Kimi-K3", evidence)
    runner._append_claim(
        derived.id,
        "lineage_declared",
        [
            {
                "parent_repo": "moonshotai/Kimi-K3",
                "relation": "quantized",
                "via": "card",
            }
        ],
        evidence,
    )
    runner._append_claim(unchecked.id, "hf_repo", "grearl/Kimi-K3-GGUF", evidence)

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"no network calls past the deadline: {request.url}")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as client:
        report = await run_lineage_backfill(
            tmp_path,
            repo,
            fetch_limit=5,
            parent_limit=5,
            max_seconds=0,
            clock=lambda: NOW,
            client=client,
        )

    assert report["deadline_reached"] == 1
    assert report["fetched"] == 0
    assert report["parents_registered"] == 0
    # Offline work still completed — including the network-free Tier-3
    # name inference, which the deadline deliberately does not cap
    # (the -GGUF release gains its suggestion edge).
    assert report["replayed_edges"] == 1
    assert report["inferred_edges"] == 1
    assert report["edges_total"] == 2
    edges = repo.list_lineage_for_child(derived.id)
    assert edges[0].parent_release_id == base.id


@pytest.mark.asyncio
async def test_backfill_infers_name_parents_without_setting_roots(
    tmp_path,
) -> None:
    """Tier-3: a -GGUF repo with no declared lineage gets a suggestion
    edge (declared=False, confidence 0.5) that never sets a root."""
    repo = repository(tmp_path)
    base = Release(
        id="release:moonshot-ai:kimi:k3",
        family_id="family:moonshot-ai:kimi",
        publisher_id="publisher:moonshot-ai",
        name="Kimi K3",
        category=ModelCategory.MULTIMODAL,
        lane=ReleaseLane.DEPLOYABLE,
        lifecycle=LifecycleState.VERIFIED,
        first_observed_at=NOW,
        discovery_evidence_strength=EvidenceStrength.TRUSTED_REGISTRY,
    )
    gguf = base.model_copy(
        update={"id": "release:grearl:kimi:k3:gguf", "name": "Kimi K3 GGUF"}
    )
    for release in (base, gguf):
        repo.upsert_release(release)
    runner = IntelligenceJobRunner(root=tmp_path, repository=repo)
    evidence = runner._persist_source_record(
        make_record("https://huggingface.co/api/models/moonshotai/Kimi-K3", b"{}")
    )
    runner._append_claim(base.id, "hf_repo", "moonshotai/Kimi-K3", evidence)
    runner._append_claim(gguf.id, "hf_repo", "grearl/Kimi-K3-GGUF", evidence)

    report = await run_lineage_backfill(
        tmp_path, repo, fetch_limit=0, clock=lambda: NOW
    )

    assert report["inferred_edges"] == 1
    edges = repo.list_lineage_for_child(gguf.id)
    assert len(edges) == 1
    assert edges[0].declared is False
    assert edges[0].confidence == 0.5
    assert edges[0].parent_release_id == base.id
    # Suggestion only: the child roots at itself, no review finding.
    assert edges[0].root_release_id == gguf.id
    assert report["review_findings"] == 0
    # Idempotent: a re-run infers nothing new.
    rerun = await run_lineage_backfill(
        tmp_path, repo, fetch_limit=0, clock=lambda: NOW
    )
    assert rerun["inferred_edges"] == 0


@pytest.mark.asyncio
async def test_lineage_triage_resolves_parents_and_reconciles_suggestions(
    tmp_path,
) -> None:
    from radar.intelligence.contracts import ReviewException
    from radar.intelligence.lineage import build_inferred_edge, list_suggestions
    from radar.intelligence.pipeline import run_lineage_triage

    repo = repository(tmp_path)
    base = Release(
        id="release:moonshot-ai:kimi:k3",
        family_id="family:moonshot-ai:kimi",
        publisher_id="publisher:moonshot-ai",
        name="Kimi K3",
        category=ModelCategory.MULTIMODAL,
        lane=ReleaseLane.DEPLOYABLE,
        lifecycle=LifecycleState.VERIFIED,
        first_observed_at=NOW,
        discovery_evidence_strength=EvidenceStrength.TRUSTED_REGISTRY,
    )
    confirmed_child = base.model_copy(
        update={"id": "release:c:confirmed", "name": "Confirmed GGUF"}
    )
    refuted_child = base.model_copy(
        update={"id": "release:c:refuted", "name": "Refuted GGUF"}
    )
    silent_child = base.model_copy(
        update={"id": "release:c:silent", "name": "Silent GGUF"}
    )
    for release in (base, confirmed_child, refuted_child, silent_child):
        repo.upsert_release(release)
    runner = IntelligenceJobRunner(root=tmp_path, repository=repo)
    evidence = runner._persist_source_record(
        make_record("https://huggingface.co/api/models/x", b"{}")
    )
    runner._append_claim(base.id, "hf_repo", "moonshotai/Kimi-K3", evidence)
    runner._append_claim(
        confirmed_child.id, "hf_repo", "grearl/Kimi-K3-GGUF", evidence
    )
    runner._append_claim(
        refuted_child.id, "hf_repo", "other/Kimi-K3-Refuted-GGUF", evidence
    )
    runner._append_claim(
        silent_child.id, "hf_repo", "quiet/Kimi-K3-Silent-GGUF", evidence
    )
    for child, repo_name in (
        (confirmed_child, "grearl/Kimi-K3-GGUF"),
        (refuted_child, "other/Kimi-K3-Refuted-GGUF"),
        (silent_child, "quiet/Kimi-K3-Silent-GGUF"),
    ):
        repo.upsert_lineage_edge(
            build_inferred_edge(
                child.id,
                repo_name,
                "moonshotai/Kimi-K3",
                LineageRelation.QUANTIZED,
                resolve_parent=lambda _: base.id,
                observed_at=NOW,
            )
        )
    repo.open_review_exception(
        ReviewException(
            id="review:lineage:external",
            subject_id="release:external",
            code="lineage-unresolved-parent",
            message=(
                "Declared lineage parent is not resolvable: "
                "hf:runwayml/stable-diffusion-v1-5"
            ),
            evidence_ids=[],
            opened_at=NOW,
        )
    )
    repo.open_review_exception(
        ReviewException(
            id="review:lineage:gone",
            subject_id="release:gone",
            code="lineage-unresolved-parent",
            message=(
                "Declared lineage parent is not resolvable: hf:acme/Deleted"
            ),
            evidence_ids=[],
            opened_at=NOW,
        )
    )

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("runwayml/stable-diffusion-v1-5"):
            return httpx.Response(
                200, json={"id": "runwayml/stable-diffusion-v1-5"},
                request=request,
            )
        if path.endswith("acme/Deleted"):
            return httpx.Response(404, request=request)
        if path.endswith("grearl/Kimi-K3-GGUF"):
            return httpx.Response(
                200,
                json={
                    "id": "grearl/Kimi-K3-GGUF",
                    "baseModels": {
                        "relation": "quantized",
                        "models": [{"id": "moonshotai/Kimi-K3"}],
                    },
                },
                request=request,
            )
        if path.endswith("other/Kimi-K3-Refuted-GGUF"):
            return httpx.Response(
                200,
                json={
                    "id": "other/Kimi-K3-Refuted-GGUF",
                    "baseModels": {
                        "relation": "quantized",
                        "models": [{"id": "somebody/Else-Entirely"}],
                    },
                },
                request=request,
            )
        if path.endswith("quiet/Kimi-K3-Silent-GGUF"):
            return httpx.Response(
                200,
                json={"id": "quiet/Kimi-K3-Silent-GGUF"},
                request=request,
            )
        return httpx.Response(500, request=request)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as client:
        report = await run_lineage_triage(
            tmp_path, repo, fetch_limit=10, clock=lambda: NOW, client=client
        )

    assert report["parents_resolved"] == 1
    assert report["parents_gone"] == 1
    assert report["suggestions_confirmed"] == 1
    assert report["suggestions_refuted"] == 1
    external = repo.get_review_exception("review:lineage:external")
    assert external is not None and external.resolved_at is not None
    gone = repo.get_review_exception("review:lineage:gone")
    assert gone is not None and gone.resolved_at is not None
    # The silent card's suggestion is untouched; the other two are gone.
    remaining = list_suggestions(repo)
    assert [edge.child_release_id for edge in remaining] == [
        "release:c:silent"
    ]
    # Confirmed ancestry now rides a DECLARED edge from the registry.
    declared = [
        edge
        for edge in repo.list_all_lineage_edges()
        if edge.child_release_id == "release:c:confirmed" and edge.declared
    ]
    assert len(declared) == 1


@pytest.mark.asyncio
async def test_alias_canonicalization_melts_org_rename_conflicts(
    tmp_path,
) -> None:
    """Two names for one repo (org rename) must not read as a dispute."""
    from radar.intelligence.lineage import LineageService
    from radar.intelligence.pipeline import run_lineage_triage

    repo = repository(tmp_path)
    parent = Release(
        id="release:dphn:dolphin",
        family_id="family:moonshot-ai:kimi",
        publisher_id="publisher:moonshot-ai",
        name="Dolphin 3.0",
        category=ModelCategory.TEXT_REASONING,
        lane=ReleaseLane.DEPLOYABLE,
        lifecycle=LifecycleState.VERIFIED,
        first_observed_at=NOW,
        discovery_evidence_strength=EvidenceStrength.TRUSTED_REGISTRY,
    )
    child = parent.model_copy(
        update={"id": "release:child:tune", "name": "Dolphin Tune"}
    )
    for release in (parent, child):
        repo.upsert_release(release)
    runner = IntelligenceJobRunner(root=tmp_path, repository=repo)
    evidence = runner._persist_source_record(
        make_record("https://huggingface.co/api/models/x", b"{}")
    )
    runner._append_claim(
        parent.id, "hf_repo", "dphn/Dolphin3.0-Llama3.2-1B", evidence
    )
    # The child's card declares BOTH the old-org and new-org names.
    declared = [
        {
            "parent_repo": "cognitivecomputations/Dolphin3.0-Llama3.2-1B",
            "relation": "finetune",
            "via": "card",
        },
        {
            "parent_repo": "dphn/Dolphin3.0-Llama3.2-1B",
            "relation": "finetune",
            "via": "card",
        },
    ]
    runner._append_claim(child.id, "lineage_declared", declared, evidence)
    service = LineageService(repo)
    service.ingest_declared(
        child.id, declared, evidence_ids=[evidence.id], observed_at=NOW
    )
    result = service.sync_roots(NOW)
    assert [f.code for f in result.findings] == ["lineage-conflict"]

    def handler(request: httpx.Request) -> httpx.Response:
        # The registry redirects the old org name to the canonical repo.
        return httpx.Response(
            200,
            json={"id": "dphn/Dolphin3.0-Llama3.2-1B"},
            request=request,
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as client:
        report = await run_lineage_triage(
            tmp_path, repo, fetch_limit=10, clock=lambda: NOW, client=client
        )

    assert report["aliases_recorded"] >= 1
    assert report["alias_edges_repaired"] >= 1
    # The conflict melted: one canonical parent, root resolves, review
    # auto-closed by the service's finding-no-longer-present path.
    final = LineageService(repo).sync_roots(NOW)
    assert final.findings == []
    assert final.roots["release:child:tune"] == parent.id
    open_conflicts = [
        review
        for review in repo.list_review_exceptions(open_only=True)
        if review.code == "lineage-conflict"
    ]
    assert open_conflicts == []
    # Replays of the OLD-name claim now converge on the canonical edge.
    edges = [
        e
        for e in repo.list_all_lineage_edges()
        if e.child_release_id == child.id
    ]
    assert len(edges) == 1
    assert edges[0].parent_external_ref == "hf:dphn/Dolphin3.0-Llama3.2-1B"
