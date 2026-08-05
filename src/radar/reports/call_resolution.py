"""Deterministic resolution of the Desk's public calls.

The brief's verdicts are produced by code, so their scoring is too —
resolving a day-old call by hand would be manufacturing a track record.
Rules (v1), printed with every resolution note:

- **Ring-move calls** resolve after a ``HOLD_WINDOW_DAYS`` observation
  window against subsequent ring history for the same subject:
  * ``confirmed`` — the ring the call reported still holds (or the
    subject moved HIGHER, e.g. a pilot-entry call whose subject later
    reached adopt).
  * ``wrong`` — the subject dropped below the call-time ring inside the
    window (the reported move did not hold).
- **Every other open call** (benchmark moves, trending repos, news)
  ``expires`` after ``EXPIRY_WINDOW_DAYS``: those verdicts are
  time-boxed prompts to evaluate, not predictions with a measurable
  truth value — an expiry is recorded, visible, and excluded from the
  hit rate by ``track_record``.

Calls younger than their window stay open; nothing is scored early.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from radar.storage.calls_ledger import CallRecord, CallState


HOLD_WINDOW_DAYS = 14
EXPIRY_WINDOW_DAYS = 28

_RING_RANK = {"avoid": 0, "watch": 1, "pilot": 2, "adopt": 3}


def _subject_ring_timeline(root: Path, subject: str) -> list[tuple[datetime, str]]:
    """(observed_at, ring) events for one subject, models + projects."""
    timeline: list[tuple[datetime, str]] = []
    try:
        from radar.models_radar.history import load_model_events

        for event in load_model_events(root / "data" / "model-history.jsonl"):
            if event.model_id == subject:
                timeline.append((event.observed_at, event.ring.value))
    except Exception:
        pass
    try:
        from radar.storage.history_log import load_events

        for project_event in load_events(root / "data" / "history.jsonl"):
            if project_event.project == subject:
                timeline.append(
                    (project_event.observed_at, project_event.ring.value)
                )
    except Exception:
        pass
    timeline.sort()
    return timeline


def _resolve_ring_call(
    root: Path,
    call: CallState,
    now: datetime,
) -> CallRecord | None:
    if now - call.made_at < timedelta(days=HOLD_WINDOW_DAYS):
        return None
    timeline = _subject_ring_timeline(root, call.subject)
    at_call = [ring for observed, ring in timeline if observed <= call.made_at]
    if not at_call:
        return None  # cannot reconstruct the triggering move — stay open
    call_ring = at_call[-1]
    after = [ring for observed, ring in timeline if observed > call.made_at]
    current_ring = after[-1] if after else call_ring
    held = _RING_RANK.get(current_ring, -1) >= _RING_RANK.get(call_ring, -1)
    window_end = (call.made_at + timedelta(days=HOLD_WINDOW_DAYS)).date()
    if held:
        note = (
            f"Auto-resolved (rules v1): ring '{call_ring}' held through the "
            f"{HOLD_WINDOW_DAYS}-day window (now '{current_ring}', "
            f"checked {window_end})"
        )
        outcome = "confirmed"
    else:
        note = (
            f"Auto-resolved (rules v1): subject dropped from '{call_ring}' "
            f"to '{current_ring}' inside the {HOLD_WINDOW_DAYS}-day window"
        )
        outcome = "wrong"
    return CallRecord(
        type="resolved",
        call_id=call.call_id,
        recorded_at=now,
        outcome=outcome,
        note=note,
    )


def auto_resolve_calls(
    root: Path,
    open_calls: list[CallState],
    now: datetime,
) -> list[CallRecord]:
    """Resolutions the documented rules can defend; everything else waits."""
    resolutions: list[CallRecord] = []
    for call in open_calls:
        if call.status != "open":
            continue
        if call.call_id.split(":")[2:3] == ["ring-moves"]:
            record = _resolve_ring_call(root, call, now)
            if record is not None:
                resolutions.append(record)
            continue
        if now - call.made_at >= timedelta(days=EXPIRY_WINDOW_DAYS):
            resolutions.append(
                CallRecord(
                    type="resolved",
                    call_id=call.call_id,
                    recorded_at=now,
                    outcome="expired",
                    note=(
                        "Auto-resolved (rules v1): evaluation window of "
                        f"{EXPIRY_WINDOW_DAYS} days elapsed — expiries are "
                        "recorded and excluded from the hit rate"
                    ),
                )
            )
    return resolutions
