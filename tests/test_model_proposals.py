from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from radar.discovery.model_proposals import (
    ModelProposal,
    load_model_proposals,
    write_model_proposals,
)


def _p(model_id: str) -> ModelProposal:
    return ModelProposal(
        model_id=model_id, name=model_id, family="Qwen",
        hf_repo=f"Qwen/{model_id}", downloads=123456, likes=789,
        modality="text", reason="trending: 123456 downloads", suggested_id=f"hf-{model_id.lower()}",
    )


def test_round_trip(tmp_path: Path):
    path = tmp_path / "proposed-model-seeds.yaml"
    write_model_proposals(path, [_p("Qwen3-32B"), _p("Qwen3-14B")])
    loaded = load_model_proposals(path)
    assert [m.model_id for m in loaded] == ["Qwen3-32B", "Qwen3-14B"]
    assert loaded[0].hf_repo == "Qwen/Qwen3-32B" and loaded[0].downloads == 123456


def test_load_missing_is_empty(tmp_path: Path):
    assert load_model_proposals(tmp_path / "nope.yaml") == []


def test_write_is_atomic_and_overwrites(tmp_path: Path):
    path = tmp_path / "proposed-model-seeds.yaml"
    write_model_proposals(path, [_p("A")])
    write_model_proposals(path, [_p("B")])
    assert [m.model_id for m in load_model_proposals(path)] == ["B"]
    assert not (tmp_path / "proposed-model-seeds.tmp").exists()


def test_model_proposal_is_frozen():
    p = _p("X")
    with pytest.raises(ValidationError):
        p.model_id = "y"
