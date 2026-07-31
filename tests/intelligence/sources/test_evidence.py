from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from radar.intelligence.contracts import EvidenceStrength
from radar.intelligence.sources.evidence import (
    EvidenceAdapter,
    EvidenceSourceConfig,
)


@pytest.mark.asyncio
async def test_evidence_uses_exact_aliases_and_queues_unresolved_subjects() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {
                    "model": "moonshotai/Kimi-K3",
                    "observed_at": "2026-07-30T08:00:00Z",
                    "score": 91.2,
                },
                {
                    "model": "K3 maybe",
                    "observed_at": "2026-07-30T08:00:00Z",
                    "score": 88.0,
                },
            ],
            request=request,
        )

    config = EvidenceSourceConfig(
        id="benchmark",
        kind="benchmark",
        url="https://bench.example/results.json",
        strength=EvidenceStrength.BENCHMARK_MAINTAINER,
        subject_id_field="model",
        observed_at_field="observed_at",
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as client:
        observations = await EvidenceAdapter(
            client,
            [config],
            subject_aliases={
                "moonshotai/Kimi-K3": "release:moonshot-ai:kimi:k3"
            },
        ).collect(datetime(2026, 7, 30, tzinfo=UTC))

    assert observations[0].subject_id == "release:moonshot-ai:kimi:k3"
    assert observations[0].review_code is None
    assert observations[1].subject_id is None
    assert observations[1].review_code == "unresolved_subject"
