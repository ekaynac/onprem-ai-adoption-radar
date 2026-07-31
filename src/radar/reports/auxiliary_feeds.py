"""Canonical writer for model, research, and digest public feeds."""

from __future__ import annotations

import json
from pathlib import Path

from radar.models_radar.history import ModelHistoryEvent
from radar.models_radar.reports import (
    model_events_to_feed_atom,
    model_events_to_feed_json,
)
from radar.reports.digest_feeds import render_digest_atom, render_digest_rss
from radar.research_radar.history import TechniqueHistoryEvent
from radar.research_radar.reports import (
    technique_events_to_feed_atom,
    technique_events_to_feed_json,
)
from radar.storage.digest_log import DigestLogEntry


def _public_url(base_url: str, path: str) -> str:
    base = base_url.rstrip("/")
    return f"{base}/{path}" if base else path


def write_digest_feeds(
    out_dir: Path,
    *,
    digests: list[DigestLogEntry],
    site_title: str,
    base_url: str,
) -> None:
    """Write the two stable weekly-digest subscription files."""

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "digest.xml").write_text(
        render_digest_atom(
            digests,
            site_title,
            _public_url(base_url, "digests/digest.xml"),
        ),
        encoding="utf-8",
    )
    (out_dir / "digest-rss.xml").write_text(
        render_digest_rss(
            digests,
            site_title,
            _public_url(base_url, "digests/digest-rss.xml"),
        ),
        encoding="utf-8",
    )


def write_auxiliary_feeds(
    out_dir: Path,
    *,
    model_events: list[ModelHistoryEvent] | None,
    technique_events: list[TechniqueHistoryEvent] | None,
    digests: list[DigestLogEntry] | None,
    site_title: str,
    base_url: str,
) -> None:
    """Publish every non-unified feed from one canonical code path."""

    out_dir.mkdir(parents=True, exist_ok=True)
    if model_events is not None:
        (out_dir / "changes-models.xml").write_text(
            model_events_to_feed_atom(
                model_events,
                site_title,
                _public_url(base_url, "changes-models.xml"),
            ),
            encoding="utf-8",
        )
        (out_dir / "changes-models.json").write_text(
            json.dumps(
                model_events_to_feed_json(model_events, site_title),
                indent=2,
            ),
            encoding="utf-8",
        )
    if technique_events is not None:
        (out_dir / "changes-research.xml").write_text(
            technique_events_to_feed_atom(
                technique_events,
                site_title,
                _public_url(base_url, "changes-research.xml"),
            ),
            encoding="utf-8",
        )
        (out_dir / "changes-research.json").write_text(
            json.dumps(
                technique_events_to_feed_json(technique_events, site_title),
                indent=2,
            ),
            encoding="utf-8",
        )
    if digests is not None:
        write_digest_feeds(
            out_dir / "digests",
            digests=digests,
            site_title=f"{site_title} — Weekly Digest",
            base_url=base_url,
        )
