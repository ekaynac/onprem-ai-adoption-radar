from datetime import datetime, timezone

import pytest

from radar.models import Category, Ring, ScoringConfig, Signal
from radar.scoring.deterministic import score_signal
from radar.scoring.rings import ring_from_score


def _make_signal(
    *,
    id: str = "s0",
    source_id: str = "test-src",
    project: str = "Test Project",
    category: Category = Category.CODING_AGENTS,
    tags: list[str] | None = None,
    metadata: dict | None = None,
) -> Signal:
    return Signal(
        id=id,
        source_id=source_id,
        project=project,
        category=category,
        title=f"{project} snapshot",
        url=f"https://example.com/{id}",
        published_at=datetime(2026, 6, 12, tzinfo=timezone.utc),
        raw_summary="",
        signal_type="github_repo_snapshot",
        tags=tags or [],
        metadata=metadata or {},
    )


def test_ring_from_score_accounts_for_security_posture():
    assert ring_from_score(4.5, security_posture=4) == Ring.ADOPT
    assert ring_from_score(4.2, security_posture=2) == Ring.PILOT
    assert ring_from_score(2.0, security_posture=1) == Ring.AVOID


def test_score_signal_marks_file_write_access_as_risk():
    signal = Signal(
        id="s1",
        source_id="github-cline",
        project="Cline",
        category=Category.CODING_AGENTS,
        title="Cline released v1",
        url="https://github.com/cline/cline/releases/tag/v1",
        published_at=datetime(2026, 6, 10, tzinfo=timezone.utc),
        raw_summary="MCP approval improvements",
        signal_type="github_release",
        tags=["coding-agent", "file-write-access", "terminal-access", "mcp"],
    )

    scored = score_signal(signal, ScoringConfig())

    assert scored.scores.workflow_impact >= 4
    assert scored.scores.security_posture == 2
    assert "needs_sandbox_review" in scored.reason_codes
    assert scored.recommended_ring == Ring.PILOT


def test_score_signal_builds_on_prem_rubric_from_tags_and_metadata():
    signal = Signal(
        id="s2",
        source_id="github-openclaw",
        project="OpenClaw",
        category=Category.GENERAL_AGENTS,
        title="OpenClaw repo snapshot",
        url="https://github.com/openclaw/openclaw",
        published_at=datetime(2026, 6, 11, tzinfo=timezone.utc),
        raw_summary="Repo snapshot",
        signal_type="github_repo_snapshot",
        tags=["open-source", "self-hosted", "local-model", "audit", "sso", "mcp"],
        metadata={"license": "Apache-2.0", "stars": 1200, "pushed_at": "2026-06-11T08:00:00Z"},
    )

    scored = score_signal(signal, ScoringConfig())

    assert scored.on_prem_rubric["local_offline_runnability"].score >= 4
    assert "local/offline" in scored.on_prem_rubric["local_offline_runnability"].reason
    assert scored.on_prem_rubric["observability_auditability"].score >= 4
    assert "license_clear" in scored.reason_codes


# ── New-category scoring tests ─────────────────────────────────────────────

def test_model_serving_scores_high_on_prem_relevance():
    """Model-serving signals should get on_prem_relevance=5 regardless of tags."""
    signal = _make_signal(
        id="s-vllm",
        source_id="github-vllm",
        project="vLLM",
        category=Category.MODEL_SERVING,
        tags=["model-serving", "openai-compatible", "self-hosted", "open-source", "gpu-required", "on-prem-relevant"],
        metadata={"license": "Apache-2.0", "stars": 25000, "pushed_at": "2026-06-10T10:00:00Z"},
    )

    scored = score_signal(signal, ScoringConfig())

    assert scored.scores.on_prem_relevance == 5
    assert scored.scores.workflow_impact >= 4
    assert scored.scores.laptop_runnability == 2  # gpu-required tag


def test_ai_infrastructure_scores_high_on_prem_relevance():
    """AI infrastructure signals (GPU Operator, KAITO) should get on_prem_relevance=5."""
    signal = _make_signal(
        id="s-gpu-op",
        source_id="github-nvidia-gpu-operator",
        project="NVIDIA GPU Operator",
        category=Category.AI_INFRASTRUCTURE,
        tags=["kubernetes", "gpu-required", "on-prem-relevant", "open-source", "operator"],
        metadata={"license": "Apache-2.0", "stars": 3000, "pushed_at": "2026-06-08T00:00:00Z"},
    )

    scored = score_signal(signal, ScoringConfig())

    assert scored.scores.on_prem_relevance == 5
    assert scored.scores.laptop_runnability == 2  # kubernetes + gpu-required
    assert scored.scores.setup_friction == 2  # kubernetes tag


def test_physical_ai_infrastructure_scores_high_on_prem_relevance_and_lower_demo():
    """Hardware signals should score max on-prem relevance, lower demo value."""
    signal = _make_signal(
        id="s-blackwell",
        source_id="manual-nvidia-blackwell",
        project="NVIDIA Blackwell / GB200",
        category=Category.PHYSICAL_AI_INFRASTRUCTURE,
        tags=["hardware", "gpu-required", "on-prem-relevant", "nvidia", "data-center"],
    )

    scored = score_signal(signal, ScoringConfig())

    assert scored.scores.on_prem_relevance == 5
    assert scored.scores.demo_value <= 4  # category reduces demo base
    assert scored.on_prem_rubric["deployment_complexity"].score <= 3  # gpu-required


@pytest.mark.parametrize("category", [
    Category.MODEL_SERVING,
    Category.AI_INFRASTRUCTURE,
    Category.PHYSICAL_AI_INFRASTRUCTURE,
])
def test_new_categories_produce_valid_scored_signal(category: Category):
    """All new categories must produce a fully valid ScoredSignal."""
    signal = _make_signal(
        id=f"s-{category.value}",
        source_id=f"test-{category.value}",
        project=f"Test {category.value}",
        category=category,
        tags=["open-source", "on-prem-relevant"],
    )

    scored = score_signal(signal, ScoringConfig())

    assert scored.scores.average >= 1.0
    assert scored.recommended_ring in {Ring.ADOPT, Ring.PILOT, Ring.WATCH, Ring.AVOID}
    assert scored.on_prem_rubric  # rubric must be non-empty
