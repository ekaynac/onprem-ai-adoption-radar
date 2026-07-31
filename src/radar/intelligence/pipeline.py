"""Executable intelligence jobs behind the freshness scheduler."""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import yaml

from radar.intelligence.contracts import (
    Claim,
    ClaimState,
    EvidenceObservation,
    LifecycleState,
    ModelCategory,
    ProductFamily,
    Release,
    ReleaseLane,
    ReviewException,
)
from radar.intelligence.event_log import EventLog
from radar.intelligence.events import IntelligenceEvent
from radar.intelligence.identity import IdentityResolver
from radar.intelligence.jobs import JobKind, JobResult
from radar.intelligence.lifecycle import LifecycleService
from radar.intelligence.qualification import QualificationService
from radar.intelligence.recommendations import RecommendationService
from radar.intelligence.source_health import SourceHealthService
from radar.intelligence.sources.base import DiscoveryCandidate, SourceAdapter, SourceRecord
from radar.intelligence.sources.registry import (
    SourceRegistryConfig,
    build_source_adapters,
)
from radar.intelligence.verification import VerificationService


class IntelligenceJobRunner:
    """Run real, deterministic ingestion and decision lifecycle work."""

    def __init__(
        self,
        *,
        root: Path,
        repository: Any,
        adapters: Sequence[SourceAdapter] = (),
        clock: Callable[[], datetime] | None = None,
    ):
        self.root = root
        self.repository = repository
        self.adapters = list(adapters)
        self.clock = clock or (lambda: datetime.now(UTC))
        self.event_log = EventLog(root / "data" / "intelligence" / "events.jsonl")

    async def run(self, kind: JobKind, job_id: str) -> JobResult:
        if kind is JobKind.DISCOVERY:
            return await self._discover(job_id)
        if kind is JobKind.ENRICHMENT:
            return await self._enrich(job_id)
        if kind is JobKind.VERIFICATION:
            return self._verify(job_id)
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
        for adapter in self.adapters:
            if health.should_skip(adapter.id, now):
                warnings.append(f"{adapter.id}: circuit open")
                continue
            started = time.monotonic()
            try:
                rows = await adapter.discover(now - timedelta(hours=2))
            except Exception as exc:
                health.record_failure(adapter.id, str(exc), now)
                warnings.append(f"{adapter.id}: {exc}")
                continue
            health.record_success(
                adapter.id,
                latency_ms=(time.monotonic() - started) * 1000,
                items=len(rows),
                now=now,
            )
            candidates.extend(rows)

        created = updated = rejected = conflicted = 0
        resolver = IdentityResolver(self.repository)
        for candidate in sorted(
            candidates,
            key=lambda item: (item.source_record.source_id, item.external_id.casefold()),
        ):
            evidence = self._persist_source_record(candidate.source_record)
            resolution = resolver.resolve(candidate)
            if resolution.publisher_id is None or resolution.release_id is None:
                self._open_identity_review(candidate, evidence, now, resolution.review_code)
                conflicted += 1
                continue
            existing = self.repository.get_release(resolution.release_id)
            if existing is None:
                if resolution.family_id is None:
                    rejected += 1
                    continue
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
                    lane=(
                        ReleaseLane.DEPLOYABLE
                        if candidate.artifact_urls
                        else ReleaseLane.MARKET_REFERENCE
                    ),
                    lifecycle=LifecycleState.DETECTED,
                    first_observed_at=candidate.source_record.retrieved_at,
                    discovery_evidence_strength=candidate.source_record.strength,
                )
                self.repository.upsert_release(release)
                created += 1
                self._emit_lifecycle(
                    release.id,
                    None,
                    LifecycleState.DETECTED,
                    candidate.source_record.retrieved_at,
                    [evidence.id],
                )
            else:
                updated += 1
            release_id = resolution.release_id
            claims = {
                **candidate.claims,
                **(
                    {"artifact_url": candidate.artifact_urls[0]}
                    if candidate.artifact_urls
                    else {}
                ),
            }
            for predicate, value in sorted(claims.items()):
                self._append_claim(release_id, predicate, value, evidence)

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
        enrichers = [adapter for adapter in self.adapters if hasattr(adapter, "enrich")]
        for release in self.repository.list_all_releases():
            repo_id = self._claim_value(release.id, "repo_id")
            if not isinstance(repo_id, str) or "/" not in repo_id:
                continue
            for adapter in enrichers:
                try:
                    enrichment = await adapter.enrich(repo_id)
                except Exception as exc:
                    warnings.append(f"{adapter.id}:{repo_id}: {exc}")
                    continue
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
                updated += 1
        return JobResult(job_id=job_id, updated=updated, warnings=tuple(warnings))

    def _verify(self, job_id: str) -> JobResult:
        service = VerificationService(self.repository)
        updated = conflicted = 0
        for release in self.repository.list_all_releases():
            if release.lifecycle is not LifecycleState.DETECTED:
                continue
            result = service.verify_release(release.id, self.clock())
            if result.verified:
                updated += 1
                self._emit_lifecycle(
                    release.id,
                    LifecycleState.DETECTED,
                    LifecycleState.VERIFIED,
                    self.clock(),
                    self._evidence_ids(release.id),
                )
            elif result.review_exception is not None:
                conflicted += 1
        return JobResult(job_id=job_id, updated=updated, conflicted=conflicted)

    def _qualify(self, job_id: str) -> JobResult:
        service = QualificationService(self.repository)
        updated = rejected = 0
        for release in self.repository.list_all_releases():
            if release.lifecycle is not LifecycleState.VERIFIED:
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
        return JobResult(job_id=job_id, updated=updated, rejected=rejected)

    def _recommend(self, job_id: str) -> JobResult:
        recommendations = RecommendationService(self.repository)
        lifecycle = LifecycleService(self.repository)
        updated = 0
        for release in self.repository.list_all_releases():
            if release.lifecycle is not LifecycleState.QUALIFIED:
                continue
            view = recommendations.public(release.id)
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
        identity = f"{record.source_id}|{record.url}|{record.checksum}"
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
