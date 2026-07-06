"""Digest newsletter feeds (Atom + RSS)."""

from __future__ import annotations

from datetime import UTC, datetime
from xml.dom.minidom import parseString

from radar.reports.digest_feeds import render_digest_atom, render_digest_rss
from radar.storage.digest_log import DigestLogEntry


def _entries():
    return [
        DigestLogEntry(label="2026-W27", generated_at=datetime(2026, 6, 29, tzinfo=UTC),
                       url="digests/digest_2026-W27.html", summary="Week 27"),
        DigestLogEntry(label="2026-W28", generated_at=datetime(2026, 7, 6, tzinfo=UTC),
                       url="digests/digest_2026-W28.html", summary="Week 28 & <fun>"),
    ]


def test_atom_newest_first_and_escapes():
    xml = render_digest_atom(_entries(), "Radar digest", "https://x/digest.xml")
    parseString(xml)  # well-formed
    assert xml.index("2026-W28") < xml.index("2026-W27")   # newest first
    assert "&lt;fun&gt;" in xml                              # escaped


def test_rss_wellformed_rfc822():
    xml = render_digest_rss(_entries(), "Radar digest", "https://x/digest-rss.xml")
    parseString(xml)
    assert "<rss" in xml and "pubDate" in xml
