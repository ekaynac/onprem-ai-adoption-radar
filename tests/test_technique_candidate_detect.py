"""Paper-candidate detection: upvote velocity, new, ranking, emerging gateway."""

from __future__ import annotations

from datetime import UTC, datetime

from radar.discovery.technique_candidate_detect import (
    build_technique_candidates,
    load_emerging_techniques,
)
from radar.storage.technique_candidate_log import (
    TechniqueCandidateObservation,
    append_technique_candidates,
)


NOW = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)


def _obs(arxiv: str, upvotes: int, day: int, citations: int = 1) -> TechniqueCandidateObservation:
    return TechniqueCandidateObservation(
        arxiv_id=arxiv, name=f"Paper {arxiv}", upvotes=upvotes, citation_count=citations,
        published="2026-06-20", suggested_domain="reasoning", suggested_category="inference",
        observed_at=datetime(2026, 7, day, 7, 0, tzinfo=UTC),
    )


def test_upvote_velocity_over_window():
    rows = [_obs("2501.1", 10, 1), _obs("2501.1", 40, 4)]   # +30 over 3 days
    entry = build_technique_candidates(rows, NOW)[0]
    assert entry.upvotes_per_day == 10.0
    assert entry.upvotes == 40 and entry.first_seen == "2026-07-01"


def test_velocity_none_single_observation():
    assert build_technique_candidates([_obs("2501.1", 10, 1)], NOW)[0].upvotes_per_day is None


def test_ranking_upvote_desc_none_last_citation_tiebreak():
    rows = [_obs("hot/1", 10, 1), _obs("hot/1", 200, 4),      # +63/day
            _obs("warm/1", 10, 1), _obs("warm/1", 40, 4),     # +10/day
            _obs("solo/1", 90, 4, citations=99)]              # None velocity, high citations
    entries = build_technique_candidates(rows, NOW)
    assert [e.arxiv_id for e in entries] == ["hot/1", "warm/1", "solo/1"]


def test_is_new_flag():
    entry = build_technique_candidates([_obs("n/1", 5, 6), _obs("n/1", 9, 7)], NOW)[0]
    assert entry.is_new is True


def test_load_emerging_excludes_tracked_and_caps(tmp_path):
    from radar.discovery.technique_candidate_detect import EMERGING_LIMIT

    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    # a tracked technique whose paper is arxiv 2501.tracked → excluded from Emerging
    (tmp_path / "config" / "technique-seed.yaml").write_text(
        "techniques:\n  - id: tracked\n    name: Tracked\n    domain: inference\n"
        "    category: model_serving\n    onprem_impact: reduces_latency\n"
        "    papers:\n      - arxiv_id: 2501.tracked\n        title: T\n        role: canonical\n",
        encoding="utf-8")
    obs = [_obs("2501.tracked", 100, 4), _obs("2501.tracked", 200, 6)]
    for i in range(EMERGING_LIMIT + 3):
        obs += [_obs(f"2501.c{i}", 10 + i, 4), _obs(f"2501.c{i}", 50 + i, 6)]
    append_technique_candidates(tmp_path / "data" / "technique-candidate-observations.jsonl", obs)

    rows = load_emerging_techniques(tmp_path, NOW)
    ids = {r.arxiv_id for r in rows}
    assert "2501.tracked" not in ids      # tracked paper excluded
    assert len(rows) == EMERGING_LIMIT     # capped
