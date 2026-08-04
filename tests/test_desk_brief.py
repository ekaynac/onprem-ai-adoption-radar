from __future__ import annotations

import json
from datetime import UTC, datetime

from radar.reports.brief import brief_id_for, build_brief
from radar.storage.calls_ledger import (
    CallRecord,
    append_call_records,
    fold_calls,
    load_call_records,
    track_record,
)


NOW = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)


def test_call_ledger_folds_resolutions_and_scores() -> None:
    records = [
        CallRecord(
            type="made",
            call_id="call:brief-2026-W31:ring-moves:vllm",
            recorded_at=datetime(2026, 7, 27, tzinfo=UTC),
            brief_id="brief-2026-W31",
            subject="vllm",
            verdict="act",
            rationale="Promotion into adopt",
        ),
        CallRecord(
            type="made",
            call_id="call:brief-2026-W31:new-repos:acme",
            recorded_at=datetime(2026, 7, 27, tzinfo=UTC),
            brief_id="brief-2026-W31",
            subject="acme/fast",
            verdict="ignore",
            rationale="Below velocity threshold",
        ),
        CallRecord(
            type="resolved",
            call_id="call:brief-2026-W31:ring-moves:vllm",
            recorded_at=NOW,
            outcome="confirmed",
            note="Pilot succeeded",
        ),
        # Resolution for an unknown call is skipped, not fatal.
        CallRecord(
            type="resolved",
            call_id="call:missing",
            recorded_at=NOW,
            outcome="wrong",
        ),
    ]

    states = fold_calls(records)

    assert len(states) == 2
    by_id = {state.call_id: state for state in states}
    vllm = by_id["call:brief-2026-W31:ring-moves:vllm"]
    assert vllm.status == "confirmed"
    assert vllm.note == "Pilot succeeded"
    record = track_record(states)
    assert record == {
        "total": 2,
        "open": 1,
        "confirmed": 1,
        "wrong": 0,
        "expired": 0,
        "hit_rate_pct": 100,
    }


def test_call_ledger_round_trip_skips_corrupt_lines(tmp_path) -> None:
    path = tmp_path / "calls-ledger.jsonl"
    append_call_records(
        path,
        [
            CallRecord(
                type="made",
                call_id="call:x",
                recorded_at=NOW,
                brief_id="brief-2026-W32",
                subject="x",
                verdict="evaluate",
                rationale="r",
            )
        ],
    )
    with path.open("a", encoding="utf-8") as handle:
        handle.write("{broken\n")

    assert [record.call_id for record in load_call_records(path)] == ["call:x"]


def _seed_stores(tmp_path) -> None:
    data = tmp_path / "data"
    data.mkdir(parents=True, exist_ok=True)
    (data / "model-history.jsonl").write_text(
        json.dumps(
            {
                "model_id": "qwen3-32b",
                "family": "Qwen3",
                "change_type": "promoted",
                "ring": "adopt",
                "previous_ring": "pilot",
                "run_id": "run-1",
                "observed_at": "2026-08-02T08:00:00Z",
                "reasons": ["promoted to adopt"],
            }
        )
        + "\n"
    )
    benchmark_rows = [
        {
            "model_id": "qwen3-32b",
            "benchmark": "mmlu-pro",
            "score": score,
            "source_id": "open-llm-leaderboard",
            "source_url": "https://ollb.example",
            "observed_at": observed_at,
            "self_reported": False,
        }
        for score, observed_at in (
            (60.0, "2026-07-30T08:00:00Z"),
            (65.0, "2026-08-03T08:00:00Z"),
        )
    ]
    # A small move stays out of the brief.
    benchmark_rows += [
        {
            "model_id": "phi-4",
            "benchmark": "mmlu",
            "score": score,
            "source_id": "open-llm-leaderboard",
            "source_url": "https://ollb.example",
            "observed_at": observed_at,
            "self_reported": False,
        }
        for score, observed_at in (
            (84.0, "2026-07-30T08:00:00Z"),
            (84.5, "2026-08-03T08:00:00Z"),
        )
    ]
    (data / "benchmark-observations.jsonl").write_text(
        "\n".join(json.dumps(row) for row in benchmark_rows) + "\n"
    )
    trending = [
        {
            "repo": "acme/fast-llm",
            "lane": "onprem",
            "stars": stars,
            "observed_at": observed_at,
            "repo_created_at": "2026-07-28T00:00:00Z",
            "description": "Fast local inference",
            "topics": ["llm"],
            "license": "MIT",
        }
        for stars, observed_at in (
            (100, "2026-07-30T08:00:00Z"),
            (1300, "2026-08-03T08:00:00Z"),
        )
    ] + [
        {
            "repo": "acme/slow-tool",
            "lane": "onprem",
            "stars": stars,
            "observed_at": observed_at,
            "repo_created_at": "2026-07-28T00:00:00Z",
            "description": "Slow burner",
            "topics": [],
            "license": "MIT",
        }
        for stars, observed_at in (
            (10, "2026-07-30T08:00:00Z"),
            (50, "2026-08-03T08:00:00Z"),
        )
    ]
    (data / "trending-observations.jsonl").write_text(
        "\n".join(json.dumps(row) for row in trending) + "\n"
    )


