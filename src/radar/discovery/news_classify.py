"""Classify raw news items into change intelligence via the Claude API.

Budget-bounded (``max_items_per_run`` per invocation) and fail-closed:
an item whose output cannot be schema-validated stays unclassified and
never reaches a product surface. Runs through the official ``anthropic``
SDK with structured outputs (``output_config.format``) so the response
is constrained to the taxonomy before validation even starts. Without
an ``ANTHROPIC_API_KEY`` the caller skips the stage visibly — a missing
key degrades the newsroom to a raw firehose, never breaks the publish.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

import anthropic
from pydantic import BaseModel, ConfigDict

from radar.discovery.news_sweep import NewsClassificationConfig
from radar.storage.news_log import NewsClassification, NewsItem


logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are an analyst for an on-prem AI adoption radar run by a "
    "consulting firm. Readers operate self-hosted LLM stacks (vLLM, "
    "llama.cpp, Ollama, TGI, open-weight models on their own GPUs). "
    "Classify the given article strictly for that audience.\n"
    "- relevant: false when the article is noise for on-prem operators "
    "(consumer app news, funding gossip, cloud-only announcements with "
    "no self-hosted angle).\n"
    "- event_type: the single best fit from the allowed values.\n"
    "- components: concrete affected components, lowercase slugs such "
    "as 'vllm', 'llama.cpp', 'ollama', 'cuda', 'qwen3', at most 6; "
    "empty when relevant is false.\n"
    "- operational_impact: 'breaking' only when an operator must act "
    "(breaking change, security advisory, removal); 'improvement' for "
    "upgrades worth adopting; 'informational' otherwise.\n"
    "- summary: one or two factual sentences for an operator, no hype.\n"
    "- citation: the article URL you were given, verbatim."
)


class NewsClassificationPayload(BaseModel):
    """The exact JSON shape the model must return."""

    model_config = ConfigDict(extra="forbid")

    relevant: bool
    event_type: Literal[
        "release",
        "breaking-change",
        "security-advisory",
        "performance",
        "deprecation",
        "integration",
        "research",
        "community",
        "other",
    ]
    components: list[str]
    operational_impact: Literal["breaking", "improvement", "informational"]
    summary: str
    citation: str


@dataclass
class NewsClassifyResult:
    classifications: list[NewsClassification] = field(default_factory=list)
    failures: list[tuple[str, str]] = field(default_factory=list)
    over_budget: int = 0


def build_anthropic_client() -> Any | None:
    """Client when ANTHROPIC_API_KEY is set; None otherwise (visible skip)."""
    import os

    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    return anthropic.Anthropic()


def _item_prompt(item: NewsItem) -> str:
    published = (
        item.published_at.isoformat() if item.published_at else "unknown"
    )
    summary = item.summary or "(no excerpt provided)"
    return (
        f"Title: {item.title}\n"
        f"URL: {item.url}\n"
        f"Source: {item.source_id}\n"
        f"Published: {published}\n"
        f"Excerpt: {summary}"
    )


def _extract_payload(response: Any) -> NewsClassificationPayload:
    if response.stop_reason == "refusal":
        raise ValueError("model declined the request (stop_reason=refusal)")
    if response.stop_reason == "max_tokens":
        raise ValueError("output truncated (stop_reason=max_tokens)")
    text = next(
        (
            block.text
            for block in response.content
            if getattr(block, "type", None) == "text"
        ),
        None,
    )
    if text is None:
        raise ValueError("response carried no text block")
    return NewsClassificationPayload.model_validate(json.loads(text))


def classify_news(
    items: list[NewsItem],
    config: NewsClassificationConfig,
    client: Any,
    now: datetime,
) -> NewsClassifyResult:
    """Classify up to the per-run budget; failures stay unclassified."""
    result = NewsClassifyResult()
    budget = items[: config.max_items_per_run]
    result.over_budget = len(items) - len(budget)
    schema = NewsClassificationPayload.model_json_schema()
    for item in budget:
        try:
            response = client.messages.create(
                model=config.model,
                max_tokens=config.max_output_tokens,
                system=_SYSTEM_PROMPT,
                output_config={
                    "format": {"type": "json_schema", "schema": schema}
                },
                messages=[{"role": "user", "content": _item_prompt(item)}],
            )
            payload = _extract_payload(response)
        except anthropic.AuthenticationError as exc:
            # Credentials are broken for every item — stop burning calls.
            result.failures.append((item.id, f"authentication error: {exc}"))
            logger.warning("News classification aborted: %s", exc)
            break
        except Exception as exc:
            result.failures.append((item.id, str(exc)))
            logger.warning(
                "News classification failed for %s: %s", item.id, exc
            )
            continue
        result.classifications.append(
            NewsClassification(
                news_id=item.id,
                relevant=payload.relevant,
                event_type=payload.event_type,
                components=payload.components[:6],
                operational_impact=payload.operational_impact,
                summary=payload.summary,
                citation=payload.citation or item.url,
                model=config.model,
                classified_at=now,
            )
        )
    return result
