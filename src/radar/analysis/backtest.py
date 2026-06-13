"""Scoring backtest: how would a different lens have changed past decisions?

Re-scores historical runs two ways and reports the ring differences:

* **profile mode** — baseline (current config) vs the same config re-weighted by
  a named profile, per run;
* **config-drift mode** — current config vs each run's persisted decision cards.

This is the comparison/report layer only — the orchestrator supplies the two
card sets per run (it owns the side-effect-free re-scoring). Pure and
deterministic.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from radar.models import DecisionCard, Ring


class RingDiff(BaseModel):
    """A project whose ring differs between baseline and candidate."""

    project: str
    baseline_ring: Ring
    candidate_ring: Ring


class RunBacktest(BaseModel):
    """One run's baseline-vs-candidate comparison."""

    run_id: str
    created_at: datetime
    moved: list[RingDiff]
    baseline_ring_counts: dict[str, int]
    candidate_ring_counts: dict[str, int]

    @classmethod
    def from_card_sets(
        cls,
        run_id: str,
        created_at: datetime,
        baseline: list[DecisionCard],
        candidate: list[DecisionCard],
    ) -> RunBacktest:
        """Diff two card sets for the same run into a RunBacktest."""
        baseline_rings = {c.project: c.ring for c in baseline}
        candidate_rings = {c.project: c.ring for c in candidate}
        moved = [
            RingDiff(
                project=project,
                baseline_ring=baseline_rings[project],
                candidate_ring=candidate_rings[project],
            )
            for project in sorted(baseline_rings.keys() & candidate_rings.keys())
            if baseline_rings[project] != candidate_rings[project]
        ]
        return cls(
            run_id=run_id,
            created_at=created_at,
            moved=moved,
            baseline_ring_counts=_ring_counts(baseline),
            candidate_ring_counts=_ring_counts(candidate),
        )


class BacktestReport(BaseModel):
    """A backtest across runs."""

    mode: str
    runs: list[RunBacktest]
    total_moves: int
    runs_analyzed: int


def build_backtest_report(mode: str, runs: list[RunBacktest]) -> BacktestReport:
    """Aggregate per-run comparisons into a report."""
    return BacktestReport(
        mode=mode,
        runs=runs,
        total_moves=sum(len(r.moved) for r in runs),
        runs_analyzed=len(runs),
    )


def _ring_counts(cards: list[DecisionCard]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for card in cards:
        counts[card.ring.value] = counts.get(card.ring.value, 0) + 1
    return counts


def render_backtest_markdown(report: BacktestReport) -> str:
    """Render the backtest report as Markdown."""
    if not report.runs:
        return (
            "# Scoring Backtest\n\nNo runs to backtest yet. Run `radar scan` first "
            "(a few times, so there's history to compare).\n"
        )

    baseline_label, candidate_label = _labels(report.mode)
    lines = [
        "# Scoring Backtest",
        "",
        f"**Mode:** {report.mode}",
        f"**Runs analyzed:** {report.runs_analyzed} · "
        f"**Total ring moves:** {report.total_moves} "
        f"({baseline_label} → {candidate_label})",
        "",
    ]
    if report.total_moves == 0:
        lines.append("No ring decisions would change. The lens is stable here.")
        return "\n".join(lines) + "\n"

    for run in report.runs:
        if not run.moved:
            continue
        lines.append(f"## {run.run_id} ({run.created_at.date().isoformat()})")
        lines.append("")
        for diff in run.moved:
            lines.append(
                f"- {diff.project}: `{diff.baseline_ring.value}` → "
                f"`{diff.candidate_ring.value}`"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _labels(mode: str) -> tuple[str, str]:
    if mode.startswith("profile:"):
        return "current config", mode.split(":", 1)[1]
    return "persisted decision", "current config"
