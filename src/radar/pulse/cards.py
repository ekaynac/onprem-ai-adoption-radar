"""Model lane enrichment: one prose paragraph from the Hugging Face model card.

A model item used to carry only its repo name, so every downstream reader
(the site row, RSS, Jev for unknown-origin models, and Claude's Turkish
sentence) had to guess what "MiMo-V2.6-Pro-RL" is. The card's first real
prose paragraph fixes that. Cards are noisy (logos, badge rows, link bars,
language switchers, HTML blocks), so extraction skips everything that is not
a paragraph of sentences.
"""

from __future__ import annotations

import re
from typing import Any

from radar.enrichment.retry import get_with_retry


CARD_URL = "https://huggingface.co/{repo}/raw/main/README.md"
SUMMARY_LIMIT = 400
MIN_PROSE_CHARS = 60
MIN_PROSE_WORDS = 8

_FRONTMATTER = re.compile(r"\A---\s*\n.*?\n---\s*\n", re.DOTALL)
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_FENCE = re.compile(r"```.*?```", re.DOTALL)
_MD_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_MD_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_TAG = re.compile(r"<[^>]+>")
_CENTERED = re.compile(r"<(p|div|h\d)\b[^>]*align\s*=\s*[\"']?center", re.IGNORECASE)
_EMPHASIS = re.compile(r"(\*\*|__|\*|`)")
_ENTITY = re.compile(r"&(nbsp|amp|lt|gt|quot|#\d+);")
_ENTITIES = {"nbsp": " ", "amp": "&", "lt": "<", "gt": ">", "quot": '"'}


def card_summary(markdown: str, limit: int = SUMMARY_LIMIT) -> str | None:
    """The first paragraph that reads like prose, cleaned; None if the card has none."""
    text = _FRONTMATTER.sub("", markdown.replace("\r\n", "\n"))
    text = _FENCE.sub("\n\n", _COMMENT.sub("", text))
    for block in re.split(r"\n\s*\n", text):
        prose = _prose(block)
        if prose is not None:
            return prose if len(prose) <= limit else prose[: limit - 1].rstrip() + "…"
    return None


def _prose(block: str) -> str | None:
    lines = [line.strip() for line in block.strip().splitlines() if line.strip()]
    if not lines:
        return None
    first = lines[0]
    if first.startswith(("#", "|", ">", "- ", "* ", "1. ")) or first.lower().startswith("license"):
        return None  # headings, tables, quotes, lists, license boilerplate
    if _CENTERED.match(first):
        return None  # centered HTML blocks are banners: logos, link bars, "join our WeChat"
    flat = " ".join(lines)
    flat = _MD_IMAGE.sub(" ", flat)
    flat = _MD_LINK.sub(r"\1", flat)
    flat = _TAG.sub(" ", flat)
    flat = _EMPHASIS.sub("", flat)
    flat = _ENTITY.sub(lambda m: _ENTITIES.get(m.group(1), " "), flat)
    flat = " ".join(flat.split())
    words = flat.split()
    letters = sum(ch.isalpha() for ch in flat)
    if len(flat) < MIN_PROSE_CHARS or len(words) < MIN_PROSE_WORDS:
        return None
    if letters < 0.6 * len(flat) or flat.count("|") >= 2:
        return None  # link bars, badge rows, navigation
    if not re.search(r"[.!?:](\s|$)", flat):
        return None  # a run of link labels, not a sentence
    return flat


async def fetch_card_summary(
    client: Any, repo: str, headers: dict[str, str] | None = None,
) -> str | None:
    """Best effort: a missing, gated or empty card yields None, never an error."""
    try:
        response = await get_with_retry(
            client, CARD_URL.format(repo=repo), label=f"hf-card:{repo}",
            headers=headers or {}, follow_redirects=True,
        )
    except Exception:
        return None
    text = getattr(response, "text", "")
    return card_summary(text) if isinstance(text, str) and text else None
