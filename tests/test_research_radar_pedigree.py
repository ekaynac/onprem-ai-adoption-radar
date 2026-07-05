"""Pedigree index: invert technique implementations into ref → techniques."""

from __future__ import annotations

from radar.models import Category, Ring
from radar.research_radar.entities import (
    ImplKind,
    OnPremImpact,
    ResolvedImplementation,
    TechniqueDomain,
    TechniqueEntry,
)
from radar.research_radar.pedigree import (
    PedigreeIndex,
    TechniquePedigree,
    build_pedigree_index,
    pedigree_for_refs,
    pedigree_note,
)


def _impl(kind: ImplKind, ref: str, ring: Ring | None = None) -> ResolvedImplementation:
    return ResolvedImplementation(kind=kind, ref=ref, ring=ring)


def _entry(technique_id: str, name: str, ring: Ring | None,
           impls: list[ResolvedImplementation], citations: int | None = 100) -> TechniqueEntry:
    return TechniqueEntry(
        id=technique_id, name=name, category=Category.MODEL_SERVING,
        domain=TechniqueDomain.INFERENCE, onprem_impact=OnPremImpact.REDUCES_LATENCY,
        ring=ring, citation_count=citations, resolved_implementations=impls,
    )


def test_build_index_inverts_tool_and_model_refs():
    entries = [
        _entry("spec-dec", "Speculative Decoding", Ring.ADOPT, [
            _impl(ImplKind.TOOL, "github-vllm", Ring.PILOT),
            _impl(ImplKind.MODEL, "llama-3.3-70b", Ring.PILOT),
        ]),
        _entry("paged-attention", "PagedAttention", Ring.PILOT, [
            _impl(ImplKind.TOOL, "github-vllm", Ring.PILOT),
        ]),
    ]

    index = build_pedigree_index(entries)

    vllm = index.by_tool_ref["github-vllm"]
    assert {t.technique_id for t in vllm} == {"spec-dec", "paged-attention"}
    assert index.by_model_ref["llama-3.3-70b"][0].technique_id == "spec-dec"
    assert vllm[0].citation_count == 100


def test_index_carries_technique_ring_not_impl_ring():
    entries = [_entry("spec-dec", "Speculative Decoding", Ring.ADOPT,
                      [_impl(ImplKind.TOOL, "github-vllm", Ring.WATCH)])]

    index = build_pedigree_index(entries)

    assert index.by_tool_ref["github-vllm"][0].ring == Ring.ADOPT


def test_empty_entries_give_empty_index():
    index = build_pedigree_index([])

    assert index == PedigreeIndex()


def test_pedigree_for_refs_unions_dedups_and_sorts_best_ring_first():
    items_a = [
        TechniquePedigree(technique_id="watch-one", name="W", ring=Ring.WATCH, citation_count=1),
        TechniquePedigree(technique_id="adopt-one", name="A", ring=Ring.ADOPT, citation_count=2),
    ]
    items_b = [
        TechniquePedigree(technique_id="adopt-one", name="A", ring=Ring.ADOPT, citation_count=2),
        TechniquePedigree(technique_id="unringed", name="U", ring=None, citation_count=None),
    ]
    index_map = {"src-a": items_a, "src-b": items_b}

    merged = pedigree_for_refs(index_map, ["src-a", "src-b", "src-missing"])

    assert [t.technique_id for t in merged] == ["adopt-one", "watch-one", "unringed"]


def test_pedigree_note_formats_counts_and_top_three():
    items = [
        TechniquePedigree(technique_id="a", name="Alpha", ring=Ring.ADOPT, citation_count=1),
        TechniquePedigree(technique_id="b", name="Beta", ring=Ring.ADOPT, citation_count=2),
        TechniquePedigree(technique_id="c", name="Gamma", ring=Ring.PILOT, citation_count=3),
        TechniquePedigree(technique_id="d", name="Delta", ring=Ring.WATCH, citation_count=4),
    ]

    note = pedigree_note(items)

    assert note == ("Implements 4 tracked research techniques (2 adopt-ring): "
                    "Alpha, Beta, Gamma…")


def test_pedigree_note_singular_no_adopt_no_ellipsis():
    items = [TechniquePedigree(technique_id="a", name="Alpha", ring=Ring.WATCH,
                               citation_count=None)]

    assert pedigree_note(items) == "Implements 1 tracked research technique: Alpha"
    assert pedigree_note([]) is None
