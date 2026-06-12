"""Decision card generation."""

from __future__ import annotations

import re
from collections import defaultdict

from radar.models import DecisionCard, OnPremAssessment, Ring, ScoredSignal
from radar.scoring.calibrate import calibrate_rings


def build_decision_cards(scored_signals: list[ScoredSignal]) -> list[DecisionCard]:
    """Build one decision card per project.

    Rings are calibrated across the whole batch (hybrid absolute + quartile)
    so they discriminate instead of collapsing into one band; the calibrated
    ring overrides each project's per-signal recommendation everywhere.
    """
    grouped: dict[str, list[ScoredSignal]] = defaultdict(list)
    for scored in scored_signals:
        grouped[scored.signal.project].append(scored)

    projects = list(grouped)
    bests = {
        project: sorted(items, key=lambda i: i.scores.average, reverse=True)[0]
        for project, items in grouped.items()
    }
    calibrated = calibrate_rings(
        [
            (
                bests[p].scores.average,
                bests[p].scores.security_posture,
                bests[p].scores.on_prem_relevance,  # tiebreak within score ties
            )
            for p in projects
        ]
    )
    rings = dict(zip(projects, calibrated))

    cards: list[DecisionCard] = []
    for project in projects:
        items = sorted(
            grouped[project], key=lambda item: item.signal.published_at, reverse=True
        )
        # Override the per-signal ring with the batch-calibrated ring so every
        # derived field (try steps, why-it-matters, demo suitability) agrees.
        best = bests[project].model_copy(
            update={"recommended_ring": rings[project]}
        )
        risk_level = _risk_level(best)
        risk_reasons = _risk_reasons(best)
        rubric = _merge_rubric(items)
        cards.append(
            DecisionCard(
                project=project,
                category=best.signal.category,
                ring=best.recommended_ring,
                score=best.scores.average,
                summary=_summary(best, rubric),
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
                what_changed=_what_changed(items),
                why_it_matters=_why_it_matters(best),
                on_prem_fit=_on_prem_fit(rubric),
                on_prem_rubric=rubric,
                risk_reasons=risk_reasons,
                risks=_risks(best, rubric),
                try_this_week=_try_steps(best),
                try_next=_try_steps(best),
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
    steps = [
        "Run a local-only smoke test on a disposable repository or workflow.",
        "Record network calls, permissions requested, generated files, and audit logs.",
    ]
    if scored.scores.security_posture <= 2:
        steps.append("Validate sandbox/approval boundaries before exposing enterprise data.")
    else:
        steps.append("Compare workflow value against setup friction and operational visibility.")
    return steps


def _summary(best: ScoredSignal, rubric: dict[str, OnPremAssessment]) -> str:
    fit = _on_prem_fit(rubric)
    return f"{best.signal.title}. {fit}"


def _what_changed(items: list[ScoredSignal]) -> list[str]:
    changes: list[str] = []
    for item in items:
        signal = item.signal
        highlights = signal.metadata.get("release_highlights") or []
        if signal.signal_type == "github_repo_snapshot":
            snapshot = signal.metadata
            bits = []
            if snapshot.get("stars") is not None:
                bits.append(f"{snapshot.get('stars')} stars")
            if snapshot.get("open_issues") is not None:
                bits.append(f"{snapshot.get('open_issues')} open issues")
            if snapshot.get("pushed_at"):
                bits.append(f"last pushed {snapshot.get('pushed_at')}")
            if snapshot.get("license"):
                bits.append(f"license {snapshot.get('license')}")
            if bits:
                changes.append("Repo snapshot: " + ", ".join(bits) + ".")
            continue
        for highlight in highlights:
            changes.append(_clean_text(highlight, max_chars=220))
        if not highlights and signal.raw_summary:
            changes.append(_clean_text(signal.raw_summary, max_chars=220))
        if len(changes) >= 5:
            break
    return _dedupe([change for change in changes if change])[:5]


def _why_it_matters(best: ScoredSignal) -> str:
    if best.recommended_ring in {Ring.ADOPT, Ring.PILOT}:
        return "High-value signal for near-term enterprise evaluation because it combines workflow relevance with testable local adoption evidence."
    if best.recommended_ring == Ring.WATCH:
        return "Worth tracking, but current signals need stronger proof around local operation, safety controls, or operational maturity."
    return "Current risk or friction signals outweigh likely short-term adoption value."


def _on_prem_fit(rubric: dict[str, OnPremAssessment]) -> str:
    if not rubric:
        return "On-prem fit unknown: no rubric evidence was available."
    avg = sum(item.score for item in rubric.values()) / len(rubric)
    strong = [name for name, item in rubric.items() if item.score >= 4]
    weak = [name for name, item in rubric.items() if item.score <= 2]
    if avg >= 4:
        prefix = "strong"
    elif avg >= 3:
        prefix = "mixed"
    else:
        prefix = "weak"
    detail = f"strongest in {', '.join(_label(name) for name in strong[:3])}" if strong else "no standout strengths yet"
    if weak:
        detail += f"; watch {_label(weak[0])}"
    return f"{prefix}: {detail}."


def _risks(best: ScoredSignal, rubric: dict[str, OnPremAssessment]) -> list[str]:
    risks = list(_risk_reasons(best))
    for name, assessment in rubric.items():
        if assessment.score <= 2:
            risks.append(f"{_label(name)}: {assessment.reason}")
    return _dedupe(risks)[:5]


def _merge_rubric(items: list[ScoredSignal]) -> dict[str, OnPremAssessment]:
    for item in items:
        if item.on_prem_rubric:
            return item.on_prem_rubric
    return {}


def _label(name: str) -> str:
    return name.replace("_", " ")


def _clean_text(text: str, max_chars: int = 240) -> str:
    text = re.sub(r"^#+\s*", "", text.strip())
    text = re.sub(r"^[>*`_\-+\s]+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result
