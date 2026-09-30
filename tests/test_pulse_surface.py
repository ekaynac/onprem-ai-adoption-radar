"""Pulse view, RSS feeds and the Telegram digest (incl. token-leak guards)."""

from __future__ import annotations

import asyncio
import logging
import xml.etree.ElementTree as ET  # parses only feeds this test just generated
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest

from radar.pulse.classify import Answer, Label
from radar.pulse.feeds import FEED_FILES, render_feed, write_feeds
from radar.pulse.items import Lane, PulseItem
from radar.pulse.pipeline import ITEMS_PATH
from radar.pulse.store import save_items
from radar.pulse.telegram import (
    TELEGRAM_LIMIT,
    TelegramError,
    mark_sent,
    record_delivery,
    render_digest,
    select_new,
    send_message,
)
from radar.pulse.triage import LABELS_PATH, append_labels
from radar.pulse.view import build_pulse_view
from radar.storage.source_health_log import (
    SourceHealthRecord,
    SourceOutcome,
    append_source_health,
)


NOW = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)
TOKEN = "123456:SECRET-bot-token"


def _seed_root(root: Path) -> None:
    items = [
        PulseItem(lane=Lane.NEWS, key="n1", title="Introducing GPT-6.1 Sol",
                  url="https://openai.com/index/gpt-6-1", source="openai-news",
                  first_seen=NOW, last_seen=NOW, summary="A <new> model & more"),
        PulseItem(lane=Lane.NEWS, key="n2", title="Airbnb widens access",
                  url="https://openai.com/index/airbnb", source="openai-news",
                  first_seen=NOW, last_seen=NOW),
        PulseItem(lane=Lane.MODEL, key="XiaomiMiMo/MiMo-V2.6-Pro-RL", title="MiMo-V2.6-Pro-RL",
                  url="https://huggingface.co/XiaomiMiMo/MiMo-V2.6-Pro-RL", source="huggingface",
                  first_seen=NOW, last_seen=NOW, kind="original",
                  signals={"likes": 603, "downloads": 78135}),
    ]
    save_items(root / ITEMS_PATH, items)
    append_labels(root / LABELS_PATH, [
        Label(item_id="news:n1", content_hash="h", question_version=1, engine="jev",
              answers={"event": Answer(value="model-release", confidence=1.0)}, labeled_at=NOW),
        Label(item_id="news:n2", content_hash="h", question_version=1, engine="jev",
              answers={"event": Answer(value="customer-story", confidence=0.9)}, labeled_at=NOW),
    ])
    append_source_health(root / "data" / "source-health.jsonl", SourceHealthRecord(
        run_id=f"pulse-{NOW.isoformat()}", observed_at=NOW,
        sources={"huggingface:lab-models": SourceOutcome(count=586, status="ok")},
    ))


@pytest.fixture
def view(tmp_path: Path) -> dict:
    _seed_root(tmp_path)
    return build_pulse_view(tmp_path, NOW)


def test_view_lanes_hide_customer_stories_and_report_health(view: dict) -> None:
    lanes = {section["lane"]: section for section in view["lanes"]}

    assert [row["title"] for row in lanes["news"]["items"]] == ["Introducing GPT-6.1 Sol"]
    assert lanes["news"]["hidden_count"] == 1
    assert lanes["model"]["items"][0]["title"] == "XiaomiMiMo/MiMo-V2.6-Pro-RL"
    assert view["health"]["sources"][0] == {
        "source": "huggingface:lab-models", "status": "ok", "count": 586,
        "observed_at": NOW.isoformat(),
    }
    assert view["health"]["degraded"] is False


def test_empty_root_yields_an_empty_but_valid_view(tmp_path: Path) -> None:
    view = build_pulse_view(tmp_path, NOW)

    assert [s["items"] for s in view["lanes"]] == [[], [], [], []]
    assert view["health"] == {"sources": [], "engines": {}, "degraded": False}


def test_feeds_are_valid_rss_and_escape_content(view: dict, tmp_path: Path) -> None:
    written = write_feeds(view, tmp_path / "site", "https://example.github.io/radar")
    assert {p.name for p in written} == set(FEED_FILES.values())
    combined = ET.fromstring((tmp_path / "site" / "pulse.xml").read_text(encoding="utf-8"))
    titles = [el.text for el in combined.iter("title")]
    assert "Introducing GPT-6.1 Sol" in titles
    assert "Airbnb widens access" not in titles  # hidden never reaches a feed
    description = next(el.text for el in combined.iter("description") if el.text and "<new>" in el.text)
    assert "A <new> model & more" in description  # parsed back from escaped XML

    news_only = ET.fromstring(render_feed(view, "news", ""))
    assert all(el.text == "news" for el in news_only.iter("category"))


