from __future__ import annotations

from radar.models import Ring
from radar.models_radar.entities import (
    HardwareTier,
    ModelEntry,
    Openness,
    QuantVariant,
)
from radar.models_radar.scoring import model_ring, score_model


def _entry(**kw):
    base = dict(
        id="m", name="M", family="F",
        params_total=8_000_000_000, openness=Openness.OPEN_PERMISSIVE,
        hardware_tier=HardwareTier.LAPTOP,
        quants=[QuantVariant(format="Q4_K_M", bits_per_weight=4.5,
                             est_memory_gb_4k=8.0, source="hf:x")],
    )
    base.update(kw)
    return ModelEntry(**base)


def test_strong_open_laptop_model_scores_high_and_adopts():
    s = score_model(_entry(hf_downloads=5_000_000))
    assert 1 <= s.openness <= 5 and 1 <= s.local_runnability <= 5
    assert s.openness == 5            # permissive → top
    assert s.local_runnability == 5   # laptop tier → top
    assert model_ring(s) in (Ring.ADOPT, Ring.PILOT)


def test_gated_datacenter_model_scores_low():
    s = score_model(_entry(
        openness=Openness.GATED, hardware_tier=HardwareTier.DATACENTER,
        params_total=400_000_000_000, hf_downloads=100,
        quants=[QuantVariant(format="Q4_K_M", bits_per_weight=4.5,
                             est_memory_gb_4k=240.0, source="hf:x")],
    ))
    assert s.openness <= 2 and s.local_runnability <= 2
    assert model_ring(s) in (Ring.WATCH, Ring.AVOID)


def test_score_is_deterministic():
    e = _entry(hf_downloads=1234)
    assert score_model(e) == score_model(e)


def test_entry_carries_score_and_ring_fields():
    e = _entry().model_copy(update={"ring": Ring.ADOPT, "score": 4.2})
    assert e.ring == Ring.ADOPT and e.score == 4.2
    assert _entry().ring is None  # default


def test_new_tier_members_score_without_keyerror():
    from radar.models_radar.scoring import MODEL_PROFILES

    for name, tier_scores in MODEL_PROFILES.items():
        for tier in HardwareTier:
            assert tier in tier_scores, (name, tier)  # bare [] lookup in score_model


def _dc_entry():
    from radar.models_radar.entities import ModelEntry, Openness, QuantVariant

    return ModelEntry.model_validate({
        "id": "big-moe", "name": "Big-MoE-1T", "family": "Big",
        "params_total": 1_000_000_000_000, "openness": Openness.OPEN_PERMISSIVE,
        "hardware_tier": "single_node",
        "quants": [QuantVariant(format="FP8", bits_per_weight=8.0,
                                est_memory_gb_4k=600.0)],
    })


def test_datacenter_first_lifts_single_node_model_to_adopt():
    from radar.models_radar.scoring import model_ring, score_model

    default = score_model(_dc_entry())
    dc = score_model(_dc_entry(), profile="datacenter-first")
    assert default.local_runnability == 1
    assert dc.local_runnability == 5
    assert model_ring(dc).value == "adopt"
    assert model_ring(default).value != "adopt"


def test_unknown_profile_raises_with_names():
    import pytest

    from radar.models_radar.scoring import ModelProfileError, score_model

    with pytest.raises(ModelProfileError, match="datacenter-first"):
        score_model(_dc_entry(), profile="nope")


def test_rescore_entries_is_a_view():
    from radar.models_radar.pipeline import score_entries
    from radar.models_radar.scoring import rescore_entries

    scored = score_entries([_dc_entry()])
    rescored = rescore_entries(scored, "datacenter-first")
    assert scored[0].ring != rescored[0].ring
    assert scored[0].ring is not None  # input untouched (frozen copies)
