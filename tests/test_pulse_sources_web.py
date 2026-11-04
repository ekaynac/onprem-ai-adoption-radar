"""GitHub new-repo and news sources: pure mappers, and failures reported, not hidden."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx

from radar.pulse.health import load_health, record_runs
from radar.pulse.items import Lane
from radar.pulse.sources.github import fetch_new_repos, repo_item
from radar.pulse.sources.news import NewsSource, fetch_news, news_key, parse_hn, parse_rss


NOW = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)
RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>Lab</title>
<item><title>Introducing  Model X</title><link>https://lab.example/x</link>
<description>&lt;p&gt;A new &lt;b&gt;open&lt;/b&gt; model.&lt;/p&gt;</description>
<pubDate>Tue, 29 Sep 2026 10:00:00 GMT</pubDate></item>
<item><title></title><link>https://lab.example/empty</link></item>
<item><title>Undated</title><link>https://lab.example/undated</link></item>
</channel></rss>"""


def test_repo_item_computes_velocity_from_creation_date() -> None:
    item = repo_item({
        "full_name": "incoai/splash", "created_at": "2026-09-20T12:00:00Z",
        "stargazers_count": 924, "description": "Local inference on Apple silicon.",
        "topics": ["mlx", "llm"],
    }, NOW)

    assert item is not None
    assert (item.lane, item.key, str(item.url)) == (Lane.REPO, "incoai/splash", "https://github.com/incoai/splash")
    assert item.signals == {"stars": 924.0, "stars_per_day": 92.4}
    assert item.tags == ("mlx", "llm")
    assert repo_item({"full_name": "no-date/repo"}, NOW) is None


def test_repos_matching_two_topics_count_once_and_failed_topics_are_reported() -> None:
    row = {"full_name": "a/b", "created_at": "2026-09-29T00:00:00Z", "stargazers_count": 60}
    queries: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        query = request.url.params["q"]
        queries.append(query)
        if query.startswith("topic:broken"):
            return httpx.Response(422, json={"message": "Validation Failed"})
        return httpx.Response(200, json={"items": [row]})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await fetch_new_repos(client, ["llm", "ai", "broken"], 50, 14, NOW)

    import asyncio
    result = asyncio.run(run())

    assert [i.key for i in result.items] == ["a/b"]
    assert result.status == "partial" and result.errors[0].startswith("broken: HTTPStatusError")
    assert queries[0] == "topic:llm created:>=2026-09-16 stars:>=50"


def test_rss_entries_keep_the_legacy_id_and_strip_markup() -> None:
    source = NewsSource(id="lab-blog", kind="rss", url="https://lab.example/feed")

    items = parse_rss(RSS, source, NOW)

    assert len(items) == 1  # untitled and undated entries are skipped
    item = items[0]
    assert item.key == news_key("https://lab.example/x")
    assert item.key.startswith("news:") and len(item.key) == 21  # sha256[:16], as before
    assert item.title == "Introducing Model X"
    assert item.summary == "A new open model."
    assert item.published_at == datetime(2026, 9, 29, 10, tzinfo=UTC)
    assert (item.source, item.kind) == ("lab-blog", "lab-blog")


def test_repo_text_keeps_the_legacy_caps_so_label_hashes_survive() -> None:
    item = repo_item({"full_name": "a/b", "created_at": "2026-09-29T00:00:00Z",
                      "description": "x" * 300, "topics": [f"t{i}" for i in range(12)]}, NOW)

    assert item is not None and item.summary == "x" * 200 and len(item.tags) == 8


def test_hn_hits_without_url_link_to_the_discussion() -> None:
    source = NewsSource(id="hn-llm-top", kind="hn-algolia", url="https://hn.algolia.com/api/v1/x")

    items = parse_hn({"hits": [{"objectID": "42", "title": "Ask HN: local LLMs?",
                                 "created_at": "2026-09-30T08:00:00Z"}]}, source, NOW)

    assert str(items[0].url) == "https://news.ycombinator.com/item?id=42"


def test_a_dead_feed_is_an_error_entry_in_health(tmp_path: Path) -> None:
    sources = [
        NewsSource(id="ok", kind="rss", url="https://ok.example/feed"),
        NewsSource(id="dead", kind="rss", url="https://dead.example/feed"),
        NewsSource(id="off", kind="rss", url="https://off.example/feed", enabled=False),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert "radar" in request.headers["User-Agent"]
        if request.url.host == "dead.example":
            return httpx.Response(404)
        return httpx.Response(200, text=RSS)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await fetch_news(client, sources, NOW)

    import asyncio
    result = asyncio.run(run())
    health = record_runs(tmp_path / "health.json", [result], NOW)

    assert result.requests == 2  # disabled feeds are not fetched
    assert health["news:feeds"]["status"] == "partial"
    assert health["news:feeds"]["errors"][0].startswith("dead: HTTPStatusError")
    assert load_health(tmp_path / "health.json") == json.loads(
        (tmp_path / "health.json").read_text(encoding="utf-8"))
