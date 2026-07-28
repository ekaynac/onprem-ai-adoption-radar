# tests/test_models_radar_seed.py
from __future__ import annotations

from pathlib import Path

import pytest

from radar.models_radar.seed import ModelSeedError, load_model_seed


_REPO_ROOT = Path(__file__).resolve().parents[1]


def test_loads_bundled_seed_with_known_families():
    seeds = load_model_seed(_REPO_ROOT / "config" / "model-seed.yaml")
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


def test_seed_catalog_is_comprehensive_and_valid():
    seeds = load_model_seed(_REPO_ROOT / "config" / "model-seed.yaml")
    assert len(seeds) >= 26
    ids = [s.id for s in seeds]
    assert len(ids) == len(set(ids)), "seed ids must be unique"
    # MoE seeds carry active params
    moe = {s.id: s for s in seeds if s.id in ("mixtral-8x7b", "deepseek-r1")}
    assert all(s.params_active and s.params_active < s.params_total for s in moe.values())


def test_seed_ornith_params_corrected():
    seeds = load_model_seed(_REPO_ROOT / "config" / "model-seed.yaml")
    ornith = next(s for s in seeds if s.id == "hf-ornith-1-0-35b")
    assert ornith.params_total == 35_000_000_000


def test_datacenter_moe_seeds_carry_active_params_or_documented_absence():
    seeds = {s.id: s for s in load_model_seed(_REPO_ROOT / "config" / "model-seed.yaml")}
    # The two flagship DeepSeek-V4 seeds drove this program — they must carry
    # curated MoE data (or the YAML documents why not, which fails this test
    # deliberately so a human revisits it when the numbers get published).
    #
    # Step-1 finding (2026-07-28): DeepSeek-V4-Flash/Pro's own model card
    # (https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash, "Hybrid Attention
    # Architecture" section) states the V4 series uses a *new* mechanism —
    # "Compressed Sparse Attention (CSA) + Heavily Compressed Attention (HCA)"
    # — not the classic MLA used by V3/R1. Their config.json also lacks the
    # `kv_lora_rank` key that marks MLA in this codebase's own auto-ingest
    # heuristic (radar.models_radar.hf_config._attention_kind). So the
    # brief's illustrative "mla" assertion is replaced with "hybrid" here —
    # verified against the primary source, not invented.
    for seed_id in ("hf-deepseek-v4-flash", "hf-deepseek-v4-pro"):
        seed = seeds[seed_id]
        assert seed.params_active is not None, f"{seed_id} lacks params_active"
        assert seed.architecture is not None, f"{seed_id} lacks architecture"
        assert seed.architecture.attention_kind.value == "hybrid"
        assert seed.spec_verified is True