def test_digest_is_numbered_compact_and_skips_delivered(view: dict) -> None:
    picks = select_new(view, delivered={"news:n1"})
    [message] = render_digest(picks, view, "https://example.github.io/radar/", date(2026, 9, 30))

    assert "GPT-6.1 Sol" not in message.text  # already delivered
    assert "30 Eylül 2026" in message.text
    # Short link text + owner + one signal; the raw repo id is not repeated.
    assert ('1. <a href="https://huggingface.co/XiaomiMiMo/MiMo-V2.6-Pro-RL">MiMo-V2.6-Pro-RL</a>'
            " · XiaomiMiMo · ♥ 603") in message.text
    assert "(1 yeni)" in message.text
    assert 'href="https://example.github.io/radar/pulse.xml">RSS</a>' in message.text
    assert message.item_ids == ("model:XiaomiMiMo/MiMo-V2.6-Pro-RL",)
    everything = {"news:n1", "model:XiaomiMiMo/MiMo-V2.6-Pro-RL"}
    assert render_digest(select_new(view, everything), view, "", date(2026, 9, 30)) == []


def _news_rows(count: int) -> list[dict]:
    return [
        {"id": f"news:{i}", "lane": "news", "title": f"Headline number {i} " + "x" * 120,
         "url": f"https://example.com/{i}", "source": "openai-news", "reasons": [], "signals": {}}
        for i in range(count)
    ]


def test_digest_caps_each_lane_and_records_the_overflow_as_seen() -> None:
    # Regression: the first live digest sent 630 items in 22 messages (unreadable).
    rows = _news_rows(120)
    view = {"lanes": [{"lane": "news", "items": rows}], "health": {"degraded": True}}

    [message] = render_digest(select_new(view, set()), view, "https://site/", date(2026, 9, 30))

    assert message.text.count("\n8. ") == 1 and "\n9. " not in message.text
    assert "+112 daha sitede" in message.text
    assert "OpenAI" in message.text and "openai-news" not in message.text
    assert "Headline number 0 " + "x" * 40 in message.text and "…" in message.text  # shortened
    assert "Jev" in message.text  # degraded warning
    assert list(message.item_ids) == [r["id"] for r in rows]  # overflow never re-sent


def test_digest_still_splits_safely_when_caps_are_raised() -> None:
    rows = _news_rows(120)
    view = {"lanes": [{"lane": "news", "items": rows}], "health": {"degraded": False}}

    messages = render_digest(select_new(view, set()), view, "https://site/", date(2026, 9, 30),
                             per_lane={"news": 120})

    assert len(messages) > 1
    assert all(len(m.text) <= TELEGRAM_LIMIT for m in messages)
    assert [i for m in messages for i in m.item_ids] == [r["id"] for r in rows]
    assert messages[1].text.startswith(f"(2/{len(messages)})")
    assert "(devam)" in messages[1].text


def test_delivery_state_records_ids_and_date_separately() -> None:
    state = record_delivery({"last_sent_date": None, "delivered": [f"x{i}" for i in range(3000)]}, ["new"])

    assert state["last_sent_date"] is None  # a partial digest must still retry today
    assert len(state["delivered"]) == 3000 and state["delivered"][-1] == "new"
    assert mark_sent(state, date(2026, 9, 30))["last_sent_date"] == "2026-09-30"


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_send_message_posts_html_without_previews() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = request.read()
        return httpx.Response(200, json={"ok": True, "result": {}})

    async def run():
        async with _client(handler) as client:
            await send_message(client, TOKEN, "42", "<b>hi</b>")

    asyncio.run(run())
    assert seen["path"] == f"/bot{TOKEN}/sendMessage"
    assert b'"parse_mode":"HTML"' in seen["body"].replace(b" ", b"")


@pytest.mark.parametrize(
    "handler",
    [
        lambda r: httpx.Response(401, json={"ok": False, "description": f"Unauthorized {TOKEN}"}),
        lambda r: (_ for _ in ()).throw(httpx.ConnectError(f"cannot reach {r.url}")),
    ],
)
def test_telegram_errors_never_leak_the_token(handler, caplog) -> None:
    async def run():
        async with _client(handler) as client:
            await send_message(client, TOKEN, "42", "hi")

    with caplog.at_level(logging.DEBUG), pytest.raises(TelegramError) as excinfo:
        asyncio.run(run())

    assert TOKEN not in str(excinfo.value)
    error = excinfo.value
    # The httpx exception (whose text carries the URL, hence the token) is never chained.
    assert error.__cause__ is None
    assert error.__context__ is None or error.__suppress_context__
    assert TOKEN not in caplog.text


def test_remote_view_validation_accepts_our_view_and_rejects_tampering(view: dict) -> None:
    import copy
    import json

    from radar.pulse.view import validate_view

    assert validate_view(json.loads(json.dumps(view))) == json.loads(json.dumps(view))

    bad_scheme = copy.deepcopy(view)
    bad_scheme["lanes"][3]["items"][0]["url"] = "javascript:alert(1)"
    for broken in (
        {"schema_version": "other"},
        {**view, "lanes": "nope"},
        {**view, "lanes": [{"lane": "weather", "items": []}]},
        bad_scheme,
    ):
        with pytest.raises(ValueError):
            validate_view(broken)
