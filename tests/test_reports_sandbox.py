"""Tests for the per-tool sandbox evaluation plan generator."""

from __future__ import annotations

from radar.models import Category, DecisionCard, Ring
from radar.reports.sandbox import build_sandbox_plan, render_sandbox_markdown


def _card(project="Cline", tags=None, ring=Ring.PILOT) -> DecisionCard:
    return DecisionCard(
        project=project,
        category=Category.CODING_AGENTS,
        ring=ring,
        summary="s",
        workflow_fit={},
        risk_level="medium",
        tags=tags or [],
    )


def test_docker_strategy_for_self_hosted_tags():
    plan = build_sandbox_plan(_card(tags=["self-hosted", "docker"]))
    assert plan.strategy == "docker"
    assert any("docker run" in s for s in plan.steps)
    assert plan.teardown  # always has teardown


def test_python_cli_strategy():
    plan = build_sandbox_plan(_card(tags=["cli", "open-source"]))
    assert plan.strategy == "python-cli"
    assert any("venv" in s or "uvx" in s for s in plan.steps)


def test_node_cli_strategy():
    plan = build_sandbox_plan(_card(tags=["npm"]))
    assert plan.strategy == "node-cli"


def test_unknown_tags_fall_back_to_manual():
    plan = build_sandbox_plan(_card(tags=[]))
    assert plan.strategy == "manual"


def test_dangerous_permissions_add_cautions():
    plan = build_sandbox_plan(
        _card(tags=["docker", "terminal-access", "file-write-access"])
    )
    text = " ".join(plan.cautions).lower()
    assert "permission" in text or "mount" in text or "network" in text
    assert plan.cautions  # non-empty


def test_gpu_required_notes_passthrough():
    plan = build_sandbox_plan(_card(tags=["docker", "gpu-required"]))
    assert any("gpu" in c.lower() for c in plan.cautions)


def test_render_markdown_includes_project_and_steps():
    card = _card(project="Aider", tags=["cli"])
    md = render_sandbox_markdown(card, build_sandbox_plan(card))
    assert md.startswith("# Sandbox trial: Aider")
    assert "## Steps" in md
    assert "## Teardown" in md
