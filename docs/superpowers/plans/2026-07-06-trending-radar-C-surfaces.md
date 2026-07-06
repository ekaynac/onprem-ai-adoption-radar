# Trending Radar — Plan C (Surfaces) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build sub-project 3 of the trending radar: a `/trending` page (two lanes) on the dashboard and static site, a top-3 index strip + nav link, and an MCP `list_trending` tool — the radar's own githubsignals surface, refreshed daily by the existing publish run.

**Architecture:** A guarded `load_trending_entries(root, now)` reads the committed observation store and derives `TrendingEntry` rows via the existing pure `build_trending`. The web route, the static writer, and the MCP service all read through it (or `build_trending` directly for the static path where observations are already in hand). No detail pages — repos link straight to GitHub. Mirror of the technique-surfaces layer built earlier.

**Tech Stack:** Python 3.12, FastAPI + Jinja2 (in-tree), FastMCP (in-tree), pytest + ruff + mypy. **No new dependencies.**

**Spec:** `docs/superpowers/specs/2026-07-05-trending-radar-design.md` §3 fully; §4 later.

## Global Constraints

- Deterministic, offline rendering: every surface reads the persisted observation store — no network. `now` is a parameter through the library layer; only the web route and MCP tool read the wall clock at the boundary.
- Guarded reads: a corrupt/absent observation store degrades to "no trending data" on every surface — never a 500 (the technique-surfaces `load_technique_entries` precedent).
- Two lanes, always both shown: `onprem` = "On-prem radar candidates", `broader` = "Elsewhere in AI". Repos link to `https://github.com/{repo}`.
- ruff line-length = 100; `python_version = 3.12`; every Python file starts with `from __future__ import annotations`.
- Coverage ≥ 80%; gates `uv run pytest`, `uv run ruff check .`, `uv run mypy src/radar`.
- Commit format `<type>: <description>`; `git add` specific paths only (unrelated modified `data/history.jsonl` never committed).
- Live/static template pairs differ ONLY in nav/link targets (the established models/techniques convention).
- Existing symbols consumed (all on main): `TrendingEntry`/`Lane` (`radar.discovery.trending_entities`), `build_trending` (`radar.discovery.trending_detect`), `load_observations` (`radar.storage.trending_observations_log`), `create_app`/`build_mcp_server`/`render_static_site` patterns, `TechniqueQueryService` + `_research_summary.html` as mirrors.

## File Structure

```
src/radar/mcp_server/trending_queries.py     # NEW: load_trending_entries (guarded) + TrendingQueryService
src/radar/mcp_server/server.py                # MODIFY: register list_trending
src/radar/web/trending_summary.py             # NEW: TrendingSummary + summarize_trending (index strip)
src/radar/web/app.py                          # MODIFY: /trending route + index context + nav
src/radar/web/static_site.py                  # MODIFY: trending_observations param + _write_trending_page
src/radar/cli.py                              # MODIFY: export loads observations + threads them
src/radar/web/templates/
    trending.html static_trending.html          # two-lane page (live/static pair)
    _trending_summary.html                       # index strip partial
    index.html static_index.html                 # MODIFY: nav + summary include
tests/test_trending_queries.py                # NEW
tests/test_mcp_server.py                       # MODIFY: list_trending registration
tests/test_trending_summary.py                 # NEW
tests/test_web.py                              # MODIFY: /trending route + index strip
tests/test_static_site.py                      # MODIFY: trending page export
tests/test_cli.py                              # MODIFY: export trending assertions
README.md, CHANGELOG.md                         # MODIFY
```

Out of scope (sub-project 4): the weekly digest + Atom/RSS feeds + social cards. This plan produces the browsable page + index strip + MCP tool. No trending detail pages, no filter/sort JS (the two lane sections + velocity-desc default ordering are the segmentation) — deliberately simpler than the techniques page.

---

### Task 1: MCP trending query service + `list_trending` tool

