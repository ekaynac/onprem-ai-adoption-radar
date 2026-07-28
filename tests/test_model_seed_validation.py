"""Catalog validation: absurd seeds are quarantined, shipped seeds are clean."""

from pathlib import Path

from radar.models_radar.seed import load_model_seed
from radar.models_radar.validate import seed_advisories, validate_seed


_REPO_ROOT = Path(__file__).resolve().parents[1]


def _seed(**overrides):
    from radar.models_radar.entities import ModelSeed

    base = {
        "id": "test-35b",
        "name": "Test-35B",
        "family": "Test",
        "params_total": 35_000_000_000,
    }
    return ModelSeed(**{**base, **overrides})


def test_implausible_params_vs_name_is_blocking():
    problems = validate_seed(_seed(params_total=664_944))  # the Ornith failure
    assert any("implausible" in p for p in problems)


def test_active_exceeding_total_is_blocking():
    problems = validate_seed(
        _seed(params_total=30_000_000_000, params_active=40_000_000_000)
    )
    assert any("params_active" in p for p in problems)


def test_nonpositive_values_are_blocking():
    assert validate_seed(_seed(params_total=0))
    assert validate_seed(_seed(context_length=0))


def test_valid_seed_has_no_problems():
    assert validate_seed(_seed(params_active=3_000_000_000, context_length=32768)) == []


def test_missing_hf_repo_is_advisory_not_blocking():
    seed = _seed(hf_repo=None)
    assert validate_seed(seed) == []
    assert any("hf_repo" in a for a in seed_advisories(seed))


def test_every_shipped_seed_passes_blocking_validation():
    seeds = load_model_seed(_REPO_ROOT / "config" / "model-seed.yaml")
    failures = {s.id: validate_seed(s) for s in seeds}
    failures = {k: v for k, v in failures.items() if v}
    assert failures == {}, f"shipped seeds must validate: {failures}"


# ---------------------------------------------------------------------------
# ENTRY-level (post-assembly) validation
# ---------------------------------------------------------------------------


def _entry(**overrides):
    from radar.models_radar.entities import ModelEntry

    base = {"id": "e-1", "name": "E", "family": "F"}
    return ModelEntry(**{**base, **overrides})


def test_entry_with_params_but_no_viable_memory_is_blocking():
    from radar.models_radar.validate import validate_entry

    entry = _entry(params_total=35_000_000_000, quants=[])  # nothing computable
    problems = validate_entry(entry)
    assert any("minimum viable memory" in p for p in problems)


def test_entry_with_computable_memory_passes():
    from radar.models_radar.entities import QuantVariant
    from radar.models_radar.validate import validate_entry

    quant = QuantVariant(format="FP8", bits_per_weight=8.0, est_memory_gb_4k=9.6)
    assert validate_entry(_entry(params_total=8_000_000_000, quants=[quant])) == []


def test_big_model_without_architecture_is_advisory():
    from radar.models_radar.validate import entry_advisories

    advisories = entry_advisories(_entry(params_total=671_000_000_000))
    assert any("no architecture" in a for a in advisories)
    assert entry_advisories(_entry(params_total=8_000_000_000)) == [] or all(
        "no architecture" not in a
        for a in entry_advisories(_entry(params_total=8_000_000_000))
    )


def test_missing_provenance_is_advisory():
    from radar.models_radar.validate import entry_advisories

    advisories = entry_advisories(_entry(params_total=8_000_000_000))
    assert any("no provenance" in a for a in advisories)
