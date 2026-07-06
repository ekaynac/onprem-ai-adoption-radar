from datetime import UTC, datetime

from radar.models import (
    Backer,
    BackerType,
    Category,
    Ring,
    ScoreBreakdown,
    ScoredSignal,
    Signal,
)
from radar.pipeline.cards import build_decision_cards


def _scored(project: str = "Cline") -> ScoredSignal:
    signal = Signal(
        id="s1",
        source_id="github-cline",
        project=project,
        category=Category.CODING_AGENTS,
        title=f"{project} released v1",
        url="https://github.com/cline/cline/releases/tag/v1",
        published_at=datetime(2026, 6, 10, tzinfo=UTC),
        raw_summary="release",
        signal_type="github_release",
        tags=[],
    )
    return ScoredSignal(
        signal=signal,
        scores=ScoreBreakdown(
            workflow_impact=4,
            laptop_runnability=4,
            open_source_maturity=4,
            on_prem_relevance=4,
            security_posture=4,
            demo_value=4,
            setup_friction=4,
        ),
        reason_codes=[],
        recommended_ring=Ring.PILOT,
    )


def test_cards_carry_backer_when_provided():
    backer = Backer(name="Cline", type=BackerType.STARTUP)
    cards = build_decision_cards(
        [_scored("Cline")], backer_by_project={"Cline": backer}
    )

    assert cards[0].backer == backer
    assert cards[0].backer.type is BackerType.STARTUP


def test_cards_without_backer_map_have_none():
    cards = build_decision_cards([_scored("Cline")])

    assert cards[0].backer is None


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


def test_cards_carry_evidence_notes_and_license_change_risk():
    from datetime import UTC, datetime

    from radar.models import (
        Category,
        ProjectEvidence,
        ScoreBreakdown,
        ScoredSignal,
        Signal,
    )
    from radar.models import Ring as RingEnum
    from radar.pipeline.cards import build_decision_cards

    signal = Signal(
        id="s1", source_id="src", project="vLLM", category=Category.MODEL_SERVING,
        title="vLLM repository snapshot", url="https://github.com/org/vllm",
        published_at=datetime(2026, 6, 12, tzinfo=UTC),
        signal_type="github_repo_snapshot",
    )
    scored = ScoredSignal(
        signal=signal,
        scores=ScoreBreakdown(
            workflow_impact=4, laptop_runnability=4, open_source_maturity=4,
            on_prem_relevance=4, security_posture=4, demo_value=4, setup_friction=4,
        ),
        recommended_ring=RingEnum.PILOT,
    )
    evidence = ProjectEvidence(
        star_growth=500, star_growth_pct=2.0,
        license_changed_from="Apache-2.0", license="BUSL-1.1",
    )

    cards = build_decision_cards([scored], evidence_by_project={"vLLM": evidence})

    card = cards[0]
    assert any("+500" in note for note in card.evidence_notes)
    assert any("Apache-2.0" in risk and "BUSL-1.1" in risk for risk in card.risks)


def test_cards_without_evidence_have_empty_notes():
    from datetime import UTC, datetime

    from radar.models import Category, ScoreBreakdown, ScoredSignal, Signal
    from radar.models import Ring as RingEnum
    from radar.pipeline.cards import build_decision_cards

    signal = Signal(
        id="s1", source_id="src", project="vLLM", category=Category.MODEL_SERVING,
        title="snapshot", url="https://github.com/org/vllm",
        published_at=datetime(2026, 6, 12, tzinfo=UTC),
        signal_type="github_repo_snapshot",
    )
    scored = ScoredSignal(
        signal=signal,
        scores=ScoreBreakdown(
            workflow_impact=4, laptop_runnability=4, open_source_maturity=4,
            on_prem_relevance=4, security_posture=4, demo_value=4, setup_friction=4,
        ),
        recommended_ring=RingEnum.PILOT,
    )

    cards = build_decision_cards([scored])

    assert cards[0].evidence_notes == []


def test_paper_urls_appear_in_card_evidence():
    from radar.models import PaperRef, ProjectEvidence

    evidence_by_project = {
        "vLLM": ProjectEvidence(
            paper_mentions=1,
            papers=[PaperRef(title="P", url="https://arxiv.org/abs/2506.1", published_at="2026-06-15")],
        )
    }
    signal = Signal(
        id="s1",
        source_id="src",
        project="vLLM",
        category=Category.MODEL_SERVING,
        title="vLLM repository snapshot",
        url="https://github.com/org/vllm",
        published_at=datetime(2026, 6, 12, tzinfo=UTC),
        signal_type="github_repo_snapshot",
    )
    scored = ScoredSignal(
        signal=signal,
        scores=ScoreBreakdown(
            workflow_impact=4,
            laptop_runnability=4,
            open_source_maturity=4,
            on_prem_relevance=4,
            security_posture=4,
            demo_value=4,
            setup_friction=4,
        ),
        recommended_ring=Ring.PILOT,
    )

    cards = build_decision_cards([scored], evidence_by_project=evidence_by_project)
    card = next(c for c in cards if c.project == "vLLM")
    assert "https://arxiv.org/abs/2506.1" in card.evidence


def test_cards_flag_upgrade_risk_from_release_highlights():
    from datetime import UTC, datetime

    from radar.models import Category, ScoreBreakdown, ScoredSignal, Signal
    from radar.models import Ring as RingEnum
    from radar.pipeline.cards import build_decision_cards

    signal = Signal(
        id="r1", source_id="src", project="vLLM", category=Category.MODEL_SERVING,
        title="vLLM released v2.0", url="https://github.com/org/vllm/releases/v2.0",
        published_at=datetime(2026, 6, 12, tzinfo=UTC),
        signal_type="github_release",
        metadata={"release_highlights": ["BREAKING CHANGE: new engine API."]},
    )
    scored = ScoredSignal(
        signal=signal,
        scores=ScoreBreakdown(
            workflow_impact=4, laptop_runnability=4, open_source_maturity=4,
            on_prem_relevance=4, security_posture=4, demo_value=4, setup_friction=4,
        ),
        recommended_ring=RingEnum.PILOT,
    )

    card = build_decision_cards([scored])[0]

    assert card.upgrade_risk == "high"
    assert any("BREAKING" in note for note in card.upgrade_risk_notes)
