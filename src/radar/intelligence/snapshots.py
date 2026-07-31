"""Content-addressed raw evidence snapshots."""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

from radar.intelligence.sources.base import SourceRecord


_SAFE_COMPONENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_CHECKSUM_RE = re.compile(r"^sha256:([a-fA-F0-9]+)$")


class SnapshotConflict(ValueError):
    """A content address already points at different bytes."""


class SnapshotStore:
    def __init__(self, root: Path):
        self.root = root

    def write(
        self,
        source_id: str,
        checksum: str,
        body: bytes,
        *,
        extension: str = "bin",
    ) -> Path:
        if _SAFE_COMPONENT_RE.fullmatch(source_id) is None:
            raise ValueError("source_id must be a safe path component")
        if _SAFE_COMPONENT_RE.fullmatch(extension) is None:
            raise ValueError("extension must be a safe path component")
        match = _CHECKSUM_RE.fullmatch(checksum)
        if match is None:
            raise ValueError("checksum must use sha256:<hex> format")
        digest = match.group(1).lower()
        if len(digest) < 2:
            raise ValueError("checksum digest must contain at least two characters")

        destination = (
            self.root / source_id / digest[:2] / f"{digest}.{extension}"
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            if destination.read_bytes() != body:
                raise SnapshotConflict(
                    f"Snapshot {destination} contains different content"
                )
            return destination

        descriptor, temporary_name = tempfile.mkstemp(
            dir=destination.parent,
            prefix=f".{digest}.",
            suffix=".tmp",
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as temporary:
                temporary.write(body)
                temporary.flush()
                os.fsync(temporary.fileno())
            temporary_path.replace(destination)
        finally:
            temporary_path.unlink(missing_ok=True)
        return destination

    def write_record(self, record: SourceRecord) -> Path:
        return self.write(
            record.source_id,
            record.checksum,
            record.body,
            extension=_extension_for(record.content_type),
        )


def _extension_for(content_type: str | None) -> str:
    normalized = (content_type or "").split(";", 1)[0].strip().casefold()
    return {
        "application/json": "json",
        "application/xml": "xml",
        "application/rss+xml": "xml",
        "application/atom+xml": "xml",
        "text/html": "html",
        "text/plain": "txt",
    }.get(normalized, "bin")
