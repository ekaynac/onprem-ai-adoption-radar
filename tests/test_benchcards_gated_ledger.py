"""The license-gated ledger must round-trip so the autopilot can skip
known-gated repos instead of re-hitting them every week.
"""

from __future__ import annotations

from pathlib import Path

from radar.cli.models_cli import _load_gated_ledger, _save_gated_ledger


def test_empty_ledger_when_missing(tmp_path: Path) -> None:
    assert _load_gated_ledger(tmp_path / "nope.jsonl") == {}


def test_round_trip_preserves_records(tmp_path: Path) -> None:
    path = tmp_path / "gated-card-repos.jsonl"
    _save_gated_ledger(
        path,
        {
            "google/gemma-2-9b-it": {
                "hf_repo": "google/gemma-2-9b-it",
                "status": "license-gated",
                "first_seen": "2026-08-28T00:00:00+00:00",
                "last_seen": "2026-08-28T00:00:00+00:00",
            }
        },
    )
    loaded = _load_gated_ledger(path)
    assert loaded == {
        "google/gemma-2-9b-it": {
            "hf_repo": "google/gemma-2-9b-it",
            "status": "license-gated",
            "first_seen": "2026-08-28T00:00:00+00:00",
            "last_seen": "2026-08-28T00:00:00+00:00",
        }
    }
