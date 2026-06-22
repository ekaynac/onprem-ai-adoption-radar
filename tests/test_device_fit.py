from __future__ import annotations

from radar.models_radar.device_fit import evaluate_fit, fit_report
from radar.models_radar.devices import DeviceProfile
from radar.models_radar.entities import ModelEntry, Platform, QuantVariant


def _model(mid: str, params: int, quants: list[tuple[str, float]]) -> ModelEntry:
    # quants: list of (format, bits); est_memory computed weights-only here for clarity
    qs = [
        QuantVariant(format=f, bits_per_weight=b, platform=Platform.GENERIC, source="x",
                     est_memory_gb_4k=round(params * b / 8 / 1e9 * 1.2, 1))
        for f, b in quants
    ]
    return ModelEntry(id=mid, name=mid, family="F", params_total=params, quants=qs)


def test_8b_q4_fits_24gb_gpu():
    m = _model("qwen3-8b", 8_000_000_000, [("Q4_K_M", 4.5), ("Q8_0", 8.0)])
    dev = DeviceProfile(name="4090", kind="gpu", total_memory_gb=24)  # usable 20.4
    fit = evaluate_fit(m, dev)
    assert fit.verdict == "fits"
    assert fit.best_quant_format == "Q8_0"  # largest that fits (8B Q8 ~9.6GB ≤ 20.4)


def test_70b_wont_fit_16gb_gpu():
    m = _model("llama-70b", 70_000_000_000, [("Q4_K_M", 4.5), ("Q8_0", 8.0)])
    dev = DeviceProfile(name="4080", kind="gpu", total_memory_gb=16)  # usable 13.6
    fit = evaluate_fit(m, dev)
    assert fit.verdict == "wont_fit" and fit.best_quant_format is None


def test_only_smaller_quant_fits():
    # 24B: Q8 ~28.8GB (won't fit 24GB→20.4), Q4 ~16.2GB (fits)
    m = _model("mistral-24b", 24_000_000_000, [("Q4_K_M", 4.5), ("Q8_0", 8.0)])
    dev = DeviceProfile(name="4090", kind="gpu", total_memory_gb=24)
    fit = evaluate_fit(m, dev)
    assert fit.verdict == "fits" and fit.best_quant_format == "Q4_K_M"


def test_apple_fraction_is_lower():
    m = _model("q", 32_000_000_000, [("Q8_0", 8.0)])  # ~38.4GB
    # 48GB Mac → usable 34.56 (won't fit Q8); 48GB GPU → usable 40.8 (fits Q8)
    assert evaluate_fit(m, DeviceProfile(name="mac", kind="apple", total_memory_gb=48)).verdict == "wont_fit"
    assert evaluate_fit(m, DeviceProfile(name="gpu", kind="gpu", total_memory_gb=48)).verdict == "fits"


def test_multi_gpu_sums():
    m = _model("big", 120_000_000_000, [("Q4_K_M", 4.5)])  # ~81GB
    dev = DeviceProfile(name="2xa100", kind="gpu", total_memory_gb=80, gpu_count=2)  # usable 136
    assert evaluate_fit(m, dev).verdict == "fits"


def test_no_params_is_unknown():
    m = ModelEntry(id="x", name="x", family="F")  # no params, no quants
    assert evaluate_fit(m, DeviceProfile(name="g", kind="gpu", total_memory_gb=24)).verdict == "unknown"


def test_fit_report_sorts_fits_first():
    fits = _model("small", 3_000_000_000, [("Q4_K_M", 4.5)])
    nofit = _model("huge", 200_000_000_000, [("Q4_K_M", 4.5)])
    report = fit_report([nofit, fits], DeviceProfile(name="g", kind="gpu", total_memory_gb=24))
    assert report[0].model_id == "small"
