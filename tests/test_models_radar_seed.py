# tests/test_models_radar_seed.py
from __future__ import annotations

from pathlib import Path

import pytest

from radar.models_radar.seed import ModelSeedError, load_model_seed


def test_loads_bundled_seed_with_known_families():
    seeds = load_model_seed(Path("config/model-seed.yaml"))
    assert len(seeds) >= 6
    families = {s.family for s in seeds}
    assert {"Llama", "Qwen3"} <= families
    # MoE entry carries active params from the manual override.
    moe = next((s for s in seeds if s.params_active and s.params_total
                and s.params_active < s.params_total), None)
    assert moe is not None


def test_missing_file_raises(tmp_path: Path):
    with pytest.raises(ModelSeedError):
        load_model_seed(tmp_path / "nope.yaml")


def test_invalid_yaml_raises(tmp_path: Path):
    p = tmp_path / "bad.yaml"
    p.write_text("models: [::::]", encoding="utf-8")
    with pytest.raises(ModelSeedError):
        load_model_seed(p)
