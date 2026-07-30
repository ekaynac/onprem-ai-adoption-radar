"""Shared deterministic category qualification behavior."""

from __future__ import annotations

from radar.intelligence.contracts import (
    Claim,
    CompatibilityAssertion,
    EvidenceLevel,
    Qualification,
    Release,
    SupportStatus,
)


class PredicateQualifier:
    required_predicates: tuple[str, ...] = ()
    fit_metrics: tuple[str, ...] = ()
    risk_checks: tuple[str, ...] = ()

    def qualify(
        self,
        release: Release,
        claims: dict[str, Claim],
        compatibility: list[CompatibilityAssertion],
    ) -> Qualification:
        missing = [
            predicate
            for predicate in self.required_predicates
            if predicate not in claims
        ]
        supported = [
            assertion
            for assertion in compatibility
            if assertion.support in {SupportStatus.YES, SupportStatus.PARTIAL}
            and assertion.evidence_level is not EvidenceLevel.INFERRED
        ]
        reasons = self.reasons(release, claims)
        if missing:
            reasons.append(
                f"Missing required predicates: {', '.join(sorted(missing))}"
            )
        if not supported:
            reasons.append(
                "No documented or tested platform compatibility evidence"
            )
        evidence_ids = {
            evidence_id
            for claim in claims.values()
            for evidence_id in claim.evidence_ids
        }
        evidence_ids.update(
            evidence_id
            for assertion in supported
            for evidence_id in assertion.evidence_ids
        )
        return Qualification(
            release_id=release.id,
            qualified=not missing and bool(supported),
            category=release.category,
            reasons=reasons,
            assumptions=self.assumptions(claims),
            evidence_ids=sorted(evidence_ids),
        )

    def reasons(
        self,
        release: Release,
        claims: dict[str, Claim],
    ) -> list[str]:
        return [f"{release.category.value} qualification policy evaluated"]

    def assumptions(self, claims: dict[str, Claim]) -> list[str]:
        return []
