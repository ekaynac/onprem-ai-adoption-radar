"""Schema layer: entities + technique-seed loader."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from radar.models import Category, Ring
from radar.research_radar.entities import (
    ImplementationLink,
    ImplKind,
    OnPremImpact,
    PaperLink,
    ResolvedImplementation,
    TechniqueDomain,
    TechniqueEntry,
    TechniqueScore,
)
from radar.research_radar.seed import TechniqueSeedError, load_technique_seed


VALID_SEED = """
techniques:
  - id: speculative-decoding
    name: Speculative Decoding
    category: model_serving
    domain: inference
    aliases: ["speculative sampling"]
    papers:
      - arxiv_id: "2211.17192"
        title: "Fast Inference from Transformers via Speculative Decoding"
    implementations:
      - kind: tool
        ref: github-vllm
      - kind: model
        ref: llama-3.3-70b
    open_code: true
    onprem_impact: reduces_latency
"""


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "technique-seed.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_load_valid_seed(tmp_path):
    seeds = load_technique_seed(_write(tmp_path, VALID_SEED))

    assert len(seeds) == 1
    seed = seeds[0]
    assert seed.id == "speculative-decoding"
    assert seed.category == Category.MODEL_SERVING
    assert seed.domain == TechniqueDomain.INFERENCE
    assert seed.papers[0].arxiv_id == "2211.17192"
    assert seed.papers[0].role.value == "canonical"  # default
    assert seed.implementations[0] == ImplementationLink(kind=ImplKind.TOOL, ref="github-vllm")
    assert seed.onprem_impact == OnPremImpact.REDUCES_LATENCY
    assert seed.enabled is True
    assert seed.superseded_by is None


def test_missing_file_raises(tmp_path):
    with pytest.raises(TechniqueSeedError, match="not found"):
        load_technique_seed(tmp_path / "nope.yaml")


def test_invalid_yaml_raises(tmp_path):
    with pytest.raises(TechniqueSeedError, match="Invalid YAML"):
        load_technique_seed(_write(tmp_path, "techniques: [::"))


def test_unknown_field_rejected(tmp_path):
    bad = VALID_SEED + "    stars: 100\n"
    with pytest.raises(TechniqueSeedError, match="validation failed"):
        load_technique_seed(_write(tmp_path, bad))


def test_duplicate_ids_rejected(tmp_path):
    dup = VALID_SEED + VALID_SEED.replace("techniques:\n", "")
    with pytest.raises(TechniqueSeedError, match=r"[Dd]uplicate"):
        load_technique_seed(_write(tmp_path, dup))


def test_dangling_superseded_by_rejected(tmp_path):
    bad = VALID_SEED + "    superseded_by: not-a-technique\n"
    with pytest.raises(TechniqueSeedError, match="superseded_by"):
        load_technique_seed(_write(tmp_path, bad))


def test_self_superseded_by_rejected(tmp_path):
    bad = VALID_SEED + "    superseded_by: speculative-decoding\n"
    with pytest.raises(TechniqueSeedError, match="own id"):
        load_technique_seed(_write(tmp_path, bad))


def test_non_mapping_top_level_rejected(tmp_path):
    bare_list = "- id: speculative-decoding\n  name: Speculative Decoding\n"
    with pytest.raises(TechniqueSeedError, match="mapping"):
        load_technique_seed(_write(tmp_path, bare_list))


def test_superseded_by_resolving_to_seeded_id_is_accepted(tmp_path):
    two = VALID_SEED + """
  - id: medusa
    name: Medusa
    category: model_serving
    domain: inference
    onprem_impact: reduces_latency
    superseded_by: speculative-decoding
"""
    seeds = load_technique_seed(_write(tmp_path, two))

    assert seeds[1].superseded_by == "speculative-decoding"


def test_technique_entry_is_frozen_with_optional_enrichment():
    entry = TechniqueEntry(
        id="lora",
        name="LoRA",
        category=Category.AI_INFRASTRUCTURE,
        domain=TechniqueDomain.FINE_TUNING,
        onprem_impact=OnPremImpact.REDUCES_MEMORY,
    )

    assert entry.citation_count is None
    assert entry.ring is None
    assert entry.warnings == []
    assert entry.momentum_direction is None
    assert entry.momentum_note is None
    with pytest.raises(ValidationError):
        entry.name = "changed"  # type: ignore[misc]


def test_technique_entry_validates_old_snapshot_missing_momentum_keys():
    """Back-compat: technique_cards.json written before momentum fields existed."""
    old_snapshot = {
        "id": "lora",
        "name": "LoRA",
        "category": "ai_infrastructure",
        "domain": "fine_tuning",
        "onprem_impact": "reduces_memory",
    }

    entry = TechniqueEntry.model_validate(old_snapshot)

    assert entry.momentum_direction is None
    assert entry.momentum_note is None


def test_technique_score_bounds():
    with pytest.raises(ValidationError):
        TechniqueScore(
            implementation_breadth=0, implementation_maturity=1, validation=1,
            reproducibility=1, momentum=1, onprem_impact=1, average=1.0,
        )


def test_resolved_implementation_carries_ring():
    resolved = ResolvedImplementation(kind=ImplKind.TOOL, ref="github-vllm", ring=Ring.ADOPT)

    assert resolved.ring == Ring.ADOPT


def test_paper_link_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        PaperLink(arxiv_id="1", title="t", doi="nope")  # type: ignore[call-arg]


def test_packaged_starter_seed_loads_and_is_coherent():
    packaged = Path(__file__).resolve().parents[1] / "config" / "technique-seed.yaml"

    seeds = load_technique_seed(packaged)

    assert len(seeds) >= 15
    assert len({s.id for s in seeds}) == len(seeds)
    domains = {s.domain for s in seeds}
    assert TechniqueDomain.INFERENCE in domains
    assert TechniqueDomain.FINE_TUNING in domains
    assert TechniqueDomain.AGENT_ARCHITECTURE in domains
    assert TechniqueDomain.RAG in domains
    # every technique with papers has exactly one canonical paper
    for seed in seeds:
        if seed.papers:
            assert sum(1 for p in seed.papers if p.role.value == "canonical") == 1
