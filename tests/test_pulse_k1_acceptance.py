"""K1 acceptance: every major lab release lands in the model lane as ORIGINAL,
and none of their quants/repacks do.

Golden set: lab releases from 2026-08..09 taken from the radar's own candidate
log, with their real Hub tags recorded 2026-09-30
(tests/fixtures/pulse/k1_releases_2026-08_09.json).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from radar.pulse.config import load_pulse_config
from radar.pulse.sources import model_item


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)

RELEASES = {
    "Qwen/Qwen3.8-27B",
    "Qwen/Qwen3.8-Flash-Next",
    "Qwen/Qwen-Image-2.1",
    "zai-org/GLM-5.3",
    "zai-org/GLM-5.3-Flash",
    "deepseek-ai/DeepSeek-V4.1-Flash",
    "deepseek-ai/DeepSeek-V4-Flash-Vision-Exp",
    "moonshotai/Kimi-K3",
    "openbmb/MiniCPM5-2B",
    "CohereLabs/North-Micro-Vision-Instruct",
    "LiquidAI/LFM2.5-VL-3B",
    "inclusionAI/Ling-3.0-flash",
    "ibm-granite/granite-4.2-8b",
    "nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-BF16",
    "apple/LensVLM-9B",
    "XiaomiMiMo/MiMo-V2.6-Pro-RL",
}

REPACKS = {
    "Qwen/Qwen3.8-27B-FP8",
    "nvidia/Qwen3.8-27B-NVFP4",
    "openbmb/MiniCPM5-2B-GGUF",
    "nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4",
    "nvidia/Kimi-K3-NVFP4",
    "LiquidAI/LFM2.5-VL-3B-GGUF",
    "inclusionAI/Ling-3.0-flash-fp8",
    "nvidia/GLM-5.3-Flash-NVFP4",
    "unsloth/DeepSeek-V4-Flash-Vision-Exp-GGUF",
}


def _verdicts() -> dict[str, str | None]:
    config = load_pulse_config(ROOT / "config" / "pulse.yaml")
    rows = json.loads(
        (ROOT / "tests" / "fixtures" / "pulse" / "k1_releases_2026-08_09.json").read_text()
    )
    items = [model_item(row, config.lab_org_set, NOW) for row in rows]
    return {item.key: item.kind for item in items if item is not None}


def test_every_golden_release_is_original() -> None:
    verdicts = _verdicts()

    missed = {repo: verdicts.get(repo) for repo in RELEASES if verdicts.get(repo) != "original"}
    assert missed == {}


def test_no_repack_is_mistaken_for_a_release() -> None:
    verdicts = _verdicts()

    leaked = {repo: verdicts.get(repo) for repo in REPACKS if verdicts.get(repo) == "original"}
    assert leaked == {}
    assert not REPACKS - verdicts.keys()
