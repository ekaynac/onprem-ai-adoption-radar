from datetime import UTC, datetime

from radar.models import Category, Signal
from radar.pipeline.dedupe import dedupe_signals


def make_signal(signal_id: str, url: str, summary: str) -> Signal:
    return Signal(
        id=signal_id,
        source_id="source",
        project="Cline",
        category=Category.CODING_AGENTS,
        title="Release",
        url=url,
        published_at=datetime(2026, 6, 10, tzinfo=UTC),
        raw_summary=summary,
        signal_type="github_release",
    )


def test_dedupe_keeps_richer_signal_for_same_url():
    short = make_signal("short", "https://example.com/a", "short")
    rich = make_signal("rich", "https://example.com/a/", "longer summary")

    result = dedupe_signals([short, rich])

    assert [signal.id for signal in result] == ["rich"]


def make_project_signal(signal_id: str, project: str, url: str, summary: str) -> Signal:
    return Signal(
        id=signal_id,
        source_id="source",
        project=project,
        category=Category.CODING_AGENTS,
        title="Release",
        url=url,
        published_at=datetime(2026, 6, 10, tzinfo=UTC),
        raw_summary=summary,
        signal_type="rss_entry",
    )


def test_dedupe_keeps_signals_for_different_projects_sharing_a_url():
    """After firehose re-attribution two projects can share a URL; neither
    project's only signal may be silently dropped."""
    a = make_project_signal("a", "Cline", "https://example.com/post", "about cline")
    b = make_project_signal("b", "Aider", "https://example.com/post", "longer text about aider")

    result = dedupe_signals([a, b])

    assert sorted(signal.project for signal in result) == ["Aider", "Cline"]
