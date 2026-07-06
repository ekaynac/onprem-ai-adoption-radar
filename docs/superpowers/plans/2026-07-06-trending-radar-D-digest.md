# Trending Radar — Plan D (Digest + Cards) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build sub-project 4 (the finale) of the trending radar: a weekly digest page assembling the week's trending + auto-adds + ring changes, Atom/RSS newsletter feeds, a fire-and-forget webhook, and Mega-branded SVG social cards rasterized to PNG in CI — the radar's shareable, digestible weekly output.

**Architecture:** A pure `reports/digest.py` windows the week's inputs (trending snapshot, autopilot-log, the three ring-change history logs) into a frozen `WeeklyDigest`. `radar digest generate` renders `digests/digest_<label>.html` + brand SVG cards + Atom/RSS feeds (built from a committed `data/digest-log.jsonl`), appends the log, and fires a webhook. A weekly `digest.yml` workflow runs it, rasterizes cards to PNG (`rsvg-convert`), commits `digests/`, and dispatches publish — separate from the daily publish so a digest failure never stales the site.

**Tech Stack:** Python 3.12, pydantic v2, typer, httpx, Jinja2 (all in-tree; **no new Python dependencies**; PNG rasterization via the `librsvg2-bin` apt package in CI, not Python). pytest + ruff + mypy.

**Spec:** `docs/superpowers/specs/2026-07-05-trending-radar-design.md` §4.

## Global Constraints

- Deterministic, offline generation: the digest reads only committed data (observation store, autopilot-log, the three history JSONLs). `now` is a parameter through the library layer; only the CLI reads the wall clock at the boundary.
- Guarded reads: trending via the guarded `load_trending_entries(root, now)` gateway (NEVER `load_observations` directly — the sub-project-3 final-review rule); the other loaders already skip corrupt lines.
- Fire-and-forget webhook: any failure is logged and swallowed — digest generation must never fail because a webhook is down (the existing `notify/webhook.py` contract).
- **Brand kit constraint (CRITICAL):** the Mega corporate brand kit must NEVER enter the repo. Cards use ONLY: the Process Blue brand color `#009FDA`, a text "MEGA" wordmark + the radar tagline, and a safe sans-serif font stack. NO embedding of the brand kit, no new binary assets. (Deliberate simplification recorded: a text wordmark, not a raster logo lockup — keeps card SVGs pure, small, and unit-testable; a logo lockup is a future refinement.)
- Cards are deterministic SVG STRINGS (zero deps, unit-testable). Two sizes: `portrait` 1080×1350 (Instagram) and `og` 1200×630 (link preview). PNG siblings are produced by a CI `rsvg-convert` step, best-effort (a rasterization hiccup must not fail the digest — the SVGs always ship).
- ruff line-length = 100; `python_version = 3.12`; every Python file starts with `from __future__ import annotations`.
- Coverage ≥ 80%; gates `uv run pytest`, `uv run ruff check .`, `uv run mypy src/radar`.
- Commit format `<type>: <description>`; `git add` specific paths only (unrelated modified `data/history.jsonl` never committed).
- Existing symbols consumed (all on main): `TrendingEntry`/`Lane`, `load_trending_entries` (guarded), `AutopilotEntry`/`load_autopilot`, `ProjectHistoryEvent`/`load_events` (`radar.storage.history_log`), `ModelHistoryEvent`/`load_model_events` (`radar.models_radar.history`), `TechniqueHistoryEvent`/`load_technique_events` (`radar.research_radar.history`), the `render_changes_atom`/`render_changes_rss` feed patterns (`radar.reports.feeds`), `NotifyConfig` + the `notify/webhook.py` fire-and-forget pattern, `load_config`.

## File Structure

```
src/radar/reports/digest.py               # NEW: iso_week_bounds, DigestChange, WeeklyDigest, build_digest (pure)
src/radar/storage/digest_log.py            # NEW: DigestLogEntry + append/load JSONL (feed source)
src/radar/reports/digest_feeds.py          # NEW: render_digest_atom / render_digest_rss (from the log)
src/radar/web/cards.py                     # NEW: SVG card strings + write_cards (pure)
src/radar/notify/webhook.py                # MODIFY: build_digest_payload + send_digest_notification
src/radar/web/templates/digest.html        # NEW: weekly digest page
src/radar/cli.py                           # MODIFY: `radar digest generate`; export copies digests/ + latest link
src/radar/web/static_site.py               # MODIFY: copy digests/ into site + latest-digest index context
src/radar/web/templates/index.html static_index.html   # MODIFY: latest-digest link
.github/workflows/digest.yml               # NEW: weekly generate + rasterize + commit + dispatch
tests/test_digest.py test_digest_log.py test_digest_feeds.py test_cards.py
tests/test_digest_cli.py test_digest_webhook.py test_digest_workflow.py   # NEW
tests/test_static_site.py test_web.py       # MODIFY: latest-digest link
README.md CHANGELOG.md                       # MODIFY
```

Out of scope: no auto-posting to social platforms (rejected); no LLM. This is the last trending sub-project.

---

### Task 1: Digest assembly (pure)

**Files:**
- Create: `src/radar/reports/digest.py`
- Test: `tests/test_digest.py`

