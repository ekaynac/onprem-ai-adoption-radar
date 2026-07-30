"""Versioned intelligence event envelope."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Literal

from radar.intelligence.contracts import FrozenModel, LifecycleState


class IntelligenceEvent(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    id: str
    type: str
    occurred_at: datetime
    subject_id: str
    workspace_id: str | None = None
    data: dict[str, Any]
    evidence_ids: list[str]

    @classmethod
    def for_lifecycle(
        cls,
        *,
        release_id: str,
        from_state: LifecycleState | None,
        to_state: LifecycleState,
        occurred_at: datetime,
        evidence_ids: list[str],
    ) -> IntelligenceEvent:
        data = {
            "from": from_state.value if from_state else None,
            "to": to_state.value,
        }
        ordered_evidence = sorted(set(evidence_ids))
        canonical = json.dumps(
            [release_id, data, occurred_at.isoformat(), ordered_evidence],
            separators=(",", ":"),
            sort_keys=True,
        )
        return cls(
            id=f"event:{hashlib.sha256(canonical.encode()).hexdigest()}",
            type=f"release.{to_state.value}",
            occurred_at=occurred_at,
            subject_id=release_id,
            data=data,
            evidence_ids=ordered_evidence,
        )


class WebhookAttempt(FrozenModel):
    """Durable result of one signed event delivery."""

    id: str
    event_id: str
    destination: str
    attempt: int
    signature: str
    http_status: int | None = None
    response_excerpt: str = ""
    next_retry_at: datetime | None = None
    terminal: bool
    attempted_at: datetime
