"""Distribution-aware (hybrid) ring calibration.

The deterministic 7-dimension average compresses into a narrow band (live data
sat at 3.43–4.29), so fixed absolute thresholds collapse every project into one
ring. This calibrates rings using BOTH:

* absolute gates — a security/blocker floor (AVOID) and an excellence ceiling
  (ADOPT) that hold regardless of the batch, so a genuinely weak batch never
  produces an ADOPT and a dangerous tool is always AVOID; and
* relative position — within the acceptable middle, the batch quartiles split
  projects so the rings actually discriminate (top quartile → ADOPT when secure
  and above a relative floor, bottom quartile → WATCH).

Input is a list of ``(average, security_posture)`` pairs; output is one Ring per
input in the same order. Pure — no mutation, no I/O.
"""

from __future__ import annotations

from radar.models import Ring

# Absolute gates (hold regardless of the batch distribution).
AVOID_AVG = 2.5
AVOID_SECURITY = 1
ADOPT_SECURITY = 3
ABSOLUTE_ADOPT = 4.15  # excellent on its own merits
ABSOLUTE_PILOT_FLOOR = 3.4  # below this is never better than WATCH
RELATIVE_ADOPT_FLOOR = 3.8  # quartile promotion needs at least this much merit


def calibrate_rings(entries: list[tuple[float, int]]) -> list[Ring]:
    """Assign a ring to each (average, security_posture) entry."""
    if not entries:
        return []

    averages = sorted(a for a, _ in entries)
    q25 = _quantile(averages, 0.25)
    q75 = _quantile(averages, 0.75)

    return [_ring(avg, security, q25, q75) for avg, security in entries]


def _ring(avg: float, security: int, q25: float, q75: float) -> Ring:
    # Absolute blocker first — never overridden by relative position.
    if avg < AVOID_AVG or security <= AVOID_SECURITY:
        return Ring.AVOID

    secure = security >= ADOPT_SECURITY
    # Absolute excellence, or relative excellence within an acceptable band.
    if secure and (
        avg >= ABSOLUTE_ADOPT or (avg >= q75 and avg >= RELATIVE_ADOPT_FLOOR)
    ):
        return Ring.ADOPT

    # Relatively weak (strictly below the lower quartile, so a lone or all-equal
    # batch is never self-demoted), or below the absolute pilot floor → WATCH.
    if avg < q25 or avg < ABSOLUTE_PILOT_FLOOR:
        return Ring.WATCH

    return Ring.PILOT


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
