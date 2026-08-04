"""Append-only ledger of the Desk's public calls and their outcomes.

A call is a falsifiable verdict the brief published (Act / Evaluate /
Ignore on a subject). Being seen keeping score is the point: calls are
never edited or deleted — resolutions append as superseding rows and the
loader folds them into current state, mirroring the repo's history-log
conventions.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator


logger = logging.getLogger(__name__)


class CallRecord(BaseModel):
    """One ledger row: either a call being made or a call being resolved."""

    model_config = ConfigDict(frozen=True)

    type: Literal["made", "resolved"]
    call_id: str
    recorded_at: datetime
    brief_id: str | None = None
    subject: str | None = None
    verdict: Literal["act", "evaluate", "ignore"] | None = None
    rationale: str | None = None
    outcome: Literal["confirmed", "wrong", "expired"] | None = None
    note: str | None = None

    @field_validator("recorded_at")
    @classmethod
    def _ensure_aware(cls, v: datetime) -> datetime:
        return v.replace(tzinfo=UTC) if v.tzinfo is None else v


class CallState(BaseModel):
    """A call folded to its current state."""

    model_config = ConfigDict(frozen=True)

    call_id: str
    brief_id: str
    subject: str
    verdict: Literal["act", "evaluate", "ignore"]
    rationale: str
    made_at: datetime
    status: Literal["open", "confirmed", "wrong", "expired"] = "open"
    resolved_at: datetime | None = None
    note: str | None = None


def append_call_records(path: Path, records: list[CallRecord]) -> None:
    if not records:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "\n".join(
        json.dumps(record.model_dump(mode="json"), ensure_ascii=False)
        for record in records
    )
    with path.open("a", encoding="utf-8") as handle:
        handle.write(payload + "\n")


def load_call_records(path: Path) -> list[CallRecord]:
    if not path.exists():
        return []
    records: list[CallRecord] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8", errors="replace").splitlines(),
        start=1,
    ):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            records.append(CallRecord.model_validate(json.loads(stripped)))
        except Exception as exc:
            logger.warning(
                "Skipping corrupt call record at %s:%d: %s",
                path,
                line_number,
                exc,
            )
    return records


def fold_calls(records: list[CallRecord]) -> list[CallState]:
    """Fold made/resolved rows into current call states, newest first."""
    states: dict[str, CallState] = {}
    for record in records:
        if record.type == "made":
            if (
                record.brief_id is None
                or record.subject is None
                or record.verdict is None
            ):
                continue
            states.setdefault(
                record.call_id,
                CallState(
                    call_id=record.call_id,
                    brief_id=record.brief_id,
                    subject=record.subject,
                    verdict=record.verdict,
                    rationale=record.rationale or "",
                    made_at=record.recorded_at,
                ),
            )
        elif record.type == "resolved" and record.call_id in states:
            current = states[record.call_id]
            if record.outcome is None:
                continue
            states[record.call_id] = current.model_copy(
                update={
                    "status": record.outcome,
                    "resolved_at": record.recorded_at,
                    "note": record.note,
                }
            )
    return sorted(
        states.values(),
        key=lambda state: (state.made_at, state.call_id),
        reverse=True,
    )


def track_record(states: list[CallState]) -> dict[str, int | float | None]:
    resolved = [state for state in states if state.status != "open"]
    confirmed = sum(1 for state in resolved if state.status == "confirmed")
    wrong = sum(1 for state in resolved if state.status == "wrong")
    scoreable = confirmed + wrong
    return {
        "total": len(states),
        "open": len(states) - len(resolved),
        "confirmed": confirmed,
        "wrong": wrong,
        "expired": sum(1 for state in resolved if state.status == "expired"),
        "hit_rate_pct": (
            round(confirmed / scoreable * 100) if scoreable else None
        ),
    }
