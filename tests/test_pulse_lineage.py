"""Deterministic model-origin triage from Hugging Face ``base_model`` tags.

Fixtures are real tag sets observed on the Hub on 2026-09-30.
"""

from __future__ import annotations

import pytest

from radar.pulse.lineage import ModelOrigin, classify_model_origin


LABS = frozenset({"Qwen", "deepseek-ai"})


@pytest.mark.parametrize(
    ("repo_id", "tags", "expected", "parent"),
    [
        # First-party release with no base model: the headline item.
        ("Qwen/Qwen-Image-2.1", ["diffusers", "text-to-image"], ModelOrigin.ORIGINAL, None),
        # First-party fine-tune of its own base: still a new release from the lab.
        (
            "Qwen/Qwen-Drive-1.0-4B",
            ["base_model:Qwen/Qwen3.5-4B", "base_model:finetune:Qwen/Qwen3.5-4B"],
            ModelOrigin.ORIGINAL,
            None,
        ),
        # First-party quant: a variant grouped under its parent, not a headline.
        (
            "Qwen/Qwen3.8-Flash-Next-FP8",
            [
                "base_model:Qwen/Qwen3.8-Flash-Next",
                "base_model:quantized:Qwen/Qwen3.8-Flash-Next",
                "fp8",
            ],
            ModelOrigin.VARIANT,
            "Qwen/Qwen3.8-Flash-Next",
        ),
        # Third-party quant of a lab release.
        (
            "unsloth/DeepSeek-V4-Flash-Vision-Exp-GGUF",
            [
                "base_model:deepseek-ai/DeepSeek-V4-Flash-Vision-Exp",
                "base_model:quantized:deepseek-ai/DeepSeek-V4-Flash-Vision-Exp",
            ],
            ModelOrigin.DERIVATIVE,
            "deepseek-ai/DeepSeek-V4-Flash-Vision-Exp",
        ),
        # Third-party re-upload tagged as "finetune" (unsloth FP8): derivative.
        (
            "unsloth/Qwen-Image-2.1-FP8",
            ["base_model:Qwen/Qwen-Image-2.1", "base_model:finetune:Qwen/Qwen-Image-2.1"],
            ModelOrigin.DERIVATIVE,
            "Qwen/Qwen-Image-2.1",
        ),
    ],
)
def test_classify_from_base_model_tags(repo_id, tags, expected, parent) -> None:
    result = classify_model_origin(repo_id, tags, LABS)

    assert result.origin is expected
    assert result.parent == parent


@pytest.mark.parametrize(
    "repo_id",
    [
        "someone/Kimi-K3-MXFP-GGUF",
        "someone/Qwen3.8-27B-AWQ",
        "someone/GLM-5.3-Flash-EXL3-Spark",
        "someone/Abliterated-MiMo-V2.6-Distill-Qwen-9B",
        "someone/Qwen3.8-27B-Heretic-GSQ-RCO-GGUF",
        "someone/Llama-4-8B-mlx-4bit",
    ],
)
def test_untagged_repos_with_derivative_names_are_derivatives(repo_id: str) -> None:
    # Many uploads omit base_model tags; the name is the fallback signal.
    assert classify_model_origin(repo_id, [], LABS).origin is ModelOrigin.DERIVATIVE


def test_untagged_repo_without_derivative_markers_is_unknown() -> None:
    # Not provably original: left for the classifier (Jev) to decide.
    result = classify_model_origin("newlab/Aurora-7B", [], LABS)

    assert result.origin is ModelOrigin.UNKNOWN
    assert result.parent is None


def test_base_model_tag_that_is_a_merge_or_adapter_is_derivative() -> None:
    tags = ["base_model:Qwen/Qwen3.8-27B", "base_model:adapter:Qwen/Qwen3.8-27B"]

    assert classify_model_origin("Qwen/Qwen3.8-27B-lora", tags, LABS).origin is ModelOrigin.VARIANT
    assert classify_model_origin("fan/Qwen3.8-27B-lora", tags, LABS).origin is ModelOrigin.DERIVATIVE


def test_untagged_lab_repo_with_format_marker_is_a_variant() -> None:
    # nvidia-style repacks inside a lab's own org often ship without tags.
    result = classify_model_origin("Qwen/Qwen3.8-27B-NVFP4", [], LABS)

    assert result.origin is ModelOrigin.VARIANT


def test_lab_org_matching_is_case_insensitive() -> None:
    assert classify_model_origin("qwen/Qwen-Image-2.1", [], LABS).origin is ModelOrigin.ORIGINAL


def test_lab_finetune_of_another_labs_base_is_a_new_release() -> None:
    # apple/LensVLM-9B (2026-09-21) is Apple's own model built on Qwen3.5-9B.
    tags = ["base_model:Qwen/Qwen3.5-9B", "base_model:finetune:Qwen/Qwen3.5-9B"]

    result = classify_model_origin("apple/LensVLM-9B", tags, LABS | {"apple"})

    assert result.origin is ModelOrigin.ORIGINAL
    assert result.parent == "Qwen/Qwen3.5-9B"


def test_lab_quant_of_another_labs_model_stays_derivative() -> None:
    # nvidia/DeepSeek-V4.1-Flash-NVFP4: a repack, not an NVIDIA model.
    tags = [
        "base_model:deepseek-ai/DeepSeek-V4.1-Flash",
        "base_model:quantized:deepseek-ai/DeepSeek-V4.1-Flash",
    ]

    result = classify_model_origin("nvidia/DeepSeek-V4.1-Flash-NVFP4", tags, LABS | {"nvidia"})

    assert result.origin is ModelOrigin.DERIVATIVE
