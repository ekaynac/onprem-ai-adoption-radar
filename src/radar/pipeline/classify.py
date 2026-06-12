"""Firehose entry -> tracked-project classification.

A "firehose" source (e.g. a broad vendor blog) emits many entries about many
different projects. Left alone, every entry collapses into a single project
card, flooding the radar. This layer re-attributes each firehose entry to a
*tracked* project (one already configured as its own source) by matching the
entry text against project names and aliases. Entries that match nothing are
dropped, and their titles returned so the caller can log/surface them.

The matcher is fully deterministic — no network, no LLM. The ``Classifier``
shape is a plain function ``(text, index) -> ProjectMatch | None`` so an
optional LLM-backed classifier can be substituted later without changing the
pipeline wiring.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from radar.models import Category, Signal, SourceConfig


@dataclass(frozen=True)
class ProjectMatch:
    """A resolved tracked project for a firehose entry."""

    project: str
    category: Category


@dataclass(frozen=True)
class _Candidate:
    project: str
    category: Category
    # Compiled word-boundary patterns for the project name and its aliases.
    patterns: tuple[re.Pattern, ...]


@dataclass(frozen=True)
class ProjectIndex:
    """Searchable index of tracked projects, longest match strings first."""

    candidates: tuple[_Candidate, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class FirehoseResult:
    """Outcome of reclassifying a batch of signals."""

    kept: list[Signal]
    dropped_titles: list[str]


_MIN_MATCH_LEN = 3


def _compile(term: str) -> re.Pattern:
    # Word-boundary match so "vLLM" does not match inside "evilllm".
    return re.compile(rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])", re.IGNORECASE)


def build_project_index(sources: list[SourceConfig]) -> ProjectIndex:
    """Build a match index from non-firehose (tracked) sources.

    Firehose sources are skipped — a firehose never attributes entries to
    itself. Match terms are the project name plus any configured aliases.
    """
    candidates: list[_Candidate] = []
    for source in sources:
        if source.firehose:
            continue
        terms = [source.project, *source.aliases]
        patterns = tuple(
            _compile(term) for term in terms if len(term) >= _MIN_MATCH_LEN
        )
        if not patterns:
            continue
        candidates.append(
            _Candidate(
                project=source.project,
                category=source.category,
                patterns=patterns,
            )
        )
    # Prefer the most specific (longest project name) on ambiguous text.
    candidates.sort(key=lambda c: len(c.project), reverse=True)
    return ProjectIndex(candidates=tuple(candidates))


def classify_text(text: str, index: ProjectIndex) -> ProjectMatch | None:
    """Return the best tracked-project match for ``text``, or None."""
    for candidate in index.candidates:
        if any(pattern.search(text) for pattern in candidate.patterns):
            return ProjectMatch(project=candidate.project, category=candidate.category)
    return None


def _is_firehose(signal: Signal) -> bool:
    return bool(signal.metadata.get("firehose"))


def reclassify_firehose(signals: list[Signal], index: ProjectIndex) -> FirehoseResult:
    """Re-attribute firehose signals to tracked projects; drop non-matches.

    Non-firehose signals pass through unchanged. Inputs are never mutated —
    matched firehose signals are returned as new copies with the resolved
    project/category.
    """
    kept: list[Signal] = []
    dropped_titles: list[str] = []
    for signal in signals:
        if not _is_firehose(signal):
            kept.append(signal)
            continue
        match = classify_text(f"{signal.title}\n{signal.raw_summary}", index)
        if match is None:
            dropped_titles.append(signal.title)
            continue
        kept.append(
            signal.model_copy(
                update={"project": match.project, "category": match.category}
            )
        )
    return FirehoseResult(kept=kept, dropped_titles=dropped_titles)