**Interfaces:**
- Consumes: `TrendingEntry`/`Lane`, `AutopilotEntry`, `ProjectHistoryEvent`, `ModelHistoryEvent`, `TechniqueHistoryEvent`.
- Produces (pure, `now` a parameter):
  - `iso_week_bounds(now) -> tuple[datetime, datetime]` — [Monday 00:00, next Monday 00:00) of now's ISO week.
  - `week_label(now) -> str` — `f"{iso_year}-W{iso_week:02d}"`.
  - `DigestChange` (frozen: `kind: str` (tool|model|technique), `name: str`, `change_type: str`, `ring: str`, `previous_ring: str | None`, `observed_at: datetime`).
  - `WeeklyDigest` (frozen: `label`, `week_start`, `week_end`, `generated_at`, `trending_onprem: list[TrendingEntry]`, `trending_broader: list[TrendingEntry]`, `auto_added: list[AutopilotEntry]`, `changes: list[DigestChange]`; property `summary_line`).
  - `build_digest(now, trending, autopilot, tool_events, model_events, technique_events, *, top_n=5) -> WeeklyDigest` — trending split by lane + capped top_n (current snapshot, not windowed); autopilot + all three event lists windowed to the ISO week and (events) normalized to `DigestChange`, sorted newest-first.

- [ ] **Step 1: Write the failing tests**

```python
"""Weekly digest assembly (pure, deterministic)."""

from __future__ import annotations

from datetime import UTC, datetime

from radar.discovery.trending_entities import Lane, TrendingEntry
from radar.models_radar.history import ModelHistoryEvent
from radar.reports.digest import (
    DigestChange,
    build_digest,
    iso_week_bounds,
    week_label,
)
from radar.storage.autopilot_log import AutopilotEntry
from radar.storage.history_log import ProjectHistoryEvent


# 2026-07-08 is a Wednesday in ISO week 28 (Mon 2026-07-06 .. Sun 2026-07-12).
NOW = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)


def test_iso_week_bounds_and_label():
    start, end = iso_week_bounds(NOW)
    assert start == datetime(2026, 7, 6, tzinfo=UTC)
    assert end == datetime(2026, 7, 13, tzinfo=UTC)
    assert week_label(NOW) == "2026-W28"


def _entry(repo, lane, vel=10.0):
    return TrendingEntry(repo=repo, lane=lane, stars=1000, velocity_per_day=vel,
                         is_new=False, first_seen="2026-07-01", description="d", topics=["llm"])


def _auto(repo, day):
    return AutopilotEntry(repo=repo, source_id=f"github-{repo.split('/')[-1]}",
                          category="model_serving", stars=1000, avg_velocity=40.0,
                          added_at=datetime(2026, 7, day, tzinfo=UTC))


def _tool_event(project, day):
    # Ring values are adopt|pilot|watch|avoid; ChangeType new|promoted|demoted|updated.
    return ProjectHistoryEvent(
        project=project, category="model_serving", change_type="new", ring="pilot",
        previous_ring=None, run_id="r1", observed_at=datetime(2026, 7, day, tzinfo=UTC),
        reasons=["seeded"],
    )


def test_build_digest_windows_and_caps():
    trending = ([_entry(f"on/{i}", Lane.ONPREM, vel=50 - i) for i in range(7)]
                + [_entry("broad/x", Lane.BROADER)])
    autopilot = [_auto("acme/rocket", 7),          # in week 28
                 _auto("old/repo", 1)]             # week 27 → excluded
    tool_events = [_tool_event("Cline", 7),        # in week
                   _tool_event("Old", 1)]          # excluded

    digest = build_digest(NOW, trending, autopilot, tool_events, [], [], top_n=5)

    assert digest.label == "2026-W28"
    assert len(digest.trending_onprem) == 5           # capped
    assert [e.repo for e in digest.trending_broader] == ["broad/x"]
    assert [a.repo for a in digest.auto_added] == ["acme/rocket"]   # windowed
    assert [c.name for c in digest.changes] == ["Cline"]            # windowed
    assert digest.changes[0].kind == "tool"


def test_build_digest_normalizes_all_three_event_kinds():
    model_ev = ModelHistoryEvent(
        model_id="qwen3-0.6b", family="Qwen3", change_type="promoted", ring="adopt",
        previous_ring="pilot", run_id="r1", observed_at=datetime(2026, 7, 7, tzinfo=UTC),
        reasons=[],
    )
    digest = build_digest(NOW, [], [], [_tool_event("Cline", 7)], [model_ev], [], top_n=5)

    kinds = {(c.kind, c.name) for c in digest.changes}
    assert ("tool", "Cline") in kinds
    assert ("model", "qwen3-0.6b") in kinds
    assert digest.summary_line  # non-empty
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_digest.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

Create `src/radar/reports/digest.py`:

```python
"""Assemble one ISO-week digest from the committed radar data (pure, no I/O)."""

from __future__ import annotations

from datetime import datetime, timedelta

from pydantic import BaseModel, ConfigDict, Field

from radar.discovery.trending_entities import Lane, TrendingEntry
from radar.models_radar.history import ModelHistoryEvent
from radar.research_radar.history import TechniqueHistoryEvent
from radar.storage.autopilot_log import AutopilotEntry
from radar.storage.history_log import ProjectHistoryEvent


