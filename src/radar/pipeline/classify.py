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
from urllib.parse import urlparse

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


def _normalize(text: str) -> str:
    """Lowercase and collapse every non-alphanumeric run to a single space.

    Normalizing both the match terms and the entry text means punctuation and
    spacing variants converge: "llama.cpp", "llama cpp" and "TensorRT-LLM",
    "TensorRT LLM" all match. Token boundaries are preserved, so "vllm" still
    cannot match inside "evilllm".
    """
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _compile(term: str) -> re.Pattern:
    # Match the normalized term on token boundaries within normalized text.
    return re.compile(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])")


def _github_slug(url: str) -> str | None:
    """Return the short repo name from a github.com URL, else None.

    Display names often carry an org prefix ("NVIDIA NemoClaw") while entries
    use the bare repo name ("NemoClaw"). The slug recovers that short form.
    Non-GitHub URLs (e.g. docs pages) are ignored to avoid junk slugs.
    """
    parsed = urlparse(url)
    host = (parsed.hostname or "").removeprefix("www.")
    if host != "github.com":
        return None
    segments = [s for s in parsed.path.split("/") if s]
    if len(segments) < 2:
        return None
    return segments[1]


def _match_terms(source: SourceConfig) -> list[str]:
    """All normalized strings that should resolve an entry to this project."""
    raw_terms = [source.project, *source.aliases]
    slug = _github_slug(str(source.url))
    if slug:
        raw_terms.append(slug)
    normalized = {_normalize(term) for term in raw_terms}
    return [term for term in normalized if len(term) >= _MIN_MATCH_LEN]


def build_project_index(sources: list[SourceConfig]) -> ProjectIndex:
    """Build a match index from non-firehose (tracked) sources.

    Firehose sources are skipped — a firehose never attributes entries to
    itself. Match terms are the project name, configured aliases, and a
    GitHub repo slug when available.
    """
    candidates: list[_Candidate] = []
    for source in sources:
        if source.firehose:
            continue
        terms = _match_terms(source)
        if not terms:
            continue
        candidates.append(
            _Candidate(
                project=source.project,
                category=source.category,
                patterns=tuple(_compile(term) for term in terms),
            )
        )
    # Prefer the most specific (longest matched term) on ambiguous text.
    candidates.sort(
        key=lambda c: max(len(p.pattern) for p in c.patterns), reverse=True
    )
    return ProjectIndex(candidates=tuple(candidates))


def classify_text(text: str, index: ProjectIndex) -> ProjectMatch | None:
    """Return the best tracked-project match for ``text``, or None."""
    normalized = _normalize(text)
    for candidate in index.candidates:
        if any(pattern.search(normalized) for pattern in candidate.patterns):
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
