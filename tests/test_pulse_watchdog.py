"""Dead-man checks: what raises, what stays quiet, and alert dedup."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from radar.pulse.watchdog import (
    Finding,
    check_digest,
    check_publish,
    check_site,
    diff_alerts,
    load_state,
    render_alert,
    save_state,
)


NOW = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)  # 15:00 Istanbul


def _view(generated: datetime, **health) -> dict:
    return {
        "generated_at": generated.isoformat(),
        "lanes": [{"lane": lane, "total": 5} for lane in ("model", "paper", "repo", "news")],
        "health": {"sources": [], "degraded": False, **health},
    }


def test_healthy_site_raises_nothing() -> None:
    assert check_site(_view(NOW - timedelta(hours=2)), NOW, None) == []


def test_stale_empty_failing_and_degraded_site_each_raise() -> None:
    view = _view(
        NOW - timedelta(hours=7),
        sources=[{"source": "huggingface:daily-papers", "status": "error", "count": 0}],
        degraded=True,
    )
    view["lanes"][1]["total"] = 0

    keys = {f.key for f in check_site(view, NOW, None)}

    assert keys == {"site-stale", "lane-empty:paper", "source:huggingface:daily-papers",
                    "triage-degraded"}


def test_unreachable_site_is_a_finding_not_a_crash() -> None:
    [finding] = check_site(None, NOW, "HTTPStatusError: 404")

    assert finding.key == "site-unreachable" and "404" in finding.message


@pytest.mark.parametrize(
    ("conclusions", "alarm"),
    [
        (["failure", "failure", "success"], True),
        (["failure", "success", "failure"], False),
        (["cancelled", "failure", "cancelled", "failure"], True),  # cancels don't reset
        ([None, "success"], False),  # in-progress run is ignored
        (["failure"], False),  # one failure is the watchdog's retry, not an alarm
    ],
)
def test_publish_alarm_needs_two_consecutive_failures(conclusions, alarm) -> None:
    runs = [{"conclusion": c, "html_url": f"https://gh/run/{i}"} for i, c in enumerate(conclusions)]

    assert bool(check_publish(runs, None)) is alarm


def test_digest_is_only_due_after_ten_local() -> None:
    morning = datetime(2026, 9, 30, 5, 0, tzinfo=UTC)  # 08:00 Istanbul

    assert check_digest(None, morning) == []
    assert check_digest("2026-09-30", NOW) == []
    assert check_digest("2026-09-29", NOW)[0].key == "digest-missing"


def test_alerts_fire_once_and_resolve_once(tmp_path: Path) -> None:
    stale = Finding("site-stale", "Live site is 7 h old")

    raised, cleared, active = diff_alerts({}, [stale])
    assert [f.key for f in raised] == ["site-stale"] and cleared == []

    raised, cleared, active2 = diff_alerts(active, [stale])
    assert raised == [] and cleared == []
    assert render_alert(raised, cleared, active) is None  # no repeat nagging

    raised, cleared, active3 = diff_alerts(active2, [])
    message = render_alert(raised, cleared, active2)
    assert cleared == ["site-stale"] and active3 == {}
    assert message is not None and "resolved: Live site is 7 h old" in message

    path = tmp_path / "watchdog-state.json"
    save_state(path, active2, NOW)
    assert load_state(path) == active2


def test_alert_text_is_html_escaped() -> None:
    message = render_alert([Finding("x", "<script> & co")], [], {})

    assert message is not None and "&lt;script&gt; &amp; co" in message


def test_state_dir_env_moves_worker_state_out_of_the_clone(tmp_path: Path, monkeypatch) -> None:
    from radar.pulse.telegram import STATE_PATH, state_file

    monkeypatch.delenv("RADAR_STATE_DIR", raising=False)
    assert state_file(tmp_path, STATE_PATH) == tmp_path / "data" / "pulse" / "telegram-state.json"
    monkeypatch.setenv("RADAR_STATE_DIR", "/var/lib/radar")
    assert state_file(tmp_path, STATE_PATH) == Path("/var/lib/radar/telegram-state.json")
