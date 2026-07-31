"""Exact-alias attachment for benchmark, paper, security, and license evidence."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal

import httpx
from pydantic import Field

from radar.intelligence.contracts import EvidenceStrength, FrozenModel
from radar.intelligence.sources.base import SourceRecord
from radar.intelligence.sources.utils import parse_datetime


class EvidenceSourceConfig(FrozenModel):
    id: str
    kind: Literal["benchmark", "paper", "security", "license"]
    url: str
    strength: EvidenceStrength
    subject_id_field: str
    observed_at_field: str
    items_path: list[str] = Field(default_factory=list)
    enabled: bool = True


class EvidenceCandidate(FrozenModel):
    source_id: str
    kind: str
    subject_alias: str
    subject_id: str | None
    observed_at: datetime
    claims: dict[str, Any]
    source_record: SourceRecord
    review_code: str | None = None


class EvidenceAdapter:
    id = "evidence"

    def __init__(
        self,
        client: httpx.AsyncClient,
        sources: list[EvidenceSourceConfig],
        *,
        subject_aliases: dict[str, str],
        source_id: str = "evidence",
        clock: Callable[[], datetime] | None = None,
    ):
        self.client = client
        self.sources = sources
        self.subject_aliases = subject_aliases
        self.id = source_id
        self.clock = clock or (lambda: datetime.now(UTC))

    async def collect(self, since: datetime) -> list[EvidenceCandidate]:
        observations: list[EvidenceCandidate] = []
        for config in sorted(self.sources, key=lambda item: item.id):
            if not config.enabled:
                continue
            response = await self.client.get(config.url)
            response.raise_for_status()
            record = SourceRecord.from_bytes(
                source_id=self.id,
                url=str(response.request.url),
                body=response.content,
                retrieved_at=self.clock(),
                strength=config.strength,
                content_type=response.headers.get("content-type"),
            )
            items = _path(response.json(), config.items_path)
            if not isinstance(items, list):
                raise ValueError(
                    f"Evidence source {config.id!r} did not resolve to a list"
                )
            for item in items:
                if not isinstance(item, dict):
                    continue
                observed_at = parse_datetime(item.get(config.observed_at_field))
                if observed_at is None or observed_at < since:
                    continue
                subject_alias = str(item[config.subject_id_field])
                subject_id = self.subject_aliases.get(subject_alias)
                observations.append(
                    EvidenceCandidate(
                        source_id=config.id,
                        kind=config.kind,
                        subject_alias=subject_alias,
                        subject_id=subject_id,
                        observed_at=observed_at,
                        claims=item,
                        source_record=record,
                        review_code=(
                            None if subject_id else "unresolved_subject"
                        ),
                    )
                )
        return observations


def _path(value: Any, fields: list[str]) -> Any:
    current = value
    for field in fields:
        if not isinstance(current, dict) or field not in current:
            return None
        current = current[field]
    return current
