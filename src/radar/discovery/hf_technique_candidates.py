"""Discover candidate techniques from Hugging Face daily papers.

Keyword-gated on purpose: a daily-papers item only becomes a proposal when its
title matches a curated technique keyword. There is NO triage fallback (unlike
repo discovery) — most daily papers are model releases or benchmarks, not
adoptable techniques, so unmatched titles are dropped, not queued for triage.
Network failures degrade to "no proposals". Results are only ever written to
the review file (see technique_proposals.py) — never auto-added.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from radar.discovery.technique_proposals import TechniqueProposal
from radar.models import Category
from radar.research_radar.entities import TechniqueDomain, TechniqueSeed
from radar.web.slugs import project_slug


logger = logging.getLogger(__name__)

HF_DAILY_PAPERS_URL = "https://huggingface.co/api/daily_papers"
_ARXIV_ID_RE = re.compile(r"^\d{4}\.\d{4,5}$")

KEYWORD_MAP: list[tuple[str, TechniqueDomain, Category]] = [
    ("quantization", TechniqueDomain.INFERENCE, Category.MODEL_SERVING),
    ("kv cache", TechniqueDomain.INFERENCE, Category.MODEL_SERVING),
    ("attention", TechniqueDomain.INFERENCE, Category.MODEL_SERVING),
    ("decoding", TechniqueDomain.INFERENCE, Category.MODEL_SERVING),
    ("inference", TechniqueDomain.INFERENCE, Category.MODEL_SERVING),
    ("serving", TechniqueDomain.INFERENCE, Category.MODEL_SERVING),
    ("distillation", TechniqueDomain.INFERENCE, Category.MODEL_SERVING),
    ("fine-tun", TechniqueDomain.FINE_TUNING, Category.AI_INFRASTRUCTURE),
    ("lora", TechniqueDomain.FINE_TUNING, Category.AI_INFRASTRUCTURE),
    ("preference optimization", TechniqueDomain.FINE_TUNING, Category.AI_INFRASTRUCTURE),
    ("rlhf", TechniqueDomain.FINE_TUNING, Category.AI_INFRASTRUCTURE),
    ("retrieval", TechniqueDomain.RAG, Category.AI_INFRASTRUCTURE),
    ("rag", TechniqueDomain.RAG, Category.AI_INFRASTRUCTURE),
    ("agent", TechniqueDomain.AGENT_ARCHITECTURE, Category.AGENT_FRAMEWORKS),
    ("tool use", TechniqueDomain.AGENT_ARCHITECTURE, Category.AGENT_FRAMEWORKS),
    ("reasoning", TechniqueDomain.AGENT_ARCHITECTURE, Category.AGENT_FRAMEWORKS),
    ("planning", TechniqueDomain.AGENT_ARCHITECTURE, Category.AGENT_FRAMEWORKS),
    ("jailbreak", TechniqueDomain.SAFETY_SANDBOXING, Category.SANDBOX_GOVERNANCE),
    ("guardrail", TechniqueDomain.SAFETY_SANDBOXING, Category.SANDBOX_GOVERNANCE),
    ("prompt injection", TechniqueDomain.SAFETY_SANDBOXING, Category.SANDBOX_GOVERNANCE),
    ("safety", TechniqueDomain.SAFETY_SANDBOXING, Category.SANDBOX_GOVERNANCE),
]


def match_keyword(title: str) -> tuple[str, TechniqueDomain, Category] | None:
    """First matching KEYWORD_MAP entry for a lowercased title, else None."""
    lowered = title.lower()
    for keyword, domain, category in KEYWORD_MAP:
        if keyword in lowered:
            return keyword, domain, category
    return None


async def discover_technique_candidates(
    seeds: list[TechniqueSeed],
    client: Any,
    min_upvotes: int = 10,
    limit: int = 20,
) -> list[TechniqueProposal]:
    known_arxiv = {p.arxiv_id for s in seeds for p in s.papers}
    known_ids = {s.id for s in seeds}
    items = await _daily_papers(client)
    by_arxiv: dict[str, TechniqueProposal] = {}
    for item in items:
        paper = item.get("paper") or item
        arxiv_id = str(paper.get("id") or "")
        title = (paper.get("title") or "").strip().replace("\n", " ")
        upvotes = int(paper.get("upvotes") or 0)
        if not _ARXIV_ID_RE.match(arxiv_id) or not title:
            continue
        if upvotes < min_upvotes or arxiv_id in known_arxiv or arxiv_id in by_arxiv:
            continue
        matched = match_keyword(title)
        if matched is None:
            continue
        suggested_id = project_slug(title)
        if suggested_id in known_ids:
            continue
        keyword, domain, category = matched
        published = str(paper.get("publishedAt") or "")[:10] or None
        by_arxiv[arxiv_id] = TechniqueProposal(
            suggested_id=suggested_id, name=title, arxiv_id=arxiv_id,
            published=published, upvotes=upvotes, suggested_domain=domain,
            suggested_category=category, matched_keyword=keyword,
        )
    ranked = sorted(by_arxiv.values(), key=lambda p: p.upvotes, reverse=True)
    return ranked[:limit]


async def _daily_papers(client: Any) -> list[dict[str, Any]]:
    try:
        response = await client.get(HF_DAILY_PAPERS_URL)
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, list) else (payload.get("papers") or [])
    except Exception as exc:
        logger.warning("HF daily-papers fetch failed: %s", exc)
        return []
