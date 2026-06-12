"""Side-by-side project comparison matrices.

Turns the accumulated per-project decision cards into a decision aid:
"Cline vs Aider vs Goose" across ring, risk, and the deterministic on-prem
rubric dimensions. Pure and deterministic — it reads existing card data, runs
no scan and no LLM.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from radar.models import Category, DecisionCard


_MISSING = "—"
_MIN_PROJECTS = 2


class ComparisonError(ValueError):
    """Raised when a comparison cannot be built."""


@dataclass(frozen=True)
class ComparisonRow:
    """One comparison dimension across the selected projects."""

    label: str
    values: dict[str, str]


@dataclass(frozen=True)
class Comparison:
    """A resolved comparison matrix: projects (columns) x rows."""

    projects: list[str]
    rows: list[ComparisonRow] = field(default_factory=list)


def build_comparison(
    cards: list[DecisionCard],
    *,
    projects: list[str] | None = None,
    category: Category | None = None,
) -> Comparison:
    """Build a comparison from cards, selected by explicit projects or category.

    Exactly one selector is required. Rows are ring, risk, then the union of
    on-prem rubric dimensions across the selected cards (missing cells are
    filled with a placeholder). Inputs are never mutated.
    """
    selected = _select(cards, projects=projects, category=category)
    if len(selected) < _MIN_PROJECTS:
        raise ComparisonError(
            f"Need at least {_MIN_PROJECTS} projects to compare, got {len(selected)}."
        )

    names = [card.project for card in selected]
    rows: list[ComparisonRow] = [
        ComparisonRow("Ring", {c.project: c.ring.value for c in selected}),
        ComparisonRow("Risk", {c.project: c.risk_level for c in selected}),
    ]
    for dimension in _rubric_dimensions(selected):
        rows.append(
            ComparisonRow(
                _humanize(dimension),
                {c.project: _rubric_value(c, dimension) for c in selected},
            )
        )
    return Comparison(projects=names, rows=rows)


def render_comparison_markdown(comparison: Comparison, title: str) -> str:
    """Render a comparison as a Markdown table."""
    header = "| Dimension | " + " | ".join(comparison.projects) + " |"
    divider = "| --- | " + " | ".join("---" for _ in comparison.projects) + " |"
    lines = [f"# {title}", "", header, divider]
    for row in comparison.rows:
        cells = " | ".join(row.values.get(p, _MISSING) for p in comparison.projects)
        lines.append(f"| {row.label} | {cells} |")
    return "\n".join(lines) + "\n"


def _select(
    cards: list[DecisionCard],
    *,
    projects: list[str] | None,
    category: Category | None,
) -> list[DecisionCard]:
    if (projects is None) == (category is None):
        raise ComparisonError("Provide exactly one of: projects, category.")

    if projects is not None:
        by_name = {card.project: card for card in cards}
        missing = [p for p in projects if p not in by_name]
        if missing:
            raise ComparisonError(f"Unknown project(s): {', '.join(missing)}")
        # Preserve caller order, drop duplicates.
        ordered = list(dict.fromkeys(projects))
        return [by_name[p] for p in ordered]

    return sorted(
        (c for c in cards if c.category == category),
        key=lambda c: c.project.lower(),
    )


def _rubric_dimensions(cards: list[DecisionCard]) -> list[str]:
    """Stable union of rubric dimension keys, first-seen order preserved."""
    dimensions: list[str] = []
    for card in cards:
        for key in card.on_prem_rubric:
            if key not in dimensions:
                dimensions.append(key)
    return dimensions


def _rubric_value(card: DecisionCard, dimension: str) -> str:
    assessment = card.on_prem_rubric.get(dimension)
    return str(assessment.score) if assessment is not None else _MISSING


def _humanize(key: str) -> str:
    return key.replace("_", " ").title()
