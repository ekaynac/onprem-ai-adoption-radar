"""Append-only JSONL log of untracked paper-candidate observations."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from radar.storage.technique_candidate_log import (
    TechniqueCandidateObservation,
    append_technique_candidates,
    load_technique_candidates,
)


def _obs(arxiv: str, upvotes: int, day: int) -> TechniqueCandidateObservation:
    return TechniqueCandidateObservation(
        arxiv_id=arxiv, name=f"Paper {arxiv}", upvotes=upvotes, citation_count=3,
        published="2026-06-20", suggested_domain="reasoning",
        suggested_category="inference", observed_at=datetime(2026, 7, day, tzinfo=UTC),
    )


def test_round_trip_and_noop_empty(tmp_path: Path):
    path = tmp_path / "technique-candidate-observations.jsonl"
    append_technique_candidates(path, [_obs("2501.1", 10, 1)])
    append_technique_candidates(path, [_obs("2501.1", 40, 4)])
    append_technique_candidates(path, [])

    rows = load_technique_candidates(path)
    assert [r.upvotes for r in rows] == [10, 40]
    assert rows[0].arxiv_id == "2501.1"


def test_missing_and_corrupt(tmp_path: Path):
    assert load_technique_candidates(tmp_path / "nope.jsonl") == []
    path = tmp_path / "technique-candidate-observations.jsonl"
    append_technique_candidates(path, [_obs("2501.1", 10, 1)])
    with path.open("a", encoding="utf-8") as h:
        h.write("{broken\n")
    assert len(load_technique_candidates(path)) == 1


def test_non_utf8_skipped(tmp_path: Path):
    path = tmp_path / "technique-candidate-observations.jsonl"
    append_technique_candidates(path, [_obs("2501.1", 10, 1)])
    with path.open("ab") as h:
        h.write(b"\xff\xfe broken\n")
    assert len(load_technique_candidates(path)) == 1


def test_naive_observed_at_normalized_to_utc(tmp_path: Path):
    path = tmp_path / "technique-candidate-observations.jsonl"
    path.write_text('{"arxiv_id":"2501.1","name":"P","upvotes":5,"citation_count":1,'
                    '"published":"2026-06-20","suggested_domain":"reasoning",'
                    '"suggested_category":"inference","observed_at":"2026-07-06T07:00:00"}\n',
                    encoding="utf-8")
    rows = load_technique_candidates(path)
    assert len(rows) == 1 and rows[0].observed_at.tzinfo is not None
