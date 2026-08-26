"""Evolving operational vocabulary — the radar's learned knowledge layer.

Nothing about what "counts as the on-prem serving stack" should be frozen
in source code. The gates that rank news and desk items read their
vocabulary from an append-only store under ``data/knowledge/``; every
LLM classification feeds it back (the classifier's ``components`` slugs
are exactly the operator-relevant terms of this week). Bundled defaults
exist only as cold-start fallback and are always shadowed by learned
terms.

Contract:
- ``data/knowledge/vocab.jsonl`` — one JSON record per line:
  ``{"term": ..., "domain": "serving"|"noise", "source": ...,
    "added_at": iso}``
- append-only: re-learning a known term is a no-op, never a duplicate.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from radar.storage.news_log import NewsClassification


logger = logging.getLogger(__name__)

VOCAB_DIR = "knowledge"
VOCAB_FILE = "vocab.jsonl"
DOMAIN_SERVING = "serving"
DOMAIN_NOISE = "noise"


def vocabulary_path(root: Path) -> Path:
    return root / "data" / VOCAB_DIR / VOCAB_FILE


def load_learned_terms(
    root: Path,
    *,
    domain: str = DOMAIN_SERVING,
) -> list[str]:
    """Learned terms for one domain, newest first; [] when nothing learned."""
    path = vocabulary_path(root)
    if not path.exists():
        return []
    terms: list[str] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("Skipping corrupt vocab line in %s", path)
                continue
            if record.get("domain") == domain and record.get("term"):
                terms.append(str(record["term"]).lower())
    except OSError as exc:
        logger.warning("Could not read vocabulary at %s: %s", path, exc)
        return []
    # Newest first, deduped.
    seen: set[str] = set()
    ordered: list[str] = []
    for term in reversed(terms):
        if term not in seen:
            seen.add(term)
            ordered.append(term)
    return ordered


def learn_from_classifications(
    root: Path,
    classifications: list[NewsClassification],
    *,
    now: datetime | None = None,
) -> int:
    """Feed classifier output back into the vocabulary.

    Every component slug of a *relevant* classification is a term an
    analyst considered operator-relevant — learn it as serving-stack
    vocabulary so tomorrow's cheap gates rank it without another LLM call.
    Returns the number of newly learned terms.
    """
    additions: list[dict[str, str]] = []
    existing = {
        record.get("term")
        for record in _read_records(vocabulary_path(root))
    }
    stamp = (now or datetime.now(UTC)).isoformat()
    for classification in classifications:
        if not classification.relevant:
            continue
        for component in classification.components:
            term = component.strip().lower()
            if not term or term in existing:
                continue
            existing.add(term)
            additions.append(
                {
                    "term": term,
                    "domain": DOMAIN_SERVING,
                    "source": f"classified-by:{classification.model}",
                    "added_at": stamp,
                }
            )
    if additions:
        path = vocabulary_path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = "\n".join(json.dumps(row, ensure_ascii=False) for row in additions)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(payload + "\n")
        logger.info("Learned %d new vocabulary term(s)", len(additions))
    return len(additions)


def merge_terms(learned: list[str], defaults: list[str]) -> list[str]:
    """Learned terms first (they carry recency signal), defaults behind."""
    seen: set[str] = set()
    merged: list[str] = []
    for term in [*learned, *defaults]:
        normalized = term.lower().strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            merged.append(normalized)
    return merged


def _read_records(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    records: list[dict[str, str]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except OSError:
        return []
    return records
