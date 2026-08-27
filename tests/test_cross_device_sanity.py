"""Cross-device sanity sweep for the advisor.

The three-way check (radar output vs independent research vs operator review)
that originally exposed the DGX Spark gap is codified here as a non-flaky
invariant sweep: for every target device x task, the advisor must run without
error and produce physically plausible decode estimates. Discovery-specific
assertions are guarded so the suite also passes in CI where the intelligence
database is not present.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from radar.models_radar.advisor import TASKS, _evidence_last_observed, build_answers
from radar.web.public_context import load_public_model_profiles


ROOT = Path(".")

TARGET_DEVICES = ["dgx-station-gb300", "mac-128gb", "b200-192gb"]


@pytest.fixture(scope="module")
def profiles() -> dict:
    return load_public_model_profiles(ROOT)


def test_advisor_runs_cleanly_on_target_devices(profiles: dict) -> None:
    for device in TARGET_DEVICES:
        for task in TASKS:
            answer = build_answers(profiles, device, task)
            assert answer["device"], device
            for candidate in answer["candidates"]:
                est = candidate.get("estimated_tok_s")
                # Decode estimate must be present and physically plausible.
                assert est is None or (0.05 <= est <= 2000), (
                    f"{device}/{task}: {candidate['name']} est_tps={est}"
                )
                # Discovered models must carry their provenance trail.
                if candidate.get("discovered"):
                    assert candidate.get("discovery_reason"), candidate["name"]


def test_gb300_coding_surfaces_gptoss_fast(profiles: dict) -> None:
    # Memory-bandwidth-bound box with room for a 120B MoE: the discovered
    # gpt-oss-120b must appear with a fast decode estimate (proves the
    # discovery bridge + throughput dimension both fire end to end).
    if "hf-gpt-oss-120b" not in profiles:
        pytest.skip("intelligence database not present in this environment")
    answer = build_answers(profiles, "dgx-station-gb300", "coding")
    by_id = {c["model_id"]: c for c in answer["candidates"]}
    gpt_oss = by_id.get("hf-gpt-oss-120b")
    assert gpt_oss is not None, "gpt-oss-120b must rank on DGX Station GB300"
    assert gpt_oss["estimated_tok_s"] is not None
    assert gpt_oss["estimated_tok_s"] >= 50, "gpt-oss-120b decode must be fast"
    assert gpt_oss.get("discovery_reason"), "gpt-oss-120b must carry provenance"


def test_perf_weight_ranks_faster_model_higher_when_otherwise_equal() -> None:
    # The throughput dimension must be a real, directionally-correct factor:
    # two otherwise-identical profiles (same ring, maturity, evidence) rank
    # faster-decode first. This is the regression guard for the Spark-class bug.
    evidence = [
        {
            "benchmark": "aider-polyglot", "label": "Aider", "consensus": 40.0,
            "spread": None, "self_reported_gap": None, "flagged": False,
            "percentile": 50, "sample_size": 2, "scores": [],
        }
    ]
    device = {
        "kind": "apple", "total_memory_gb": 512, "memory_bandwidth_gbs": 800,
    }

    def make(pid: str, active: int) -> dict:
        return {
            "id": pid, "name": pid, "family": "F", "modality": "text",
            "ring": "pilot", "score": 3.2, "license": "apache-2.0",
            "params_total": active, "params_active": active,
            "context_length": 32768,
            "quants": [{"format": "FP16", "bits_per_weight": 16.0, "source": "manual"}],
            "benchmark_aggregates": evidence,
            "discovered": True, "lifecycle": "verified",
        }

    # Fast MoE (small active) vs slow dense (large active), identical otherwise.
    profiles = {"fast": make("fast", 2_000_000_000), "slow": make("slow", 30_000_000_000)}
    answer = build_answers(profiles, device, "coding")
    ranked_ids = [c["model_id"] for c in answer["candidates"]]
    assert ranked_ids.index("fast") < ranked_ids.index("slow"), ranked_ids
    fast_tps = next(c["estimated_tok_s"] for c in answer["candidates"] if c["model_id"] == "fast")
    slow_tps = next(c["estimated_tok_s"] for c in answer["candidates"] if c["model_id"] == "slow")
    assert fast_tps > slow_tps * 3, (fast_tps, slow_tps)


def test_staleness_flag_is_computable() -> None:
    stale = {
        "benchmark_aggregates": [
            {
                "benchmark": "mmlu-pro",
                "scores": [
                    {
                        "source_id": "aider-polyglot",
                        "score": 60.0,
                        "observed_at": (
                            datetime.now(UTC) - timedelta(days=400)
                        ).isoformat(),
                        "self_reported": False,
                    }
                ],
            }
        ]
    }
    recent = {
        "benchmark_aggregates": [
            {
                "benchmark": "mmlu-pro",
                "scores": [
                    {
                        "source_id": "aider-polyglot",
                        "score": 60.0,
                        "observed_at": datetime.now(UTC).isoformat(),
                        "self_reported": False,
                    }
                ],
            }
        ]
    }
    assert _evidence_last_observed(stale) is not None
    assert _evidence_last_observed(recent) is not None
    # Seed-card-only profile (no observed_at) is not decayed.
    assert _evidence_last_observed({"benchmark_aggregates": []}) is None
