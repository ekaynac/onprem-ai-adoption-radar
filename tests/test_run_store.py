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
