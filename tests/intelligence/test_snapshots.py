from __future__ import annotations

from pathlib import Path

import pytest

from radar.intelligence.snapshots import SnapshotConflict, SnapshotStore


def test_snapshot_store_does_not_duplicate_same_content(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path)

    one = store.write("hf", "sha256:abc", b"payload")
    two = store.write("hf", "sha256:abc", b"payload")

    assert one == two
    assert one == tmp_path / "hf" / "ab" / "abc.bin"
    assert len([path for path in tmp_path.rglob("*") if path.is_file()]) == 1


def test_snapshot_store_rejects_changed_body_for_existing_address(
    tmp_path: Path,
) -> None:
    store = SnapshotStore(tmp_path)
    store.write("hf", "sha256:abc", b"payload")

    with pytest.raises(SnapshotConflict, match="different content"):
        store.write("hf", "sha256:abc", b"changed")


def test_snapshot_store_rejects_unsafe_source_id(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path)

    with pytest.raises(ValueError, match="source_id"):
        store.write("../escape", "sha256:abc", b"payload")
