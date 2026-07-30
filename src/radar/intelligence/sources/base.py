"""Normalized records shared by every intelligence source."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Protocol

from pydantic import Field

from radar.intelligence.contracts import (
    EvidenceStrength,
    FrozenModel,
    ModelCategory,
)


class SourceRecord(FrozenModel):
    source_id: str
    url: str
    body: bytes
    retrieved_at: datetime
    strength: EvidenceStrength
    checksum: str
    content_type: str | None = None

    @classmethod
    def from_bytes(
        cls,
        *,
        source_id: str,
        url: str,
        body: bytes,
        retrieved_at: datetime,
        strength: EvidenceStrength,
        content_type: str | None = None,
    ) -> SourceRecord:
        digest = hashlib.sha256(body).hexdigest()
        return cls(
            source_id=source_id,
            url=url,
            body=body,
            retrieved_at=retrieved_at,
            strength=strength,
            checksum=f"sha256:{digest}",
            content_type=content_type,
        )


class DiscoveryCandidate(FrozenModel):
    source_record: SourceRecord
    external_id: str
    publisher_hint: str
    release_name: str
    category_hint: ModelCategory | None = None
    artifact_urls: list[str] = Field(default_factory=list)


class SourceAdapter(Protocol):
    id: str

    async def discover(self, since: datetime) -> list[DiscoveryCandidate]: ...

    async def fetch(self, url: str) -> SourceRecord: ...
