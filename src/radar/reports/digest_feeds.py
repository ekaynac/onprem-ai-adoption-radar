"""Newsletter feeds (Atom + RSS) over generated weekly digests."""

from __future__ import annotations

from email.utils import format_datetime
from xml.sax.saxutils import escape

from radar.storage.digest_log import DigestLogEntry


def _newest_first(entries: list[DigestLogEntry]) -> list[DigestLogEntry]:
    return sorted(entries, key=lambda e: e.generated_at, reverse=True)


def render_digest_atom(entries: list[DigestLogEntry], site_title: str, self_url: str) -> str:
    ordered = _newest_first(entries)
    updated = ordered[0].generated_at.isoformat() if ordered else "1970-01-01T00:00:00+00:00"
    parts = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<feed xmlns="http://www.w3.org/2005/Atom">',
        f"  <title>{escape(site_title)}</title>",
        f'  <link rel="self" href="{escape(self_url)}"/>',
        f"  <id>{escape(self_url)}</id>",
        f"  <updated>{updated}</updated>",
    ]
    for e in ordered:
        parts.extend([
            "  <entry>",
            f"    <title>{escape(e.summary)}</title>",
            f'    <link href="{escape(e.url)}"/>',
            f"    <id>urn:radar:digest:{escape(e.label)}</id>",
            f"    <updated>{e.generated_at.isoformat()}</updated>",
            f"    <summary>{escape(e.summary)}</summary>",
            "  </entry>",
        ])
    parts.append("</feed>")
    return "\n".join(parts) + "\n"


def render_digest_rss(entries: list[DigestLogEntry], site_title: str, self_url: str) -> str:
    ordered = _newest_first(entries)
    build_date = format_datetime(ordered[0].generated_at) if ordered else None
    parts = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">',
        "  <channel>",
        f"    <title>{escape(site_title)}</title>",
        f"    <link>{escape(self_url)}</link>",
        f"    <description>{escape(site_title)} — weekly digest</description>",
        f'    <atom:link href="{escape(self_url)}" rel="self" type="application/rss+xml"/>',
    ]
    if build_date:
        parts.append(f"    <lastBuildDate>{build_date}</lastBuildDate>")
    for e in ordered:
        parts.extend([
            "    <item>",
            f"      <title>{escape(e.summary)}</title>",
            f"      <link>{escape(e.url)}</link>",
            f"      <description>{escape(e.summary)}</description>",
            f'      <guid isPermaLink="false">urn:radar:digest:{escape(e.label)}</guid>',
            f"      <pubDate>{format_datetime(e.generated_at)}</pubDate>",
            "    </item>",
        ])
    parts.extend(["  </channel>", "</rss>"])
    return "\n".join(parts) + "\n"
