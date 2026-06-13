"""Scoring-calibration diagnostic: is the radar's scoring meaningful?

A radar whose scores all cluster in one band, or whose rings flip every scan,
is not making real decisions. This read-only report measures three things from
persisted state:

* **score distribution** — how spread out the 7-dimension averages are (a tight
  cluster means the rubric isn't discriminating);
* **ring distribution** — whether the calibrated rings actually separate
  projects or collapse into one band;
* **stability & evidence** — how much rings churn over the timeline, and how
  often observed evidence (advisories, momentum, license changes) moved a score.

Pure analysis over inputs — no scan, no mutation.
"""

from __future__ import annotations

from pydantic import BaseModel

from radar.models import Ring, ScoredSignal
from radar.pipeline.delta import ChangeType
from radar.storage.history_store import ProjectHistoryEvent


# Above this single-ring share, the batch isn't really being discriminated.
DOMINANCE_THRESHOLD = 0.8


class ScoreStats(BaseModel):
    """Five-number summary of the batch's representative scores."""

    count: int
    minimum: float = 0.0
    p25: float = 0.0
    median: float = 0.0
    p75: float = 0.0
    maximum: float = 0.0
    spread: float = 0.0  # maximum - minimum


class RingChurn(BaseModel):
    """How much rings move over the recorded timeline."""

    total_ring_moves: int = 0
    projects_with_moves: int = 0


class CalibrationReport(BaseModel):
    """The full calibration diagnostic."""

    score_stats: ScoreStats
    ring_counts: dict[str, int]
    dominant_ring_fraction: float = 0.0
    discriminates: bool = False
    evidence_impact: dict[str, int]
    churn: RingChurn


def build_calibration_report(
    scored_signals: list[ScoredSignal],
    ring_by_project: dict[str, Ring],
    history_events: list[ProjectHistoryEvent],
) -> CalibrationReport:
    """Compute the calibration diagnostic from a scan's scored signals + history."""
    # One representative score per project (best by average), to match cards.
    best_by_project: dict[str, ScoredSignal] = {}
    for scored in scored_signals:
        project = scored.signal.project
        current = best_by_project.get(project)
        if current is None or scored.scores.average > current.scores.average:
            best_by_project[project] = scored

    averages = sorted(s.scores.average for s in best_by_project.values())
    score_stats = _score_stats(averages)

    ring_counts: dict[str, int] = {}
    for ring in ring_by_project.values():
        ring_counts[ring.value] = ring_counts.get(ring.value, 0) + 1
    total = sum(ring_counts.values())
    dominant = max(ring_counts.values()) / total if total else 0.0
    # Discriminating = more than one ring used and no single ring dominating.
    discriminates = len(ring_counts) > 1 and dominant <= DOMINANCE_THRESHOLD

    evidence_impact: dict[str, int] = {}
    for scored in best_by_project.values():
        for code in scored.reason_codes:
            evidence_impact[code] = evidence_impact.get(code, 0) + 1

    return CalibrationReport(
        score_stats=score_stats,
        ring_counts=ring_counts,
        dominant_ring_fraction=round(dominant, 3),
        discriminates=discriminates,
        evidence_impact=evidence_impact,
        churn=_churn(history_events),
    )


def _score_stats(sorted_avgs: list[float]) -> ScoreStats:
    if not sorted_avgs:
        return ScoreStats(count=0)
    return ScoreStats(
        count=len(sorted_avgs),
        minimum=sorted_avgs[0],
        p25=_quantile(sorted_avgs, 0.25),
        median=_quantile(sorted_avgs, 0.5),
        p75=_quantile(sorted_avgs, 0.75),
        maximum=sorted_avgs[-1],
        spread=round(sorted_avgs[-1] - sorted_avgs[0], 2),
    )


def _quantile(sorted_values: list[float], q: float) -> float:
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = (len(sorted_values) - 1) * q
    low = int(pos)
    high = min(low + 1, len(sorted_values) - 1)
    frac = pos - low
    return round(sorted_values[low] + (sorted_values[high] - sorted_values[low]) * frac, 2)


def _churn(events: list[ProjectHistoryEvent]) -> RingChurn:
    moves = [e for e in events if e.change_type in {ChangeType.PROMOTED, ChangeType.DEMOTED}]
    return RingChurn(
        total_ring_moves=len(moves),
        projects_with_moves=len({e.project for e in moves}),
    )


def render_calibration_markdown(report: CalibrationReport) -> str:
    """Render the calibration report as Markdown."""
    if report.score_stats.count == 0:
        return "# Scoring Calibration\n\nNo scored signals to analyze yet. Run `radar scan` first.\n"

    stats = report.score_stats
    lines = [
        "# Scoring Calibration",
        "",
        f"**Verdict:** rings {'discriminate' if report.discriminates else 'do NOT discriminate well'} "
        f"(largest single ring = {report.dominant_ring_fraction:.0%} of projects).",
        "",
        "## Score distribution",
        "",
        f"- Projects scored: {stats.count}",
        f"- Range: {stats.minimum} … {stats.maximum} (spread {stats.spread})",
        f"- Quartiles: p25 {stats.p25} · median {stats.median} · p75 {stats.p75}",
    ]
    if stats.spread < 1.0:
        lines.append(
            "- ⚠ Scores are tightly clustered (spread < 1.0) — calibration is "
            "doing the heavy lifting; consider widening the rubric."
        )

    lines += ["", "## Ring distribution", ""]
    for ring in ("adopt", "pilot", "watch", "avoid"):
        if ring in report.ring_counts:
            lines.append(f"- `{ring}`: {report.ring_counts[ring]}")

    lines += ["", "## Evidence impact", ""]
    if report.evidence_impact:
        for code, count in sorted(
            report.evidence_impact.items(), key=lambda kv: kv[1], reverse=True
        ):
            lines.append(f"- `{code}`: {count}")
    else:
        lines.append("- No evidence-driven score adjustments this scan.")

    lines += [
        "",
        "## Ring stability",
        "",
        f"- Ring moves recorded: {report.churn.total_ring_moves} "
        f"across {report.churn.projects_with_moves} project(s).",
    ]
    return "\n".join(lines) + "\n"