**Files:**
- Create: `src/radar/mcp_server/trending_queries.py`
- Modify: `src/radar/mcp_server/server.py` (register `list_trending`)
- Test: `tests/test_trending_queries.py`, `tests/test_mcp_server.py` (append)

**Interfaces:**
- Consumes: `TrendingEntry`/`Lane`, `build_trending`, `load_observations`.
- Produces:
  - `load_trending_entries(root: Path, now: datetime) -> list[TrendingEntry]` — `build_trending(load_observations(root/"data"/"trending-observations.jsonl"), now)`; `[]` on ANY failure with a `logger.warning` (guarded gateway — a corrupt store never breaks a surface). Task 2/3 also use it.
  - `TrendingQueryService(root)` with `list_trending(self, lane: str | None = None, limit: int = 20, now: datetime | None = None) -> list[dict[str, Any]]` — `now` defaults to `datetime.now(UTC)` at this boundary; filter by lane (case-insensitive) if given; cap at `limit`; each row = `{repo, lane, stars, velocity_per_day, is_new, first_seen, description, topics}`.
  - Registered MCP tool `list_trending(lane, limit)` on `build_mcp_server(root)`.

- [ ] **Step 1: Write the failing tests (tests/test_trending_queries.py)**

```python
"""MCP trending query service over the observation store."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from radar.discovery.trending_entities import Lane, TrendingObservation
from radar.mcp_server.trending_queries import TrendingQueryService, load_trending_entries
from radar.storage.trending_observations_log import append_observations


NOW = datetime(2026, 7, 8, 7, 0, tzinfo=UTC)


def _obs(repo: str, stars: int, day: int, lane: Lane = Lane.ONPREM,
         created: str = "2026-06-01") -> TrendingObservation:
    return TrendingObservation(
        repo=repo, lane=lane, stars=stars,
        observed_at=datetime(2026, 7, day, 7, 0, tzinfo=UTC),
        repo_created_at=datetime.fromisoformat(created).replace(tzinfo=UTC),
        description="d", topics=["llm"], license="MIT",
    )


def _seed(root: Path, rows: list[TrendingObservation]) -> None:
    (root / "data").mkdir(parents=True, exist_ok=True)
    append_observations(root / "data" / "trending-observations.jsonl", rows)


def test_load_trending_entries_empty_without_store(tmp_path):
    assert load_trending_entries(tmp_path, NOW) == []


def test_load_trending_entries_guards_corrupt_store(tmp_path):
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "trending-observations.jsonl").write_text(
        "{not json}\n", encoding="utf-8"
    )
    # corrupt lines are skipped by load_observations → empty derived list, no raise
    assert load_trending_entries(tmp_path, NOW) == []


def test_list_trending_compact_rows_and_lane_filter(tmp_path):
    _seed(tmp_path, [
        _obs("fast/repo", 100, 1), _obs("fast/repo", 400, 4),
        _obs("broad/repo", 900, 4, lane=Lane.BROADER),
    ])
    svc = TrendingQueryService(tmp_path)

    rows = svc.list_trending(now=NOW)
    assert {r["repo"] for r in rows} == {"fast/repo", "broad/repo"}
    assert rows[0].keys() >= {"repo", "lane", "stars", "velocity_per_day",
                              "is_new", "first_seen", "description", "topics"}

    onprem = svc.list_trending(lane="onprem", now=NOW)
    assert [r["repo"] for r in onprem] == ["fast/repo"]


def test_list_trending_respects_limit(tmp_path):
    _seed(tmp_path, [
        _obs("a/a", 100, 1), _obs("a/a", 500, 4),
        _obs("b/b", 100, 1), _obs("b/b", 300, 4),
    ])
    svc = TrendingQueryService(tmp_path)

    assert len(svc.list_trending(limit=1, now=NOW)) == 1
```

