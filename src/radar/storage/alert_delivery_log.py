"""Append-only log of delivered stack alerts (exactly-once semantics).

Rows are (alert_id, profile, delivered_at); write-time dedupe by
(alert_id, profile) means an alert is pushed to the webhook exactly
once per profile, however many publish cycles re-observe it.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, field_validator


logger = logging.getLogger(__name__)


class DeliveredAlert(BaseModel):
    model_config = ConfigDict(frozen=True)

    alert_id: str
    profile: str
    delivered_at: datetime

    @field_validator("delivered_at")
    @classmethod
    def _ensure_aware(cls, v: datetime) -> datetime:
        return v.replace(tzinfo=UTC) if v.tzinfo is None else v


def load_delivered_alerts(path: Path) -> list[DeliveredAlert]:
    if not path.exists():
        return []
    rows: list[DeliveredAlert] = []
    for line_no, raw in enumerate(
        path.read_text(encoding="utf-8", errors="replace").splitlines(),
        start=1,
    ):
        line = raw.strip()
        if not line:
            continue
        try:
            rows.append(DeliveredAlert.model_validate_json(line))
        except ValueError as exc:
            logger.warning(
                "Skipping corrupt delivered-alert row at %s:%d: %s",
                path,
                line_no,
                exc,
            )
    return rows


def append_delivered_alerts(path: Path, rows: list[DeliveredAlert]) -> int:
    existing = {
        (row.alert_id, row.profile) for row in load_delivered_alerts(path)
    }
    fresh: list[DeliveredAlert] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        key = (row.alert_id, row.profile)
        if key in existing or key in seen:
            continue
        seen.add(key)
        fresh.append(row)
    if fresh:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(
                "\n".join(
                    json.dumps(row.model_dump(mode="json"), ensure_ascii=False)
                    for row in fresh
                )
                + "\n"
            )
    return len(fresh)
