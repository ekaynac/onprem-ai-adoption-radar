"""Safe, portable bundles for canonical intelligence workflow state."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tarfile
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import BinaryIO


SCHEMA_VERSION = "1.0"
MANIFEST_NAME = "manifest.json"
_SINGLE_FILE_PATHS = {
    PurePosixPath("data/intelligence.db"),
    PurePosixPath("data/intelligence/events.jsonl"),
}
_SNAPSHOT_PREFIX = PurePosixPath("data/intelligence/snapshots")


class StateBundleError(ValueError):
    """Raised when an intelligence state archive is invalid or unsafe."""


@dataclass(frozen=True)
class StateBundleManifest:
    """Metadata and integrity checks for a state bundle."""

    schema_version: str
    created_at: str
    files: list[str]
    sha256: dict[str, str]


def _is_allowed_state_path(path: PurePosixPath) -> bool:
    return path in _SINGLE_FILE_PATHS or (
        len(path.parts) > len(_SNAPSHOT_PREFIX.parts)
        and path.parts[: len(_SNAPSHOT_PREFIX.parts)] == _SNAPSHOT_PREFIX.parts
    )


def _validate_member_path(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise StateBundleError(f"unsafe archive path: {name}")
    if path == PurePosixPath(MANIFEST_NAME) or _is_allowed_state_path(path):
        return path
    raise StateBundleError(f"archive path is not allowed: {name}")


def _sha256_stream(stream: BinaryIO) -> str:
    digest = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest()


def _sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        return _sha256_stream(stream)


def _state_files(root: Path) -> list[tuple[PurePosixPath, Path]]:
    candidates: list[tuple[PurePosixPath, Path]] = []
    for relative in sorted(_SINGLE_FILE_PATHS, key=str):
        local = root.joinpath(*relative.parts)
        if local.is_file():
            candidates.append((relative, local))
    snapshots = root.joinpath(*_SNAPSHOT_PREFIX.parts)
    if snapshots.is_dir():
        for local in sorted(path for path in snapshots.rglob("*") if path.is_file()):
            relative = PurePosixPath(local.relative_to(root).as_posix())
            candidates.append((relative, local))
    return sorted(candidates, key=lambda item: str(item[0]))


def pack_intelligence_state(root: Path, destination: Path) -> StateBundleManifest:
    """Pack allowlisted canonical state into a gzip-compressed tar archive."""
    root = root.resolve()
    files = _state_files(root)
    checksums = {str(relative): _sha256_file(local) for relative, local in files}
    manifest = StateBundleManifest(
        schema_version=SCHEMA_VERSION,
        created_at=datetime.now(UTC).isoformat(),
        files=list(checksums),
        sha256=checksums,
    )
    manifest_payload = json.dumps(
        {
            "schema_version": manifest.schema_version,
            "created_at": manifest.created_at,
            "files": manifest.files,
            "sha256": manifest.sha256,
        },
        indent=2,
        sort_keys=True,
    ).encode("utf-8")

    destination = destination.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    try:
        with tarfile.open(temporary, "w:gz") as bundle:
            manifest_info = tarfile.TarInfo(MANIFEST_NAME)
            manifest_info.size = len(manifest_payload)
            manifest_info.mtime = 0
            manifest_info.mode = 0o644
            import io

            bundle.addfile(manifest_info, io.BytesIO(manifest_payload))
            for relative, local in files:
                info = bundle.gettarinfo(str(local), arcname=str(relative))
                info.mtime = 0
                info.mode = 0o644
                info.uid = 0
                info.gid = 0
                info.uname = ""
                info.gname = ""
                with local.open("rb") as stream:
                    bundle.addfile(info, stream)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return manifest


def _parse_manifest(payload: bytes) -> StateBundleManifest:
    try:
        raw = json.loads(payload)
        manifest = StateBundleManifest(
            schema_version=str(raw["schema_version"]),
            created_at=str(raw["created_at"]),
            files=[str(item) for item in raw["files"]],
            sha256={str(key): str(value) for key, value in raw["sha256"].items()},
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise StateBundleError("invalid state bundle manifest") from exc
    if manifest.schema_version != SCHEMA_VERSION:
        raise StateBundleError(
            f"unsupported state bundle schema: {manifest.schema_version}"
        )
    if manifest.files != sorted(set(manifest.files)):
        raise StateBundleError("manifest file list must be sorted and unique")
    if set(manifest.files) != set(manifest.sha256):
        raise StateBundleError("manifest checksums do not match file list")
    for name in manifest.files:
        _validate_member_path(name)
    return manifest


def _path_exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def _swap_state_targets(root: Path, staged_root: Path) -> None:
    targets = [
        PurePosixPath("data/intelligence.db"),
        PurePosixPath("data/intelligence/events.jsonl"),
        _SNAPSHOT_PREFIX,
    ]
    backup_root = staged_root / ".backup"
    backed_up: list[PurePosixPath] = []
    installed: list[PurePosixPath] = []

    try:
        for relative in targets:
            target = root.joinpath(*relative.parts)
            if not _path_exists(target):
                continue
            backup = backup_root.joinpath(*relative.parts)
            backup.parent.mkdir(parents=True, exist_ok=True)
            os.replace(target, backup)
            backed_up.append(relative)
    except Exception:
        for relative in reversed(backed_up):
            backup = backup_root.joinpath(*relative.parts)
            target = root.joinpath(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(backup, target)
        raise

    try:
        for relative in targets:
            staged = staged_root.joinpath(*relative.parts)
            if not _path_exists(staged):
                continue
            target = root.joinpath(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staged, target)
            installed.append(relative)
    except Exception:
        for relative in reversed(installed):
            _remove_path(root.joinpath(*relative.parts))
        for relative in reversed(backed_up):
            backup = backup_root.joinpath(*relative.parts)
            target = root.joinpath(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(backup, target)
        raise


def restore_intelligence_state(root: Path, archive: Path) -> StateBundleManifest:
    """Validate and restore a canonical-state bundle without unsafe extraction."""
    root = root.resolve()
    archive = archive.resolve()
    root.parent.mkdir(parents=True, exist_ok=True)

    with tarfile.open(archive, "r:gz") as bundle:
        members = bundle.getmembers()
        names: set[str] = set()
        for member in members:
            _validate_member_path(member.name)
            if member.name in names:
                raise StateBundleError(f"duplicate archive member: {member.name}")
            names.add(member.name)
            if member.issym() or member.islnk():
                raise StateBundleError(f"archive links are not allowed: {member.name}")
            if not member.isfile():
                raise StateBundleError(f"archive member must be a file: {member.name}")

        try:
            manifest_member = bundle.getmember(MANIFEST_NAME)
        except KeyError as exc:
            raise StateBundleError("state bundle manifest is missing") from exc
        manifest_stream = bundle.extractfile(manifest_member)
        if manifest_stream is None:
            raise StateBundleError("state bundle manifest is unreadable")
        manifest = _parse_manifest(manifest_stream.read())
        state_names = names - {MANIFEST_NAME}
        if state_names != set(manifest.files):
            raise StateBundleError("archive members do not match manifest")

        with tempfile.TemporaryDirectory(
            prefix=".radar-state-", dir=root.parent
        ) as temporary_directory:
            staged_root = Path(temporary_directory)
            for name in manifest.files:
                member = bundle.getmember(name)
                source = bundle.extractfile(member)
                if source is None:
                    raise StateBundleError(f"archive member is unreadable: {name}")
                target = staged_root.joinpath(*PurePosixPath(name).parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("wb") as output:
                    shutil.copyfileobj(source, output)
                if _sha256_file(target) != manifest.sha256[name]:
                    raise StateBundleError(f"checksum mismatch for archive member: {name}")

            root.mkdir(parents=True, exist_ok=True)
            _swap_state_targets(root, staged_root)

    return manifest
