"""News sweep adapters: RSS, HN Algolia, one-source-down, config guards."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from radar.discovery.news_sweep import (
    NewsClassificationConfig,
    NewsSourceConfig,
    NewsSourcesConfig,
    load_news_sources,
    sweep_news,
)


NOW = datetime(2026, 8, 4, 10, 0, tzinfo=UTC)

RSS_XML = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel>
  <title>vLLM Blog</title>
  <item>
    <title>vLLM v0.10 released</title>
    <link>https://blog.vllm.ai/2026/08/01/v0-10.html</link>
    <description>&lt;p&gt;Big &lt;b&gt;release&lt;/b&gt; notes&lt;/p&gt;</description>
    <pubDate>Sat, 01 Aug 2026 08:00:00 GMT</pubDate>
  </item>
  <item>
    <title>No link entry is skipped</title>
  </item>
</channel></rss>
"""

HN_PAYLOAD = {
    "hits": [
        {
            "title": "Ollama adds new engine",
            "url": "https://ollama.com/blog/new-engine",
            "objectID": "41",
            "created_at": "2026-08-02T09:30:00Z",
        },
        {
            "title": "Ask HN: local LLM stack?",
            "url": None,
            "objectID": "42",
            "created_at": "2026-08-03T09:30:00Z",
        },
        {"objectID": "43"},
    ]
}


class _Resp:
    def __init__(self, text: str = "", payload=None, status: int = 200):
        self.text = text
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class _Client:
    def __init__(self, routes: dict[str, _Resp], fail_substr: str | None = None):
        self._routes = routes
        self._fail = fail_substr
        self.urls: list[str] = []

    async def get(self, url, **kwargs):
        self.urls.append(url)
        if self._fail and self._fail in url:
            raise RuntimeError("boom")
        for fragment, resp in self._routes.items():
            if fragment in url:
                return resp
        return _Resp(status=404)


def _config(sources: list[NewsSourceConfig]) -> NewsSourcesConfig:
    return NewsSourcesConfig(
        version="1",
        classification=NewsClassificationConfig(
            enabled=True,
            model="claude-opus-5",
            max_items_per_run=25,
            max_output_tokens=1024,
        ),
        sources=sources,
    )


def _rss_source(enabled: bool = True) -> NewsSourceConfig:
    return NewsSourceConfig(
        id="vllm-blog",
        kind="rss",
        enabled=enabled,
        url="https://blog.vllm.ai/feed.xml",
    )


def _hn_source() -> NewsSourceConfig:
    return NewsSourceConfig(
        id="hn-ollama",
        kind="hn-algolia",
        enabled=True,
        url="https://hn.algolia.com/api/v1/search_by_date?query=ollama",
    )


@pytest.mark.asyncio
async def test_rss_entries_become_items():
    client = _Client({"vllm": _Resp(text=RSS_XML)})
    result = await sweep_news(_config([_rss_source()]), client, NOW)
    assert result.outcomes["vllm-blog"] == {"count": 1, "status": "ok"}
    item = result.items[0]
    assert item.title == "vLLM v0.10 released"
    assert item.url == "https://blog.vllm.ai/2026/08/01/v0-10.html"
    assert item.summary == "Big release notes"
    assert item.published_at == datetime(2026, 8, 1, 8, 0, tzinfo=UTC)
    assert item.id.startswith("news:")


@pytest.mark.asyncio
async def test_hn_hits_become_items_with_fallback_url():
    client = _Client({"algolia": _Resp(payload=HN_PAYLOAD)})
    result = await sweep_news(_config([_hn_source()]), client, NOW)
    assert result.outcomes["hn-ollama"] == {"count": 2, "status": "ok"}
    assert result.items[0].url == "https://ollama.com/blog/new-engine"
    assert (
        result.items[1].url == "https://news.ycombinator.com/item?id=42"
    )
    assert result.items[0].published_at == datetime(
        2026, 8, 2, 9, 30, tzinfo=UTC
    )


@pytest.mark.asyncio
async def test_one_source_down_does_not_abort_the_rest():
    client = _Client(
        {"algolia": _Resp(payload=HN_PAYLOAD)}, fail_substr="vllm"
    )
    result = await sweep_news(
        _config([_rss_source(), _hn_source()]), client, NOW
    )
    assert result.outcomes["vllm-blog"] == {"count": 0, "status": "error"}
    assert result.outcomes["hn-ollama"]["status"] == "ok"
    assert len(result.items) == 2


@pytest.mark.asyncio
async def test_disabled_source_is_never_fetched():
    client = _Client({})
    result = await sweep_news(
        _config([_rss_source(enabled=False)]), client, NOW
    )
    assert result.items == []
    assert result.outcomes == {}
    assert client.urls == []


def test_shipped_config_loads(tmp_path):
    from pathlib import Path

    config = load_news_sources(
        Path(__file__).resolve().parents[1] / "config" / "news-sources.yaml"
    )
    assert config.classification.model == "claude-opus-5"
    assert any(source.kind == "hn-algolia" for source in config.sources)
    assert all(source.id for source in config.sources)


def test_unknown_config_keys_are_rejected(tmp_path):
    bad = tmp_path / "news-sources.yaml"
    bad.write_text(
        "version: '1'\n"
        "classification:\n"
        "  enabled: true\n"
        "  model: claude-opus-5\n"
        "  max_items_per_run: 5\n"
        "  max_output_tokens: 512\n"
        "sources:\n"
        "  - id: x\n"
        "    kind: rss\n"
        "    enabled: true\n"
        "    url: https://example.com/feed\n"
        "    surprise: true\n",
        encoding="utf-8",
    )
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        load_news_sources(bad)
