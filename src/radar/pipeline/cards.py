"""Decision card generation."""

from __future__ import annotations

import html
import re
from collections import defaultdict

from radar.models import (
    Backer,
    DecisionCard,
    OnPremAssessment,
    ProjectEvidence,
    Ring,
    ScoredSignal,
)
from radar.pipeline.evidence import evidence_notes
from radar.pipeline.upgrade_risk import assess_upgrade_risk
from radar.scoring.calibrate import calibrate_rings
from radar.scoring.profiles import weighted_average


def build_decision_cards(
    scored_signals: list[ScoredSignal],
    evidence_by_project: dict[str, ProjectEvidence] | None = None,
    weights: dict[str, float] | None = None,
    backer_by_project: dict[str, Backer] | None = None,
) -> list[DecisionCard]:
    """Build one decision card per project.

    Rings are calibrated across the whole batch (hybrid absolute + quartile)
    so they discriminate instead of collapsing into one band; the calibrated
    ring overrides each project's per-signal recommendation everywhere.
    ``evidence_by_project`` adds observed-data notes (and license-change
    risks) to each project's card. ``weights`` re-weights the dimensions
    (a scoring profile) before ranking and is reflected in each card score.
    """
    grouped: dict[str, list[ScoredSignal]] = defaultdict(list)
    for scored in scored_signals:
        grouped[scored.signal.project].append(scored)

    projects = list(grouped)

    def project_score(item: ScoredSignal) -> float:
        return weighted_average(item.scores, weights)

    bests = {
        project: sorted(items, key=project_score, reverse=True)[0]
        for project, items in grouped.items()
    }
    calibrated = calibrate_rings(
        [
            (
                project_score(bests[p]),
                bests[p].scores.security_posture,
                bests[p].scores.on_prem_relevance,  # tiebreak within score ties
            )
            for p in projects
        ]
    )
    rings = dict(zip(projects, calibrated, strict=True))

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
        evidence_for_project = (evidence_by_project or {}).get(project)
        upgrade_risk, upgrade_risk_notes = assess_upgrade_risk(
            _release_note_lines(items)
        )
        cards.append(
            DecisionCard(
                project=project,
                category=best.signal.category,
                backer=(backer_by_project or {}).get(project),
                ring=best.recommended_ring,
                score=project_score(best),
                score_breakdown=best.scores,
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
                risks=_risks(best, rubric, evidence_for_project),
                evidence_notes=(
                    evidence_notes(evidence_for_project) if evidence_for_project else []
                ),
                upgrade_risk=upgrade_risk,
                upgrade_risk_notes=[
                    _clean_text(note) for note in upgrade_risk_notes[:3]
                ],
                try_this_week=_try_steps(best),
                try_next=_try_steps(best),
                company_demo={
                    "suitable": best.recommended_ring in {Ring.ADOPT, Ring.PILOT},
                    "angle": f"{project} adoption review with workflow and safety notes",
                },
                evidence=sorted(
                    {str(item.signal.url) for item in items}
                    | {
                        p.url
                        for p in (
                            evidence_for_project.papers if evidence_for_project else []
                        )
                    }
                ),
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


def _risks(
    best: ScoredSignal,
    rubric: dict[str, OnPremAssessment],
    evidence: ProjectEvidence | None = None,
) -> list[str]:
    risks: list[str] = []
    if evidence is not None:
        # Observed risk events lead the list — they must survive the [:5] cap.
        if evidence.license_changed_from:
            risks.append(
                f"License changed from {evidence.license_changed_from} to "
                f"{evidence.license or 'unknown'}; re-review commercial terms."
            )
        for advisory in evidence.advisories:
            risks.append(f"Recent {advisory.severity} security advisory {advisory.id}.")
    risks.extend(_risk_reasons(best))
    for name, assessment in rubric.items():
        if assessment.score <= 2:
            risks.append(f"{_label(name)}: {assessment.reason}")
    return _dedupe(risks)[:5]


def _release_note_lines(items: list[ScoredSignal]) -> list[str]:
    """All release-note lines for a project's signals in this scan."""
    lines: list[str] = []
    for item in items:
        if item.signal.signal_type != "github_release":
            continue
        highlights = item.signal.metadata.get("release_highlights") or []
        lines.extend(str(h) for h in highlights)
        if not highlights and item.signal.raw_summary:
            lines.extend(item.signal.raw_summary.splitlines())
    return lines


def _merge_rubric(items: list[ScoredSignal]) -> dict[str, OnPremAssessment]:
    for item in items:
        if item.on_prem_rubric:
            return item.on_prem_rubric
    return {}


def _label(name: str) -> str:
    return name.replace("_", " ")


def _clean_text(text: str, max_chars: int = 240) -> str:
    # RSS summaries arrive as HTML, often with double-escaped entities
    # (&amp;#39;). Strip comments and tags first, then unescape twice so the
    # report shows plain prose instead of markup soup.
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(html.unescape(text))
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
