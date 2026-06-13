"""Tests for URL/file slugging shared by the web layer."""

from __future__ import annotations

from radar.web.slugs import build_slug_map, project_slug


def test_project_slug_basic():
    assert project_slug("vLLM") == "vllm"
    assert project_slug("Model Context Protocol") == "model-context-protocol"
    assert project_slug("Open WebUI!") == "open-webui"


def test_build_slug_map_is_one_to_one_without_collisions():
    slugs = build_slug_map(["vLLM", "Ollama", "Aider"])

    assert slugs == {"vLLM": "vllm", "Ollama": "ollama", "Aider": "aider"}


def test_build_slug_map_resolves_collisions_deterministically():
    # Two distinct names that slug to the same base must get distinct slugs.
    # "Open WebUI" and "Open-WebUI" both reduce to "open-webui".
    slugs = build_slug_map(["Open WebUI", "Open-WebUI"])

    assert slugs["Open WebUI"] != slugs["Open-WebUI"]
    assert set(slugs.values()) == {"open-webui", "open-webui-2"}
    # Deterministic regardless of input order.
    assert build_slug_map(["Open-WebUI", "Open WebUI"]) == build_slug_map(
        ["Open WebUI", "Open-WebUI"]
    )
