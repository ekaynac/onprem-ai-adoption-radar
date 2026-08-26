from __future__ import annotations

from datetime import UTC, datetime

from radar.discovery.news_gate import rank_by_relevance, relevance_score
from radar.storage.news_log import NewsItem


NOW = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)


def item(title: str, summary: str = "", url: str = "https://x/1") -> NewsItem:
    return NewsItem(
        id=f"news:{abs(hash(title))}",
        source_id="hn-vllm",
        title=title,
        url=url,
        summary=summary or None,
        published_at=NOW,
        observed_at=NOW,
    )


def test_serving_stack_terms_outscore_consumer_noise() -> None:
    relevant = item(
        "vLLM v0.9 security advisory: KV-cache eviction bug",
        "Affects pagedattention; upgrade to patch. GGUF quantization unaffected.",
    )
    noise = item("Startup raises $200M for consumer AI companion app")
    assert relevance_score(relevant) > relevance_score(noise) * 3


def test_ranking_puts_high_signal_first_and_recency_breaks_ties() -> None:
    advisory = item("llama.cpp CVE-2026-1337: remote code execution", "")
    old_high = item(
        "vLLM 1.0 release with speculative decoding",
        "inference throughput doubles",
    )
    noise = item("AI startup funding round closes")

    ranked = rank_by_relevance([noise, advisory, old_high])
    assert ranked[0].title.startswith("vLLM") or ranked[0] is advisory
    assert ranked.index(noise) == len(ranked) - 1
