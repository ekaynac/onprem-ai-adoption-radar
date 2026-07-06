"""promotable_candidates gates promotion on sustained download momentum (pure, no HF)."""

from __future__ import annotations

from datetime import UTC, datetime

from radar.discovery.model_promotion import promotable_candidates
from radar.discovery.model_proposals import ModelProposal
from radar.storage.model_candidate_log import ModelCandidateObservation


def _proposal(repo: str, downloads: int) -> ModelProposal:
    name = repo.split("/")[-1]
    return ModelProposal(model_id=name, name=name, family=repo.split("/")[0], hf_repo=repo,
                         downloads=downloads, likes=10, modality="text", reason="t",
                         suggested_id=f"hf-{name}")


def _obs(repo: str, downloads: int, day: int) -> ModelCandidateObservation:
    return ModelCandidateObservation(hf_repo=repo, name=repo.split("/")[-1],
                                     family=repo.split("/")[0], downloads=downloads, likes=1,
                                     observed_at=datetime(2026, 7, day, tzinfo=UTC))


def test_sustained_candidate_passes_flat_popular_gated_out():
    proposals = [_proposal("acme/rocket", 200000), _proposal("bigco/flat", 500000)]
    observations = [
        _obs("acme/rocket", 100000, 1), _obs("acme/rocket", 130000, 4), _obs("acme/rocket", 150000, 6),
        _obs("bigco/flat", 500000, 1), _obs("bigco/flat", 501000, 4), _obs("bigco/flat", 502000, 6),
    ]  # rocket +50% (sustained); flat +0.4% (flat)

    kept = promotable_candidates(proposals, observations, min_downloads=100000, seeded_repos=set())

    assert [p.hf_repo for p in kept] == ["acme/rocket"]   # popular-but-flat is gated out


def test_no_observations_gates_everything_out():
    proposals = [_proposal("acme/rocket", 200000)]
    kept = promotable_candidates(proposals, [], min_downloads=100000, seeded_repos=set())
    assert kept == []   # fail-closed: no momentum evidence → not promoted