def iso_week_bounds(now: datetime) -> tuple[datetime, datetime]:
    """[Monday 00:00, next Monday 00:00) of now's ISO week (tz preserved)."""
    monday = (now - timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return monday, monday + timedelta(days=7)


def week_label(now: datetime) -> str:
    iso = now.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


class DigestChange(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: str  # tool | model | technique
    name: str
    change_type: str
    ring: str
    previous_ring: str | None
    observed_at: datetime


class WeeklyDigest(BaseModel):
    model_config = ConfigDict(frozen=True)

    label: str
    week_start: datetime
    week_end: datetime
    generated_at: datetime
    trending_onprem: list[TrendingEntry] = Field(default_factory=list)
    trending_broader: list[TrendingEntry] = Field(default_factory=list)
    auto_added: list[AutopilotEntry] = Field(default_factory=list)
    changes: list[DigestChange] = Field(default_factory=list)

    @property
    def summary_line(self) -> str:
        return (f"Week {self.label}: {len(self.auto_added)} source(s) added · "
                f"{len(self.changes)} ring change(s) · "
                f"{len(self.trending_onprem)} on-prem candidate(s)")


def _change(kind: str, name: str, ev: object) -> DigestChange:
    return DigestChange(
        kind=kind, name=name,
        change_type=ev.change_type.value, ring=ev.ring.value,
        previous_ring=ev.previous_ring.value if ev.previous_ring else None,
        observed_at=ev.observed_at,
    )


def build_digest(
    now: datetime,
    trending: list[TrendingEntry],
    autopilot: list[AutopilotEntry],
    tool_events: list[ProjectHistoryEvent],
    model_events: list[ModelHistoryEvent],
    technique_events: list[TechniqueHistoryEvent],
    *,
    top_n: int = 5,
) -> WeeklyDigest:
    start, end = iso_week_bounds(now)

    def _in_week(when: datetime) -> bool:
        return start <= when < end

    onprem = [e for e in trending if e.lane == Lane.ONPREM][:top_n]
    broader = [e for e in trending if e.lane == Lane.BROADER][:top_n]
    auto_added = [a for a in autopilot if _in_week(a.added_at)]

    changes: list[DigestChange] = []
    changes += [_change("tool", e.project, e) for e in tool_events if _in_week(e.observed_at)]
    changes += [_change("model", e.model_id, e) for e in model_events if _in_week(e.observed_at)]
    changes += [_change("technique", e.technique_id, e)
                for e in technique_events if _in_week(e.observed_at)]
    changes.sort(key=lambda c: c.observed_at, reverse=True)

    return WeeklyDigest(
        label=week_label(now), week_start=start, week_end=end, generated_at=now,
        trending_onprem=onprem, trending_broader=broader,
        auto_added=auto_added, changes=changes,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_digest.py -v`
Expected: PASS (4 tests). If mypy flags `ev: object` attribute access in `_change`, type the param as a `Union[ProjectHistoryEvent, ModelHistoryEvent, TechniqueHistoryEvent]` (all three share `.change_type/.ring/.previous_ring/.observed_at`).

- [ ] **Step 5: Lint + typecheck + commit**

```bash
uv run ruff check src/radar/reports tests/test_digest.py && uv run mypy src/radar
git add src/radar/reports/digest.py tests/test_digest.py
git commit -m "feat: weekly digest assembly (window + normalize the week's data)"
```

---

### Task 2: Digest log + newsletter feeds

**Files:**
- Create: `src/radar/storage/digest_log.py`, `src/radar/reports/digest_feeds.py`
- Test: `tests/test_digest_log.py`, `tests/test_digest_feeds.py`

**Interfaces:**
- Consumes: nothing new (pydantic, json, xml).
- Produces:
  - `DigestLogEntry` (frozen: `label: str`, `generated_at: datetime`, `url: str`, `summary: str`), `append_digest(path, entries)` / `load_digests(path)` (append-only JSONL, missing → [], corrupt lines skipped — the sibling-log pattern).
  - `render_digest_atom(entries: list[DigestLogEntry], site_title: str, self_url: str) -> str` and `render_digest_rss(...)` — one feed entry per weekly digest, newest first (mirror of `reports/feeds.py`'s Atom/RSS with `xml.sax.saxutils.escape` + RFC-822 dates for RSS via `email.utils.format_datetime`).

- [ ] **Step 1: Write the failing tests (tests/test_digest_log.py)**

```python
"""Append-only JSONL log of generated digests (feed source)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from radar.storage.digest_log import DigestLogEntry, append_digest, load_digests


def _entry(label: str) -> DigestLogEntry:
    return DigestLogEntry(label=label, generated_at=datetime(2026, 7, 8, tzinfo=UTC),
                          url=f"digests/digest_{label}.html", summary=f"Week {label}")


def test_round_trip_and_noop_empty(tmp_path: Path):
    path = tmp_path / "digest-log.jsonl"
    append_digest(path, [_entry("2026-W27")])
    append_digest(path, [_entry("2026-W28")])
    append_digest(path, [])

    rows = load_digests(path)
    assert [r.label for r in rows] == ["2026-W27", "2026-W28"]


def test_missing_and_corrupt(tmp_path: Path):
    assert load_digests(tmp_path / "nope.jsonl") == []
    path = tmp_path / "digest-log.jsonl"
    append_digest(path, [_entry("2026-W28")])
    with path.open("a", encoding="utf-8") as h:
        h.write("{broken\n")
    assert len(load_digests(path)) == 1
```

tests/test_digest_feeds.py:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_digest_log.py tests/test_digest_feeds.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write the implementations**

`digest_log.py` mirrors `trending_observations_log.py` (with the `DigestLogEntry` model inline); `digest_feeds.py` mirrors `reports/feeds.py`'s Atom + RSS renderers (newest-first by `generated_at`, `escape` all text, `<id>`/`<guid>` = `urn:radar:digest:{label}`, `<link>` = `entry.url`). Both in full below.

`digest_log.py`:

```python
"""Append-only JSONL log of generated digests — the newsletter feed source."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict


logger = logging.getLogger(__name__)


class DigestLogEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    label: str
    generated_at: datetime
    url: str
    summary: str


def append_digest(path: Path, entries: list[DigestLogEntry]) -> None:
    if not entries:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(e.model_dump(mode="json"), ensure_ascii=False) for e in entries]
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def load_digests(path: Path) -> list[DigestLogEntry]:
    if not path.exists():
        return []
    rows: list[DigestLogEntry] = []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line_no, raw in enumerate(handle, start=1):
                line = raw.strip()
                if not line:
                    continue
                try:
                    rows.append(DigestLogEntry.model_validate_json(line))
                except ValueError as exc:
                    logger.warning("Skipping corrupt digest-log line %d in %s: %s",
                                   line_no, path, exc)
    except OSError as exc:
        logger.warning("Could not read digest log %s: %s", path, exc)
    return rows
```

`digest_feeds.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_digest_log.py tests/test_digest_feeds.py -v`
Expected: PASS

- [ ] **Step 5: Lint + typecheck + commit**

```bash
uv run ruff check src/radar/storage src/radar/reports tests/test_digest_log.py tests/test_digest_feeds.py && uv run mypy src/radar
git add src/radar/storage/digest_log.py src/radar/reports/digest_feeds.py \
  tests/test_digest_log.py tests/test_digest_feeds.py
git commit -m "feat: digest log + Atom/RSS newsletter feeds"
```

---

### Task 3: Mega-branded SVG cards

**Files:**
- Create: `src/radar/web/cards.py`
- Test: `tests/test_cards.py`

**Interfaces:**
- Consumes: `WeeklyDigest`/`DigestChange` (Task 1), `TrendingEntry`.
- Produces (pure):
  - `PROCESS_BLUE = "#009FDA"`, `CARD_SIZES = {"portrait": (1080, 1350), "og": (1200, 630)}`, `WORDMARK = "MEGA"`, `TAGLINE = "on-prem AI adoption radar"`.
  - `render_card(headline: str, rows: list[str], size: str) -> str` — self-contained SVG string: brand-blue header band with the MEGA wordmark, the headline, up to ~6 rows of pre-formatted text, the tagline footer; ALL dynamic text XML-escaped; font `font-family="'Hanken Grotesk', Arial, Helvetica, sans-serif"`; well-formed XML.
  - `write_cards(digest: WeeklyDigest, out_dir: Path) -> list[Path]` — writes, for both sizes, a trending card (top-3 on-prem, `"repo  +V★/day"` rows) and, if `digest.changes` is non-empty, a movers card (top change rows); returns the written SVG paths. Filenames: `trending_{size}.svg`, `movers_{size}.svg`.

- [ ] **Step 1: Write the failing tests**

```python
"""Deterministic Mega-branded SVG social cards."""

from __future__ import annotations

from datetime import UTC, datetime
from xml.dom.minidom import parseString

from radar.discovery.trending_entities import Lane, TrendingEntry
from radar.reports.digest import DigestChange, WeeklyDigest
from radar.web.cards import CARD_SIZES, PROCESS_BLUE, render_card, write_cards


def test_render_card_wellformed_branded_and_sized():
    svg = render_card("Trending this week", ["vllm/vllm  +240★/day", "a&b/x  +9★/day"],
                      "portrait")
    parseString(svg)  # well-formed XML
    assert 'width="1080"' in svg and 'height="1350"' in svg
    assert PROCESS_BLUE in svg
    assert "MEGA" in svg
    assert "vllm/vllm" in svg
    assert "a&amp;b/x" in svg      # escaped, not raw '&'


def test_render_card_both_sizes():
    for size, (w, h) in CARD_SIZES.items():
        svg = render_card("H", ["r"], size)
        assert f'width="{w}"' in svg and f'height="{h}"' in svg


def _digest():
    entry = TrendingEntry(repo="acme/rocket", lane=Lane.ONPREM, stars=1500,
                          velocity_per_day=42.0, is_new=True, first_seen="2026-07-01",
                          description="d", topics=["llm"])
    change = DigestChange(kind="tool", name="Cline", change_type="promoted", ring="adopt",
                          previous_ring="trial", observed_at=datetime(2026, 7, 7, tzinfo=UTC))
    return WeeklyDigest(label="2026-W28",
                        week_start=datetime(2026, 7, 6, tzinfo=UTC),
                        week_end=datetime(2026, 7, 13, tzinfo=UTC),
                        generated_at=datetime(2026, 7, 8, tzinfo=UTC),
                        trending_onprem=[entry], trending_broader=[],
                        auto_added=[], changes=[change])


def test_write_cards_emits_both_sizes(tmp_path):
    paths = write_cards(_digest(), tmp_path)

    names = {p.name for p in paths}
    assert "trending_portrait.svg" in names and "trending_og.svg" in names
    assert "movers_portrait.svg" in names           # changes present → movers card
    assert (tmp_path / "trending_portrait.svg").read_text(encoding="utf-8")


def test_write_cards_skips_movers_when_no_changes(tmp_path):
    d = _digest().model_copy(update={"changes": []})
    names = {p.name for p in write_cards(d, tmp_path)}
    assert not any("movers" in n for n in names)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cards.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

Create `src/radar/web/cards.py`:

```python
"""Deterministic Mega-branded SVG social cards (pure strings, zero deps).

Cards use ONLY the Process Blue brand color, a text wordmark, and a safe
sans-serif stack — the Mega brand kit never enters the repo. Two sizes:
Instagram portrait and link-preview OG. A CI step rasterizes PNG siblings.
"""

from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

from radar.reports.digest import WeeklyDigest


PROCESS_BLUE = "#009FDA"
CARD_SIZES: dict[str, tuple[int, int]] = {"portrait": (1080, 1350), "og": (1200, 630)}
WORDMARK = "MEGA"
TAGLINE = "on-prem AI adoption radar"
_FONT = "'Hanken Grotesk', Arial, Helvetica, sans-serif"
_MAX_ROWS = 6


def render_card(headline: str, rows: list[str], size: str) -> str:
    width, height = CARD_SIZES[size]
    band = max(120, height // 8)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="{_FONT}">',
        f'<rect width="{width}" height="{height}" fill="#ffffff"/>',
        f'<rect width="{width}" height="{band}" fill="{PROCESS_BLUE}"/>',
        f'<text x="48" y="{band - 40}" font-size="56" font-weight="700" '
        f'fill="#ffffff">{WORDMARK}</text>',
        f'<text x="48" y="{band + 90}" font-size="52" font-weight="700" '
        f'fill="#111111">{escape(headline)}</text>',
    ]
    y = band + 180
    for row in rows[:_MAX_ROWS]:
        parts.append(
            f'<text x="48" y="{y}" font-size="40" fill="#222222">{escape(row)}</text>'
        )
        y += 64
    parts.append(
        f'<text x="48" y="{height - 48}" font-size="32" '
        f'fill="{PROCESS_BLUE}">{escape(TAGLINE)}</text>'
    )
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def _trending_rows(digest: WeeklyDigest) -> list[str]:
    rows = []
    for e in digest.trending_onprem[:3]:
        vel = f"{e.velocity_per_day:+.0f}★/day" if e.velocity_per_day is not None else "new"
        rows.append(f"{e.repo}  {vel}")
    return rows


def _mover_rows(digest: WeeklyDigest) -> list[str]:
    rows = []
    for c in digest.changes[:3]:
        arrow = f"{c.previous_ring} → {c.ring}" if c.previous_ring else c.ring
        rows.append(f"{c.name}  ({c.kind}) {arrow}")
    return rows


def write_cards(digest: WeeklyDigest, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    specs = [("trending", f"Trending · {digest.label}", _trending_rows(digest))]
    if digest.changes:
        specs.append(("movers", f"Ring changes · {digest.label}", _mover_rows(digest)))
    for stem, headline, rows in specs:
        for size in CARD_SIZES:
            path = out_dir / f"{stem}_{size}.svg"
            path.write_text(render_card(headline, rows, size), encoding="utf-8")
            written.append(path)
    return written
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cards.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Lint + typecheck + commit**

```bash
uv run ruff check src/radar/web/cards.py tests/test_cards.py && uv run mypy src/radar
git add src/radar/web/cards.py tests/test_cards.py
git commit -m "feat: deterministic Mega-branded SVG social cards"
```

---

### Task 4: Webhook + `radar digest generate` CLI + digest.html

**Files:**
- Modify: `src/radar/notify/webhook.py`, `src/radar/cli.py`
- Create: `src/radar/web/templates/digest.html`
- Test: `tests/test_digest_webhook.py`, `tests/test_digest_cli.py`

**Interfaces:**
- Consumes: Tasks 1–3; `load_trending_entries` (guarded), `load_autopilot`, `load_events`/`load_model_events`/`load_technique_events`, `load_config`, `NotifyConfig`.
- Produces:
  - `notify/webhook.py`: `build_digest_payload(digest: WeeklyDigest) -> dict[str, Any]` and `async send_digest_notification(config: NotifyConfig, digest: WeeklyDigest, client: Any) -> bool` — fire-and-forget (never raises; returns True only on a successful POST; no-op when `not config.enabled or not config.webhook_url`).
  - `digest.html`: renders a `WeeklyDigest` (summary line; trending onprem/broader tables like the /trending page; auto-added list; changes list).
  - `radar digest generate [--root .] [--base-url ""] [--top-n 5]`: build the digest at `now=datetime.now(UTC)`; render `digests/digest_<label>.html`; `write_cards(digest, root/"digests"/"cards")`; append a `DigestLogEntry` to `data/digest-log.jsonl`; write `digests/digest.xml` + `digests/digest-rss.xml` from the full log; fire `send_digest_notification`; print a one-line summary. Idempotent per week: if the label's digest HTML already exists, overwrite it and do NOT append a duplicate log row (dedup by label).

- [ ] **Step 1: Write the failing tests (tests/test_digest_webhook.py)**

```python
"""Fire-and-forget digest webhook."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from radar.models import NotifyConfig
from radar.notify.webhook import build_digest_payload, send_digest_notification
from radar.reports.digest import WeeklyDigest


def _digest():
    return WeeklyDigest(label="2026-W28", week_start=datetime(2026, 7, 6, tzinfo=UTC),
                        week_end=datetime(2026, 7, 13, tzinfo=UTC),
                        generated_at=datetime(2026, 7, 8, tzinfo=UTC))


def test_payload_has_label_and_summary():
    payload = build_digest_payload(_digest())
    assert payload["label"] == "2026-W28" and "summary" in payload


class _OKClient:
    def __init__(self): self.posted = None
    async def post(self, url, json):
        self.posted = (url, json)
        class _R:
            def raise_for_status(self): return None
        return _R()


class _BoomClient:
    async def post(self, url, json): raise RuntimeError("down")


@pytest.mark.asyncio
async def test_sends_when_enabled():
    client = _OKClient()
    ok = await send_digest_notification(
        NotifyConfig(enabled=True, webhook_url="https://x/hook"), _digest(), client)
    assert ok is True and client.posted[0] == "https://x/hook"


@pytest.mark.asyncio
async def test_disabled_is_noop():
    ok = await send_digest_notification(NotifyConfig(enabled=False), _digest(), _OKClient())
    assert ok is False


@pytest.mark.asyncio
async def test_failure_is_swallowed():
    ok = await send_digest_notification(
        NotifyConfig(enabled=True, webhook_url="https://x/hook"), _digest(), _BoomClient())
    assert ok is False   # never raises
```

tests/test_digest_cli.py:

```python
"""radar digest generate."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from radar.cli import app
from radar.discovery.trending_entities import Lane, TrendingObservation
from radar.storage.digest_log import load_digests
from radar.storage.trending_observations_log import append_observations


def _seed_trending(root: Path) -> None:
    (root / "data").mkdir(parents=True, exist_ok=True)
    append_observations(root / "data" / "trending-observations.jsonl", [
        TrendingObservation(repo="acme/rocket", lane=Lane.ONPREM, stars=stars,
                            observed_at=datetime(2026, 7, day, 7, 0, tzinfo=UTC),
                            repo_created_at=datetime(2026, 6, 1, tzinfo=UTC),
                            description="d", topics=["llm"], license="MIT")
        for day, stars in ((1, 100), (4, 400))
    ])


def test_digest_generate_writes_page_cards_feeds_log(tmp_path):
    _seed_trending(tmp_path)
    result = CliRunner().invoke(app, ["digest", "generate", "--root", str(tmp_path)])

    assert result.exit_code == 0
    digests = tmp_path / "digests"
    assert list(digests.glob("digest_*.html"))          # dated page
    assert (digests / "digest.xml").exists() and (digests / "digest-rss.xml").exists()
    assert list((digests / "cards").glob("trending_*.svg"))
    log = load_digests(tmp_path / "data" / "digest-log.jsonl")
    assert len(log) == 1


def test_digest_generate_is_idempotent_per_week(tmp_path):
    _seed_trending(tmp_path)
    runner = CliRunner()
    runner.invoke(app, ["digest", "generate", "--root", str(tmp_path)])
    runner.invoke(app, ["digest", "generate", "--root", str(tmp_path)])

    log = load_digests(tmp_path / "data" / "digest-log.jsonl")
    assert len(log) == 1   # same ISO week → no duplicate log row
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_digest_webhook.py tests/test_digest_cli.py -v`
Expected: FAIL — import errors / no `digest` command

- [ ] **Step 3: Implement webhook helpers**

Append to `src/radar/notify/webhook.py`:

```python
def build_digest_payload(digest: "WeeklyDigest") -> dict[str, Any]:
    """Structured generic JSON payload for a weekly digest."""
    return {
        "label": digest.label,
        "summary": digest.summary_line,
        "onprem_candidates": [e.repo for e in digest.trending_onprem],
        "auto_added": [a.repo for a in digest.auto_added],
        "ring_changes": len(digest.changes),
    }


async def send_digest_notification(
    config: NotifyConfig, digest: "WeeklyDigest", client: Any
) -> bool:
    """POST the digest summary if enabled. Never raises (fire-and-forget)."""
    if not config.enabled or not config.webhook_url:
        return False
    body: dict[str, Any] = (
        {"text": digest.summary_line} if config.format == "slack"
        else build_digest_payload(digest)
    )
    try:
        response = await client.post(config.webhook_url, json=body)
        response.raise_for_status()
        return True
    except Exception as exc:
        logger.warning("Digest webhook failed: %s", exc)
        return False
```

Add `from radar.reports.digest import WeeklyDigest` under a `TYPE_CHECKING` guard (avoid a runtime import cycle: reports → nothing in notify, so a direct import is also fine — prefer the direct import at module top if no cycle arises; the implementer verifies with `uv run mypy`).

- [ ] **Step 4: Implement digest.html + the CLI command**

Create `src/radar/web/templates/digest.html` — a standalone page (same `_base_styles.html`/`_hero.html`/`_footer.html` includes as `trending.html`) with: `page_title = "Weekly Digest — " ~ digest.label`, the `digest.summary_line`, an on-prem trending table + a broader table (repo GitHub link, stars, velocity), an "Auto-added this week" list (`auto_added`: repo + category), and a "Ring changes this week" list (`changes`: kind, name, previous_ring → ring). Nav `{"Radar": "index.html", "Trending": "trending.html"}`.

In `src/radar/cli.py`, register a `digest_app` (`app.add_typer(digest_app, name="digest")`) and add `generate` (local imports; mirror the export command's env). Behavior per the interface above; the dedup rule: read `load_digests` first; only `append_digest` when the label is not already present. Fire the webhook inside an `httpx.AsyncClient` via `asyncio.run`, wrapped so a webhook failure never fails the command. Render `digest.html` via the same Jinja `Environment` the other CLI renders use.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_digest_webhook.py tests/test_digest_cli.py -v`
Expected: PASS

- [ ] **Step 6: Lint + typecheck + commit**

```bash
uv run ruff check src/radar tests/test_digest_webhook.py tests/test_digest_cli.py && uv run mypy src/radar
git add src/radar/notify/webhook.py src/radar/cli.py src/radar/web/templates/digest.html \
  tests/test_digest_webhook.py tests/test_digest_cli.py
git commit -m "feat: radar digest generate (page + cards + feeds + webhook)"
```

---

### Task 5: Publish integration + weekly workflow

**Files:**
- Modify: `src/radar/web/static_site.py`, `src/radar/web/templates/index.html`, `src/radar/web/templates/static_index.html`, `src/radar/cli.py` (export)
- Create: `.github/workflows/digest.yml`
- Test: `tests/test_static_site.py` (append), `tests/test_digest_workflow.py`

**Interfaces:**
- Consumes: `load_digests` (Task 2).
- Produces:
  - `render_static_site(..., digest_dir: Path | None = None)`: when given and it exists, copy its tree into `out_dir/digests`; a `latest_digest` context (the newest `DigestLogEntry` from `data/digest-log.jsonl`, passed by the CLI) drives an index link. Guarded — a missing digests dir / empty log is a no-op.
  - `radar export`: pass `digest_dir=root/"digests"` and `latest_digest=<newest log entry or None>`.
  - index/static_index: a "Latest digest →" link when `latest_digest` is set.
  - `.github/workflows/digest.yml`: weekly (`cron: "0 8 * * 1"`, Mondays 08:00 UTC — offset from the autopilots) + `workflow_dispatch`; `contents: write` + `actions: write`; concurrency `digest`; steps: checkout → install → `radar digest generate --root . --base-url <pages url>` → rasterize (`sudo apt-get install -y librsvg2-bin`; `for f in digests/cards/*.svg; do rsvg-convert "$f" -o "${f%.svg}.png" || true; done`) → commit `digests/` + `data/digest-log.jsonl` if changed → `gh workflow run publish.yml`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_static_site.py`:

```python
def test_static_site_copies_digests_and_links_latest(tmp_path):
    from radar.storage.digest_log import DigestLogEntry

    digests = tmp_path / "digests"
    (digests / "cards").mkdir(parents=True)
    (digests / "digest_2026-W28.html").write_text("<h1>W28</h1>", encoding="utf-8")
    latest = DigestLogEntry(label="2026-W28", generated_at=datetime(2026, 7, 8, tzinfo=UTC),
                            url="digests/digest_2026-W28.html", summary="Week 28")

    render_static_site([], tmp_path / "_site", datetime(2026, 7, 8, tzinfo=UTC),
                       digest_dir=digests, latest_digest=latest)
    site = tmp_path / "_site"

    assert (site / "digests" / "digest_2026-W28.html").exists()
    assert 'href="digests/digest_2026-W28.html"' in (site / "index.html").read_text("utf-8")


def test_static_site_without_digests_is_backcompat(tmp_path):
    render_static_site([], tmp_path / "_site", datetime(2026, 7, 8, tzinfo=UTC))
    assert not (tmp_path / "_site" / "digests").exists()
    assert (tmp_path / "_site" / "index.html").exists()
```

tests/test_digest_workflow.py:

```python
"""The weekly digest workflow generates, rasterizes, commits, dispatches."""

from __future__ import annotations

from pathlib import Path

import yaml


def test_workflow_schedule_and_perms():
    wf = yaml.safe_load(Path(".github/workflows/digest.yml").read_text(encoding="utf-8"))
    triggers = wf.get("on") or wf.get(True)
    assert "schedule" in triggers and "workflow_dispatch" in triggers
    assert triggers["schedule"][0]["cron"] == "0 8 * * 1"
    assert wf["permissions"]["contents"] == "write"


def test_workflow_generates_rasterizes_commits_dispatches():
    text = Path(".github/workflows/digest.yml").read_text(encoding="utf-8")
    assert "radar digest generate" in text
    assert "librsvg2-bin" in text and "rsvg-convert" in text
    assert "digests/" in text and "data/digest-log.jsonl" in text
    assert "gh workflow run publish.yml" in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_static_site.py tests/test_digest_workflow.py -v -k "digest"`
Expected: FAIL — `TypeError` on `digest_dir` / file not found

- [ ] **Step 3: Implement static_site copy + link**

In `src/radar/web/static_site.py`: add params `digest_dir: Path | None = None`, `latest_digest: DigestLogEntry | None = None` (import the type). After the main writes, if `digest_dir and digest_dir.exists()`: `shutil.copytree(digest_dir, out_dir / "digests", dirs_exist_ok=True)`. Pass `latest_digest` into the index render context. In `index.html` + `static_index.html`, add near the summaries: `{% if latest_digest %}<p class="scan-health"><a href="{{ latest_digest.url }}">📰 Latest digest: {{ latest_digest.label }} →</a></p>{% endif %}`.

- [ ] **Step 4: Wire the export CLI**

In `src/radar/cli.py` `export`: `from radar.storage.digest_log import load_digests`; `digests = load_digests(root/"data"/"digest-log.jsonl")`; `latest = max(digests, key=lambda d: d.generated_at) if digests else None`; pass `digest_dir=root/"digests", latest_digest=latest` into `render_static_site(...)`.

- [ ] **Step 5: Create the workflow**

Create `.github/workflows/digest.yml` mirroring `source-autopilot.yml` (checkout → install uv/python/package → generate → rasterize → commit-if-changed → dispatch). Use the concrete Pages base URL for `--base-url` (read it from `catalog-autopilot.yml`/`publish.yml` if one is templated there; else `https://ekaynac.github.io/onprem-ai-adoption-radar`). Commit `digests/` and `data/digest-log.jsonl`.

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_static_site.py tests/test_digest_workflow.py tests/test_cli.py -v`
Expected: PASS (new + existing; back-compat proves no-digest exports unchanged)

- [ ] **Step 7: Lint + typecheck + commit**

```bash
uv run ruff check src/radar .github tests/test_static_site.py tests/test_digest_workflow.py && uv run mypy src/radar
git add src/radar/web/static_site.py src/radar/web/templates/index.html \
  src/radar/web/templates/static_index.html src/radar/cli.py \
  .github/workflows/digest.yml tests/test_static_site.py tests/test_digest_workflow.py
git commit -m "feat: publish integration + weekly digest workflow"
```

---

### Task 6: README + CHANGELOG + full gates

**Files:**
- Modify: `README.md`, `CHANGELOG.md`
- Test: the full suite

- [ ] **Step 1: README**

Add to the CLI table, after the `radar trending promote` row:

```markdown
| `radar digest generate [--base-url URL]` | Build the weekly digest page + Mega-branded social cards + Atom/RSS newsletter feeds; append the digest log and fire the webhook. |
```

Extend the 📈 Trending radar Highlights bullet with a final sentence:

```markdown
 A weekly **digest** rolls the week's trending + auto-adds + ring changes into a shareable page, Atom/RSS newsletter feeds, a webhook ping, and Mega-branded social cards (SVG → PNG in CI).
```

- [ ] **Step 2: CHANGELOG**

Under `## [Unreleased]` → `### Added`, at the top:

```markdown
- **Weekly digest + social cards** — `radar digest generate` assembles the
  ISO week's top trending (both lanes), autopilot additions, and ring changes
  across all three radars into `digests/digest_<year>-W<week>.html`, with
  Atom (`digest.xml`) + RSS (`digest-rss.xml`) newsletter feeds built from a
  committed `data/digest-log.jsonl`, a fire-and-forget webhook ping, and
  deterministic Mega-branded SVG cards (Instagram-portrait + OG) rasterized
  to PNG via `rsvg-convert` in a weekly `digest.yml` workflow. Separate from
  the daily publish, so a digest failure never stales the site.
```

- [ ] **Step 3: Full gates**

Run: `uv run pytest && uv run ruff check . && uv run mypy src/radar`
Expected: all pass, coverage ≥ 80%, ruff + mypy clean. Fix anything failing (implementation, not tests, unless a test is genuinely wrong).

- [ ] **Step 4: Commit**

```bash
git add README.md CHANGELOG.md
git commit -m "docs: weekly digest + cards in README + CHANGELOG"
```

---

## Self-Review Notes (already applied)

- Spec §4 coverage: `reports/digest.py` weekly assembly of top trending + best broader + auto-adds + ring changes across 3 radars (T1); `digest_<label>.html` + latest-digest index link (T4/T5); Atom `digest.xml` + RSS `digest-rss.xml` newsletter feeds one-entry-per-digest (T2); fire-and-forget webhook (T4); `web/cards.py` deterministic SVG cards two sizes → PNG via `rsvg-convert` in CI (T3/T5); weekly workflow generates+commits, separate from daily publish (T5).
- Brand-kit constraint honored: cards embed NO brand asset — Process Blue `#009FDA` + text wordmark + safe font stack only (recorded simplification vs a raster logo lockup).
- Guarded reads: trending via `load_trending_entries` (never raw `load_observations`); digest-log/history loaders skip corrupt lines; static-site digest copy + latest-link are no-ops when absent (back-compat test).
- Determinism: `iso_week_bounds`/`build_digest`/`render_card` pure with `now`/inputs as parameters; only the CLI reads `datetime.now(UTC)`; cards are deterministic strings (PNG rasterization is a best-effort CI step, never in Python).
- Type consistency: `WeeklyDigest`/`DigestChange` (T1) → cards (T3), webhook (T4), template (T4); `DigestLogEntry` (T2) → feeds (T2), CLI (T4), static link (T5); `write_cards`/`render_card`/`send_digest_notification`/`build_digest` names identical across producer and consumer tasks.

## Open items for plan time (resolved)

- `rsvg-convert` via `librsvg2-bin` on `ubuntu-latest`: standard apt package; the rasterization loop is best-effort (`|| true`) so a runner hiccup never fails the digest — the SVGs always ship and are what the page references.
- Font: safe stack `'Hanken Grotesk', Arial, …, sans-serif` — the runner substitutes a system sans for the raster; no font embedded, no brand kit in the repo.
