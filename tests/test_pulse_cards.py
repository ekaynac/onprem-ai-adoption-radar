"""Model-card summaries: extraction from real cards, enrichment, persistence."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from radar.pulse.cards import SUMMARY_LIMIT, card_summary
from radar.pulse.items import Lane, PulseItem
from radar.pulse.pipeline import add_card_summaries
from radar.pulse.store import merge_items


CARDS = Path(__file__).parent / "fixtures" / "pulse" / "cards"
NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("card", "starts_with"),
    [
        # Real Hub cards (2026-10-06), trimmed: logos, badge rows, link bars,
        # centered "join our WeChat" banners and headings must all be skipped.
        ("apple_LensVLM-9B.md", "LensVLM is a 9B Vision Language Model"),
        ("deepseek-ai_DeepSeek-V4.1-Flash.md", "We introduce DeepSeek-V4.1-Flash, a multimodal"),
        ("openbmb_MiniCPM5-2B.md", "We are releasing MiniCPM5-2B"),
        ("Qwen_Qwen-Image-2.1.md", "We are excited to open-source Qwen-Image-2.1"),
        ("XiaomiMiMo_MiMo-V2.6-Pro-RL.md", "MiMo-V2.6-Pro-RL is the flagship checkpoint"),
        ("zai-org_GLM-5.3-Flash.md", "We introduce GLM-5.3-Flash"),
    ],
)
def test_real_cards_yield_their_introduction(card: str, starts_with: str) -> None:
    summary = card_summary((CARDS / card).read_text(encoding="utf-8"))

    assert summary is not None and summary.startswith(starts_with)
    assert "**" not in summary and "<" not in summary and len(summary) <= SUMMARY_LIMIT


@pytest.mark.parametrize(
    "card",
    [
        "---\nlicense: mit\n---\n# Title\n\n![badge](https://x/y.svg)\n",
        '<p align="center">👋 Join our <a href="x">WeChat</a> community. See the blog.</p>\n',
        "[Home](a) | [Docs](b) | [Discord](c) | [Paper](d) | [Demo](e) | [Blog](f)\n",
        "## Usage\n\n```python\nprint('this is code, not a description of the model')\n```\n",
        "",
    ],
)
def test_cards_without_prose_give_none(card: str) -> None:
    assert card_summary(card) is None


def test_long_paragraphs_are_cut_at_the_limit() -> None:
    card = "This model " + "does a great many useful things. " * 40

    summary = card_summary(card)

    assert summary is not None and SUMMARY_LIMIT - 2 <= len(summary) <= SUMMARY_LIMIT
    assert summary.endswith("…")


def _model(key: str, kind: str, summary: str | None = None, day: int = 5) -> PulseItem:
    seen = datetime(2026, 10, day, tzinfo=UTC)
    return PulseItem(lane=Lane.MODEL, key=key, title=key.split("/")[1],
                     url=f"https://huggingface.co/{key}", source="huggingface",
                     published_at=seen, first_seen=seen, last_seen=seen, kind=kind, summary=summary)


def test_enrichment_reads_cards_of_releases_only_and_respects_the_limit() -> None:
    lens = (CARDS / "apple_LensVLM-9B.md").read_text(encoding="utf-8")
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request.url.path)
        if "missing" in request.url.path:
            return httpx.Response(404)
        return httpx.Response(200, text=lens)

    items = [
        _model("apple/LensVLM-9B", "original", day=6),
        _model("newlab/missing-card", "unknown", day=5),
        _model("Qwen/Qwen3.8-27B-FP8", "variant"),
        _model("someone/Thing-GGUF", "derivative"),
        _model("Qwen/Already", "original", summary="Known."),
        _model("old/release", "original", day=1),
    ]

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await add_card_summaries(items, client, limit=2)

    updated, added = asyncio.run(run())

    by_key = {i.key: i for i in updated}
    assert added == 1
    assert by_key["apple/LensVLM-9B"].summary.startswith("LensVLM is a 9B")
    assert by_key["newlab/missing-card"].summary is None  # 404: retried next run
    assert by_key["Qwen/Already"].summary == "Known."
    assert sorted(requested) == ["/apple/LensVLM-9B/raw/main/README.md",
                                 "/newlab/missing-card/raw/main/README.md"]  # newest two only


def test_merge_keeps_a_fetched_card_summary_across_runs() -> None:
    stored = [_model("apple/LensVLM-9B", "original", summary="LensVLM is a 9B VLM.")]
    seen_again = [_model("apple/LensVLM-9B", "original", day=6)]  # Hub list rows carry none

    [merged] = merge_items(stored, seen_again, NOW, window_days=14)

    assert merged.summary == "LensVLM is a 9B VLM."
