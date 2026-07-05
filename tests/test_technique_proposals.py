"""Technique proposals: human-review file round-trip (mirror of proposals.py)."""

from __future__ import annotations

from pathlib import Path

from radar.discovery.technique_proposals import (
    TechniqueProposal,
    load_technique_proposals,
    write_technique_proposals,
)
from radar.models import Category
from radar.research_radar.entities import TechniqueDomain


def _proposal(suggested_id: str = "test-time-scaling") -> TechniqueProposal:
    return TechniqueProposal(
        suggested_id=suggested_id, name="Test-Time Scaling", arxiv_id="2502.12345",
        published="2025-02-18", upvotes=142, suggested_domain=TechniqueDomain.INFERENCE,
        suggested_category=Category.MODEL_SERVING, matched_keyword="inference",
    )


def test_write_and_load_round_trip(tmp_path: Path):
    path = tmp_path / "proposed-technique-seeds.yaml"

    write_technique_proposals(path, [_proposal()])
    loaded = load_technique_proposals(path)

    assert loaded == [_proposal()]
    assert not path.with_suffix(".tmp").exists()  # atomic write cleaned up


def test_load_missing_file_returns_empty(tmp_path: Path):
    assert load_technique_proposals(tmp_path / "nope.yaml") == []


def test_write_overwrites_previous_file(tmp_path: Path):
    path = tmp_path / "proposed-technique-seeds.yaml"
    write_technique_proposals(path, [_proposal("old-one")])

    write_technique_proposals(path, [_proposal("new-one")])

    assert [p.suggested_id for p in load_technique_proposals(path)] == ["new-one"]


def test_gitignore_covers_the_proposals_file():
    gitignore = Path(__file__).resolve().parents[1] / ".gitignore"

    assert "data/proposed-technique-seeds.yaml" in gitignore.read_text(encoding="utf-8")
