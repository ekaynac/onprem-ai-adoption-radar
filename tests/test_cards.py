from datetime import UTC, datetime

from radar.models import Category, Ring, ScoreBreakdown, ScoredSignal, Signal
from radar.pipeline.cards import build_decision_cards


def test_build_decision_cards_groups_by_project():
    signal = Signal(
        id="s1",
        source_id="github-cline",
        project="Cline",
        category=Category.CODING_AGENTS,
        title="Cline released v1",
        url="https://github.com/cline/cline/releases/tag/v1",
        published_at=datetime(2026, 6, 10, tzinfo=UTC),
        raw_summary="MCP approval improvements",
        signal_type="github_release",
        tags=["file-write-access"],
    )
    scored = ScoredSignal(
        signal=signal,
        scores=ScoreBreakdown(
            workflow_impact=5,
            laptop_runnability=5,
            open_source_maturity=4,
            on_prem_relevance=3,
            security_posture=2,
            demo_value=4,
            setup_friction=4,
        ),
        reason_codes=["needs_sandbox_review"],
        recommended_ring=Ring.PILOT,
    )

    cards = build_decision_cards([scored])

    assert len(cards) == 1
    assert cards[0].project == "Cline"
    assert cards[0].ring == Ring.PILOT
    assert cards[0].risk_level == "high"
    assert "https://github.com/cline/cline/releases/tag/v1" in cards[0].evidence


def test_clean_text_unescapes_entities_and_strips_html_tags():
    from radar.pipeline.cards import _clean_text

    text = "It&amp;#39;s a <strong>big</strong> release<br/> with &lt;tags&gt; <!-- noise -->"

    assert _clean_text(text) == "It's a big release with <tags>"
