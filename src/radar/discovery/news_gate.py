"""Cheap relevance gate for the news firehose.

The LLM classification budget is small; spending it FIFO wastes calls on
funding gossip and consumer-app headlines while a vLLM release note ages
out unclassified. This gate scores every pending item against on-prem
serving vocabulary in microseconds so ``classify_news`` can spend its
budget where evidence of operator relevance is strongest.

It is a *prioritizer*, not a filter: low-scoring items still get their
turn eventually, they simply queue behind high-signal ones. That keeps
novel-but-unusual relevant items reachable while starving pure noise.

The vocabulary is not frozen: bundled tiers are cold-start defaults, and
the live gate merges in the learned store under ``data/knowledge/`` —
every LLM classification feeds its component slugs back (radar.knowledge),
so a new engine the analyst recognized tomorrow scores without a code
change.
"""

from __future__ import annotations

from radar.storage.news_log import NewsItem


# Weighted serving-stack vocabulary. Tier weights reflect how strongly a
# term predicts operator relevance. Cold-start defaults only — learned
# terms from data/knowledge/ take precedence (tier 3 equivalent).
_TIER_3 = (
    "vllm", "llama.cpp", "llama-cpp", "ollama", "tgi ", "sglang",
    "tensorrt-llm", "lmdeploy", "localai", "llamafile", "gguf", "awq",
    "gptq", "quantization", "quantized", "kv-cache", "pagedattention",
    "speculative decoding", "inference server", "model serving",
)
_TIER_2 = (
    "self-host", "on-prem", "on prem", "open-weight", "open weight",
    "gpu", "h100", "h200", "a100", "mi300x", "rtx 4090", "rtx 5090",
    "vram", "inference", "fine-tune", "finetune", "lora", "rag ",
    "embedding", "context window", "tokens/sec", "throughput",
    "benchmark", "leaderboard", "license change", "security advisory",
)
_TIER_1 = (
    "release", "version", "upgrade", "deprecat", "breaking change",
    "cve", "vulnerability", "exploit", "patch",
)

_SCORE_3, _SCORE_2, _SCORE_1 = 4, 2, 1


def relevance_score(
    item: NewsItem,
    *,
    learned_serving_terms: list[str] | None = None,
) -> int:
    """Heuristic 0-N relevance score; higher queues earlier.

    ``learned_serving_terms`` carries the evolved vocabulary (radar.knowledge);
    each hit scores like a tier-3 term since the analyst explicitly labeled it.
    """
    haystack = f"{item.title}\n{item.summary or ''}".lower()
    score = 0
    for term in learned_serving_terms or ():
        if term in haystack:
            score += _SCORE_3
    for tier, weight in ((_TIER_3, _SCORE_3), (_TIER_2, _SCORE_2), (_TIER_1, _SCORE_1)):
        for term in tier:
            if term in haystack:
                score += weight
    return score


def rank_by_relevance(
    items: list[NewsItem],
    *,
    learned_serving_terms: list[str] | None = None,
) -> list[NewsItem]:
    """Highest relevance first; recency breaks ties (newest wins)."""
    return sorted(
        items,
        key=lambda item: (
            -relevance_score(item, learned_serving_terms=learned_serving_terms),
            item.observed_at,
        ),
    )
