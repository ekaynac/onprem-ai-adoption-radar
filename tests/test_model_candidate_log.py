"""Append-only JSONL log of untracked model-candidate observations."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from radar.storage.model_candidate_log import (
    ModelCandidateObservation,
    append_model_candidates,
    load_model_candidates,
)


def _obs(repo: str, downloads: int, day: int) -> ModelCandidateObservation:
    return ModelCandidateObservation(
        hf_repo=repo, name=repo.split("/")[-1], family=repo.split("/")[0],
        downloads=downloads, likes=5, observed_at=datetime(2026, 7, day, tzinfo=UTC),
    )


def test_round_trip_and_noop_empty(tmp_path: Path):
    path = tmp_path / "model-candidate-observations.jsonl"
    append_model_candidates(path, [_obs("a/b", 100, 1)])
    append_model_candidates(path, [_obs("a/b", 180, 4)])
    append_model_candidates(path, [])

    rows = load_model_candidates(path)
    assert [r.downloads for r in rows] == [100, 180]
    assert rows[0].hf_repo == "a/b"


def test_missing_and_corrupt(tmp_path: Path):
    assert load_model_candidates(tmp_path / "nope.jsonl") == []
    path = tmp_path / "model-candidate-observations.jsonl"
    append_model_candidates(path, [_obs("a/b", 100, 1)])
    with path.open("a", encoding="utf-8") as h:
        h.write("{broken\n")
    assert len(load_model_candidates(path)) == 1


def test_non_utf8_skipped(tmp_path: Path):
    path = tmp_path / "model-candidate-observations.jsonl"
    append_model_candidates(path, [_obs("a/b", 100, 1)])
    with path.open("ab") as h:
        h.write(b"\xff\xfe broken\n")
    assert len(load_model_candidates(path)) == 1
