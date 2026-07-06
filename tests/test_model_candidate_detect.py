"""Model-candidate detection: velocity, new, sustained momentum (pure)."""

from __future__ import annotations

from datetime import UTC, datetime

from radar.discovery.model_candidate_detect import (
    build_model_candidates,
    has_sustained_download_momentum,
)
from radar.storage.model_candidate_log import ModelCandidateObservation


NOW = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)


def _obs(repo: str, downloads: int, day: int) -> ModelCandidateObservation:
    return ModelCandidateObservation(
        hf_repo=repo, name=repo.split("/")[-1], family=repo.split("/")[0],
        downloads=downloads, likes=1, observed_at=datetime(2026, 7, day, 7, 0, tzinfo=UTC),
    )


def test_velocity_over_window():
    rows = [_obs("a/b", 100, 1), _obs("a/b", 400, 4)]   # +300 over 3 days
    entry = build_model_candidates(rows, NOW)[0]
    assert entry.downloads_per_day == 100.0
    assert entry.downloads == 400            # latest row = current
    assert entry.first_seen == "2026-07-01"


def test_velocity_none_single_observation():
    entry = build_model_candidates([_obs("a/b", 100, 1)], NOW)[0]
    assert entry.downloads_per_day is None


def test_ranking_velocity_desc_none_last():
    rows = [_obs("fast/x", 100, 1), _obs("fast/x", 700, 4),   # +200/day
            _obs("slow/y", 100, 1), _obs("slow/y", 130, 4),   # +10/day
            _obs("solo/z", 900, 4)]                            # None
    entries = build_model_candidates(rows, NOW)
    assert [e.hf_repo for e in entries] == ["fast/x", "slow/y", "solo/z"]


def test_is_new_flag():
    # first_seen 2026-07-06 → within 14 days of NOW(07-08)
    entry = build_model_candidates([_obs("n/m", 60, 6), _obs("n/m", 90, 7)], NOW)[0]
    assert entry.is_new is True


def test_sustained_momentum_requires_days_span_growth():
    strong = [_obs("a/b", 100, 1), _obs("a/b", 110, 4), _obs("a/b", 130, 6)]  # 3 days, span 5, +30%
    assert has_sustained_download_momentum(strong) is True

    too_few_days = [_obs("a/b", 100, 1), _obs("a/b", 200, 6)]                 # 2 days
    assert has_sustained_download_momentum(too_few_days) is False

    flat = [_obs("a/b", 100, 1), _obs("a/b", 101, 4), _obs("a/b", 102, 6)]    # +2% < 25%
    assert has_sustained_download_momentum(flat) is False


def test_velocity_none_on_zero_span_same_day():
    # two observations on the SAME calendar day → zero span → no velocity
    rows = [_obs("a/b", 100, 4), _obs("a/b", 500, 4)]
    assert build_model_candidates(rows, NOW)[0].downloads_per_day is None


def test_momentum_false_with_single_observation():
    assert has_sustained_download_momentum([_obs("a/b", 100, 1)]) is False


def test_momentum_false_when_earliest_downloads_zero():
    # 3 days over span 5, but earliest is 0 → growth % undefined → not sustained
    rows = [_obs("a/b", 0, 1), _obs("a/b", 5000, 4), _obs("a/b", 9000, 6)]
    assert has_sustained_download_momentum(rows) is False


def test_load_emerging_excludes_seeded_and_caps(tmp_path):
    from radar.discovery.model_candidate_detect import EMERGING_LIMIT, load_emerging_candidates
    from radar.models_radar.seed import load_model_seed  # noqa: F401  (import proves module path)
    from radar.storage.model_candidate_log import append_model_candidates

    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config" / "model-seed.yaml").write_text(
        "models:\n  - id: tracked\n    name: T\n    family: T\n    hf_repo: tracked/model\n",
        encoding="utf-8")
    obs = [_obs("tracked/model", 5000, 4), _obs("tracked/model", 6000, 6)]  # seeded → excluded
    for i in range(EMERGING_LIMIT + 3):
        obs += [_obs(f"cand/m{i}", 1000 + i, 4), _obs(f"cand/m{i}", 2000 + i, 6)]
    append_model_candidates(tmp_path / "data" / "model-candidate-observations.jsonl", obs)

    rows = load_emerging_candidates(tmp_path, NOW)
    repos = {r.hf_repo for r in rows}
    assert "tracked/model" not in repos          # seeded model dropped from Emerging
    assert len(rows) == EMERGING_LIMIT            # capped


def test_last_seen_and_not_stale_when_recent():
    # NOW = 2026-07-08; latest obs 2026-07-06 → 2 days → not stale
    rows = [_obs("a/b", 100, 1), _obs("a/b", 400, 6)]
    entry = build_model_candidates(rows, NOW)[0]
    assert entry.last_seen == "2026-07-06"
    assert entry.is_stale is False


def test_is_stale_when_latest_observation_old():
    from radar.discovery.model_candidate_detect import STALE_AFTER_DAYS
    assert STALE_AFTER_DAYS == 4
    # latest obs 2026-07-01, NOW 2026-07-08 → 7 days > 4 → stale
    rows = [_obs("a/b", 100, 1), _obs("a/b", 400, 1)]  # both day 1 (velocity None); latest = 07-01
    entry = build_model_candidates(rows, NOW)[0]
    assert entry.last_seen == "2026-07-01"
    assert entry.is_stale is True
