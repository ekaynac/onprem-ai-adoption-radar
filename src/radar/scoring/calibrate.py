"""Distribution-aware (hybrid) ring calibration.

The deterministic 7-dimension average compresses into a narrow band (live data
sat at 3.43–4.29, with a large tie cluster at 4.14), so neither fixed thresholds
nor a plain quartile cut produce a useful ADOPT set: thresholds collapse
everything into one ring, and a quartile boundary that lands on the tie cluster
promotes all of it. This calibrates with three layers:

* absolute gates — a security/blocker floor (AVOID) and an excellence ceiling
  (ADOPT) that hold regardless of the batch, so a weak batch yields no ADOPT and
  a dangerous tool is always AVOID;
* a capped relative promotion — among acceptable, secure candidates below the
  absolute ceiling, only enough are promoted to reach a target ADOPT size,
  ranked by average then a tiebreak (on-prem relevance), so a tie cluster does
  not flood ADOPT; and
* a relative WATCH floor — projects below the lower quartile (or the absolute
  pilot floor) drop to WATCH so the bottom is visible too.

Each entry is ``(average, security_posture)`` or ``(average, security_posture,
tiebreak)``; output is one Ring per entry in input order. Pure — no mutation,
no I/O.
"""

from __future__ import annotations

import math

from radar.models import Ring


# Absolute gates (hold regardless of the batch distribution).
AVOID_AVG = 2.5
AVOID_SECURITY = 1
ADOPT_SECURITY = 3
ABSOLUTE_ADOPT = 4.15  # excellent on its own merits — always ADOPT when secure
ABSOLUTE_PILOT_FLOOR = 3.4  # below this is never better than WATCH
RELATIVE_ADOPT_FLOOR = 4.0  # relative promotion needs at least this much merit

# Target ADOPT breadth: a fraction of the batch, bounded, so "Try This Week"
# stays a short, high-conviction list even when many projects score well.
ADOPT_FRACTION = 0.22
ADOPT_MIN = 3
ADOPT_MAX = 12


def calibrate_rings(entries: list[tuple]) -> list[Ring]:
    """Assign a ring to each (average, security_posture[, tiebreak]) entry."""
    if not entries:
        return []

    parsed = [_parse(entry) for entry in entries]
    averages = sorted(avg for avg, _, _ in parsed)
    q25 = _quantile(averages, 0.25)

    rings: list[Ring | None] = [None] * len(parsed)

    # Absolute blocker first — never overridden by anything below.
    for i, (avg, security, _) in enumerate(parsed):
        if avg < AVOID_AVG or security <= AVOID_SECURITY:
            rings[i] = Ring.AVOID

    # Absolute excellence: always ADOPT when secure, uncapped.
    for i, (avg, security, _) in enumerate(parsed):
        if rings[i] is None and security >= ADOPT_SECURITY and avg >= ABSOLUTE_ADOPT:
            rings[i] = Ring.ADOPT

    # Capped relative promotion to reach the target ADOPT size.
    target = _adopt_target(len(parsed))
    already = sum(1 for r in rings if r == Ring.ADOPT)
    pool = [
        i
        for i, (avg, security, _) in enumerate(parsed)
        if rings[i] is None
        and security >= ADOPT_SECURITY
        and avg >= RELATIVE_ADOPT_FLOOR
    ]
    # Rank by average, then tiebreak (e.g. on-prem relevance), highest first.
    pool.sort(key=lambda i: (parsed[i][0], parsed[i][2]), reverse=True)
    for i in pool[: max(0, target - already)]:
        rings[i] = Ring.ADOPT

    # Everyone else: relative/absolute WATCH floor, otherwise PILOT.
    for i, (avg, _, _) in enumerate(parsed):
        if rings[i] is None:
            if avg < q25 or avg < ABSOLUTE_PILOT_FLOOR:
                rings[i] = Ring.WATCH
            else:
                rings[i] = Ring.PILOT

    return [r for r in rings if r is not None]


def _adopt_target(n: int) -> int:
    return max(ADOPT_MIN, min(ADOPT_MAX, math.ceil(n * ADOPT_FRACTION)))


def _parse(entry: tuple) -> tuple[float, int, float]:
    avg, security, *rest = entry
    tiebreak = rest[0] if rest else avg
    return avg, security, tiebreak


def _quantile(sorted_values: list[float], q: float) -> float:
    """Linear-interpolation quantile over a pre-sorted list."""
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = (len(sorted_values) - 1) * q
    low = int(pos)
    high = min(low + 1, len(sorted_values) - 1)
    frac = pos - low
    return sorted_values[low] + (sorted_values[high] - sorted_values[low]) * frac