def test_brief_applies_documented_verdict_rules(tmp_path) -> None:
    _seed_stores(tmp_path)

    brief = build_brief(tmp_path, NOW)

    assert brief["id"] == brief_id_for(NOW)
    by_subject = {item["subject"]: item for item in brief["items"]}

    ring = by_subject["qwen3-32b"]
    assert ring["verdict"] == "act"
    assert "adopt" in ring["what_happened"]

    move = by_subject["qwen3-32b · mmlu-pro"]
    assert move["verdict"] == "evaluate"
    assert "+5" in move["what_happened"]
    assert move["receipts"] == ["https://ollb.example"]
    # The 0.5-point move is below threshold and absent.
    assert "phi-4 · mmlu" not in by_subject

    fast = by_subject["acme/fast-llm"]
    assert fast["verdict"] == "evaluate"
    slow = by_subject["acme/slow-tool"]
    assert slow["verdict"] == "ignore"
    assert "scoreable" in slow["rationale"]

    assert brief["verdict_counts"]["act"] == 1
    assert brief["verdict_counts"]["ignore"] == 1
    # Deterministic: same inputs, same brief (minus nothing — clock passed in).
    assert build_brief(tmp_path, NOW) == brief


def test_cli_brief_is_idempotent_and_resolve_keeps_score(tmp_path) -> None:
    from typer.testing import CliRunner

    from radar.cli import app
    from radar.storage.calls_ledger import (
        fold_calls,
        load_call_records,
        track_record,
    )

    _seed_stores(tmp_path)
    runner = CliRunner()

    first = runner.invoke(app, ["desk", "brief", "--root", str(tmp_path)])
    assert first.exit_code == 0, first.output
    ledger = tmp_path / "data" / "calls-ledger.jsonl"
    made = [r for r in load_call_records(ledger) if r.type == "made"]
    assert made

    # Second run the same week records zero new calls.
    second = runner.invoke(app, ["desk", "brief", "--root", str(tmp_path)])
    assert second.exit_code == 0
    assert "0 new call(s)" in second.output
    assert len([r for r in load_call_records(ledger) if r.type == "made"]) == len(made)

    call_id = made[0].call_id
    resolve = runner.invoke(
        app,
        ["desk", "resolve", call_id, "--outcome", "confirmed",
         "--note", "verified in a pilot", "--root", str(tmp_path)],
    )
    assert resolve.exit_code == 0, resolve.output
    # Double-resolution is refused: the ledger keeps score, not opinions.
    again = runner.invoke(
        app,
        ["desk", "resolve", call_id, "--outcome", "wrong", "--root", str(tmp_path)],
    )
    assert again.exit_code == 1

    states = fold_calls(load_call_records(ledger))
    record = track_record(states)
    assert record["confirmed"] == 1
    assert record["hit_rate_pct"] == 100