Append to `tests/test_mcp_server.py` (reuse the file's existing patterns; seed the observation store directly):

```python
def _seed_trending(root: Path) -> None:
    from datetime import UTC, datetime

    from radar.discovery.trending_entities import Lane, TrendingObservation
    from radar.storage.trending_observations_log import append_observations

    (root / "data").mkdir(parents=True, exist_ok=True)
    rows = [
        TrendingObservation(
            repo="acme/rocket", lane=Lane.ONPREM, stars=stars,
            observed_at=datetime(2026, 7, day, 7, 0, tzinfo=UTC),
            repo_created_at=datetime(2026, 6, 1, tzinfo=UTC),
            description="d", topics=["llm"], license="MIT",
        )
        for day, stars in ((1, 100), (4, 500))
    ]
    append_observations(root / "data" / "trending-observations.jsonl", rows)


def test_server_registers_trending_tool(tmp_path: Path):
    _seed_trending(tmp_path)
    server = build_mcp_server(tmp_path)

    names = {t.name for t in asyncio.run(server.list_tools())}

    assert "list_trending" in names


def test_list_trending_tool_returns_rows(tmp_path: Path):
    _seed_trending(tmp_path)
    server = build_mcp_server(tmp_path)

    result = asyncio.run(server.call_tool("list_trending", {"lane": "onprem"}))
    payload = result[1].get("result", result[1])

    assert any(item["repo"] == "acme/rocket" for item in payload)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_trending_queries.py tests/test_mcp_server.py -v -k trending`
Expected: FAIL — `ModuleNotFoundError` / tool name missing

- [ ] **Step 3: Write the service**

Create `src/radar/mcp_server/trending_queries.py`:

```python
"""Query service over the trending observation store (mirror of the model/technique services)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from radar.discovery.trending_detect import build_trending
from radar.discovery.trending_entities import TrendingEntry
from radar.storage.trending_observations_log import load_observations


logger = logging.getLogger(__name__)


def load_trending_entries(root: Path, now: datetime) -> list[TrendingEntry]:
    """Derived trending entries from the observation store; [] on ANY failure.

    Guarded gateway: a corrupt or absent store degrades to "no trending data"
    on every surface rather than raising.
    """
    try:
        path = Path(root) / "data" / "trending-observations.jsonl"
        return build_trending(load_observations(path), now)
    except Exception as exc:
        logger.warning("Trending store unreadable under %s: %s", root, exc)
        return []


class TrendingQueryService:
    """Read-only trending queries for the MCP tool (and web/static loaders)."""

    def __init__(self, root: Path):
        self.root = Path(root)

    def list_trending(
        self,
        lane: str | None = None,
        limit: int = 20,
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        entries = load_trending_entries(self.root, now or datetime.now(UTC))
        if lane:
            entries = [e for e in entries if e.lane.value == lane.lower()]
        return [self._row(e) for e in entries[:limit]]

    @staticmethod
    def _row(entry: TrendingEntry) -> dict[str, Any]:
        return {
            "repo": entry.repo,
            "lane": entry.lane.value,
            "stars": entry.stars,
            "velocity_per_day": entry.velocity_per_day,
            "is_new": entry.is_new,
            "first_seen": entry.first_seen,
            "description": entry.description,
            "topics": entry.topics,
        }
```

In `src/radar/mcp_server/server.py`, next to the technique tools: instantiate `trending = TrendingQueryService(root)` (import at top: `from radar.mcp_server.trending_queries import TrendingQueryService`) and register:

```python
    @mcp.tool()
    def list_trending(lane: str | None = None, limit: int = 20) -> list[dict]:
        """Trending/newly-created GitHub repos by star velocity (lane: onprem | broader)."""
        return trending.list_trending(lane=lane, limit=limit)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_trending_queries.py tests/test_mcp_server.py -v`
Expected: PASS (existing + new)

- [ ] **Step 5: Lint + typecheck + commit**

```bash
uv run ruff check src/radar/mcp_server tests/test_trending_queries.py tests/test_mcp_server.py && uv run mypy src/radar
git add src/radar/mcp_server/trending_queries.py src/radar/mcp_server/server.py \
  tests/test_trending_queries.py tests/test_mcp_server.py
git commit -m "feat: MCP list_trending query service + tool"
```

---

### Task 2: Live `/trending` page + index strip + nav

**Files:**
- Create: `src/radar/web/trending_summary.py`, `src/radar/web/templates/trending.html`, `src/radar/web/templates/_trending_summary.html`
- Modify: `src/radar/web/app.py`, `src/radar/web/templates/index.html`
- Test: `tests/test_trending_summary.py`, `tests/test_web.py` (append)

**Interfaces:**
- Consumes: `load_trending_entries` (Task 1), `TrendingEntry`/`Lane`.
- Produces:
  - `TrendingSummary` (frozen: `onprem_top: list[TrendingEntry]` (≤3), `onprem_count: int`, `broader_count: int`, property `has_trending: bool`, property `one_line: str`), `summarize_trending(entries: list[TrendingEntry]) -> TrendingSummary`.
  - `_trending_summary.html` — renders when `trending_summary.has_trending`, links via `trending_href|default('trending.html')`.
  - `trending.html` — two `<table>`s (onprem "On-prem radar candidates", broader "Elsewhere in AI"); columns Repo (GitHub link), Stars, Velocity/day, NEW badge, First seen, Description.
  - Live `GET /trending` renders `trending.html` with `onprem`/`broader` lists (split from `load_trending_entries(root, now)`). Index gains `trending_summary` context + nav `"Trending": "/trending"` + `_trending_summary.html` include.

- [ ] **Step 1: Write the failing tests (tests/test_trending_summary.py)**

```python
"""Index-strip summary of the trending catalog."""

from __future__ import annotations

from radar.discovery.trending_entities import Lane, TrendingEntry
from radar.web.trending_summary import TrendingSummary, summarize_trending


def _entry(repo: str, lane: Lane, vel: float | None = 10.0) -> TrendingEntry:
    return TrendingEntry(
        repo=repo, lane=lane, stars=1000, velocity_per_day=vel, is_new=False,
        first_seen="2026-07-01", description="d", topics=["llm"],
    )


def test_summarize_top3_onprem_and_counts():
    entries = [
        _entry("a/1", Lane.ONPREM, 50.0), _entry("a/2", Lane.ONPREM, 40.0),
        _entry("a/3", Lane.ONPREM, 30.0), _entry("a/4", Lane.ONPREM, 20.0),
        _entry("b/1", Lane.BROADER), _entry("b/2", Lane.BROADER),
    ]
    summary = summarize_trending(entries)

    assert [e.repo for e in summary.onprem_top] == ["a/1", "a/2", "a/3"]  # top 3
    assert summary.onprem_count == 4
    assert summary.broader_count == 2
    assert summary.has_trending is True
    assert "4" in summary.one_line


def test_empty_summary_has_no_trending():
    summary = summarize_trending([])

    assert summary == TrendingSummary()
    assert summary.has_trending is False
```

Append to `tests/test_web.py`:

```python
def _seed_trending_obs(root: Path) -> None:
    from datetime import UTC, datetime

    from radar.discovery.trending_entities import Lane as _L
    from radar.discovery.trending_entities import TrendingObservation as _O
    from radar.storage.trending_observations_log import append_observations

    (root / "data").mkdir(parents=True, exist_ok=True)
    rows = [
        _O(repo="acme/rocket", lane=_L.ONPREM, stars=stars,
           observed_at=datetime(2026, 7, day, 7, 0, tzinfo=UTC),
           repo_created_at=datetime(2026, 6, 1, tzinfo=UTC),
           description="fast serving", topics=["llm"], license="MIT")
        for day, stars in ((1, 100), (4, 400))
    ] + [
        _O(repo="big/model", lane=_L.BROADER, stars=90000,
           observed_at=datetime(2026, 7, 4, 7, 0, tzinfo=UTC),
           repo_created_at=datetime(2024, 1, 1, tzinfo=UTC),
           description="a model", topics=["llm"], license="Apache-2.0"),
    ]
    append_observations(root / "data" / "trending-observations.jsonl", rows)


def test_trending_route_shows_both_lanes(tmp_path):
    _seed_trending_obs(tmp_path)
    client = TestClient(create_app(tmp_path))

    r = client.get("/trending")

    assert r.status_code == 200
    assert "acme/rocket" in r.text and "big/model" in r.text
    assert "On-prem radar candidates" in r.text
    assert "Elsewhere in AI" in r.text
    assert 'href="https://github.com/acme/rocket"' in r.text


def test_trending_route_empty_without_store(tmp_path):
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    client = TestClient(create_app(tmp_path))

    r = client.get("/trending")

    assert r.status_code == 200
    assert "No trending" in r.text


def test_index_shows_trending_strip_and_nav(tmp_path):
    _seed_trending_obs(tmp_path)
    client = TestClient(create_app(tmp_path))

    r = client.get("/")

    assert 'href="/trending"' in r.text
    assert "acme/rocket" in r.text  # top strict-lane repo in the strip
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_trending_summary.py tests/test_web.py -v -k trending`
Expected: FAIL — `ModuleNotFoundError` / 404 on `/trending`

- [ ] **Step 3: Write the summary module + partial**

Create `src/radar/web/trending_summary.py`:

```python
"""Immutable index-strip summary of the trending catalog (mirror of research_summary)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from radar.discovery.trending_entities import Lane, TrendingEntry


_TOP_N = 3


class TrendingSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    onprem_top: list[TrendingEntry] = Field(default_factory=list)
    onprem_count: int = 0
    broader_count: int = 0

    @property
    def has_trending(self) -> bool:
        return self.onprem_count > 0 or self.broader_count > 0

    @property
    def one_line(self) -> str:
        return (f"Trending: {self.onprem_count} on-prem candidates · "
                f"{self.broader_count} elsewhere in AI")


def summarize_trending(entries: list[TrendingEntry]) -> TrendingSummary:
    onprem = [e for e in entries if e.lane == Lane.ONPREM]
    broader = [e for e in entries if e.lane == Lane.BROADER]
    return TrendingSummary(
        onprem_top=onprem[:_TOP_N], onprem_count=len(onprem), broader_count=len(broader),
    )
```

Create `src/radar/web/templates/_trending_summary.html`:

```html
{# Trending strip. Context: trending_summary (TrendingSummary) | None. #}
{% if trending_summary and trending_summary.has_trending %}
<div class="scan-health">
  <details>
    <summary>📈 {{ trending_summary.one_line }}</summary>
    <ul>
      {% for e in trending_summary.onprem_top %}
      <li><a href="https://github.com/{{ e.repo }}">{{ e.repo }}</a>
          {% if e.velocity_per_day is not none %}+{{ e.velocity_per_day }}★/day{% endif %}
          {% if e.is_new %} · NEW{% endif %}</li>
      {% endfor %}
    </ul>
    <p><a href="{{ trending_href|default('trending.html') }}">Browse trending →</a></p>
  </details>
</div>
{% endif %}
```

Create `src/radar/web/templates/trending.html`:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Trending · Repos</title>
    <link rel="icon" type="image/png" href="{{ asset_base }}static/brand/favicon.png" />
    {% include "_base_styles.html" %}
  </head>
  <body>
    {% set page_title = "Trending Repos" %}
    {% set tagline = "Fast-rising and newly-created AI repos across GitHub — the radar's own signal." %}
    {% set nav = {"Radar": "/", "Models": "/models", "Research": "/research"} %}
    {% include "_hero.html" %}
    <main class="container">
      {% if not onprem and not broader %}<p>No trending observations yet.</p>{% endif %}
      {% for section, rows in [("On-prem radar candidates", onprem),
                                ("Elsewhere in AI", broader)] %}
      {% if rows %}
      <h2>{{ section }}</h2>
      <table>
        <thead><tr><th>Repo</th><th>Stars</th><th>Velocity/day</th><th></th>
                   <th>First seen</th><th>Description</th></tr></thead>
        <tbody>
          {% for e in rows %}
          <tr>
            <td><a href="https://github.com/{{ e.repo }}">{{ e.repo }}</a></td>
            <td>{{ e.stars }}</td>
            <td>{% if e.velocity_per_day is not none %}{{ e.velocity_per_day }}{% else %}—{% endif %}</td>
            <td>{% if e.is_new %}NEW{% endif %}</td>
            <td>{{ e.first_seen }}</td>
            <td>{{ e.description }}</td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
      {% endif %}
      {% endfor %}
    </main>
    {% include "_footer.html" %}
  </body>
</html>
```

- [ ] **Step 4: Wire the route + index**

In `src/radar/web/app.py`: import `from radar.mcp_server.trending_queries import load_trending_entries` and `from radar.web.trending_summary import summarize_trending`, `from radar.discovery.trending_entities import Lane`.

Add a loader helper near `_technique_entries`:

```python
    def _trending_entries():
        from datetime import UTC, datetime
        return load_trending_entries(root, datetime.now(UTC))
```

Extend the index context (inside `index()`'s return dict):

```python
                "trending_summary": summarize_trending(_trending_entries()),
                "trending_href": "/trending",
```

Add the route near the other pages:

```python
    @app.get("/trending", response_class=HTMLResponse)
    def trending_page(request: Request):
        entries = _trending_entries()
        onprem = [e for e in entries if e.lane == Lane.ONPREM]
        broader = [e for e in entries if e.lane == Lane.BROADER]
        return TEMPLATES.TemplateResponse(
            request, "trending.html", {"onprem": onprem, "broader": broader}
        )
```

In `src/radar/web/templates/index.html`: add `"Trending": "/trending"` to the `nav` dict (after `"Research"`) and `{% include "_trending_summary.html" %}` immediately after the `_research_summary.html` include.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_trending_summary.py tests/test_web.py -v`
Expected: PASS (existing + new)

- [ ] **Step 6: Lint + typecheck + commit**

```bash
uv run ruff check src/radar/web tests/test_trending_summary.py tests/test_web.py && uv run mypy src/radar
git add src/radar/web/trending_summary.py src/radar/web/templates/trending.html \
  src/radar/web/templates/_trending_summary.html src/radar/web/app.py \
  src/radar/web/templates/index.html tests/test_trending_summary.py tests/test_web.py
git commit -m "feat: /trending dashboard page + index strip + nav"
```

---

### Task 3: Static export — trending page

**Files:**
- Create: `src/radar/web/templates/static_trending.html`
- Modify: `src/radar/web/static_site.py`, `src/radar/web/templates/static_index.html`, `src/radar/cli.py` (export)
- Test: `tests/test_static_site.py`, `tests/test_cli.py` (append)

**Interfaces:**
- Consumes: `build_trending`, `load_observations`, `summarize_trending`, `Lane`; the live `trending.html` markup.
- Produces: `render_static_site(..., trending_observations: list[TrendingObservation] | None = None)`; `_write_trending_page(env, out_dir, entries, generated_at)` writes `trending.html`; index gains `trending_summary` + `"Trending": "trending.html"` nav + the strip include; `radar export` loads observations and threads them.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_static_site.py`:

```python
def _trending_obs():
    from datetime import UTC, datetime

    from radar.discovery.trending_entities import Lane, TrendingObservation

    return [
        TrendingObservation(
            repo="acme/rocket", lane=Lane.ONPREM, stars=stars,
            observed_at=datetime(2026, 7, day, 7, 0, tzinfo=UTC),
            repo_created_at=datetime(2026, 6, 1, tzinfo=UTC),
            description="fast serving", topics=["llm"], license="MIT")
        for day, stars in ((1, 100), (4, 400))
    ]


def test_static_site_renders_trending_page(tmp_path):
    render_static_site(
        [], tmp_path / "_site", datetime(2026, 7, 8, tzinfo=UTC),
        trending_observations=_trending_obs(),
    )
    site = tmp_path / "_site"

    page = (site / "trending.html").read_text(encoding="utf-8")
    assert "acme/rocket" in page
    assert 'href="https://github.com/acme/rocket"' in page
    assert "On-prem radar candidates" in page
    index = (site / "index.html").read_text(encoding="utf-8")
    assert 'href="trending.html"' in index
    assert "Trending:" in index


def test_static_site_backcompat_without_trending(tmp_path):
    render_static_site([], tmp_path / "_site", datetime(2026, 7, 8, tzinfo=UTC))

    assert not (tmp_path / "_site" / "trending.html").exists()
    assert (tmp_path / "_site" / "index.html").exists()
```

Append to `tests/test_cli.py`:

```python
def test_export_includes_trending_page(tmp_path):
    from datetime import UTC, datetime

    from radar.discovery.trending_entities import Lane, TrendingObservation
    from radar.storage.trending_observations_log import append_observations

    runner = CliRunner()
    runner.invoke(app, ["init", "--root", str(tmp_path)])
    append_observations(tmp_path / "data" / "trending-observations.jsonl", [
        TrendingObservation(
            repo="acme/rocket", lane=Lane.ONPREM, stars=stars,
            observed_at=datetime(2026, 7, day, 7, 0, tzinfo=UTC),
            repo_created_at=datetime(2026, 6, 1, tzinfo=UTC),
            description="d", topics=["llm"], license="MIT")
        for day, stars in ((1, 100), (4, 400))
    ])

    result = runner.invoke(app, ["export", "--root", str(tmp_path),
                                 "--out", str(tmp_path / "_site")])

    assert result.exit_code == 0
    assert (tmp_path / "_site" / "trending.html").exists()
    assert "acme/rocket" in (tmp_path / "_site" / "trending.html").read_text(encoding="utf-8")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_static_site.py tests/test_cli.py -v -k trending`
Expected: FAIL — `TypeError` on `trending_observations` kwarg / no `trending.html`

- [ ] **Step 3: Create the static template**

`src/radar/web/templates/static_trending.html` — copy the committed `src/radar/web/templates/trending.html` byte-for-byte, changing ONLY the nav dict:

```html
    {% set nav = {"Radar": "index.html", "Models": "models.html", "Research": "techniques.html"} %}
```

- [ ] **Step 4: Wire static_site.py**

In `src/radar/web/static_site.py`:
- Add imports: `from radar.discovery.trending_detect import build_trending`, `from radar.discovery.trending_entities import Lane, TrendingObservation`, `from radar.web.trending_summary import summarize_trending`.
- `render_static_site` gains a param (after `technique_events`): `trending_observations: list[TrendingObservation] | None = None`.
- Near `techniques_summary = ...`:

```python
    trending_entries = (
        build_trending(trending_observations, generated_at) if trending_observations else []
    )
    trending_summary = summarize_trending(trending_entries) if trending_entries else None
```

- Pass `trending_summary=trending_summary` into the `static_index.html` render context (next to `techniques_summary`).
- Next to the `_write_technique_pages` call:

```python
    if trending_entries:
        _write_trending_page(env, out_dir, trending_entries, stamp)
```

- Add the writer:

```python
def _write_trending_page(
    env: Environment,
    out_dir: Path,
    trending_entries: list[TrendingEntry],
    generated_at: str = "",
) -> None:
    """Render trending.html (two lanes) from derived trending entries."""
    onprem = [e for e in trending_entries if e.lane == Lane.ONPREM]
    broader = [e for e in trending_entries if e.lane == Lane.BROADER]
    (out_dir / "trending.html").write_text(
        env.get_template("static_trending.html").render(
            onprem=onprem, broader=broader, generated_at=generated_at
        ),
        encoding="utf-8",
    )
```

(Import `TrendingEntry` too for the annotation.)

In `src/radar/web/templates/static_index.html`: add `"Trending": "trending.html"` to the nav dict (after `"Research"`) and `{% include "_trending_summary.html" %}` after the `_research_summary.html` include (the partial's `trending_href` default is already `trending.html`).

- [ ] **Step 5: Wire the export CLI**

In `src/radar/cli.py` `export`, near the technique-entries loading block:

```python
    from radar.storage.trending_observations_log import load_observations as _load_trending_obs

    trending_observations = _load_trending_obs(root / "data" / "trending-observations.jsonl")
```

and thread into the `render_static_site(...)` call: `trending_observations=trending_observations or None`.

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_static_site.py tests/test_cli.py tests/test_web.py -v`
Expected: PASS (new + existing; back-compat proves no-trending exports unchanged)

- [ ] **Step 7: Lint + typecheck + commit**

```bash
uv run ruff check src/radar tests/test_static_site.py tests/test_cli.py && uv run mypy src/radar
git add src/radar/web/templates/static_trending.html src/radar/web/templates/static_index.html \
  src/radar/web/static_site.py src/radar/cli.py tests/test_static_site.py tests/test_cli.py
git commit -m "feat: static export trending page"
```

---

### Task 4: README + CHANGELOG + full gates

**Files:**
- Modify: `README.md`, `CHANGELOG.md`
- Test: the full suite

- [ ] **Step 1: README**

Extend the 📈 Trending radar Highlights bullet with a closing sentence:

```markdown
 Browsable at `/trending` (dashboard + static site) with two lanes — on-prem radar candidates and "elsewhere in AI" — plus a top-3 strip on the index and an MCP `list_trending` tool.
```

- [ ] **Step 2: CHANGELOG**

Under `## [Unreleased]` → `### Added`, at the top:

```markdown
- **Trending surfaces** — a `/trending` page (dashboard + static site) shows
  the two-lane GitHub trending signal (on-prem radar candidates + elsewhere in
  AI) with star velocity, NEW-repo badges, and first-seen dates; the index
  gains a top-3 strip and a Trending nav link, and MCP gains `list_trending`.
  All read the committed observation store — a corrupt store degrades to "no
  trending data" rather than breaking any page.
```

- [ ] **Step 3: Full gates**

Run: `uv run pytest && uv run ruff check . && uv run mypy src/radar`
Expected: all pass, coverage ≥ 80%, ruff + mypy clean. Fix anything failing (implementation, not tests, unless a test is genuinely wrong).

- [ ] **Step 4: Commit**

```bash
git add README.md CHANGELOG.md
git commit -m "docs: trending surfaces in README + CHANGELOG"
```

---

## Self-Review Notes (already applied)

- Spec §3 coverage: two-lane `/trending` page live + static (T2/T3), index top-3 strip + nav (T2/T3), MCP `list_trending` (T1). No detail pages (repos link to GitHub) — matches "columns: repo (GitHub link), stars, velocity/day, NEW, first-seen, description".
- Guarded reads recorded: `load_trending_entries` wraps the store read so a corrupt store never 500s a surface (the `load_technique_entries` precedent); `load_observations` already skips corrupt lines.
- Determinism: `now` threads through `build_trending`/`load_trending_entries`; only the web route + MCP tool read `datetime.now(UTC)` at the boundary; the static path uses `generated_at`.
- Type consistency: `TrendingEntry`/`Lane` flow through T1/T2/T3; `load_trending_entries(root, now)` (T1) consumed by T2's route; `summarize_trending`/`trending_summary`/`trending_href` names match partial ↔ index ↔ static; `_write_trending_page`/`trending_observations` param names match writer ↔ render_static_site ↔ CLI.
- Live/static `trending.html`/`static_trending.html` differ only in the nav dict (the established convention) — T3 copies the committed live template.
