"""Platform capability matrix seed."""

from __future__ import annotations

from pathlib import Path

import pytest

from radar.models_radar.platform_matrix import (
    PlatformMatrixError,
    load_platform_matrix,
)


_REPO_ROOT = Path(__file__).resolve().parents[1]
_SEED = _REPO_ROOT / "config" / "platform-matrix.yaml"


def test_bundled_matrix_loads_with_priority_engines():
    platforms = {p.id: p for p in load_platform_matrix(_SEED)}
    for pid in ("vllm", "sglang", "tensorrt-llm", "llama-cpp", "ollama"):
        assert pid in platforms, pid
    vllm = platforms["vllm"]
    assert vllm.features["mla"] == "yes"          # vLLM ships DeepSeek MLA
    assert vllm.hardware["nvidia"] == "yes"
    assert vllm.sources and vllm.verified


def test_every_engine_cites_sources_and_no_stray_keys():
    for p in load_platform_matrix(_SEED):
        assert p.sources, p.id
        assert p.verified, p.id


def test_unknown_feature_key_rejected(tmp_path: Path):
    bad = tmp_path / "m.yaml"
    bad.write_text(
        "platforms:\n"
        "  - id: x\n    name: X\n    repo_url: https://x\n"
        '    hardware: {nvidia: "yes"}\n'
        '    features: {warp_drive: "yes"}\n'
        "    sources: [https://x/docs]\n    verified: '2026-07-29'\n",
        encoding="utf-8",
    )
    with pytest.raises(PlatformMatrixError, match="warp_drive"):
        load_platform_matrix(bad)


def test_bare_yaml_booleans_are_coerced_not_fatal(tmp_path: Path):
    hand_edited = tmp_path / "m.yaml"
    hand_edited.write_text(
        "platforms:\n"
        "  - id: x\n    name: X\n    repo_url: https://x\n"
        "    hardware: {nvidia: yes, amd: no}\n"   # YAML 1.1 booleans
        '    features: {fp8: "partial"}\n'
        "    sources: [https://x/docs]\n    verified: '2026-07-29'\n",
        encoding="utf-8",
    )
    (platform,) = load_platform_matrix(hand_edited)
    assert platform.hardware["nvidia"] == "yes"
    assert platform.hardware["amd"] == "no"
