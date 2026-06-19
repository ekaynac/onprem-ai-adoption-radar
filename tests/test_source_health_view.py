"""Tests for the source-health display summary (web layer)."""

from __future__ import annotations

from radar.models import Category, SourceConfig, SourceType
from radar.web.source_health import summarize_source_health


def _src(source_id: str, project: str, *, enabled: bool = True, firehose: bool = False):
    return SourceConfig(
        id=source_id,
        type=SourceType.RSS,
        enabled=enabled,
        project=project,
        category=Category.MODEL_SERVING,
        url="https://example.com/feed.xml",
        firehose=firehose,
    )


def test_no_scans_is_empty_and_healthy():
    view = summarize_source_health([], {}, [])
    assert view.total_sources == 0
    assert not view.has_stale
    assert "no scans yet" in view.one_line


def test_all_active_when_no_stale():
    sources = [_src("rss-a", "A"), _src("rss-b", "B")]
    view = summarize_source_health([], {"rss-a": 3, "rss-b": 1}, sources)

    assert view.total_sources == 2
    assert not view.has_stale
    assert "all 2 feeds active" in view.one_line


def test_stale_feed_carries_context():
    sources = [_src("rss-a", "A"), _src("rss-dead", "Dead Blog", firehose=True)]
    view = summarize_source_health(["rss-dead"], {"rss-a": 3, "rss-dead": 0}, sources)

    assert view.has_stale
    assert [f.source_id for f in view.stale] == ["rss-dead"]
    feed = view.stale[0]
    assert feed.project == "Dead Blog"
    assert feed.firehose is True
    assert "1 stale feed of 2" in view.one_line


def test_disabled_sources_excluded_from_total():
    sources = [_src("rss-a", "A"), _src("rss-off", "Off", enabled=False)]
    view = summarize_source_health([], {}, sources)
    assert view.total_sources == 1


def test_stale_id_without_matching_source_is_skipped():
    # Config changed since the scan recorded the id; don't crash, just skip it.
    sources = [_src("rss-a", "A")]
    view = summarize_source_health(["rss-removed"], {}, sources)
    assert view.stale == []
