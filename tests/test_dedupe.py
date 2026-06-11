from datetime import datetime, timezone

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
        published_at=datetime(2026, 6, 10, tzinfo=timezone.utc),
        raw_summary=summary,
        signal_type="github_release",
    )


def test_dedupe_keeps_richer_signal_for_same_url():
    short = make_signal("short", "https://example.com/a", "short")
    rich = make_signal("rich", "https://example.com/a/", "longer summary")

    result = dedupe_signals([short, rich])

    assert [signal.id for signal in result] == ["rich"]
