"""Decision card generation."""

from __future__ import annotations

from collections import defaultdict

from radar.models import DecisionCard, Ring, ScoredSignal


def build_decision_cards(scored_signals: list[ScoredSignal]) -> list[DecisionCard]:
    """Build one decision card per project."""
    grouped: dict[str, list[ScoredSignal]] = defaultdict(list)
    for scored in scored_signals:
        grouped[scored.signal.project].append(scored)

    cards: list[DecisionCard] = []
    for project, items in grouped.items():
        best = sorted(items, key=lambda item: item.scores.average, reverse=True)[0]
        risk_level = _risk_level(best)
        risk_reasons = _risk_reasons(best)
        cards.append(
            DecisionCard(
                project=project,
                category=best.signal.category,
                ring=best.recommended_ring,
                summary=best.signal.raw_summary or best.signal.title,
                workflow_fit={
                    "personal_dev": (
                        "high" if best.scores.workflow_impact >= 4 else "medium"
                    ),
                    "company_demo": (
                        "high" if best.scores.demo_value >= 4 else "medium"
                    ),
                    "enterprise_onprem": (
                        "high" if best.scores.on_prem_relevance >= 4 else "medium"
                    ),
                },
                risk_level=risk_level,
                risk_reasons=risk_reasons,
                try_this_week=_try_steps(best),
                company_demo={
                    "suitable": best.recommended_ring in {Ring.ADOPT, Ring.PILOT},
                    "angle": f"{project} adoption review with workflow and safety notes",
                },
                evidence=sorted({str(item.signal.url) for item in items}),
                tags=sorted({tag for item in items for tag in item.signal.tags}),
            )
        )
    return sorted(cards, key=lambda card: (card.category.value, card.project.lower()))


def _risk_level(scored: ScoredSignal) -> str:
    if scored.scores.security_posture <= 2:
        return "high"
    if scored.scores.security_posture == 3:
        return "medium"
    return "low"


def _risk_reasons(scored: ScoredSignal) -> list[str]:
    if "needs_sandbox_review" in scored.reason_codes:
        return ["Requires sandbox or approval review before serious use."]
    return ["No major local execution risk detected from configured tags."]


def _try_steps(scored: ScoredSignal) -> list[str]:
    if scored.recommended_ring == Ring.AVOID:
        return []
    return [
        "Read official docs and release notes.",
        "Try on a disposable repository or low-risk workflow.",
        "Record setup friction, permissions needed, and workflow value.",
    ]
