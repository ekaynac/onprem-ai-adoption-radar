"""Ring assignment rules."""

from __future__ import annotations

from radar.models import Ring


def ring_from_score(average: float, security_posture: int) -> Ring:
    """Map an average score and security posture to a radar ring (absolute).

    This is the per-signal absolute recommendation. The final card ring is
    calibrated across the batch (see ``scoring.calibrate``); the absolute gates
    here are kept aligned with that module.
    """
    if average < 2.5 or security_posture <= 1:
        return Ring.AVOID
    if average >= 4.15 and security_posture >= 3:
        return Ring.ADOPT
    if average >= 3.4:
        return Ring.PILOT
    return Ring.WATCH
