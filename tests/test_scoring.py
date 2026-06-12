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


def test_score_signal_builds_on_prem_rubric_from_tags_and_metadata():
    signal = Signal(
        id="s2",
        source_id="github-openclaw",
        project="OpenClaw",
        category=Category.GENERAL_AGENTS,
        title="OpenClaw repo snapshot",
        url="https://github.com/openclaw/openclaw",
        published_at=datetime(2026, 6, 11, tzinfo=timezone.utc),
        raw_summary="Repo snapshot",
        signal_type="github_repo_snapshot",
        tags=["open-source", "self-hosted", "local-model", "audit", "sso", "mcp"],
        metadata={"license": "Apache-2.0", "stars": 1200, "pushed_at": "2026-06-11T08:00:00Z"},
    )

    scored = score_signal(signal, ScoringConfig())

    assert scored.on_prem_rubric["local_offline_runnability"].score >= 4
    assert "local/offline" in scored.on_prem_rubric["local_offline_runnability"].reason
    assert scored.on_prem_rubric["observability_auditability"].score >= 4
    assert "license_clear" in scored.reason_codes
