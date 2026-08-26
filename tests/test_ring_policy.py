"""Policy invariants for the hybrid ring calibration.

These lock the guarantees documented in ``scoring.calibrate`` so future
threshold edits cannot silently break them:
- a weak batch yields NO adopt (absolute excellence only),
- a dangerous tool is always AVOID regardless of average,
- the capped relative promotion never floods ADOPT,
- the bottom of the batch is visible as WATCH.
"""

from __future__ import annotations

from radar.models import Ring
from radar.scoring.calibrate import calibrate_rings
from radar.scoring.rings import ring_from_score


def entry(avg: float, security: int, tiebreak: float = 0.0) -> tuple:
    return (avg, security, tiebreak)


def test_weak_batch_yields_no_adopt() -> None:
    # Everything below the relative floor (4.0) and below absolute
    # excellence (4.15): a genuinely weak batch must produce no ADOPT.
    rings = calibrate_rings([entry(3.95, 3), entry(3.8, 3), entry(3.6, 3)])
    assert Ring.ADOPT not in rings


def test_relative_promotion_requires_merit_floor() -> None:
    # Above the relative floor, secure candidates may promote even without
    # absolute excellence — that is the capped-relative layer working.
    rings = calibrate_rings([entry(4.05, 3), entry(4.0, 3), entry(3.9, 3)])
    assert Ring.ADOPT in rings


def test_absolute_excellence_is_always_adopt_when_secure() -> None:
    rings = calibrate_rings([entry(4.2, 3)])
    assert rings == [Ring.ADOPT]


def test_dangerous_tool_is_avoid_regardless_of_average() -> None:
    # Excellent average but security posture 1 must not slip into pilot.
    assert ring_from_score(4.5, 1) is Ring.AVOID
    rings = calibrate_rings([entry(4.5, 1), entry(4.4, 0)])
    assert all(r is Ring.AVOID for r in rings)


def test_relative_promotion_is_capped_not_flooding() -> None:
    # A tie cluster at 4.1 with strong security: relative promotion may
    # fill ADOPT up to the cap, but not every member.
    batch = [entry(4.1, 3, tiebreak=i / 100) for i in range(20)]
    rings = calibrate_rings(batch)
    adopt_count = sum(1 for r in rings if r is Ring.ADOPT)
    assert 0 < adopt_count < len(batch)


def test_bottom_of_batch_stays_visible_as_watch() -> None:
    batch = [entry(4.3, 3), entry(4.25, 3), entry(3.0, 3), entry(2.9, 3)]
    rings = calibrate_rings(batch)
    assert Ring.WATCH in rings


def test_security_below_three_never_promotes_to_adopt() -> None:
    batch = [entry(4.1, 2), entry(4.12, 2)]
    rings = calibrate_rings(batch)
    assert Ring.ADOPT not in rings
