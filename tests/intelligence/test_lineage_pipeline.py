"""End-to-end lineage: discover → edges → roots, enrichment, and backfill."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest

from radar.intelligence.contracts import (
    EvidenceStrength,
    LifecycleState,
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
