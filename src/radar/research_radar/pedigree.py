"""Research pedigree: invert technique implementations into ref → techniques.

The index answers "which techniques does this tool/model implement?" for
cards, detail pages, and MCP payloads. Display and evidence only — pedigree
is never a scoring input (spec §9).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from radar.models import Ring
from radar.research_radar.entities import ImplKind, TechniqueEntry


_RING_SORT = {Ring.ADOPT: 0, Ring.PILOT: 1, Ring.WATCH: 2, Ring.AVOID: 3, None: 4}
_NOTE_NAME_LIMIT = 3


class TechniquePedigree(BaseModel):
    """One technique as seen from an implementing tool/model."""

    model_config = ConfigDict(frozen=True)

    technique_id: str
    name: str
    ring: Ring | None = None
    citation_count: int | None = None


class PedigreeIndex(BaseModel):
    """ref → techniques, split by ref kind (tool source id vs model id)."""

    model_config = ConfigDict(frozen=True)

    by_tool_ref: dict[str, list[TechniquePedigree]] = Field(default_factory=dict)
    by_model_ref: dict[str, list[TechniquePedigree]] = Field(default_factory=dict)


def build_pedigree_index(entries: list[TechniqueEntry]) -> PedigreeIndex:
    by_tool: dict[str, list[TechniquePedigree]] = {}
    by_model: dict[str, list[TechniquePedigree]] = {}
    for entry in entries:
        pedigree = TechniquePedigree(
            technique_id=entry.id, name=entry.name, ring=entry.ring,
            citation_count=entry.citation_count,
        )
        for impl in entry.resolved_implementations:
            target = by_tool if impl.kind == ImplKind.TOOL else by_model
            target.setdefault(impl.ref, []).append(pedigree)
    return PedigreeIndex(by_tool_ref=by_tool, by_model_ref=by_model)


def pedigree_for_refs(
    index_map: dict[str, list[TechniquePedigree]], refs: list[str],
) -> list[TechniquePedigree]:
    """Union across refs, dedup by technique id, best ring first then id."""
    seen: dict[str, TechniquePedigree] = {}
    for ref in refs:
        for item in index_map.get(ref, []):
            seen.setdefault(item.technique_id, item)
    return sorted(seen.values(), key=lambda t: (_RING_SORT[t.ring], t.technique_id))


def pedigree_note(items: list[TechniquePedigree]) -> str | None:
    """Human-readable evidence line, or None when there is nothing to say."""
    if not items:
        return None
    adopt = sum(1 for t in items if t.ring == Ring.ADOPT)
    noun = "technique" if len(items) == 1 else "techniques"
    counts = f"Implements {len(items)} tracked research {noun}"
    if adopt:
        counts += f" ({adopt} adopt-ring)"
    names = ", ".join(t.name for t in items[:_NOTE_NAME_LIMIT])
    suffix = "…" if len(items) > _NOTE_NAME_LIMIT else ""
    return f"{counts}: {names}{suffix}"
