"""Citation counts + venue per arXiv id. Best-effort; a scan never fails here.

Primary: Semantic Scholar Graph batch endpoint (POST, up to 500 ids/call,
keyless). Fallback: OpenAlex works filtered by arXiv DOI (GET, up to 50 DOIs
per piped filter, keyless; ``mailto`` joins the polite pool). The two count
citations differently, so every record carries its ``source`` and velocity is
only ever computed between same-source counts (see momentum.py).
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, ConfigDict

from radar.enrichment.retry import get_with_retry, post_with_retry


logger = logging.getLogger(__name__)

S2_BATCH_URL = "https://api.semanticscholar.org/graph/v1/paper/batch"
S2_FIELDS = "citationCount,venue"
S2_BATCH_SIZE = 500
OPENALEX_WORKS_URL = "https://api.openalex.org/works"
OPENALEX_BATCH_SIZE = 50


class CitationRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    arxiv_id: str
    citation_count: int
    venue: str | None = None
    peer_reviewed: bool = False
    source: str  # "s2" | "openalex"


async def fetch_citations(
    arxiv_ids: list[str],
    client: Any,
    contact_email: str | None = None,
) -> dict[str, CitationRecord]:
    """Citation record per arXiv id; ids the APIs don't know are simply absent."""
    if not arxiv_ids:
        return {}
    try:
        return await _from_semantic_scholar(arxiv_ids, client)
    except Exception as exc:
        logger.warning("Semantic Scholar citations failed, trying OpenAlex: %s", exc)
    try:
        return await _from_openalex(arxiv_ids, client, contact_email)
    except Exception as exc:
        logger.warning("OpenAlex citations failed too: %s", exc)
        return {}


def _is_peer_reviewed(venue: str | None) -> bool:
    """Deterministic rule from the spec: a non-arXiv venue means peer-reviewed."""
    return bool(venue) and "arxiv" not in (venue or "").lower()


async def _from_semantic_scholar(
    arxiv_ids: list[str], client: Any,
) -> dict[str, CitationRecord]:
    records: dict[str, CitationRecord] = {}
    for start in range(0, len(arxiv_ids), S2_BATCH_SIZE):
        chunk = arxiv_ids[start:start + S2_BATCH_SIZE]
        response = await post_with_retry(
            client,
            S2_BATCH_URL,
            label="semantic-scholar",
            params={"fields": S2_FIELDS},
            json={"ids": [f"ARXIV:{arxiv_id}" for arxiv_id in chunk]},
        )
        payload = response.json()
        if not isinstance(payload, list):
            raise ValueError(f"unexpected S2 batch payload: {type(payload).__name__}")
        for arxiv_id, item in zip(chunk, payload, strict=False):
            if not isinstance(item, dict):
                continue  # unmatched ids come back as null
            venue = (item.get("venue") or "").strip() or None
            records[arxiv_id] = CitationRecord(
                arxiv_id=arxiv_id,
                citation_count=int(item.get("citationCount") or 0),
                venue=venue,
                peer_reviewed=_is_peer_reviewed(venue),
                source="s2",
            )
    return records


async def _from_openalex(
    arxiv_ids: list[str], client: Any, contact_email: str | None,
) -> dict[str, CitationRecord]:
    records: dict[str, CitationRecord] = {}
    for start in range(0, len(arxiv_ids), OPENALEX_BATCH_SIZE):
        chunk = arxiv_ids[start:start + OPENALEX_BATCH_SIZE]
        try:
            records.update(await _openalex_chunk(chunk, client, contact_email))
        except Exception as exc:  # keep earlier chunks: OpenAlex is the last fallback
            logger.warning("OpenAlex chunk failed (%d ids): %s", len(chunk), exc)
    return records


async def _openalex_chunk(
    chunk: list[str], client: Any, contact_email: str | None,
) -> dict[str, CitationRecord]:
    """Fetch and parse a single OpenAlex batch (up to 50 ids)."""
    records: dict[str, CitationRecord] = {}
    dois = "doi:" + "|".join(f"10.48550/arXiv.{arxiv_id}" for arxiv_id in chunk)
    params: dict[str, str] = {
        "filter": dois,
        "select": "doi,cited_by_count,primary_location",
        "per-page": str(OPENALEX_BATCH_SIZE),
    }
    if contact_email:
        params["mailto"] = contact_email
    response = await get_with_retry(
        client, OPENALEX_WORKS_URL, label="openalex", params=params,
    )
    for item in response.json().get("results") or []:
        arxiv_id = _arxiv_id_from_doi(str(item.get("doi") or ""))
        if arxiv_id is None:
            continue
        source = (item.get("primary_location") or {}).get("source") or {}
        venue = (source.get("display_name") or "").strip() or None
        records[arxiv_id] = CitationRecord(
            arxiv_id=arxiv_id,
            citation_count=int(item.get("cited_by_count") or 0),
            venue=venue,
            peer_reviewed=_is_peer_reviewed(venue),
            source="openalex",
        )
    return records


def _arxiv_id_from_doi(doi: str) -> str | None:
    """'https://doi.org/10.48550/arxiv.2211.17192' → '2211.17192' (case-insensitive)."""
    marker = "10.48550/arxiv."
    lowered = doi.lower()
    if marker not in lowered:
        return None
    return doi[lowered.index(marker) + len(marker):] or None
