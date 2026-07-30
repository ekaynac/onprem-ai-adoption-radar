"""Exact, deterministic publisher and release identity resolution."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

from radar.intelligence.contracts import (
    PUBLIC_DISCOVERY_STRENGTHS,
    ProductFamily,
    Publisher,
    Release,
)
from radar.intelligence.sources.base import DiscoveryCandidate


_TOKEN_RE = re.compile(r"[^a-z0-9]+")


def normalize_identity(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "-".join(part for part in _TOKEN_RE.split(normalized) if part)


@dataclass(frozen=True)
class IdentityResolution:
    publisher_id: str | None
    family_id: str | None
    release_id: str | None
    confidence: float
    matched_aliases: tuple[str, ...]
    review_code: str | None = None
    is_new_release: bool = False


class IdentityRepository(Protocol):
    def list_publishers(self) -> list[Publisher]: ...

    def list_families_for_publisher(
        self,
        publisher_id: str,
    ) -> list[ProductFamily]: ...

    def list_releases_for_publisher(
        self,
        publisher_id: str,
    ) -> list[Release]: ...


class IdentityResolver:
    def __init__(self, repository: IdentityRepository):
        self.repository = repository

    def resolve(self, candidate: DiscoveryCandidate) -> IdentityResolution:
        publishers = self._publisher_matches(candidate.publisher_hint)
        if len(publishers) != 1:
            return IdentityResolution(
                publisher_id=None,
                family_id=None,
                release_id=None,
                confidence=0.0,
                matched_aliases=(),
                review_code="ambiguous_identity",
            )
        publisher = publishers[0]
        candidate_aliases = _candidate_release_aliases(candidate)
        release_matches = [
            release
            for release in self.repository.list_releases_for_publisher(
                publisher.id
            )
            if candidate_aliases & _release_aliases(release)
        ]
        if len(release_matches) == 1:
            release = release_matches[0]
            return IdentityResolution(
                publisher_id=publisher.id,
                family_id=release.family_id,
                release_id=release.id,
                confidence=1.0,
                matched_aliases=tuple(sorted(candidate_aliases)),
            )
        if len(release_matches) > 1:
            return IdentityResolution(
                publisher_id=publisher.id,
                family_id=None,
                release_id=None,
                confidence=0.0,
                matched_aliases=tuple(sorted(candidate_aliases)),
                review_code="ambiguous_identity",
            )
        if (
            candidate.source_record.strength
            not in PUBLIC_DISCOVERY_STRENGTHS
        ):
            return IdentityResolution(
                publisher_id=publisher.id,
                family_id=None,
                release_id=None,
                confidence=0.25,
                matched_aliases=tuple(sorted(candidate_aliases)),
                review_code="insufficient_identity_evidence",
            )
        return self._new_release(publisher, candidate_aliases)

    def _publisher_matches(self, hint: str) -> list[Publisher]:
        normalized_hint = normalize_identity(hint)
        matches: list[Publisher] = []
        for publisher in self.repository.list_publishers():
            aliases = {
                publisher.id,
                publisher.id.removeprefix("publisher:"),
                publisher.name,
                *publisher.aliases,
                *publisher.official_accounts,
                *publisher.official_domains,
            }
            if hint == publisher.id or normalized_hint in {
                normalize_identity(alias) for alias in aliases
            }:
                matches.append(publisher)
        return matches

    def _new_release(
        self,
        publisher: Publisher,
        candidate_aliases: set[str],
    ) -> IdentityResolution:
        release_key = min(
            candidate_aliases,
            key=lambda value: (len(value.split("-")), len(value), value),
        )
        families = self.repository.list_families_for_publisher(publisher.id)
        matching_families = [
            family
            for family in families
            if any(
                release_key == alias
                or release_key.startswith(f"{alias}-")
                for alias in _family_aliases(family)
            )
        ]
        if matching_families:
            family = max(
                matching_families,
                key=lambda value: len(normalize_identity(value.name)),
            )
            family_id = family.id
            family_key = normalize_identity(family.name)
        else:
            family_key = release_key.split("-", 1)[0]
            publisher_key = publisher.id.removeprefix("publisher:")
            family_id = f"family:{publisher_key}:{family_key}"
        publisher_key = publisher.id.removeprefix("publisher:")
        release_parts = release_key.split("-")
        version_parts = release_parts[len(family_key.split("-")) :]
        version_key = ":".join(version_parts) or "base"
        release_id = (
            f"release:{publisher_key}:{family_key.replace('-', ':')}:"
            f"{version_key}"
        )
        return IdentityResolution(
            publisher_id=publisher.id,
            family_id=family_id,
            release_id=release_id,
            confidence=0.85,
            matched_aliases=tuple(sorted(candidate_aliases)),
            is_new_release=True,
        )


def _candidate_release_aliases(candidate: DiscoveryCandidate) -> set[str]:
    aliases = {normalize_identity(candidate.release_name)}
    external_id = candidate.external_id
    parsed = urlsplit(external_id)
    if parsed.scheme and parsed.netloc:
        external_name = parsed.path.rstrip("/").rsplit("/", 1)[-1]
    else:
        external_name = external_id.rsplit("/", 1)[-1]
    aliases.add(normalize_identity(external_name))
    return {alias for alias in aliases if alias}


def _release_aliases(release: Release) -> set[str]:
    return {
        normalize_identity(release.name),
        normalize_identity(release.id.removeprefix("release:")),
        normalize_identity(":".join(release.id.split(":")[-2:])),
    }


def _family_aliases(family: ProductFamily) -> set[str]:
    return {
        normalize_identity(family.name),
        *(normalize_identity(alias) for alias in family.aliases),
    }
