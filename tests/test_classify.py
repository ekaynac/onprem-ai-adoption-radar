"""Tests for the firehose entry->project classification layer."""

from __future__ import annotations

from datetime import datetime, timezone

from radar.models import Category, Signal, SourceConfig, SourceType
from radar.pipeline.classify import (
    build_project_index,
    classify_text,
    reclassify_firehose,
)


def _tracked(project: str, category: Category, aliases=None) -> SourceConfig:
    return SourceConfig(
        id=f"github-{project.lower()}",
        type=SourceType.GITHUB_REPO,
        project=project,
        category=category,
        url=f"https://github.com/x/{project.lower()}",
        aliases=aliases or [],
    )


def _signal(title: str, *, firehose: bool, source_id: str = "rss-hf") -> Signal:
    return Signal(
        id=f"rss:{source_id}:{title}",
        source_id=source_id,
        project="HuggingFace Blog",
        category=Category.MODEL_SERVING,
        title=title,
        url=f"https://example.com/{abs(hash(title))}",
        published_at=datetime(2026, 6, 10, tzinfo=timezone.utc),
        raw_summary="",
        signal_type="rss_entry",
        metadata={"firehose": firehose},
    )


def _index():
    return build_project_index(
        [
            _tracked("vLLM", Category.MODEL_SERVING),
            _tracked("TensorRT-LLM", Category.MODEL_SERVING, aliases=["tensorrt llm"]),
        ]
    )


# ── classify_text ─────────────────────────────────────────────────────────────


def test_classify_matches_project_name_word_boundary():
    match = classify_text("New vLLM 0.6 release boosts throughput", _index())
    assert match is not None
    assert match.project == "vLLM"
    assert match.category == Category.MODEL_SERVING


def test_classify_matches_alias():
    match = classify_text("Deploying with TensorRT LLM on Hopper", _index())
    assert match is not None
    assert match.project == "TensorRT-LLM"


def test_classify_returns_none_when_no_tracked_project_mentioned():
    assert classify_text("A general post about prompt engineering", _index()) is None


def test_classify_avoids_substring_false_positive():
    # "evilllm" must not match "vLLM"
    assert classify_text("the evilllm chronicles", _index()) is None


def test_classify_normalizes_punctuation_in_project_name():
    # Project "llama.cpp" should match text that writes it as "llama cpp".
    index = build_project_index([_tracked("llama.cpp", Category.MODEL_SERVING)])
    match = classify_text("Running models with llama cpp on a laptop", index)
    assert match is not None
    assert match.project == "llama.cpp"


def test_classify_matches_hyphenated_name_written_with_space():
    index = build_project_index([_tracked("TensorRT-LLM", Category.MODEL_SERVING)])
    assert classify_text("TensorRT LLM speeds up inference", index) is not None


def test_classify_derives_alias_from_github_repo_slug():
    # Display name has an org prefix; the repo slug is the short name people use.
    src = SourceConfig(
        id="github-nemoclaw",
        type=SourceType.GITHUB_REPO,
        project="NVIDIA NemoClaw",
        category=Category.SANDBOX_GOVERNANCE,
        url="https://github.com/NVIDIA/NemoClaw",
    )
    index = build_project_index([src])
    match = classify_text("NemoClaw adds new guardrails", index)
    assert match is not None
    assert match.project == "NVIDIA NemoClaw"


def test_slug_alias_not_derived_for_non_github_urls():
    # A docs URL must not contribute a junk slug like "intro".
    src = SourceConfig(
        id="manual-mcp",
        type=SourceType.MANUAL,
        project="Model Context Protocol",
        category=Category.MCP_TOOLING,
        url="https://modelcontextprotocol.io/docs/getting-started/intro",
    )
    index = build_project_index([src])
    assert classify_text("a quick intro to gardening", index) is None


# ── reclassify_firehose ───────────────────────────────────────────────────────


def test_reclassify_reattributes_firehose_signal_to_matched_project():
    result = reclassify_firehose([_signal("vLLM hits new speed", firehose=True)], _index())

    assert len(result.kept) == 1
    assert result.kept[0].project == "vLLM"
    assert result.kept[0].category == Category.MODEL_SERVING
    assert result.dropped_titles == []


def test_reclassify_drops_unmatched_firehose_and_records_title():
    result = reclassify_firehose(
        [_signal("Unrelated musings on UX", firehose=True)], _index()
    )

    assert result.kept == []
    assert result.dropped_titles == ["Unrelated musings on UX"]


def test_reclassify_passes_through_non_firehose_signals_untouched():
    sig = _signal("NVIDIA blog post", firehose=False, source_id="rss-nvidia")
    sig = sig.model_copy(update={"project": "NVIDIA Developer Blog"})

    result = reclassify_firehose([sig], _index())

    assert len(result.kept) == 1
    assert result.kept[0].project == "NVIDIA Developer Blog"  # unchanged
    assert result.dropped_titles == []


def test_reclassify_does_not_mutate_input():
    sig = _signal("vLLM speed", firehose=True)
    reclassify_firehose([sig], _index())
    assert sig.project == "HuggingFace Blog"  # original untouched


# ── optional LLM analyst (second pass on the dropped tail) ─────────────────────


def test_analyst_recovers_a_deterministically_dropped_entry():
    # Text never names the project literally, so deterministic match drops it.
    seen = {}

    def fake_analyst(text, candidates):
        seen["candidates"] = candidates
        return "vLLM"  # the analyst resolves the ambiguous entry

    result = reclassify_firehose(
        [_signal("A new way to serve models fast", firehose=True)],
        _index(),
        analyst=fake_analyst,
    )

    assert len(result.kept) == 1
    assert result.kept[0].project == "vLLM"
    assert result.kept[0].category == Category.MODEL_SERVING
    assert result.dropped_titles == []
    assert result.llm_recovered == 1
    # The analyst is only offered tracked project names as candidates.
    assert "vLLM" in seen["candidates"]


def test_analyst_returning_non_candidate_is_ignored():
    def bad_analyst(text, candidates):
        return "Totally Made Up Project"

    result = reclassify_firehose(
        [_signal("ramblings", firehose=True)], _index(), analyst=bad_analyst
    )

    assert result.kept == []
    assert result.dropped_titles == ["ramblings"]
    assert result.llm_recovered == 0


def test_analyst_not_called_for_deterministically_matched_entries():
    calls = []

    def spy_analyst(text, candidates):
        calls.append(text)
        return None

    reclassify_firehose(
        [_signal("vLLM 0.7 is out", firehose=True)], _index(), analyst=spy_analyst
    )

    assert calls == []  # deterministic match short-circuits; no LLM call
