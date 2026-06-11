from radar.models import Category, DecisionCard, Ring
from radar.pipeline.quotas import apply_category_quotas


def card(project: str, category: Category) -> DecisionCard:
    return DecisionCard(
        project=project,
        category=category,
        ring=Ring.PILOT,
        summary=project,
        workflow_fit={"personal_dev": "high"},
        risk_level="medium",
    )


def test_apply_category_quotas_limits_each_category():
    cards = [
        card("A", Category.CODING_AGENTS),
        card("B", Category.CODING_AGENTS),
        card("C", Category.MCP_TOOLING),
    ]

    selected = apply_category_quotas(cards, {Category.CODING_AGENTS: 1})

    assert [item.project for item in selected] == ["A", "C"]
