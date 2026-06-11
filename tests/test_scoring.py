from datetime import datetime, timezone

from radar.models import Category, Ring, ScoringConfig, Signal
from radar.scoring.deterministic import score_signal
from radar.scoring.rings import ring_from_score


def test_ring_from_score_accounts_for_security_posture():
    assert ring_from_score(4.5, security_posture=4) == Ring.ADOPT
    assert ring_from_score(4.2, security_posture=2) == Ring.PILOT
    assert ring_from_score(2.0, security_posture=1) == Ring.AVOID


def test_score_signal_marks_file_write_access_as_risk():
    signal = Signal(
        id="s1",
        source_id="github-cline",
        project="Cline",
        category=Category.CODING_AGENTS,
        title="Cline released v1",
        url="https://github.com/cline/cline/releases/tag/v1",
        published_at=datetime(2026, 6, 10, tzinfo=timezone.utc),
        raw_summary="MCP approval improvements",
        signal_type="github_release",
        tags=["coding-agent", "file-write-access", "terminal-access", "mcp"],
    )

    scored = score_signal(signal, ScoringConfig())

    assert scored.scores.workflow_impact >= 4
    assert scored.scores.security_posture == 2
    assert "needs_sandbox_review" in scored.reason_codes
    assert scored.recommended_ring == Ring.PILOT
