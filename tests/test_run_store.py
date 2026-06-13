import json
from pathlib import Path

import pytest

from radar.storage.run_store import RunStore


def test_create_run_writes_meta(tmp_path: Path):
    store = RunStore(tmp_path)

    run_id = store.create_run("run-test")

    assert run_id == "run-test"
    meta = json.loads((tmp_path / "run-test" / "meta.json").read_text())
    assert meta["run_id"] == "run-test"
    assert "created_at" in meta


def test_save_and_load_stage(tmp_path: Path):
    store = RunStore(tmp_path)
    store.create_run("run-test")

    store.save_stage("run-test", "raw_signals", [{"id": "s1"}])

    assert store.load_stage("run-test", "raw_signals") == [{"id": "s1"}]


def test_rejects_invalid_run_id(tmp_path: Path):
    store = RunStore(tmp_path)

    with pytest.raises(ValueError):
        store.create_run("../escape")


def test_list_runs_chronological(tmp_path: Path):
    store = RunStore(tmp_path)
    store.create_run("run-3")
    store.create_run("run-1")
    store.create_run("run-2")
    # created_at is written in order; override to make order explicit.
    store.update_meta("run-3", {"created_at": "2026-06-03T00:00:00+00:00"})
    store.update_meta("run-1", {"created_at": "2026-06-01T00:00:00+00:00"})
    store.update_meta("run-2", {"created_at": "2026-06-02T00:00:00+00:00"})

    assert store.list_runs() == ["run-1", "run-2", "run-3"]


def test_list_runs_excludes_replays_by_default(tmp_path: Path):
    store = RunStore(tmp_path)
    store.create_run("run-scan")
    store.create_run("run-replay")
    store.update_meta("run-replay", {"replay_of": "run-scan"})

    assert store.list_runs() == ["run-scan"]
    assert set(store.list_runs(include_replays=True)) == {"run-scan", "run-replay"}


def test_list_runs_empty_when_no_runs(tmp_path: Path):
    assert RunStore(tmp_path).list_runs() == []
