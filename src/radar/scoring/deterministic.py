"""Deterministic signal scoring."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from radar.models import (
    Category,
    OnPremAssessment,
    ScoredSignal,
    ScoreBreakdown,
    ScoringConfig,
    Signal,
)
from radar.scoring.rings import ring_from_score


CLEAR_LICENSES = {
    "Apache-2.0",
    "MIT",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "MPL-2.0",
    "ISC",
}
RESTRICTIVE_LICENSES = {"AGPL-3.0", "GPL-2.0", "GPL-3.0", "SSPL-1.0"}


def score_signal(signal: Signal, config: ScoringConfig) -> ScoredSignal:
    """Score a signal using explainable rules."""
    tags = set(signal.tags)
    reason_codes: list[str] = []
    metadata = signal.metadata or {}

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
    on_prem_relevance = 4 if {"on-prem-relevant", "sandbox", "mcp", "self-hosted"} & tags else 3
    demo_value = 4 if signal.category != Category.AGENT_FRAMEWORKS else 3
    setup_friction = 4 if "kubernetes" not in tags else 2

    risky_tags = set(config.security_penalty_tags) & tags
    if risky_tags:
        security_posture = 2
        reason_codes.append("needs_sandbox_review")
    else:
        security_posture = 4

    rubric = build_on_prem_rubric(signal)
    reason_codes.extend(_reason_codes_from_rubric(rubric, metadata))

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
        reason_codes=sorted(set(reason_codes)),
        recommended_ring=ring,
        on_prem_rubric=rubric,
    )


def build_on_prem_rubric(signal: Signal) -> dict[str, OnPremAssessment]:
    """Build a deterministic on-prem enterprise adoption assessment."""
    tags = set(signal.tags)
    metadata = signal.metadata or {}
    repo_snapshot = metadata.get("repo_snapshot") or {}
    merged_metadata: dict[str, Any] = {**repo_snapshot, **metadata}
    text = " ".join(
        [signal.title, signal.raw_summary, " ".join(tags), " ".join(merged_metadata.get("topics") or [])]
    ).lower()

    license_id = str(merged_metadata.get("license") or "NOASSERTION")
    stars = int(merged_metadata.get("stars") or 0)
    pushed_at = str(merged_metadata.get("pushed_at") or "")

    return {
        "local_offline_runnability": _assessment(
            _score_keywords(
                tags,
                text,
                positives={"self-hosted", "local-model", "offline", "ollama", "lm studio"},
                negatives={"cloud-only", "saas-only", "gpu-required"},
                base=3,
            ),
            "local/offline posture inferred from self-hosted, local model, cloud-only, and hardware signals.",
        ),
        "model_provider_flexibility": _assessment(
            _score_keywords(
                tags,
                text,
                positives={"local-model", "ollama", "openai-compatible", "provider-agnostic", "mcp"},
                negatives={"single-provider", "cloud-only"},
                base=3,
            ),
            "Provider flexibility based on local model, OpenAI-compatible, MCP, and provider-lock signals.",
        ),
        "data_exposure_risk": _assessment(
            _score_keywords(
                tags,
                text,
                positives={"self-hosted", "offline", "local-model", "redaction"},
                negatives={"browser-access", "telemetry", "cloud-only", "external-api"},
                base=3,
            ),
            "Data exposure risk considers local execution, external APIs, browser access, telemetry, and redaction hints.",
        ),
        "tool_permission_sandbox_posture": _assessment(
            _score_keywords(
                tags,
                text,
                positives={"sandbox", "approval", "policy", "permissions", "audit"},
                negatives={"terminal-access", "file-write-access", "persistent-agent", "browser-access"},
                base=3,
            ),
            "Tool safety posture weighs sandbox/approval controls against terminal, file, browser, and persistent-agent access.",
        ),
        "deployment_complexity": _assessment(
            _score_keywords(
                tags,
                text,
                positives={"desktop", "cli", "docker", "single-binary", "self-hosted"},
                negatives={"kubernetes", "operator", "gpu-required", "multi-service"},
                base=3,
            ),
            "Deployment complexity balances laptop/CLI/Docker paths against Kubernetes, GPU, and multi-service requirements.",
        ),
        "observability_auditability": _assessment(
            _score_keywords(
                tags,
                text,
                positives={"audit", "logs", "observability", "trace", "policy"},
                negatives={"opaque", "no-logs"},
                base=3,
            ),
            "Auditability checks for logs, traces, policy, and explicit audit hooks.",
        ),
        "license_commercial_risk": _license_assessment(license_id),
        "enterprise_integration": _assessment(
            _score_keywords(
                tags,
                text,
                positives={"sso", "ldap", "rbac", "scim", "mcp", "api", "self-hosted"},
                negatives={"personal-only", "desktop-only"},
                base=3,
            ),
            "Enterprise integration looks for SSO/RBAC/API/MCP/self-hosted integration signals.",
        ),
        "maintenance_velocity": _maintenance_assessment(stars, pushed_at),
        "demo_value": _assessment(
            _score_keywords(
                tags,
                text,
                positives={"demo", "quickstart", "desktop", "cli", "template", "agent"},
                negatives={"framework-only", "research", "kubernetes"},
                base=4 if signal.category != Category.AGENT_FRAMEWORKS else 3,
            ),
            "Demo value estimates whether the project can show practical value quickly in a safe pilot.",
        ),
    }


def _score_keywords(
    tags: set[str],
    text: str,
    *,
    positives: set[str],
    negatives: set[str],
    base: int,
) -> int:
    score = base
    haystack = set(tags)
    for keyword in positives:
        if keyword in haystack or keyword in text:
            score += 1
            break
    for keyword in positives:
        if keyword in haystack or keyword in text:
            if keyword not in {"mcp", "api"}:
                score += 1
                break
    for keyword in negatives:
        if keyword in haystack or keyword in text:
            score -= 1
    return max(1, min(score, 5))


def _license_assessment(license_id: str) -> OnPremAssessment:
    if license_id in CLEAR_LICENSES:
        return _assessment(5, f"license {license_id} is commonly commercial-friendly; verify notices and dependencies.")
    if license_id in RESTRICTIVE_LICENSES:
        return _assessment(2, f"license {license_id} may add copyleft/commercial obligations; legal review needed.")
    return _assessment(3, f"license {license_id} is unknown or not asserted; confirm commercial terms before adoption.")


def _maintenance_assessment(stars: int, pushed_at: str) -> OnPremAssessment:
    score = 3
    if stars >= 1000:
        score += 1
    if pushed_at:
        try:
            pushed = datetime.fromisoformat(pushed_at.replace("Z", "+00:00"))
            age_days = (datetime.now(timezone.utc) - pushed).days
            if age_days <= 45:
                score += 1
            elif age_days > 365:
                score -= 1
        except ValueError:
            pass
    return _assessment(
        max(1, min(score, 5)),
        f"Maintenance velocity inferred from GitHub stars ({stars}) and latest push timestamp ({pushed_at or 'unknown'}).",
    )


def _assessment(score: int, reason: str) -> OnPremAssessment:
    return OnPremAssessment(score=max(1, min(score, 5)), reason=reason)


def _reason_codes_from_rubric(
    rubric: dict[str, OnPremAssessment], metadata: dict[str, Any]
) -> list[str]:
    codes: list[str] = []
    if rubric["local_offline_runnability"].score >= 4:
        codes.append("local_offline_ready")
    if rubric["tool_permission_sandbox_posture"].score <= 2:
        codes.append("permission_sandbox_gap")
    if rubric["observability_auditability"].score >= 4:
        codes.append("auditability_positive")
    license_id = str((metadata.get("repo_snapshot") or metadata).get("license") or "NOASSERTION")
    if license_id in CLEAR_LICENSES:
        codes.append("license_clear")
    elif license_id in RESTRICTIVE_LICENSES:
        codes.append("license_review_required")
    return codes
