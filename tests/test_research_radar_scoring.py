"""Six scoring ladders + the technique ring gate, boundary by boundary."""

from __future__ import annotations

import pytest

from radar.models import Category, Ring
from radar.research_radar.entities import (
    ImplKind,
    OnPremImpact,
    ResolvedImplementation,
    TechniqueDomain,
    TechniqueEntry,
    TechniqueScore,
)
from radar.research_radar.momentum import MomentumSignal
from radar.research_radar.scoring import score_technique, technique_ring


def _impl(ring: Ring | None, kind: ImplKind = ImplKind.TOOL, ref: str = "x"):
    return ResolvedImplementation(kind=kind, ref=ref, ring=ring)


def _entry(impls=(), citations=None, peer_reviewed=None, open_code=False,
           superseded=None, impact=OnPremImpact.IMPROVES_QUALITY) -> TechniqueEntry:
    return TechniqueEntry(
        id="t", name="t", category=Category.MODEL_SERVING,
        domain=TechniqueDomain.INFERENCE, onprem_impact=impact,
        resolved_implementations=list(impls), citation_count=citations,
        peer_reviewed=peer_reviewed, open_code=open_code, superseded_by=superseded,
    )


def _steady() -> MomentumSignal:
    return MomentumSignal(technique_id="t", score=3, direction="steady")


@pytest.mark.parametrize(("impl_count", "expected"), [(0, 1), (1, 2), (2, 3), (3, 4),
                                                      (4, 4), (5, 5), (7, 5)])
def test_breadth_ladder(impl_count, expected):
    impls = [_impl(Ring.WATCH, ref=f"tool-{i}") for i in range(impl_count)]

    score = score_technique(_entry(impls=impls), _steady())

    assert score.implementation_breadth == expected


def test_maturity_two_adopts_is_5():
    impls = [_impl(Ring.ADOPT, ref="a"), _impl(Ring.ADOPT, ref="b")]
    assert score_technique(_entry(impls=impls), _steady()).implementation_maturity == 5


def test_maturity_one_adopt_is_4():
    impls = [_impl(Ring.ADOPT), _impl(Ring.WATCH, ref="w")]
    assert score_technique(_entry(impls=impls), _steady()).implementation_maturity == 4


def test_maturity_best_pilot_is_3():
    assert score_technique(_entry(impls=[_impl(Ring.PILOT)]), _steady()).implementation_maturity == 3


def test_maturity_watch_only_is_2():
    assert score_technique(_entry(impls=[_impl(Ring.WATCH)]), _steady()).implementation_maturity == 2


def test_maturity_unringed_or_avoid_is_1():
    assert score_technique(_entry(impls=[_impl(None)]), _steady()).implementation_maturity == 1
    assert score_technique(_entry(impls=[_impl(Ring.AVOID)]), _steady()).implementation_maturity == 1


def test_maturity_no_impls_is_1():
    assert score_technique(_entry(), _steady()).implementation_maturity == 1


@pytest.mark.parametrize(("citations", "peer_reviewed", "expected"), [
    (600, True, 5),   # peer-reviewed + >=500
    (600, False, 4),  # >=100 but not peer-reviewed → falls to the >=100 rung
    (150, False, 4),
    (30, False, 3),   # >=25
    (10, True, 3),    # peer-reviewed rescues low counts
    (10, False, 2),
    (None, None, 2),  # unknown → neutral
])
def test_validation_ladder(citations, peer_reviewed, expected):
    score = score_technique(_entry(citations=citations, peer_reviewed=peer_reviewed), _steady())

    assert score.validation == expected


def test_validation_superseded_forces_1():
    entry = _entry(citations=10_000, peer_reviewed=True, superseded="newer-technique")

    assert score_technique(entry, _steady()).validation == 1


def test_reproducibility_ladder():
    tool = [_impl(Ring.ADOPT)]
    model_only = [_impl(Ring.ADOPT, kind=ImplKind.MODEL)]
    assert score_technique(_entry(open_code=True, impls=tool), _steady()).reproducibility == 5
    assert score_technique(_entry(open_code=True), _steady()).reproducibility == 4
    assert score_technique(_entry(open_code=True, impls=model_only), _steady()).reproducibility == 4
    assert score_technique(_entry(impls=tool), _steady()).reproducibility == 3
    assert score_technique(_entry(), _steady()).reproducibility == 1


def test_onprem_impact_mapping():
    assert score_technique(_entry(impact=OnPremImpact.REDUCES_MEMORY), _steady()).onprem_impact == 5
    assert score_technique(_entry(impact=OnPremImpact.REDUCES_LATENCY), _steady()).onprem_impact == 5
    assert score_technique(_entry(impact=OnPremImpact.ENABLES_SCALE), _steady()).onprem_impact == 4
    assert score_technique(_entry(impact=OnPremImpact.IMPROVES_SAFETY), _steady()).onprem_impact == 4
    assert score_technique(_entry(impact=OnPremImpact.IMPROVES_QUALITY), _steady()).onprem_impact == 3


def test_momentum_flows_through_and_average_rounds():
    momentum = MomentumSignal(technique_id="t", score=5, direction="rising")

    score = score_technique(_entry(), momentum)

    assert score.momentum == 5
    expected = round((1 + 1 + 2 + 1 + 5 + 3) / 6, 2)
    assert score.average == expected


def _score(avg: float, maturity: int = 3) -> TechniqueScore:
    return TechniqueScore(
        implementation_breadth=3, implementation_maturity=maturity, validation=3,
        reproducibility=3, momentum=3, onprem_impact=3, average=avg,
    )


def test_ring_no_impls_caps_at_watch_even_with_high_average():
    assert technique_ring(_score(4.8, maturity=5), resolved_count=0) == Ring.WATCH


def test_ring_avoid_stays_reachable_below_the_cap():
    assert technique_ring(_score(1.5), resolved_count=0) == Ring.AVOID


def test_ring_adopt_needs_average_and_maturity():
    assert technique_ring(_score(4.2, maturity=4), resolved_count=3) == Ring.ADOPT
    assert technique_ring(_score(4.2, maturity=3), resolved_count=3) == Ring.PILOT


def test_ring_pilot_and_watch_thresholds():
    assert technique_ring(_score(3.0), resolved_count=2) == Ring.PILOT
    assert technique_ring(_score(2.9), resolved_count=2) == Ring.WATCH
    assert technique_ring(_score(1.9), resolved_count=2) == Ring.AVOID
