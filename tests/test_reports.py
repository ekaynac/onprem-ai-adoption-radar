import json

from radar.models import Category, DecisionCard, Ring
from radar.reports.json_export import cards_to_json
from radar.reports.markdown import render_markdown_report


def test_render_markdown_report_contains_sections():
    card = DecisionCard(
        project="Cline",
        category=Category.CODING_AGENTS,
        ring=Ring.PILOT,
        summary="Coding agent",
        workflow_fit={"personal_dev": "high"},
        risk_level="high",
        risk_reasons=["Needs sandbox review."],
        evidence=["https://example.com"],
    )

    markdown = render_markdown_report([card], title="Weekly Agent Radar")

    assert "# Weekly Agent Radar" in markdown
    assert "## Try This Week" in markdown
    assert "Cline" in markdown
    assert "Needs sandbox review." in markdown


def test_cards_to_json_returns_valid_json():
    card = DecisionCard(
        project="Cline",
        category=Category.CODING_AGENTS,
        ring=Ring.PILOT,
        summary="Coding agent",
        workflow_fit={"personal_dev": "high"},
        risk_level="medium",
    )

    payload = json.loads(cards_to_json([card]))

    assert payload[0]["project"] == "Cline"
    assert payload[0]["ring"] == "pilot"


def test_markdown_report_uses_structured_sections_and_sanitizes_headings():
    card = DecisionCard(
        project="OpenClaw",
        category=Category.GENERAL_AGENTS,
        ring=Ring.PILOT,
        summary="## Raw upstream heading should not render",
        workflow_fit={"enterprise_onprem": "high"},
        risk_level="medium",
        what_changed=["Added local provider routing.", "Fixed audit logging."],
        why_it_matters="Better fit for controlled enterprise pilots.",
        on_prem_fit="strong: local/offline runnability and audit hooks look promising.",
        risks=["Needs permission sandbox validation."],
        try_next=["Run a local-only smoke test."],
        evidence=["https://example.com/release"],
    )

    markdown = render_markdown_report([card], title="Weekly Agent Radar")

    assert "What changed" in markdown
    assert "Why it matters" in markdown
    assert "On-prem fit" in markdown
    assert "Risks" in markdown
    assert "Try next" in markdown
    assert "Evidence" in markdown
    assert "### Raw upstream heading" not in markdown
    assert "- Added local provider routing." in markdown
