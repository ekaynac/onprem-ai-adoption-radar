"""Tests for the side-by-side project comparison matrix."""

from __future__ import annotations

import pytest

from radar.models import Category, DecisionCard, OnPremAssessment, Ring
from radar.reports.comparison import (
    ComparisonError,
    build_comparison,
    render_comparison_markdown,
)


def _card(project, ring, risk, rubric, category=Category.CODING_AGENTS) -> DecisionCard:
    return DecisionCard(
        project=project,
        category=category,
        ring=ring,
        summary="x",
        workflow_fit={},
        risk_level=risk,
        on_prem_rubric={k: OnPremAssessment(score=v, reason="r") for k, v in rubric.items()},
    )


def _cards():
    return [
        _card("Cline", Ring.PILOT, "medium", {"deployment_complexity": 4, "license_commercial_risk": 5}),
        _card("Aider", Ring.ADOPT, "low", {"deployment_complexity": 5, "enterprise_integration": 3}),
        _card("Goose", Ring.WATCH, "high", {"deployment_complexity": 2, "license_commercial_risk": 4}),
    ]


# ── selection ─────────────────────────────────────────────────────────────────


def test_build_comparison_by_explicit_projects():
    comp = build_comparison(_cards(), projects=["Cline", "Aider"])
    assert comp.projects == ["Cline", "Aider"]


def test_build_comparison_by_category():
    comp = build_comparison(_cards(), category=Category.CODING_AGENTS)
    assert set(comp.projects) == {"Cline", "Aider", "Goose"}


def test_build_comparison_requires_a_selector():
    with pytest.raises(ComparisonError):
        build_comparison(_cards())


def test_build_comparison_unknown_project_raises():
    with pytest.raises(ComparisonError) as exc:
        build_comparison(_cards(), projects=["Cline", "Nope"])
    assert "Nope" in str(exc.value)


def test_build_comparison_needs_two_projects():
    with pytest.raises(ComparisonError):
        build_comparison(_cards(), projects=["Cline"])


# ── rows ──────────────────────────────────────────────────────────────────────


def test_comparison_has_ring_and_risk_rows():
    comp = build_comparison(_cards(), projects=["Cline", "Aider"])
    labels = [r.label for r in comp.rows]
    assert "Ring" in labels
    assert "Risk" in labels


def test_comparison_includes_union_of_rubric_dimensions():
    comp = build_comparison(_cards(), projects=["Cline", "Aider"])
    labels = [r.label.lower() for r in comp.rows]
    # Cline has license_commercial_risk; Aider has enterprise_integration.
    assert any("deployment" in l for l in labels)
    assert any("license" in l for l in labels)
    assert any("enterprise" in l for l in labels)


def test_missing_dimension_renders_dash():
    comp = build_comparison(_cards(), projects=["Cline", "Aider"])
    ent_row = next(r for r in comp.rows if "enterprise" in r.label.lower())
    # Cline lacks enterprise_integration → placeholder, Aider has 3.
    assert ent_row.values["Cline"] == "—"
    assert ent_row.values["Aider"] == "3"


# ── render ────────────────────────────────────────────────────────────────────


def test_render_markdown_table():
    comp = build_comparison(_cards(), projects=["Cline", "Aider"])
    md = render_comparison_markdown(comp, "Coding Agents")
    assert md.startswith("# Coding Agents")
    assert "| Cline | Aider |" in md
    assert "adopt" in md  # Aider's ring
