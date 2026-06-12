"""Tests for distribution-aware (hybrid) ring calibration."""

from __future__ import annotations

from radar.models import Ring
from radar.scoring.calibrate import calibrate_rings


def test_empty_input():
    assert calibrate_rings([]) == []


def test_security_blocker_always_avoid():
    # Even a top score with no security posture is AVOID.
    rings = calibrate_rings([(4.9, 1), (3.8, 4)])
    assert rings[0] == Ring.AVOID


def test_absolute_avoid_for_very_low_average():
    rings = calibrate_rings([(2.0, 4), (3.8, 4)])
    assert rings[0] == Ring.AVOID


def test_spread_batch_discriminates_into_three_rings():
    # A realistic compressed-but-ranked batch (like the live data).
    averages = [4.29, 4.14, 4.0, 3.86, 3.71, 3.57, 3.43]
    entries = [(a, 4) for a in averages]
    rings = calibrate_rings(entries)
    # Top must reach ADOPT, bottom must fall to WATCH, middle PILOT.
    assert rings[0] == Ring.ADOPT
    assert rings[-1] == Ring.WATCH
    assert Ring.PILOT in rings
    # Not everything in one ring (the bug we are fixing).
    assert len(set(rings)) >= 3


def test_relative_promotion_requires_security():
    # Top of the batch but weak security → cannot be ADOPT.
    entries = [(4.2, 2), (3.5, 4), (3.4, 4)]
    rings = calibrate_rings(entries)
    assert rings[0] != Ring.ADOPT


def test_no_adopt_when_whole_batch_is_weak():
    # Quartiles must not promote a "best of a bad batch" to ADOPT.
    entries = [(2.9, 4), (2.8, 4), (2.7, 4), (2.6, 4)]
    rings = calibrate_rings(entries)
    assert Ring.ADOPT not in rings


def test_absolute_adopt_floor_independent_of_quartile():
    # An excellent score is ADOPT even if it is the batch minimum.
    entries = [(4.6, 4), (4.7, 4), (4.8, 4)]
    rings = calibrate_rings(entries)
    assert all(r == Ring.ADOPT for r in rings)
