"""Closed-loop resolution: implementation links → current rings from own catalogs."""

from radar.models import Ring
from radar.research_radar.entities import ImplementationLink, ImplKind
from radar.research_radar.resolve import (
    ResolutionContext,
    build_resolution_context,
    resolve_implementations,
)


def _context(**kwargs) -> ResolutionContext:
    defaults = {"tool_rings": {}, "model_rings": {}, "warnings": []}
    defaults.update(kwargs)
    return ResolutionContext(**defaults)


def test_tool_link_resolves_with_ring():
    context = _context(tool_rings={"github-vllm": Ring.ADOPT})

    resolved, warnings = resolve_implementations(
        [ImplementationLink(kind=ImplKind.TOOL, ref="github-vllm")], context
    )

    assert warnings == []
    assert resolved[0].ring == Ring.ADOPT
    assert resolved[0].kind == ImplKind.TOOL


def test_model_link_resolves_with_ring():
    context = _context(model_rings={"llama-3.3-70b": Ring.PILOT})

    resolved, _warnings = resolve_implementations(
        [ImplementationLink(kind=ImplKind.MODEL, ref="llama-3.3-70b")], context
    )

    assert resolved[0].ring == Ring.PILOT


def test_known_entity_without_ring_resolves_as_unringed():
    context = _context(tool_rings={"github-new-tool": None})

    resolved, warnings = resolve_implementations(
        [ImplementationLink(kind=ImplKind.TOOL, ref="github-new-tool")], context
    )

    assert warnings == []
    assert resolved[0].ring is None


def test_dangling_ref_warns_and_drops():
    resolved, warnings = resolve_implementations(
        [ImplementationLink(kind=ImplKind.TOOL, ref="github-removed")], _context()
    )

    assert resolved == []
    assert "github-removed" in warnings[0]


def test_build_context_from_real_stores(tmp_path):
    from radar.models import Category, DecisionCard
    from radar.storage.database import RadarDatabase

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
sources:
  - id: github-vllm
    type: github_repo
    project: vLLM
    category: model_serving
    url: https://github.com/vllm-project/vllm
""",
        encoding="utf-8",
    )
    db = RadarDatabase(tmp_path / "radar.db")
    db.initialize()
    db.upsert_cards([DecisionCard(
        project="vLLM", category=Category.MODEL_SERVING, ring=Ring.ADOPT,
        summary="s", workflow_fit={}, risk_level="low",
    )])
    model_seed = tmp_path / "model-seed.yaml"
    model_seed.write_text(
        "models:\n  - id: llama-3.3-70b\n    name: Llama 3.3 70B\n    family: llama\n",
        encoding="utf-8",
    )

    context = build_resolution_context(
        config_path, tmp_path / "radar.db", model_seed, tmp_path / "model-history.jsonl"
    )

    assert context.tool_rings == {"github-vllm": Ring.ADOPT}
    assert context.model_rings == {"llama-3.3-70b": None}  # seeded, never ringed


def test_build_context_degrades_when_stores_missing(tmp_path):
    context = build_resolution_context(
        tmp_path / "no-config.yaml", tmp_path / "no.db",
        tmp_path / "no-model-seed.yaml", tmp_path / "no-history.jsonl",
    )

    assert context.tool_rings == {}
    assert context.model_rings == {}
    assert len(context.warnings) == 2  # config unavailable + model seed unavailable
