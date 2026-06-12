"""Tests for the optional LLM analyst (offline, injected completion)."""

from __future__ import annotations

from radar.models import LLMConfig
from radar.pipeline.llm_classify import LLMAnalyst, build_analyst


CANDIDATES = ["vLLM", "Ollama", "TensorRT-LLM"]


def test_analyst_returns_matched_candidate():
    captured = {}

    def complete(prompt: str) -> str:
        captured["prompt"] = prompt
        return "vLLM"

    analyst = LLMAnalyst(complete)
    assert analyst("a fast serving engine", CANDIDATES) == "vLLM"
    # The prompt must constrain the model to the candidate list + the entry.
    assert "vLLM" in captured["prompt"]
    assert "a fast serving engine" in captured["prompt"]


def test_analyst_none_answer_returns_none():
    analyst = LLMAnalyst(lambda p: "NONE")
    assert analyst("unrelated", CANDIDATES) is None


def test_analyst_hallucinated_answer_rejected():
    analyst = LLMAnalyst(lambda p: "Some Other Thing")
    assert analyst("text", CANDIDATES) is None


def test_analyst_is_case_insensitive_and_trims():
    analyst = LLMAnalyst(lambda p: "  ollama\n")
    assert analyst("local models", CANDIDATES) == "Ollama"


def test_analyst_ignores_extra_prose_around_answer():
    analyst = LLMAnalyst(lambda p: "Answer: TensorRT-LLM")
    assert analyst("nvidia inference", CANDIDATES) == "TensorRT-LLM"


def test_completion_errors_are_swallowed_to_none():
    def boom(prompt: str) -> str:
        raise RuntimeError("model down")

    analyst = LLMAnalyst(boom)
    assert analyst("text", CANDIDATES) is None


# ── factory gating ────────────────────────────────────────────────────────────


def test_build_analyst_disabled_returns_none():
    assert build_analyst(LLMConfig(enabled=False)) is None


def test_build_analyst_enabled_returns_callable():
    analyst = build_analyst(
        LLMConfig(enabled=True, base_url="http://localhost:11434/v1", model="qwen2.5:3b")
    )
    assert callable(analyst)
