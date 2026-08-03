from __future__ import annotations

import io
import tarfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

from radar.cli import app
from radar.intelligence.state_bundle import (
    StateBundleError,
    pack_intelligence_state,
    restore_intelligence_state,
)


def _seed_state(root: Path) -> None:
    (root / "data" / "intelligence" / "snapshots" / "daily").mkdir(
        parents=True
    )
    (root / "data" / "intelligence.db").write_bytes(b"sqlite-state")
    (root / "data" / "intelligence" / "events.jsonl").write_text(
        '{"event":"created"}\n', encoding="utf-8"
    )
    (root / "data" / "intelligence" / "snapshots" / "daily" / "one.json").write_text(
        '{"count":1}\n', encoding="utf-8"
    )
    (root / "data" / "private-token.txt").write_text("do-not-pack", encoding="utf-8")


def test_state_bundle_round_trips_only_canonical_state(tmp_path: Path) -> None:
    source = tmp_path / "source"
    restored = tmp_path / "restored"
    archive = tmp_path / "build" / "intelligence-state.tar.gz"
    _seed_state(source)

    packed = pack_intelligence_state(source, archive)
    restored_manifest = restore_intelligence_state(restored, archive)

    assert packed.schema_version == "1.0"
    assert packed.files == restored_manifest.files
    assert packed.files == [
        "data/intelligence.db",
        "data/intelligence/events.jsonl",
        "data/intelligence/snapshots/daily/one.json",
    ]
    assert (restored / "data" / "intelligence.db").read_bytes() == b"sqlite-state"
    assert (
        restored / "data" / "intelligence" / "events.jsonl"
    ).read_text(encoding="utf-8") == '{"event":"created"}\n'
    assert (
        restored
        / "data"
        / "intelligence"
        / "snapshots"
        / "daily"
        / "one.json"
    ).read_text(encoding="utf-8") == '{"count":1}\n'
    assert not (restored / "data" / "private-token.txt").exists()


@pytest.mark.parametrize(
    "member_name",
    ["../outside.txt", "/absolute.txt", "data/intelligence/../../outside.txt"],
)
def test_restore_rejects_unsafe_member_paths_without_changing_state(
    tmp_path: Path, member_name: str
) -> None:
    root = tmp_path / "root"
    archive = tmp_path / "unsafe.tar.gz"
    (root / "data").mkdir(parents=True)
    database = root / "data" / "intelligence.db"
    database.write_bytes(b"existing")
    with tarfile.open(archive, "w:gz") as bundle:
        info = tarfile.TarInfo(member_name)
        payload = b"unsafe"
        info.size = len(payload)
        bundle.addfile(info, io.BytesIO(payload))

    with pytest.raises(StateBundleError, match=r"unsafe|allowed"):
        restore_intelligence_state(root, archive)

    assert database.read_bytes() == b"existing"
    assert not (tmp_path / "outside.txt").exists()


@pytest.mark.parametrize("link_type", [tarfile.SYMTYPE, tarfile.LNKTYPE])
def test_restore_rejects_links_without_changing_state(
    tmp_path: Path, link_type: bytes
) -> None:
    root = tmp_path / "root"
    archive = tmp_path / "link.tar.gz"
    (root / "data").mkdir(parents=True)
    database = root / "data" / "intelligence.db"
    database.write_bytes(b"existing")
    with tarfile.open(archive, "w:gz") as bundle:
        info = tarfile.TarInfo("data/intelligence.db")
        info.type = link_type
        info.linkname = "../../outside.txt"
        bundle.addfile(info)

    with pytest.raises(StateBundleError, match="link"):
        restore_intelligence_state(root, archive)

    assert database.read_bytes() == b"existing"


def test_state_bundle_cli_packs_and_restores(tmp_path: Path) -> None:
    source = tmp_path / "source"
    restored = tmp_path / "restored"
    archive = tmp_path / "intelligence-state.tar.gz"
    _seed_state(source)
    runner = CliRunner()

    packed = runner.invoke(
        app,
        ["intelligence-state-pack", "--root", str(source), "--out", str(archive)],
    )
    restored_result = runner.invoke(
        app,
        [
            "intelligence-state-restore",
            "--root",
            str(restored),
            "--archive",
            str(archive),
        ],
    )

    assert packed.exit_code == 0, packed.output
    assert '"schema_version": "1.0"' in packed.stdout
    assert restored_result.exit_code == 0, restored_result.output
    assert (restored / "data" / "intelligence.db").read_bytes() == b"sqlite-state"
