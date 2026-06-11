"""Deterministic signal scoring."""

from __future__ import annotations

from radar.models import Category, ScoredSignal, ScoreBreakdown, ScoringConfig, Signal
from radar.scoring.rings import ring_from_score


def score_signal(signal: Signal, config: ScoringConfig) -> ScoredSignal:
    """Score a signal using explainable rules."""
    tags = set(signal.tags)
    reason_codes: list[str] = []

    workflow_impact = (
        4
        if signal.category in {Category.CODING_AGENTS, Category.GENERAL_AGENTS}
        else 3
    )
    if "mcp" in tags:
        workflow_impact += 1
        reason_codes.append("mcp_relevant")

    laptop_runnability = 5 if not {"kubernetes", "gpu-required"} & tags else 2
    open_source_maturity = 4 if "open-source" in tags else 3
    on_prem_relevance = 4 if {"on-prem-relevant", "sandbox", "mcp"} & tags else 3
    demo_value = 4 if signal.category != Category.AGENT_FRAMEWORKS else 3
    setup_friction = 4 if "kubernetes" not in tags else 2

    risky_tags = set(config.security_penalty_tags) & tags
    if risky_tags:
        security_posture = 2
        reason_codes.append("needs_sandbox_review")
    else:
        security_posture = 4

    scores = ScoreBreakdown(
        workflow_impact=min(workflow_impact, 5),
        laptop_runnability=laptop_runnability,
        open_source_maturity=open_source_maturity,
        on_prem_relevance=on_prem_relevance,
        security_posture=security_posture,
        demo_value=demo_value,
        setup_friction=setup_friction,
    )
    ring = ring_from_score(scores.average, scores.security_posture)
    return ScoredSignal(
        signal=signal,
        scores=scores,
        reason_codes=reason_codes,
        recommended_ring=ring,
    )
