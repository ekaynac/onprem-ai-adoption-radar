"""Executable intelligence jobs behind the freshness scheduler."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import yaml

from radar.intelligence.contracts import (
    PUBLIC_DISCOVERY_STRENGTHS,
    Claim,
    ClaimState,
    CompatibilityAssertion,
    EvidenceLevel,
    EvidenceObservation,
    EvidenceStrength,
    LifecycleState,
    ModelCategory,
    ProductFamily,
    Publisher,
    Release,
    ReleaseLane,
    ReviewException,
    SupportStatus,
)
from radar.intelligence.event_log import EventLog
from radar.intelligence.events import IntelligenceEvent
from radar.intelligence.identity import IdentityResolver
from radar.intelligence.jobs import JobKind, JobResult
from radar.intelligence.lifecycle import LifecycleService
from radar.intelligence.lineage import LineageService
from radar.intelligence.platforms import PlatformIntelligenceService
from radar.intelligence.qualification import QualificationService
from radar.intelligence.recommendations import RecommendationService
from radar.intelligence.source_health import SourceHealthService
from radar.intelligence.sources.base import DiscoveryCandidate, SourceAdapter, SourceRecord
from radar.intelligence.sources.registry import (
    SourceRegistryConfig,
    build_source_adapters,
)
from radar.intelligence.verification import VerificationService


DISCOVERY_OVERLAP = timedelta(minutes=15)
logger = logging.getLogger(__name__)

DEFAULT_VERIFICATION_BATCH_SIZE = 500
DEFAULT_ENRICHMENT_BATCH_SIZE = 100
DEFAULT_ADAPTER_TIMEOUT_SECONDS = 600.0
DEFAULT_ENRICHMENT_CONCURRENCY = 8
_WEIGHT_SUFFIXES = (
    ".bin",
    ".gguf",
    ".ggml",
    ".onnx",
    ".safetensors",
)


class IntelligenceJobRunner:
    """Run real, deterministic ingestion and decision lifecycle work."""

    def __init__(
        self,
        *,
        root: Path,
        repository: Any,
        adapters: Sequence[SourceAdapter] = (),
        clock: Callable[[], datetime] | None = None,
        verification_batch_size: int = DEFAULT_VERIFICATION_BATCH_SIZE,
        enrichment_batch_size: int = DEFAULT_ENRICHMENT_BATCH_SIZE,
        adapter_timeout_seconds: float = DEFAULT_ADAPTER_TIMEOUT_SECONDS,
        enrichment_concurrency: int = DEFAULT_ENRICHMENT_CONCURRENCY,
    ):
        self.root = root
        self.repository = repository
        self.adapters = list(adapters)
        self.clock = clock or (lambda: datetime.now(UTC))
        self.verification_batch_size = max(1, verification_batch_size)
        self.enrichment_batch_size = max(1, enrichment_batch_size)
        self.adapter_timeout_seconds = max(0.001, adapter_timeout_seconds)
        self.enrichment_concurrency = max(1, enrichment_concurrency)
        self.event_log = EventLog(root / "data" / "intelligence" / "events.jsonl")

    async def run(self, kind: JobKind, job_id: str) -> JobResult:
        if kind is JobKind.DISCOVERY:
            return await self._discover(job_id)
        if kind is JobKind.ENRICHMENT:
            return await self._enrich(job_id)
        if kind is JobKind.VERIFY_NEW:
            return self._verify(job_id, detected_only=True)
        if kind is JobKind.VERIFICATION:
            return self._verify(job_id, detected_only=False)
        if kind is JobKind.QUALIFICATION:
            return self._qualify(job_id)
        if kind is JobKind.RECOMMENDATIONS:
            return self._recommend(job_id)
        return JobResult(job_id=job_id, warnings=(f"No handler for {kind.value}",))

    async def _discover(self, job_id: str) -> JobResult:
        now = self.clock()
        candidates: list[DiscoveryCandidate] = []
        warnings: list[str] = []
        health = SourceHealthService(self.repository)
        pending: list[tuple[SourceAdapter, datetime, float]] = []
        for adapter in self.adapters:
            if health.should_skip(adapter.id, now):
                warnings.append(f"{adapter.id}: circuit open")
                continue
            state = self.repository.get_source_health(adapter.id)
            since = (
                now - timedelta(days=3650)
                if state is None or state.last_success_at is None
                else min(now, state.last_success_at) - DISCOVERY_OVERLAP
            )
            pending.append((adapter, since, time.monotonic()))

        async def discover_one(
            adapter: SourceAdapter,
            since: datetime,
            started: float,
        ) -> tuple[SourceAdapter, list[DiscoveryCandidate], float, str | None]:
            try:
                rows = await asyncio.wait_for(
                    adapter.discover(since),
                    timeout=self.adapter_timeout_seconds,
                )
                return adapter, rows, (time.monotonic() - started) * 1000, None
            except TimeoutError:
                return (
                    adapter,
                    [],
                    (time.monotonic() - started) * 1000,
                    f"timed out after {self.adapter_timeout_seconds:g}s",
                )
            except Exception as exc:
                return adapter, [], (time.monotonic() - started) * 1000, str(exc)

        outcomes = await asyncio.gather(
            *(discover_one(*operation) for operation in pending)
        )
        for adapter, rows, latency_ms, error in outcomes:
            if error is not None:
                health.record_failure(adapter.id, error, now)
                warnings.append(f"{adapter.id}: {error}")
                continue
            health.record_success(
                adapter.id,
                latency_ms=latency_ms,
                items=len(rows),
                now=now,
            )
            candidates.extend(rows)

        created = updated = rejected = conflicted = 0
        lineage_batch: list[tuple[str, Any, str, datetime]] = []
        resolver = IdentityResolver(self.repository)
        for candidate in sorted(
            candidates,
            key=lambda item: (item.source_record.source_id, item.external_id.casefold()),
        ):
            release_id, status = self._ingest_candidate(
                candidate,
                resolver,
                now,
                lineage_batch,
            )
            del release_id
            if status == "created":
                created += 1
            elif status == "updated":
                updated += 1
            elif status == "rejected":
                rejected += 1
            else:
                conflicted += 1

        self._sync_lineage(lineage_batch, now)

        return JobResult(
            job_id=job_id,
            discovered=len(candidates),
            created=created,
            updated=updated,
            rejected=rejected,
            conflicted=conflicted,
            warnings=tuple(warnings),
        )

    async def _enrich(self, job_id: str) -> JobResult:
        updated = 0
        warnings: list[str] = []
        lineage_batch: list[tuple[str, Any, str, datetime]] = []
        enrichers = [adapter for adapter in self.adapters if hasattr(adapter, "enrich")]
        eligible: list[tuple[Release, str]] = []
        for release in self.repository.list_all_releases():
            if release.lifecycle is not LifecycleState.VERIFIED:
                continue
            repo_id = self._repository_identity(release.id)
            if repo_id is not None:
                eligible.append((release, repo_id))
        attempts = self._latest_processed_attempts(JobKind.ENRICHMENT)
        lineage_priority = self._lineage_priority()
        eligible.sort(
            key=lambda item: _attempt_priority(
                item[0],
                attempts,
                lineage_priority.get(item[0].id),
            )
        )
        selected = eligible[: self.enrichment_batch_size]
        semaphore = asyncio.Semaphore(self.enrichment_concurrency)

        async def enrich_one(release: Release, repo_id: str, adapter: Any):
            async with semaphore:
                try:
                    enrichment = await asyncio.wait_for(
                        adapter.enrich(repo_id),
                        timeout=self.adapter_timeout_seconds,
                    )
                    return release, repo_id, adapter, enrichment, None
                except TimeoutError:
                    return (
                        release,
                        repo_id,
                        adapter,
                        None,
                        f"timed out after {self.adapter_timeout_seconds:g}s",
                    )
                except Exception as exc:
                    return release, repo_id, adapter, None, str(exc)

        outcomes = await asyncio.gather(
            *(
                enrich_one(release, repo_id, adapter)
                for release, repo_id in selected
                for adapter in enrichers
            )
        )
        for release, repo_id, adapter, enrichment, error in outcomes:
            if error is not None:
                warnings.append(f"{adapter.id}:{repo_id}: {error}")
                continue
            if enrichment is not None:
                evidence = [
                    self._persist_source_record(record.source_record)
                    for record in enrichment.records
                ]
                if not evidence:
                    continue
                for predicate, value in sorted(enrichment.claims.items()):
                    self._append_claim(release.id, predicate, value, evidence[0])
                for url in enrichment.artifact_urls[:1]:
                    self._append_claim(release.id, "artifact_url", url, evidence[0])
                self._upsert_declared_compatibility(
                    release.id,
                    enrichment.claims,
                    evidence[0],
                )
                declared_lineage = enrichment.claims.get("lineage_declared")
                if declared_lineage:
                    lineage_batch.append(
                        (
                            release.id,
                            declared_lineage,
                            evidence[0].id,
                            evidence[0].retrieved_at,
                        )
                    )
                updated += 1
        self._sync_lineage(lineage_batch, self.clock())
        return JobResult(
            job_id=job_id,
            processed=len(selected),
            remaining=max(0, len(eligible) - len(selected)),
            processed_ids=tuple(release.id for release, _repo_id in selected),
            updated=updated,
            warnings=tuple(warnings),
        )

    def _ingest_candidate(
        self,
        candidate: DiscoveryCandidate,
        resolver: IdentityResolver,
        now: datetime,
        lineage_batch: list[tuple[str, Any, str, datetime]],
    ) -> tuple[str | None, str]:
        """Persist one discovery candidate; returns (release_id, status)."""
        evidence = self._persist_source_record(candidate.source_record)
        self._ensure_provisional_publisher(candidate)
        resolution = resolver.resolve(candidate)
        if resolution.publisher_id is None or resolution.release_id is None:
            self._open_identity_review(
                candidate,
                evidence,
                now,
                resolution.review_code,
            )
            return None, "conflicted"
        existing = self.repository.get_release(resolution.release_id)
        if existing is None:
            if resolution.family_id is None:
                return None, "rejected"
            self._ensure_family(
                resolution.family_id,
                resolution.publisher_id,
                candidate.release_name,
            )
            release = Release(
                id=resolution.release_id,
                family_id=resolution.family_id,
                publisher_id=resolution.publisher_id,
                name=candidate.release_name,
                category=candidate.category_hint or ModelCategory.TEXT_REASONING,
                lane=_candidate_lane(candidate),
                lifecycle=LifecycleState.DETECTED,
                first_observed_at=candidate.source_record.retrieved_at,
                discovery_evidence_strength=candidate.source_record.strength,
            )
            self.repository.upsert_release(release)
            self._emit_lifecycle(
                release.id,
                None,
                LifecycleState.DETECTED,
                candidate.source_record.retrieved_at,
                [evidence.id],
            )
            status = "created"
        else:
            status = "updated"
        release_id = resolution.release_id
        candidate_claims = dict(candidate.claims)
        repo_id = candidate_claims.pop("repo_id", None)
        if repo_id is not None and "hf_repo" not in candidate_claims:
            candidate_claims["hf_repo"] = repo_id
        claims = {
            **candidate_claims,
            **(
                {"artifact_url": candidate.artifact_urls[0]}
                if candidate.artifact_urls
                else {}
            ),
        }
        for predicate, value in sorted(claims.items()):
            self._append_claim(release_id, predicate, value, evidence)
        declared_lineage = claims.get("lineage_declared")
        if declared_lineage:
            lineage_batch.append(
                (
                    release_id,
                    declared_lineage,
                    evidence.id,
                    evidence.retrieved_at,
                )
            )
        return release_id, status

    def _sync_lineage(
        self,
        batch: list[tuple[str, Any, str, datetime]],
        now: datetime,
    ) -> None:
        if not batch:
            return
        service = LineageService(self.repository)
        for release_id, declared, evidence_id, observed_at in batch:
            service.ingest_declared(
                release_id,
                declared,
                evidence_ids=[evidence_id],
                observed_at=observed_at,
            )
        service.sync_roots(now)

    def _lineage_priority(self) -> dict[str, tuple[int, int]]:
        """Enrichment order signal: roots and high-descendant parents first.

        A root's enrichment unblocks every declared descendant's resolution,
        so within an attempt-recency band derivatives wait behind their
        parents, and parents with many descendants come first.
        """
        lister = getattr(self.repository, "list_all_lineage_edges", None)
        if lister is None:
            return {}
        children: dict[str, int] = {}
        has_parent: set[str] = set()
        for edge in lister():
            has_parent.add(edge.child_release_id)
            if edge.parent_release_id is not None:
                children[edge.parent_release_id] = (
                    children.get(edge.parent_release_id, 0) + 1
                )
        return {
            release_id: (
                1 if release_id in has_parent else 0,
                -children.get(release_id, 0),
            )
            for release_id in set(children) | has_parent
        }

    def _repository_identity(self, release_id: str) -> str | None:
        for predicate in ("hf_repo", "repo_id"):
            value = self._claim_value(release_id, predicate)
            if isinstance(value, str) and "/" in value:
                return value
        return None

    def _verify(self, job_id: str, *, detected_only: bool) -> JobResult:
        service = VerificationService(self.repository)
        updated = conflicted = 0
        eligible = [
            release
            for release in self.repository.list_all_releases()
            if not detected_only
            or release.lifecycle is LifecycleState.DETECTED
        ]
        attempts = self._latest_processed_attempts(
            JobKind.VERIFY_NEW if detected_only else JobKind.VERIFICATION
        )
        eligible.sort(key=lambda release: _attempt_priority(release, attempts))
        selected = eligible[: self.verification_batch_size]
        for release in selected:
            result = service.verify_release(release.id, self.clock())
            if result.verified:
                updated += 1
                if release.lifecycle is LifecycleState.DETECTED:
                    self._emit_lifecycle(
                        release.id,
                        LifecycleState.DETECTED,
                        LifecycleState.VERIFIED,
                        self.clock(),
                        self._evidence_ids(release.id),
                    )
            if result.review_exception is not None:
                conflicted += 1
        return JobResult(
            job_id=job_id,
            processed=len(selected),
            remaining=max(0, len(eligible) - len(selected)),
            processed_ids=tuple(release.id for release in selected),
            updated=updated,
            conflicted=conflicted,
        )

    def _latest_processed_attempts(
        self,
        kind: JobKind,
    ) -> dict[str, datetime]:
        method = getattr(self.repository, "latest_processed_attempts", None)
        return method(kind.value) if method is not None else {}

    def _qualify(self, job_id: str) -> JobResult:
        verification = VerificationService(self.repository)
        service = QualificationService(self.repository)
        updated = rejected = conflicted = 0
        for release in self.repository.list_all_releases():
            if release.lifecycle is not LifecycleState.VERIFIED:
                continue
            verification_result = verification.verify_release(
                release.id,
                self.clock(),
            )
            if (
                verification_result.review_exception is not None
                and not verification_result.verified
            ):
                conflicted += 1
                continue
            if not verification_result.verified:
                rejected += 1
                continue
            result = service.qualify(release.id, self.clock())
            if result.qualified:
                updated += 1
                self._emit_lifecycle(
                    release.id,
                    LifecycleState.VERIFIED,
                    LifecycleState.QUALIFIED,
                    self.clock(),
                    result.evidence_ids,
                )
            else:
                rejected += 1
        return JobResult(
            job_id=job_id,
            updated=updated,
            rejected=rejected,
            conflicted=conflicted,
        )

    def _recommend(self, job_id: str) -> JobResult:
        recommendations = RecommendationService(self.repository)
        lifecycle = LifecycleService(self.repository)
        updated = 0
        for release in self.repository.list_all_releases():
            if release.lifecycle is not LifecycleState.QUALIFIED:
                continue
            view = recommendations.compute_public(release.id)
            if view.ring is None or not view.evidence_ids:
                continue
            lifecycle.transition(
                release.id,
                LifecycleState.RECOMMENDED,
                reason=f"Public recommendation computed as {view.ring.value}",
                evidence_ids=view.evidence_ids,
                now=self.clock(),
            )
            self._emit_lifecycle(
                release.id,
                LifecycleState.QUALIFIED,
                LifecycleState.RECOMMENDED,
                self.clock(),
                view.evidence_ids,
            )
            updated += 1
        return JobResult(job_id=job_id, updated=updated)

    def _persist_source_record(self, record: SourceRecord) -> EvidenceObservation:
        digest = record.checksum.removeprefix("sha256:")
        path = self.root / "data" / "intelligence" / "snapshots" / f"{digest}.bin"
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(record.body)
        identity = (
            f"{record.source_id}|{record.url}|{record.checksum}|"
            f"{record.retrieved_at.isoformat()}"
        )
        evidence = EvidenceObservation(
            id=f"evidence:{hashlib.sha256(identity.encode()).hexdigest()}",
            source_url=record.url,
            strength=record.strength,
            retrieved_at=record.retrieved_at,
            checksum=record.checksum,
            extractor_version="intelligence-pipeline-v1",
            raw_snapshot_path=str(path.relative_to(self.root)),
        )
        self.repository.append_evidence(evidence)
        return evidence

    def _upsert_declared_compatibility(
        self,
        release_id: str,
        claims: dict[str, Any],
        evidence: EvidenceObservation,
    ) -> None:
        library = claims.get("library_name")
        if not isinstance(library, str) or not library.strip():
            return
        library_key = "-".join(
            part
            for part in "".join(
                character.casefold()
                if character.isalnum()
                else "-"
                for character in library
            ).split("-")
            if part
        )
        platform_id = f"platform:library:{library_key}"
        if not any(
            item["id"] == platform_id
            for item in self.repository.list_platforms()
        ):
            self.repository.import_platform(
                platform_id=platform_id,
                name=library,
                repo_url=f"https://huggingface.co/docs/{library_key}",
                verified_at=evidence.retrieved_at.date().isoformat(),
                payload={
                    "kind": "model_library",
                    "source": "huggingface",
                },
            )
        assertion_id = (
            f"compat:{hashlib.sha256(
                f'{release_id}|{platform_id}|{evidence.id}'.encode()
            ).hexdigest()}"
        )
        PlatformIntelligenceService(self.repository).upsert_assertion(
            CompatibilityAssertion(
                id=assertion_id,
                release_id=release_id,
                platform_id=platform_id,
                platform_version="*",
                feature="model_loading",
                support=SupportStatus.YES,
                evidence_level=EvidenceLevel.DOCUMENTED,
                evidence_ids=[evidence.id],
            ),
            now=evidence.retrieved_at,
        )

    def _append_claim(
        self,
        release_id: str,
        predicate: str,
        value: Any,
        evidence: EvidenceObservation,
    ) -> None:
        canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
        identity = f"{release_id}|{predicate}|{canonical}|{evidence.id}"
        self.repository.append_claim(
            Claim(
                id=f"claim:{hashlib.sha256(identity.encode()).hexdigest()}",
                subject_id=release_id,
                predicate=predicate,
                value=value,
                state=ClaimState.CANDIDATE,
                observed_at=evidence.retrieved_at,
                evidence_ids=[evidence.id],
            )
        )

    def _ensure_family(self, family_id: str, publisher_id: str, name: str) -> None:
        if any(
            family.id == family_id
            for family in self.repository.list_families_for_publisher(publisher_id)
        ):
            return
        family_name = name.split(maxsplit=1)[0]
        self.repository.upsert_family(
            ProductFamily(
                id=family_id,
                publisher_id=publisher_id,
                name=family_name,
                aliases=[family_name],
            )
        )

    def _ensure_provisional_publisher(
        self,
        candidate: DiscoveryCandidate,
    ) -> None:
        prefix = "provisional:"
        if (
            not candidate.publisher_hint.startswith(prefix)
            or candidate.source_record.strength
            not in PUBLIC_DISCOVERY_STRENGTHS
        ):
            return
        account = candidate.publisher_hint.removeprefix(prefix).strip()
        key = "-".join(
            part
            for part in "".join(
                character.casefold()
                if character.isalnum()
                else "-"
                for character in account
            ).split("-")
            if part
        )
        if not key:
            return
        self.repository.upsert_publisher(
            Publisher(
                id=f"publisher:provisional:{key}",
                name=account,
                official_domains=[],
                official_accounts=[account],
                aliases=[account],
            )
        )

    def _open_identity_review(
        self,
        candidate: DiscoveryCandidate,
        evidence: EvidenceObservation,
        now: datetime,
        code: str | None,
    ) -> None:
        identity = f"{candidate.source_record.source_id}|{candidate.external_id}"
        self.repository.open_review_exception(
            ReviewException(
                id=f"review:identity:{hashlib.sha256(identity.encode()).hexdigest()}",
                subject_id=f"candidate:{candidate.external_id}",
                code=code or "ambiguous_identity",
                message=f"Identity review required for {candidate.release_name}",
                evidence_ids=[evidence.id],
                opened_at=now,
            )
        )

    def _emit_lifecycle(
        self,
        release_id: str,
        from_state: LifecycleState | None,
        to_state: LifecycleState,
        now: datetime,
        evidence_ids: list[str],
    ) -> None:
        event = IntelligenceEvent.for_lifecycle(
            release_id=release_id,
            from_state=from_state,
            to_state=to_state,
            occurred_at=now,
            evidence_ids=evidence_ids,
        )
        self.repository.append_event(event)
        self.event_log.append(event)

    def _claim_value(self, release_id: str, predicate: str) -> Any:
        claims = [
            claim
            for claim in self.repository.list_claims_for_subject(release_id)
            if claim.predicate == predicate
        ]
        return max(claims, key=lambda claim: (claim.observed_at, claim.id)).value if claims else None

    def _evidence_ids(self, release_id: str) -> list[str]:
        return sorted(
            {
                evidence_id
                for claim in self.repository.list_claims_for_subject(release_id)
                for evidence_id in claim.evidence_ids
            }
        )


def _candidate_lane(candidate: DiscoveryCandidate) -> ReleaseLane:
    artifact_paths = [url.casefold().split("?", 1)[0] for url in candidate.artifact_urls]
    supported_task_or_runtime = candidate.category_hint is not None or any(
        candidate.claims.get(predicate)
        for predicate in (
            "library_name",
            "pipeline_tag",
            "runtime",
            "runtime_support",
        )
    )
    if (
        supported_task_or_runtime
        and any(path.endswith(_WEIGHT_SUFFIXES) for path in artifact_paths)
    ):
        return ReleaseLane.DEPLOYABLE
    if artifact_paths:
        return ReleaseLane.ADJACENT
    return ReleaseLane.MARKET_REFERENCE


def _processing_priority(release: Release) -> tuple[int, float, int, str]:
    strength_rank = {
        strength: index
        for index, strength in enumerate(
            (
                EvidenceStrength.OFFICIAL_ARTIFACT,
                EvidenceStrength.OFFICIAL_DOCUMENTATION,
                EvidenceStrength.OFFICIAL_REPOSITORY,
                EvidenceStrength.OFFICIAL_ANNOUNCEMENT,
                EvidenceStrength.TRUSTED_REGISTRY,
                EvidenceStrength.BENCHMARK_MAINTAINER,
                EvidenceStrength.AGGREGATOR,
                EvidenceStrength.COMMUNITY,
            )
        )
    }
    provisional = release.publisher_id.startswith("publisher:provisional:")
    return (
        int(provisional),
        -release.first_observed_at.timestamp(),
        strength_rank[release.discovery_evidence_strength],
        release.id,
    )


def _attempt_priority(
    release: Release,
    attempts: dict[str, datetime],
    lineage: tuple[int, int] | None = None,
) -> tuple[datetime, int, int, int, float, int, str]:
    has_parent, negative_children = lineage or (0, 0)
    return (
        attempts.get(release.id, datetime.min.replace(tzinfo=UTC)),
        has_parent,
        negative_children,
        *_processing_priority(release),
    )


async def run_lineage_backfill(
    root: Path,
    repository: Any,
    *,
    fetch_limit: int = 0,
    parent_limit: int | None = None,
    max_seconds: float | None = None,
    clock: Callable[[], datetime] | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict[str, int]:
    """Backfill lineage edges for the existing index.

    Always replays stored ``lineage_declared`` claims (no network). With
    ``fetch_limit > 0`` it additionally queries the HF ``baseModels``
    expansion for the highest-download releases that have never been
    checked, storing the response as evidence plus a claim so future
    backfills replay it offline. ``parent_limit`` (default: ``fetch_limit``)
    independently budgets registering declared parents that are missing
    from the index, so parent resolution can run without new sweeps.
    ``max_seconds`` is a wall-clock budget for the network phases: when
    HF rate limiting turns per-request retries into a crawl, the run
    stops fetching cleanly at the deadline (replay and the final root
    sync still complete) and the 2-hourly cadence finishes the tail —
    a slow quota day must never stall the publish pipeline for hours.
    """
    from radar.intelligence.sources.huggingface import fetch_base_models

    now = (clock or (lambda: datetime.now(UTC)))()
    deadline = None if max_seconds is None else time.monotonic() + max_seconds

    def over_deadline() -> bool:
        return deadline is not None and time.monotonic() >= deadline

    service = LineageService(repository)
    runner = IntelligenceJobRunner(root=root, repository=repository)
    releases = repository.list_all_releases()
    release_ids = [release.id for release in releases]
    stored = repository.latest_claim_values(release_ids, {"lineage_declared"})

    replayed_edges = 0
    for release_id in sorted(stored):
        declared = stored[release_id].get("lineage_declared")
        if not declared:
            continue
        claims = [
            claim
            for claim in repository.list_claims_for_subject(release_id)
            if claim.predicate == "lineage_declared"
        ]
        latest = max(claims, key=lambda claim: (claim.observed_at, claim.id))
        replayed_edges += service.ingest_declared(
            release_id,
            declared,
            evidence_ids=latest.evidence_ids,
            observed_at=latest.observed_at,
        )

    effective_parent_limit = fetch_limit if parent_limit is None else parent_limit
    fetched = fetched_edges = parents_registered = parent_fetch_failures = 0
    deadline_reached = 0
    if fetch_limit > 0 or effective_parent_limit > 0:
        from radar.intelligence.sources.huggingface import HuggingFaceAdapter

        headers = {}
        if token := os.environ.get("HF_TOKEN"):
            headers["Authorization"] = f"Bearer {token}"
        owned_client = client is None
        active_client = client or httpx.AsyncClient(
            headers=headers,
            timeout=httpx.Timeout(30.0),
            follow_redirects=True,
        )
        try:
            if fetch_limit > 0:
                metadata = repository.latest_claim_values(
                    release_ids,
                    {"hf_repo", "repo_id", "downloads"},
                )
                pending: list[tuple[int, str, str]] = []
                for release in releases:
                    if release.id in stored:
                        continue
                    values = metadata.get(release.id, {})
                    repo = values.get("hf_repo") or values.get("repo_id")
                    if not isinstance(repo, str) or "/" not in repo:
                        continue
                    downloads = values.get("downloads")
                    pending.append(
                        (
                            -(downloads if isinstance(downloads, int) else 0),
                            release.id,
                            repo,
                        )
                    )
                pending.sort()
                for _, release_id, repo in pending[:fetch_limit]:
                    if over_deadline():
                        deadline_reached = 1
                        break
                    record, entries = await fetch_base_models(
                        active_client,
                        repo,
                        clock=lambda: now,
                    )
                    if record is None:
                        parent_fetch_failures += 1
                        continue
                    evidence = runner._persist_source_record(record)
                    runner._append_claim(
                        release_id,
                        "lineage_declared",
                        entries,
                        evidence,
                    )
                    if entries:
                        fetched_edges += service.ingest_declared(
                            release_id,
                            entries,
                            evidence_ids=[evidence.id],
                            observed_at=evidence.retrieved_at,
                        )
                    fetched += 1

            # Declared parents outside the index (e.g. the -Base repo an
            # instruct model derives from) can never resolve from the
            # rolling discovery window. Register them through the normal
            # ingestion path, iterating so grandparent chains close too.
            if effective_parent_limit > 0:
                publishers = {
                    account: publisher.id
                    for publisher in repository.list_publishers()
                    for account in publisher.official_accounts
                }
                adapter = HuggingFaceAdapter(active_client, publishers)
                attempted: set[str] = set()
                for _round in range(3):
                    if over_deadline():
                        deadline_reached = 1
                        break
                    round_service = LineageService(repository)
                    round_service.sync_roots(now)
                    unresolved_refs = sorted(
                        {
                            edge.parent_external_ref.removeprefix("hf:")
                            for edge in repository.list_unresolved_lineage()
                            if edge.parent_external_ref.startswith("hf:")
                        }
                        - attempted
                    )[:effective_parent_limit]
                    if not unresolved_refs:
                        break
                    resolver = IdentityResolver(repository)
                    parent_lineage: list[tuple[str, Any, str, datetime]] = []
                    progressed = False
                    for repo in unresolved_refs:
                        if over_deadline():
                            deadline_reached = 1
                            break
                        attempted.add(repo)
                        candidate = await adapter.fetch_candidate(repo)
                        if candidate is None:
                            parent_fetch_failures += 1
                            continue
                        parent_id, _status = runner._ingest_candidate(
                            candidate,
                            resolver,
                            now,
                            parent_lineage,
                        )
                        if parent_id is not None:
                            parents_registered += 1
                            progressed = True
                            if not candidate.claims.get("lineage_declared"):
                                # Mark parentless parents as checked so they
                                # read as confirmed bases, not never-asked.
                                runner._append_claim(
                                    parent_id,
                                    "lineage_declared",
                                    [],
                                    runner._persist_source_record(
                                        candidate.source_record
                                    ),
                                )
                    ingest_service = LineageService(repository)
                    for entry in parent_lineage:
                        parent_id, declared, evidence_id, observed_at = entry
                        fetched_edges += ingest_service.ingest_declared(
                            parent_id,
                            declared,
                            evidence_ids=[evidence_id],
                            observed_at=observed_at,
                        )
                    if not progressed:
                        break
        finally:
            if owned_client:
                await active_client.aclose()

    # Tier-3 name inference (offline, no network): releases with no
    # edges whose repo name carries a derivative suffix (-GGUF, -AWQ...)
    # matching exactly one indexed repo get an UNDECLARED suggestion
    # edge. Root resolution ignores undeclared edges — this surfaces
    # candidates without auto-accepting ancestry.
    from radar.intelligence.lineage import build_inferred_edge, infer_name_parent

    inference_service = LineageService(repository)
    children_with_edges = {
        edge.child_release_id
        for edge in repository.list_all_lineage_edges()
    }
    release_repos = repository.latest_claim_values(
        release_ids, {"hf_repo", "repo_id"}
    )
    index_repos = {
        repo.casefold(): repo
        for values in release_repos.values()
        for repo in [values.get("hf_repo") or values.get("repo_id")]
        if isinstance(repo, str) and "/" in repo
    }
    inferred_edges = 0
    for release_id in sorted(release_repos):
        if release_id in children_with_edges:
            continue
        values = release_repos[release_id]
        child_repo = values.get("hf_repo") or values.get("repo_id")
        if not isinstance(child_repo, str) or "/" not in child_repo:
            continue
        inferred = infer_name_parent(child_repo, index_repos)
        if inferred is None:
            continue
        parent_repo, relation = inferred
        edge = build_inferred_edge(
            release_id,
            child_repo,
            parent_repo,
            relation,
            resolve_parent=inference_service.resolve_parent,
            observed_at=now,
        )
        if repository.upsert_lineage_edge(edge):
            inferred_edges += 1

    result = LineageService(repository).sync_roots(now)
    return {
        "replayed_edges": replayed_edges,
        "inferred_edges": inferred_edges,
        "fetched": fetched,
        "fetched_edges": fetched_edges,
        "parents_registered": parents_registered,
        "parent_fetch_failures": parent_fetch_failures,
        "edges_total": len(result.edges),
        "roots_resolved": sum(
            1 for root_id in result.roots.values() if root_id is not None
        ),
        "review_findings": len(result.findings),
        "deadline_reached": deadline_reached,
    }


async def run_lineage_triage(
    root: Path,
    repository: Any,
    *,
    fetch_limit: int = 50,
    max_seconds: float | None = None,
    clock: Callable[[], datetime] | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict[str, int]:
    """Evidence-driven triage of the lineage review/suggestion queue.

    Two passes against the HF registry (bounded by ``fetch_limit`` and a
    wall-clock budget), each recording its check as evidence:

    1. Open ``lineage-unresolved-parent`` reviews: if the declared parent
       exists upstream, the declaration is valid — the parent is simply
       outside the tracked catalog; resolve the review. If upstream
       returns 404/410, the declaration is unverifiable forever; resolve
       with that note. Anything else (rate limit, 5xx) stays open.
    2. Tier-3 suggestions: fetch the child's own ``baseModels``
       declaration when it was never checked. A declaration naming the
       suggested parent replaces the suggestion with a declared edge (the
       normal ingest path); a declaration naming OTHER parents refutes
       the suggestion (deleted); a silent card keeps the suggestion
       pending for a human.
    """
    from radar.intelligence.lineage import list_suggestions
    from radar.intelligence.sources.huggingface import fetch_base_models

    now = (clock or (lambda: datetime.now(UTC)))()
    deadline = None if max_seconds is None else time.monotonic() + max_seconds

    def over_deadline() -> bool:
        return deadline is not None and time.monotonic() >= deadline

    headers = {}
    if token := os.environ.get("HF_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"
    owned_client = client is None
    active_client = client or httpx.AsyncClient(
        headers=headers,
        timeout=httpx.Timeout(30.0),
        follow_redirects=True,
    )
    parents_resolved = parents_gone = suggestions_confirmed = 0
    suggestions_refuted = fetches = failures = deadline_reached = 0
    aliases_recorded = alias_edges_repaired = 0
    prefix = "Declared lineage parent is not resolvable: hf:"
    conflict_prefix = "Conflicting lineage parents declared: "
    try:
        open_reviews = [
            review
            for review in repository.list_review_exceptions(open_only=True)
            if review.code == "lineage-unresolved-parent"
            and review.message.startswith(prefix)
        ]
        for review in sorted(open_reviews, key=lambda r: r.id)[:fetch_limit]:
            if over_deadline():
                deadline_reached = 1
                break
            repo = review.message.removeprefix(prefix).strip()
            try:
                response = await active_client.get(
                    f"https://huggingface.co/api/models/{repo}"
                )
            except httpx.HTTPError:
                failures += 1
                continue
            fetches += 1
            if response.status_code in {200, 401, 403}:
                # Exists (401/403 = gated/private: it exists, we cannot
                # ingest it) — a valid external parent, not an anomaly.
                repository.resolve_review_exception(
                    review.id,
                    (
                        f"Parent hf:{repo} exists upstream "
                        f"(HTTP {response.status_code}) but is outside the "
                        "tracked catalog; the chain intentionally stays "
                        "unresolved (triage 2026-08-06)"
                    ),
                    [],
                    now,
                )
                parents_resolved += 1
            elif response.status_code in {404, 410}:
                repository.resolve_review_exception(
                    review.id,
                    (
                        f"Parent hf:{repo} is gone upstream "
                        f"(HTTP {response.status_code}); the declaration "
                        "is permanently unverifiable (triage 2026-08-06)"
                    ),
                    [],
                    now,
                )
                parents_gone += 1
            else:
                failures += 1

        service = LineageService(repository)
        release_ids = [r.id for r in repository.list_all_releases()]
        stored = repository.latest_claim_values(
            release_ids, {"lineage_declared", "hf_repo", "repo_id"}
        )
        runner = IntelligenceJobRunner(root=root, repository=repository)

        # Conflict pass: most "conflicting parents" are the SAME repo
        # under an org rename or name variant — the registry redirects
        # and reports one canonical id. Record proven aliases as claims,
        # delete edges keyed to stale names, and re-ingest the affected
        # children so conflicts melt in this very run.
        from radar.intelligence.contracts import Claim, ClaimState
        from radar.intelligence.lineage import (
            ALIAS_PREDICATE,
            ALIAS_SUBJECT_PREFIX,
        )

        known_aliases = service.repo_alias_map()
        conflict_refs: set[str] = set()
        for review in repository.list_review_exceptions(open_only=True):
            if review.code != "lineage-conflict":
                continue
            if not review.message.startswith(conflict_prefix):
                continue
            for part in review.message.removeprefix(conflict_prefix).split(
                ","
            ):
                ref = part.strip()
                if ref.startswith("hf:"):
                    conflict_refs.add(ref.removeprefix("hf:"))
        alias_checked = 0
        for repo in sorted(conflict_refs):
            if over_deadline():
                deadline_reached = 1
                break
            if repo.casefold() in known_aliases or alias_checked >= fetch_limit:
                continue
            alias_checked += 1
            try:
                response = await active_client.get(
                    f"https://huggingface.co/api/models/{repo}"
                )
            except httpx.HTTPError:
                failures += 1
                continue
            fetches += 1
            if response.status_code != 200:
                continue
            try:
                canonical = response.json().get("id")
            except ValueError:
                failures += 1
                continue
            if not isinstance(canonical, str) or "/" not in canonical:
                continue
            evidence = runner._persist_source_record(
                SourceRecord.from_bytes(
                    source_id="huggingface",
                    url=str(response.request.url),
                    body=response.content,
                    retrieved_at=now,
                    strength=EvidenceStrength.TRUSTED_REGISTRY,
                )
            )
            repository.append_claim(
                Claim(
                    id=(
                        "claim:repo-alias:"
                        + hashlib.sha256(
                            f"{repo.casefold()}|{canonical}".encode()
                        ).hexdigest()[:32]
                    ),
                    subject_id=f"{ALIAS_SUBJECT_PREFIX}{repo.casefold()}",
                    predicate=ALIAS_PREDICATE,
                    value=canonical,
                    state=ClaimState.CANDIDATE,
                    observed_at=now,
                    evidence_ids=[evidence.id],
                )
            )
            if canonical.casefold() != repo.casefold():
                aliases_recorded += 1

        # Repair: drop edges keyed to a stale name and re-ingest the
        # affected children through the (now alias-aware) declared path.
        alias_service = LineageService(repository)
        aliases = alias_service.repo_alias_map()
        affected_children: set[str] = set()
        for edge in repository.list_all_lineage_edges():
            ref = edge.parent_external_ref.removeprefix("hf:")
            canonical = aliases.get(ref.casefold())
            if canonical is not None and canonical.casefold() != ref.casefold():
                repository.delete_lineage_edge(edge.id)
                alias_edges_repaired += 1
                affected_children.add(edge.child_release_id)
        for child in sorted(affected_children):
            declared = stored.get(child, {}).get("lineage_declared")
            if not declared:
                continue
            claims = [
                claim
                for claim in repository.list_claims_for_subject(child)
                if claim.predicate == "lineage_declared"
            ]
            if not claims:
                continue
            latest = max(claims, key=lambda c: (c.observed_at, c.id))
            alias_service.ingest_declared(
                child,
                declared,
                evidence_ids=latest.evidence_ids,
                observed_at=latest.observed_at,
            )
        checked = 0
        for suggestion in list_suggestions(repository):
            if over_deadline():
                deadline_reached = 1
                break
            child_values = stored.get(suggestion.child_release_id, {})
            declared = child_values.get("lineage_declared")
            if declared is None and checked < fetch_limit:
                repo = child_values.get("hf_repo") or child_values.get(
                    "repo_id"
                )
                if not isinstance(repo, str) or "/" not in repo:
                    continue
                checked += 1
                record, entries = await fetch_base_models(
                    active_client, repo, clock=lambda: now
                )
                if record is None:
                    failures += 1
                    continue
                fetches += 1
                evidence = runner._persist_source_record(record)
                runner._append_claim(
                    suggestion.child_release_id,
                    "lineage_declared",
                    entries,
                    evidence,
                )
                if entries:
                    service.ingest_declared(
                        suggestion.child_release_id,
                        entries,
                        evidence_ids=[evidence.id],
                        observed_at=evidence.retrieved_at,
                    )
                declared = entries
            if not isinstance(declared, list) or not declared:
                continue  # card is silent — the human call stands
            declared_repos = {
                str(entry.get("parent_repo", "")).casefold()
                for entry in declared
                if isinstance(entry, dict)
            }
            suggested = suggestion.parent_external_ref.removeprefix(
                "hf:"
            ).casefold()
            if suggested in declared_repos:
                # Superseded: the registry declaration carries this
                # ancestry now. Same relation ⇒ ingest upserted the very
                # same edge id to declared (keep it); a different relation
                # ⇒ the declared edge lives under its own id, so the
                # leftover suggestion row goes.
                promoted = any(
                    edge.id == suggestion.id and edge.declared
                    for edge in repository.list_all_lineage_edges()
                )
                if not promoted:
                    repository.delete_lineage_edge(suggestion.id)
                suggestions_confirmed += 1
            else:
                repository.delete_lineage_edge(suggestion.id)
                suggestions_refuted += 1
        LineageService(repository).sync_roots(now)
    finally:
        if owned_client:
            await active_client.aclose()
    return {
        "parents_resolved": parents_resolved,
        "parents_gone": parents_gone,
        "suggestions_confirmed": suggestions_confirmed,
        "suggestions_refuted": suggestions_refuted,
        "aliases_recorded": aliases_recorded,
        "alias_edges_repaired": alias_edges_repaired,
        "fetches": fetches,
        "failures": failures,
        "deadline_reached": deadline_reached,
    }


async def run_configured_job(
    root: Path,
    repository: Any,
    kind: JobKind,
    job_id: str,
) -> JobResult:
    """Build locked source adapters and run one scheduled job."""

    config_path = root / "config" / "intelligence-sources.yaml"
    adapters: list[SourceAdapter] = []
    if config_path.exists() and kind in {JobKind.DISCOVERY, JobKind.ENRICHMENT}:
        payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        config = SourceRegistryConfig.model_validate(payload)
        headers = {}
        if token := os.environ.get("HF_TOKEN"):
            headers["Authorization"] = f"Bearer {token}"
        async with httpx.AsyncClient(
            headers=headers,
            timeout=httpx.Timeout(30.0),
            follow_redirects=True,
        ) as client:
            adapters = build_source_adapters(config, client)
            return await IntelligenceJobRunner(
                root=root,
                repository=repository,
                adapters=adapters,
            ).run(kind, job_id)
    return await IntelligenceJobRunner(
        root=root,
        repository=repository,
    ).run(kind, job_id)
