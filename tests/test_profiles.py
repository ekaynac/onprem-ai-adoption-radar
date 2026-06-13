"""Tests for scoring profiles (per-dimension weight presets)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from radar.models import Config, ScoreBreakdown
from radar.scoring.profiles import weighted_average


def _scores(**overrides) -> ScoreBreakdown:
    base = dict(
        workflow_impact=4, laptop_runnability=4, open_source_maturity=4,
        on_prem_relevance=4, security_posture=2, demo_value=4, setup_friction=4,
    )
    base.update(overrides)
    return ScoreBreakdown(**base)


def test_no_weights_equals_plain_average():
    scores = _scores()

    assert weighted_average(scores, None) == scores.average


def test_weights_shift_the_average():
    scores = _scores()  # security_posture=2 drags a security-heavy profile down

    security_first = weighted_average(scores, {"security_posture": 3.0})

    assert security_first < scores.average


def test_zero_total_weight_rejected():
    with pytest.raises(ValueError):
        weighted_average(_scores(), {"security_posture": 0.0, "workflow_impact": 0.0,
                                     "laptop_runnability": 0.0, "open_source_maturity": 0.0,
                                     "on_prem_relevance": 0.0, "demo_value": 0.0,
                                     "setup_friction": 0.0})


def test_config_validates_profile_dimension_names():
    with pytest.raises(ValidationError):
        Config.model_validate(
            {
                "sources": [
                    {
                        "id": "x", "type": "manual", "project": "X",
                        "category": "mcp_tooling", "url": "https://example.com",
                    }
                ],
                "profiles": {"security-first": {"not_a_dimension": 2.0}},
            }
        )


def test_config_accepts_valid_profiles():
    config = Config.model_validate(
        {
            "sources": [
                {
                    "id": "x", "type": "manual", "project": "X",
                    "category": "mcp_tooling", "url": "https://example.com",
                }
            ],
            "profiles": {"security-first": {"security_posture": 2.5}},
        }
    )

    assert config.profiles["security-first"]["security_posture"] == 2.5


def test_cards_rank_by_weighted_score():
    from datetime import UTC, datetime

    from radar.models import Category, Ring, ScoredSignal, Signal
    from radar.pipeline.cards import build_decision_cards

    def scored(project: str, security: int) -> ScoredSignal:
        return ScoredSignal(
            signal=Signal(
                id=project, source_id="s", project=project,
                category=Category.MODEL_SERVING, title=project,
                url="https://example.com", signal_type="github_repo_snapshot",
                published_at=datetime(2026, 6, 12, tzinfo=UTC),
            ),
            scores=_scores(security_posture=security),
            recommended_ring=Ring.PILOT,
        )

    weights = {"security_posture": 3.0}
    cards = build_decision_cards(
        [scored("Secure", 5), scored("Sketchy", 2)], weights=weights
    )

    secure = next(c for c in cards if c.project == "Secure")
    sketchy = next(c for c in cards if c.project == "Sketchy")
    assert secure.score > sketchy.score
    assert secure.score == weighted_average(_scores(security_posture=5), weights)


def _stored_card(project: str, security: int, ring):
    from radar.models import Category, DecisionCard

    return DecisionCard(
        project=project, category=Category.MODEL_SERVING, ring=ring,
        score=_scores(security_posture=security).average,
        score_breakdown=_scores(security_posture=security),
        summary="s", workflow_fit={}, risk_level="low",
    )


def test_reweight_cards_reranks_without_rescan():
    from radar.models import Ring
    from radar.scoring.profiles import reweight_cards

    cards = [
        _stored_card("Secure", 5, Ring.PILOT),
        _stored_card("Sketchy", 2, Ring.PILOT),
    ]

    out = reweight_cards(cards, {"security_posture": 4.0})

    secure = next(c for c in out if c.project == "Secure")
    sketchy = next(c for c in out if c.project == "Sketchy")
    assert secure.score > sketchy.score
    # Input not mutated.
    assert cards[0].score == _scores(security_posture=5).average


def test_reweight_cards_preserves_pins():
    from radar.models import Ring
    from radar.scoring.profiles import reweight_cards

    pinned = _stored_card("Pinned", 5, Ring.AVOID).model_copy(
        update={"pinned": True, "pinned_reason": "policy"}
    )

    out = reweight_cards([pinned], {"security_posture": 4.0})

    assert out[0].ring == Ring.AVOID  # human decision wins


def test_resolve_weights_unknown_profile_lists_available():
    from radar.scoring.profiles import UnknownProfileError, resolve_weights

    with pytest.raises(UnknownProfileError) as exc:
        resolve_weights({"security-first": {}}, "nope")

    assert "security-first" in str(exc.value)
