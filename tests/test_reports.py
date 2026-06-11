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
