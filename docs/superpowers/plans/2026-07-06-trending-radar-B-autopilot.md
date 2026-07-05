# Trending Radar — Plan B (Source Autopilot) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build sub-project 2 of the trending radar: a weekly, gated auto-promotion of sustained-momentum strict-lane repos from the observation store into `config/seed-sources.yaml` — the radar growing its own tool catalog, code-as-gate.

**Architecture:** A pure `discovery/source_promotion.py` (mirror of `model_promotion.py`) computes sustained-momentum + all gates over the committed `data/trending-observations.jsonl` — **fully offline**, because sub-project 1 stored each repo's license in its observation (no network needed). `radar trending promote` gates candidates, validate-or-abort appends `SourceConfig` blocks to the seed, and appends an audit row to `data/autopilot-log.jsonl`. A weekly `source-autopilot.yml` runs it and dispatches publish, mirroring the models autopilot's commit-if-changed + integrity-gate flow.

**Tech Stack:** Python 3.12, pydantic v2, typer, PyYAML (all in-tree; **no new dependencies**), pytest + ruff + mypy.

**Spec:** `docs/superpowers/specs/2026-07-05-trending-radar-design.md` §2 fully; §3–§4 later.

## Global Constraints

- **Strict lane only promotes.** The `broader` lane is content, never catalog — the identity firewall. Filter to `Lane.ONPREM` before any promotion.
- **Techniques stay human-gated** — this autopilot only adds tool `SourceConfig` entries to `config/seed-sources.yaml`.
- Deterministic + offline: promotion reads only the committed observation store + config (license, stars, topics, description all already in the store). No network in the promotion path.
- Validate-or-abort write: temp file → `load_config` round-trip → unique-id check → replace only on success (the exact mechanism `models promote` ships with). Nothing invalid ever lands.
- Every auto-add carries an `auto-added` tag (provenance in `radar seed list` + on the site; the prune lever) and an audit row in `data/autopilot-log.jsonl`.
- ruff line-length = 100; `python_version = 3.12`; every file starts with `from __future__ import annotations`.
- Coverage ≥ 80%; gates `uv run pytest`, `uv run ruff check .`, `uv run mypy src/radar`.
- Commit format `<type>: <description>`; `git add` specific paths only (unrelated modified `data/history.jsonl` never committed).
- Existing symbols consumed (all on main): `TrendingObservation`/`Lane` (`radar.discovery.trending_entities`), `load_observations` (`radar.storage.trending_observations_log`), `SourceConfig`/`SourceType`/`Category`/`ConfigError` (`radar.models`, `radar.storage.config`), `load_config`, `project_slug` (`radar.web.slugs`). Serializer mirrors `discovery/model_promotion.py:seed_to_yaml_block`; workflow + CLI mirror `catalog-autopilot.yml` + `models promote`.

## File Structure

```
src/radar/discovery/source_promotion.py     # NEW: gates, classifier, build_source, source_to_yaml_block (pure)
src/radar/storage/autopilot_log.py           # NEW: AutopilotEntry + append/load JSONL
src/radar/cli.py                              # MODIFY: trending_app gains `promote`
.github/workflows/source-autopilot.yml        # NEW: weekly gated promotion + dispatch publish
.gitignore                                    # (no change — autopilot-log.jsonl IS committed, like the history logs)
tests/test_source_promotion.py                # NEW
tests/test_autopilot_log.py                   # NEW
tests/test_trending_promote_cli.py            # NEW
tests/test_source_autopilot_workflow.py       # NEW
README.md, CHANGELOG.md                        # MODIFY
```

Out of scope (later sub-projects): the `/trending` page + MCP tool (sub-project 3), the digest + cards (sub-project 4). Deliberate simplification recorded: auto-added sources carry `backer: None` (a human curating the entry later adds the backer; the site renders None backers fine) — the spec §2 action does not specify a backer.

---

### Task 1: Source promotion module (gates + classifier + builder + serializer)

**Files:**
- Create: `src/radar/discovery/source_promotion.py`
- Test: `tests/test_source_promotion.py`

**Interfaces:**
- Consumes: `TrendingObservation`, `Lane`; `SourceConfig`, `SourceType`, `Category`; `project_slug`; `yaml`.
- Produces (pure, no I/O — mirror of `model_promotion.py`):
  - Constants: `MIN_OBSERVATION_DAYS = 3`, `MIN_SPAN_DAYS = 5`, `MIN_AVG_VELOCITY = 30.0`, `MIN_TOTAL_GROWTH_PCT = 25.0`, `PROMOTE_MIN_STARS = 800`, `LICENSE_ALLOWLIST` (frozenset of lowercased spdx: `apache-2.0, mit, bsd-2-clause, bsd-3-clause, mpl-2.0`), `ORG_DENYLIST` (frozenset, seed a couple), `REPO_DENYLIST` (frozenset), `MAX_TAGS = 4`.
  - `MomentumStats` (frozen: `distinct_days: int`, `span_days: int`, `avg_velocity: float`, `growth_pct: float`).
  - `momentum_stats(rows: list[TrendingObservation]) -> MomentumStats | None` — over a single repo's rows (any lane): `None` with <2 rows or zero calendar span; else distinct calendar days, span in calendar days, avg velocity (calendar span), growth pct (vs earliest; earliest 0 stars → growth 0.0).
  - `has_sustained_momentum(rows) -> bool` — `stats is not None and distinct_days >= MIN_OBSERVATION_DAYS and span_days >= MIN_SPAN_DAYS and (avg_velocity >= MIN_AVG_VELOCITY or growth_pct >= MIN_TOTAL_GROWTH_PCT)`.
  - `classify_category(topics: list[str], description: str) -> Category | None` — first `_CATEGORY_KEYWORDS` entry whose keyword matches any lowercased topic, else any keyword in the lowercased description; `None` if no confident match (repo is NOT promoted, stays on the trending page).
  - `is_promotable_source(repo, rows, *, tracked_repos, existing_ids, existing_projects) -> bool` — ALL of: lane of latest row is `ONPREM`; `repo.lower() not in tracked_repos`; latest stars `>= PROMOTE_MIN_STARS`; latest `license` (lowercased) in `LICENSE_ALLOWLIST`; org (before `/`) not in `ORG_DENYLIST` and `repo.lower() not in REPO_DENYLIST`; `has_sustained_momentum(rows)`; `classify_category(...) is not None`; and the built id/project don't collide with `existing_ids`/`existing_projects`.
  - `build_source(repo, rows, *, existing_ids) -> SourceConfig | None` — latest row supplies stars/topics/description/license; `classify_category` gives the category (None → return None); `id = f"github-{project_slug(name)}"` (name = repo's last path segment; resolve a unique id vs `existing_ids` with a `-2..-51` suffix loop, else None); `project = name`; `url = https://github.com/{repo}`; `tags = topics[:MAX_TAGS] + ["auto-added"]`; `type=github_repo`, `enabled=True`, `backer=None`.
  - `source_to_yaml_block(source: SourceConfig) -> str` — hand-authored-style block matching `seed-sources.yaml` (`  - id:` then 4-space keys; `type`, `enabled`, `project`, `category.value`, `url`, `tags: [a, b, c]` inline flow list; string scalars YAML-safe-quoted via a `_yaml_str` helper mirroring `model_promotion._yaml_str`).

- [ ] **Step 1: Write the failing tests**

```python
"""Source-promotion gates, classifier, builder, serializer (pure)."""

from __future__ import annotations

from datetime import UTC, datetime

from radar.discovery.source_promotion import (
    LICENSE_ALLOWLIST,
    MomentumStats,
    build_source,
    classify_category,
    has_sustained_momentum,
    is_promotable_source,
    momentum_stats,
    source_to_yaml_block,
)
from radar.discovery.trending_entities import Lane, TrendingObservation
from radar.models import Category, SourceConfig
from radar.storage.config import load_config


def _obs(repo: str, stars: int, day: int, lane: Lane = Lane.ONPREM,
         license: str | None = "Apache-2.0",
         topics: list[str] | None = None) -> TrendingObservation:
    return TrendingObservation(
        repo=repo, lane=lane, stars=stars,
        observed_at=datetime(2026, 7, day, 7, 0, tzinfo=UTC),
        repo_created_at=datetime(2026, 1, 1, tzinfo=UTC),
        description="fast llm serving", topics=topics or ["llm-inference"],
        license=license,
    )


# ── momentum ────────────────────────────────────────────────────────────────

def test_momentum_stats_computed_over_calendar_days():
    rows = [_obs("a/b", 800, 1), _obs("a/b", 900, 4), _obs("a/b", 1000, 6)]
    stats = momentum_stats(rows)

    assert stats == MomentumStats(distinct_days=3, span_days=5, avg_velocity=40.0,
                                  growth_pct=25.0)


def test_momentum_none_with_single_row_or_zero_span():
    assert momentum_stats([_obs("a/b", 800, 1)]) is None
    assert momentum_stats([_obs("a/b", 800, 1), _obs("a/b", 810, 1)]) is None  # same day


def test_sustained_requires_days_span_and_rate_or_growth():
    strong = [_obs("a/b", 800, 1), _obs("a/b", 900, 4), _obs("a/b", 1050, 6)]
    assert has_sustained_momentum(strong) is True  # ≥3 days, span 5, growth 31%

    too_few_days = [_obs("a/b", 800, 1), _obs("a/b", 2000, 6)]  # 2 days
    assert has_sustained_momentum(too_few_days) is False

    flat = [_obs("a/b", 800, 1), _obs("a/b", 802, 4), _obs("a/b", 804, 6)]
    assert has_sustained_momentum(flat) is False  # <30/day and <25% growth


# ── classifier ──────────────────────────────────────────────────────────────

def test_classify_by_topic_then_description():
    assert classify_category(["mcp-server"], "") == Category.MCP_TOOLING
    # topic substring match (keyword is a substring of the topic):
    assert classify_category(["my-agent-framework"], "") == Category.AGENT_FRAMEWORKS
    # description fallback (no topic match, keyword appears in prose):
    assert classify_category(["unknown"], "an llmops platform") \
        == Category.AI_INFRASTRUCTURE
    assert classify_category(["cats"], "a photo gallery") is None


# ── promotable gate ─────────────────────────────────────────────────────────

def _sustained(repo: str, license: str | None = "Apache-2.0",
              lane: Lane = Lane.ONPREM, topics=None) -> list[TrendingObservation]:
    return [
        _obs(repo, 800, 1, lane=lane, license=license, topics=topics),
        _obs(repo, 900, 4, lane=lane, license=license, topics=topics),
        _obs(repo, 1050, 6, lane=lane, license=license, topics=topics),
    ]


def test_is_promotable_happy_path():
    assert is_promotable_source(
        "acme/rocket", _sustained("acme/rocket"),
        tracked_repos=set(), existing_ids=set(), existing_projects=set(),
    ) is True


def test_is_promotable_rejects_broader_lane():
    assert is_promotable_source(
        "acme/rocket", _sustained("acme/rocket", lane=Lane.BROADER),
        tracked_repos=set(), existing_ids=set(), existing_projects=set(),
    ) is False


def test_is_promotable_rejects_bad_license():
    assert is_promotable_source(
        "acme/rocket", _sustained("acme/rocket", license=None),
        tracked_repos=set(), existing_ids=set(), existing_projects=set(),
    ) is False
    assert is_promotable_source(
        "acme/rocket", _sustained("acme/rocket", license="BUSL-1.1"),
        tracked_repos=set(), existing_ids=set(), existing_projects=set(),
    ) is False


def test_is_promotable_rejects_low_stars():
    rows = [_obs("a/b", 100, 1), _obs("a/b", 150, 4), _obs("a/b", 400, 6)]  # <800 latest
    assert is_promotable_source(
        "a/b", rows, tracked_repos=set(), existing_ids=set(), existing_projects=set(),
    ) is False


def test_is_promotable_rejects_uncategorizable():
    rows = _sustained("a/b", topics=["cats"])
    # description default "fast llm serving" would match — override to neutral
    rows = [r.model_copy(update={"description": "a gallery", "topics": ["cats"]})
            for r in rows]
    assert is_promotable_source(
        "a/b", rows, tracked_repos=set(), existing_ids=set(), existing_projects=set(),
    ) is False


def test_is_promotable_rejects_tracked_and_dupes():
    rows = _sustained("acme/rocket")
    assert is_promotable_source("acme/rocket", rows, tracked_repos={"acme/rocket"},
                                existing_ids=set(), existing_projects=set()) is False
    assert is_promotable_source("acme/rocket", rows, tracked_repos=set(),
                                existing_ids={"github-rocket"},
                                existing_projects=set()) is False


# ── builder + serializer ────────────────────────────────────────────────────

def test_build_source_fields_and_auto_added_tag():
    source = build_source("acme/rocket", _sustained("acme/rocket"), existing_ids=set())

    assert source is not None
    assert source.id == "github-rocket"
    assert source.project == "rocket"
    assert str(source.url) == "https://github.com/acme/rocket"
    assert source.category == Category.MODEL_SERVING
    assert "auto-added" in source.tags
    assert source.backer is None


def test_build_source_resolves_id_collision():
    source = build_source("acme/rocket", _sustained("acme/rocket"),
                          existing_ids={"github-rocket"})
    assert source is not None and source.id == "github-rocket-2"


def test_source_to_yaml_block_round_trips(tmp_path):
    source = build_source("acme/rocket", _sustained("acme/rocket"), existing_ids=set())
    assert source is not None
    seed = tmp_path / "seed.yaml"
    seed.write_text(
        "version: \"1.0\"\nsources:\n" + source_to_yaml_block(source), encoding="utf-8"
    )

    config = load_config(seed)
    assert config.sources[0].id == "github-rocket"
    assert "auto-added" in config.sources[0].tags
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_source_promotion.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'radar.discovery.source_promotion'`

- [ ] **Step 3: Write the implementation**

Create `src/radar/discovery/source_promotion.py`:

```python
"""Auto-promote sustained-momentum trending repos into the source catalog.

Pure and offline: every gate reads only the committed observation store
(sub-project 1 stored each repo's license, stars, topics, description on its
observations), so promotion needs no network. Strict-lane repos only —
the broader lane is content, never catalog. Mirror of model_promotion.py.
"""

from __future__ import annotations

import yaml
from pydantic import BaseModel, ConfigDict

from radar.discovery.trending_entities import Lane, TrendingObservation
from radar.models import Category, SourceConfig, SourceType
from radar.web.slugs import project_slug


MIN_OBSERVATION_DAYS = 3
MIN_SPAN_DAYS = 5
MIN_AVG_VELOCITY = 30.0
MIN_TOTAL_GROWTH_PCT = 25.0
PROMOTE_MIN_STARS = 800
MAX_TAGS = 4

LICENSE_ALLOWLIST: frozenset[str] = frozenset(
    {"apache-2.0", "mit", "bsd-2-clause", "bsd-3-clause", "mpl-2.0"}
)
ORG_DENYLIST: frozenset[str] = frozenset({"awesome", "collections"})
REPO_DENYLIST: frozenset[str] = frozenset()

# topic/keyword → category, first match wins (topics first, then description).
_CATEGORY_KEYWORDS: list[tuple[str, Category]] = [
    ("coding-agent", Category.CODING_AGENTS),
    ("code-assistant", Category.CODING_AGENTS),
    ("mcp-server", Category.MCP_TOOLING),
    ("model-context-protocol", Category.MCP_TOOLING),
    ("mcp", Category.MCP_TOOLING),
    ("sandbox", Category.SANDBOX_GOVERNANCE),
    ("guardrail", Category.SANDBOX_GOVERNANCE),
    ("agent-framework", Category.AGENT_FRAMEWORKS),
    ("llm-framework", Category.AGENT_FRAMEWORKS),
    ("llm-inference", Category.MODEL_SERVING),
    ("model-serving", Category.MODEL_SERVING),
    ("llm-serving", Category.MODEL_SERVING),
    ("inference", Category.MODEL_SERVING),
    ("local-llm", Category.MODEL_SERVING),
    ("llmops", Category.AI_INFRASTRUCTURE),
    ("ai-infrastructure", Category.AI_INFRASTRUCTURE),
    ("self-hosted", Category.AI_INFRASTRUCTURE),
    ("robotics", Category.PHYSICAL_AI_INFRASTRUCTURE),
    ("embodied", Category.PHYSICAL_AI_INFRASTRUCTURE),
    ("autonomous-agents", Category.GENERAL_AGENTS),
    ("ai-agents", Category.GENERAL_AGENTS),
    ("agent", Category.GENERAL_AGENTS),
]


class MomentumStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    distinct_days: int
    span_days: int
    avg_velocity: float
    growth_pct: float


def momentum_stats(rows: list[TrendingObservation]) -> MomentumStats | None:
    """Momentum over one repo's observation rows. None with <2 rows or zero span."""
    if len(rows) < 2:
        return None
    ordered = sorted(rows, key=lambda r: r.observed_at)
    distinct_days = len({r.observed_at.date() for r in ordered})
    span_days = (ordered[-1].observed_at.date() - ordered[0].observed_at.date()).days
    if span_days <= 0:
        return None
    delta = ordered[-1].stars - ordered[0].stars
    avg_velocity = round(delta / span_days, 1)
    earliest = ordered[0].stars
    growth_pct = round(delta / earliest * 100, 1) if earliest else 0.0
    return MomentumStats(distinct_days=distinct_days, span_days=span_days,
                         avg_velocity=avg_velocity, growth_pct=growth_pct)


def has_sustained_momentum(rows: list[TrendingObservation]) -> bool:
    stats = momentum_stats(rows)
    if stats is None:
        return False
    if stats.distinct_days < MIN_OBSERVATION_DAYS or stats.span_days < MIN_SPAN_DAYS:
        return False
    return (stats.avg_velocity >= MIN_AVG_VELOCITY
            or stats.growth_pct >= MIN_TOTAL_GROWTH_PCT)


def classify_category(topics: list[str], description: str) -> Category | None:
    lowered_topics = {t.lower() for t in topics}
    for keyword, category in _CATEGORY_KEYWORDS:
        if any(keyword in topic for topic in lowered_topics):
            return category
    desc = description.lower()
    for keyword, category in _CATEGORY_KEYWORDS:
        if keyword in desc:
            return category
    return None


def is_promotable_source(
    repo: str,
    rows: list[TrendingObservation],
    *,
    tracked_repos: set[str],
    existing_ids: set[str],
    existing_projects: set[str],
) -> bool:
    if not rows:
        return False
    latest = max(rows, key=lambda r: r.observed_at)
    if latest.lane != Lane.ONPREM:
        return False
    if repo.lower() in tracked_repos:
        return False
    if latest.stars < PROMOTE_MIN_STARS:
        return False
    if latest.license is None or latest.license.lower() not in LICENSE_ALLOWLIST:
        return False
    org = repo.split("/")[0].lower()
    if org in ORG_DENYLIST or repo.lower() in REPO_DENYLIST:
        return False
    if not has_sustained_momentum(rows):
        return False
    if classify_category(latest.topics, latest.description) is None:
        return False
    name = repo.split("/")[-1]
    if f"github-{project_slug(name)}" in existing_ids or name in existing_projects:
        return False
    return True


def build_source(
    repo: str, rows: list[TrendingObservation], *, existing_ids: set[str]
) -> SourceConfig | None:
    if not rows:
        return None
    latest = max(rows, key=lambda r: r.observed_at)
    category = classify_category(latest.topics, latest.description)
    if category is None:
        return None
    name = repo.split("/")[-1]
    base_id = f"github-{project_slug(name)}"
    candidate = base_id
    for attempt in range(2, 52):
        if candidate not in existing_ids:
            break
        candidate = f"{base_id}-{attempt}"
    else:
        return None
    tags = [*latest.topics[:MAX_TAGS], "auto-added"]
    return SourceConfig(
        id=candidate, type=SourceType.GITHUB_REPO, enabled=True, project=name,
        category=category, url=f"https://github.com/{repo}", tags=tags,
    )


def _yaml_str(s: str) -> str:
    """YAML-safe scalar via safe_dump (quotes colons etc.) — mirror of model_promotion."""
    dumped = yaml.safe_dump({"_": s}, default_flow_style=False)
    return dumped.split("_: ", 1)[1].strip()


def source_to_yaml_block(source: SourceConfig) -> str:
    """Render one SourceConfig as a hand-authored-style YAML list item."""
    tags = ", ".join(source.tags)
    lines = [
        f"  - id: {_yaml_str(source.id)}",
        f"    type: {source.type.value}",
        f"    enabled: {'true' if source.enabled else 'false'}",
        f"    project: {_yaml_str(source.project)}",
        f"    category: {source.category.value}",
        f"    url: {str(source.url)}",
        f"    tags: [{tags}]",
        "",
    ]
    return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_source_promotion.py -v`
Expected: PASS (all). If the `url` field (pydantic `HttpUrl`) renders with a trailing slash in `str(source.url)`, adjust the round-trip test's expectation to the normalized form pydantic produces — do NOT special-case the serializer.

- [ ] **Step 5: Lint + typecheck + commit**

```bash
uv run ruff check src/radar/discovery tests/test_source_promotion.py && uv run mypy src/radar
git add src/radar/discovery/source_promotion.py tests/test_source_promotion.py
git commit -m "feat: source-promotion gates + category classifier + serializer"
```

---

### Task 2: Autopilot audit log

**Files:**
- Create: `src/radar/storage/autopilot_log.py`
- Test: `tests/test_autopilot_log.py`

**Interfaces:**
- Consumes: nothing new (pydantic, json).
- Produces: `AutopilotEntry` (frozen: `repo: str`, `source_id: str`, `category: str`, `stars: int`, `avg_velocity: float`, `added_at: datetime`), `append_autopilot(path: Path, entries: list[AutopilotEntry]) -> None` (append-only JSONL, mkdir parents, no-op empty), `load_autopilot(path: Path) -> list[AutopilotEntry]` (missing → `[]`, corrupt lines skipped with warning). Mirror of `trending_observations_log.py`. Sub-project 4's digest reads this for "added this week".

- [ ] **Step 1: Write the failing tests**

```python
"""Append-only JSONL audit log of autopilot promotions."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from radar.storage.autopilot_log import AutopilotEntry, append_autopilot, load_autopilot


def _entry(repo: str) -> AutopilotEntry:
    return AutopilotEntry(
        repo=repo, source_id=f"github-{repo.split('/')[-1]}", category="model_serving",
        stars=1050, avg_velocity=41.7, added_at=datetime(2026, 7, 6, tzinfo=UTC),
    )


def test_append_and_load_round_trip(tmp_path: Path):
    path = tmp_path / "autopilot-log.jsonl"

    append_autopilot(path, [_entry("acme/rocket")])
    append_autopilot(path, [_entry("beta/engine")])
    append_autopilot(path, [])  # no-op

    rows = load_autopilot(path)
    assert [r.repo for r in rows] == ["acme/rocket", "beta/engine"]
    assert rows[0].avg_velocity == 41.7


def test_load_missing_returns_empty(tmp_path: Path):
    assert load_autopilot(tmp_path / "nope.jsonl") == []


def test_load_skips_corrupt_lines(tmp_path: Path):
    path = tmp_path / "autopilot-log.jsonl"
    append_autopilot(path, [_entry("acme/rocket")])
    with path.open("a", encoding="utf-8") as handle:
        handle.write("{broken\n")

    assert len(load_autopilot(path)) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_autopilot_log.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

Create `src/radar/storage/autopilot_log.py`:

```python
"""Append-only JSONL audit log of autopilot source promotions.

Every auto-add appends a row here; the file is committed by the autopilot
workflow (like the history logs) and read by the weekly digest for the
"added this week" section. Mirror of trending_observations_log.py.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict


logger = logging.getLogger(__name__)


class AutopilotEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    repo: str
    source_id: str
    category: str
    stars: int
    avg_velocity: float
    added_at: datetime


def append_autopilot(path: Path, entries: list[AutopilotEntry]) -> None:
    if not entries:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(e.model_dump(mode="json"), ensure_ascii=False) for e in entries]
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def load_autopilot(path: Path) -> list[AutopilotEntry]:
    if not path.exists():
        return []
    entries: list[AutopilotEntry] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, raw in enumerate(handle, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                entries.append(AutopilotEntry.model_validate_json(line))
            except ValueError as exc:
                logger.warning("Skipping corrupt autopilot-log line %d in %s: %s",
                               line_no, path, exc)
    return entries
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_autopilot_log.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Lint + typecheck + commit**

```bash
uv run ruff check src/radar/storage tests/test_autopilot_log.py && uv run mypy src/radar
git add src/radar/storage/autopilot_log.py tests/test_autopilot_log.py
git commit -m "feat: autopilot promotion audit log"
```

---

### Task 3: `radar trending promote` CLI (validate-or-abort)

**Files:**
- Modify: `src/radar/cli.py` (`trending_app` gains `promote`)
- Test: `tests/test_trending_promote_cli.py`

**Interfaces:**
- Consumes: Tasks 1–2; `load_observations`, `load_config` (+ `ConfigError`), `SourceConfig`, the seed-sources path.
- Produces: `radar trending promote [--limit 3] [--dry-run] [--root .]`:
  - load observations from `data/trending-observations.jsonl`; group by repo; keep only repos whose latest row is `Lane.ONPREM`.
  - load `config/seed-sources.yaml` (best-effort: the packaged path fallback like other commands — but for promote, a missing config is a hard error, exit 1 with a clear message; you cannot append to a nonexistent seed). Build `tracked_repos` (owner/name from github source urls), `existing_ids`, `existing_projects` from `config.sources`.
  - filter to `is_promotable_source(...)`, rank by latest-window `avg_velocity` desc (via `momentum_stats`), take up to `--limit`.
  - `build_source(...)` each (threading a growing `existing_ids` so within-run ids stay unique); drop `None`.
  - `--dry-run`: print a table (id, category, stars, avg velocity, repo) and return without writing.
  - Else validate-or-abort append: `old_text.rstrip("\n") + "\n" + blocks` where each block is `source_to_yaml_block(s)`; write temp `config/seed-sources.promote.tmp`; `load_config(tmp)`; unique-id check; on failure unlink + red message + exit 1; on success `tmp.replace(seed_path)`.
  - append one `AutopilotEntry` per promoted source to `data/autopilot-log.jsonl`.
  - print `"Promoted N source(s) into config/seed-sources.yaml"` (or "No sources qualified.").
  - Mirror `models promote`'s structure exactly (read it in `src/radar/cli.py`).

- [ ] **Step 1: Write the failing tests**

```python
"""CLI: radar trending promote (validate-or-abort append + audit log)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from radar.cli import app
from radar.discovery.trending_entities import Lane, TrendingObservation
from radar.storage.autopilot_log import load_autopilot
from radar.storage.config import load_config
from radar.storage.trending_observations_log import append_observations


_SEED = """version: "1.0"
sources:
  - id: github-cline
    type: github_repo
    enabled: true
    project: Cline
    category: coding_agents
    url: https://github.com/cline/cline
    tags: [coding-agent]
"""


def _sustained(repo: str, stars_end: int = 1050, lane: Lane = Lane.ONPREM,
               license: str | None = "Apache-2.0",
               topics: list[str] | None = None) -> list[TrendingObservation]:
    days = [(1, 800), (4, 900), (6, stars_end)]
    return [
        TrendingObservation(
            repo=repo, lane=lane, stars=stars,
            observed_at=datetime(2026, 7, day, 7, 0, tzinfo=UTC),
            repo_created_at=datetime(2026, 1, 1, tzinfo=UTC),
            description="fast llm serving", topics=topics or ["llm-inference"],
            license=license,
        )
        for day, stars in days
    ]


def _project(tmp_path: Path, observations: list[TrendingObservation]) -> Path:
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config" / "seed-sources.yaml").write_text(_SEED, encoding="utf-8")
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    append_observations(tmp_path / "data" / "trending-observations.jsonl", observations)
    return tmp_path


def test_promote_appends_and_logs(tmp_path):
    root = _project(tmp_path, _sustained("acme/rocket"))
    runner = CliRunner()

    result = runner.invoke(app, ["trending", "promote", "--root", str(root)])

    assert result.exit_code == 0
    assert "1 source" in result.stdout
    config = load_config(root / "config" / "seed-sources.yaml")
    added = [s for s in config.sources if s.id == "github-rocket"]
    assert added and "auto-added" in added[0].tags
    audit = load_autopilot(root / "data" / "autopilot-log.jsonl")
    assert audit[0].repo == "acme/rocket"


def test_promote_dry_run_writes_nothing(tmp_path):
    root = _project(tmp_path, _sustained("acme/rocket"))
    before = (root / "config" / "seed-sources.yaml").read_text(encoding="utf-8")
    runner = CliRunner()

    result = runner.invoke(app, ["trending", "promote", "--root", str(root), "--dry-run"])

    assert result.exit_code == 0
    assert (root / "config" / "seed-sources.yaml").read_text(encoding="utf-8") == before
    assert not (root / "data" / "autopilot-log.jsonl").exists()


def test_promote_skips_broader_lane_and_unqualified(tmp_path):
    observations = (
        _sustained("broad/repo", lane=Lane.BROADER)          # broader → never
        + _sustained("weak/repo", stars_end=805)             # flat → not sustained
    )
    root = _project(tmp_path, observations)
    runner = CliRunner()

    result = runner.invoke(app, ["trending", "promote", "--root", str(root)])

    assert result.exit_code == 0
    assert "No sources qualified" in result.stdout


def test_promote_respects_limit(tmp_path):
    observations = (
        _sustained("acme/rocket", stars_end=2000, topics=["llm-inference"])
        + _sustained("beta/serve", stars_end=1500, topics=["model-serving"])
    )
    root = _project(tmp_path, observations)
    runner = CliRunner()

    result = runner.invoke(app, ["trending", "promote", "--root", str(root), "--limit", "1"])

    assert result.exit_code == 0
    config = load_config(root / "config" / "seed-sources.yaml")
    auto = [s for s in config.sources if "auto-added" in s.tags]
    assert len(auto) == 1  # highest-velocity one only


def test_promote_missing_config_exits_1(tmp_path):
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    append_observations(tmp_path / "data" / "trending-observations.jsonl",
                        _sustained("acme/rocket"))
    runner = CliRunner()

    result = runner.invoke(app, ["trending", "promote", "--root", str(tmp_path)])

    assert result.exit_code == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_trending_promote_cli.py -v`
Expected: FAIL — `No such command` for `promote`

- [ ] **Step 3: Implement the command**

Add to `src/radar/cli.py`, next to the other `trending_app` commands (mirror `models promote`'s validate-or-abort structure — read it around `src/radar/cli.py:305-420`):

```python
@trending_app.command("promote")
def trending_promote(
    root: Path = typer.Option(Path("."), help="Project root."),
    limit: int = typer.Option(3, help="Max sources to auto-add per run."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print what would be added; do not write."),
) -> None:
    """Auto-add sustained-momentum strict-lane repos into config/seed-sources.yaml."""
    from datetime import UTC, datetime

    from radar.discovery.source_promotion import (
        build_source,
        is_promotable_source,
        momentum_stats,
        source_to_yaml_block,
    )
    from radar.discovery.trending_entities import Lane
    from radar.storage.autopilot_log import AutopilotEntry, append_autopilot
    from radar.storage.config import ConfigError, load_config
    from radar.storage.trending_observations_log import load_observations

    seed_path = root / "config" / "seed-sources.yaml"
    try:
        config = load_config(seed_path)
    except ConfigError as exc:
        console.print(f"[red]No source config to promote into: {exc}[/red]")
        raise typer.Exit(code=1) from exc

    observations = load_observations(root / "data" / "trending-observations.jsonl")
    by_repo: dict[str, list] = {}
    for obs in observations:
        by_repo.setdefault(obs.repo, []).append(obs)

    tracked_repos = _tracked_source_repos(config.sources)
    existing_ids = {s.id for s in config.sources}
    existing_projects = {s.project for s in config.sources}

    candidates = [
        (repo, rows) for repo, rows in by_repo.items()
        if is_promotable_source(repo, rows, tracked_repos=tracked_repos,
                                existing_ids=existing_ids, existing_projects=existing_projects)
    ]

    def _velocity(rows: list) -> float:
        stats = momentum_stats(rows)
        return stats.avg_velocity if stats else 0.0

    candidates.sort(key=lambda rr: _velocity(rr[1]), reverse=True)

    collected: list[tuple] = []
    working_ids = set(existing_ids)
    for repo, rows in candidates:
        if len(collected) >= limit:
            break
        source = build_source(repo, rows, existing_ids=working_ids)
        if source is None:
            continue
        working_ids.add(source.id)
        collected.append((source, rows))

    if not collected:
        console.print("No sources qualified.")
        return

    if dry_run:
        from rich.table import Table

        table = Table(title="Would auto-add (dry run)")
        for col in ("id", "category", "stars", "velocity/day", "repo"):
            table.add_column(col)
        for source, rows in collected:
            latest = max(rows, key=lambda r: r.observed_at)
            table.add_row(source.id, source.category.value, str(latest.stars),
                          f"{_velocity(rows):.1f}", latest.repo)
        console.print(table)
        return

    old_text = seed_path.read_text(encoding="utf-8")
    blocks = "".join("\n" + source_to_yaml_block(s).strip("\n") + "\n"
                     for s, _ in collected)
    new_text = old_text.rstrip("\n") + "\n" + blocks

    tmp = seed_path.with_suffix(".promote.tmp")
    tmp.write_text(new_text, encoding="utf-8")
    try:
        loaded = load_config(tmp)
    except ConfigError as exc:
        tmp.unlink(missing_ok=True)
        console.print(f"[red]Validation failed: {exc}[/red]")
        raise typer.Exit(code=1) from exc
    loaded_ids = [s.id for s in loaded.sources]
    if len(loaded_ids) != len(set(loaded_ids)):
        tmp.unlink(missing_ok=True)
        console.print("[red]Validation failed: duplicate source ids after append[/red]")
        raise typer.Exit(code=1)
    tmp.replace(seed_path)

    now = datetime.now(UTC)
    append_autopilot(root / "data" / "autopilot-log.jsonl", [
        AutopilotEntry(
            repo=max(rows, key=lambda r: r.observed_at).repo, source_id=source.id,
            category=source.category.value,
            stars=max(rows, key=lambda r: r.observed_at).stars,
            avg_velocity=_velocity(rows), added_at=now,
        )
        for source, rows in collected
    ])
    console.print(f"Promoted {len(collected)} source(s) into {seed_path.relative_to(root)}")
```

Add the `_tracked_source_repos` module-level helper near the other CLI helpers (or reuse `radar.discovery.trending_sweep._tracked_repos` by importing it — it does exactly this: owner/name lowercased from github source urls). Prefer importing `from radar.discovery.trending_sweep import _tracked_repos as _tracked_source_repos` to avoid duplication.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_trending_promote_cli.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Lint + typecheck + commit**

```bash
uv run ruff check src/radar/cli.py tests/test_trending_promote_cli.py && uv run mypy src/radar
git add src/radar/cli.py tests/test_trending_promote_cli.py
git commit -m "feat: radar trending promote (gated auto-add + audit log)"
```

---

### Task 4: Weekly source-autopilot workflow

**Files:**
- Create: `.github/workflows/source-autopilot.yml`
- Test: `tests/test_source_autopilot_workflow.py`

**Interfaces:**
- Produces a weekly workflow mirroring `catalog-autopilot.yml`: Monday 07:30 UTC (offset from catalog-autopilot's 07:00) + `workflow_dispatch`; `contents: write` + `actions: write`; concurrency group `source-autopilot`. Steps: checkout → install uv/python/package → `radar trending promote --root . --limit 3` (env `GITHUB_TOKEN`) → integrity gate (inline python: `load_config('config/seed-sources.yaml')`, assert unique ids) → commit `config/seed-sources.yaml` + `data/autopilot-log.jsonl` **only when `config/seed-sources.yaml` changed** (git diff gate + `$GITHUB_OUTPUT` `changed` flag) → dispatch `publish.yml` if changed.

Design note (recorded): the workflow does **not** run a fresh `trending scan` first. Promotion reads the observation store the daily publish already keeps fresh; scanning here would append an observation row on every weekly run (making "commit if changed" always fire) and add a network dependency to a deterministic step. Gating the commit on `seed-sources.yaml` keeps "did we promote anything" clean. (This narrows the spec §2's "fresh scan → promote" to "promote from the committed store"; the scan was belt-and-suspenders freshness the daily publish already provides.)

- [ ] **Step 1: Write the failing test**

```python
"""The source-autopilot workflow promotes and commits under the right gates."""

from __future__ import annotations

from pathlib import Path

import yaml


def _workflow() -> dict:
    text = Path(".github/workflows/source-autopilot.yml").read_text(encoding="utf-8")
    return yaml.safe_load(text)


def test_workflow_runs_weekly_with_dispatch_and_write_perms():
    wf = _workflow()
    # PyYAML parses the bare `on:` key as boolean True — accept either.
    triggers = wf.get("on") or wf.get(True)
    assert "schedule" in triggers and "workflow_dispatch" in triggers
    assert triggers["schedule"][0]["cron"] == "30 7 * * 1"
    assert wf["permissions"]["contents"] == "write"
    assert wf["permissions"]["actions"] == "write"


def test_workflow_promotes_gates_commits_and_dispatches():
    text = Path(".github/workflows/source-autopilot.yml").read_text(encoding="utf-8")

    assert "radar trending promote" in text
    assert "config/seed-sources.yaml" in text
    assert "data/autopilot-log.jsonl" in text
    # commit is gated on the seed changing, then publish is dispatched
    assert "git diff --quiet -- config/seed-sources.yaml" in text
    assert "gh workflow run publish.yml" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_source_autopilot_workflow.py -v`
Expected: FAIL — file not found

- [ ] **Step 3: Write the workflow**

Create `.github/workflows/source-autopilot.yml`:

```yaml
name: Source autopilot

on:
  schedule:
    - cron: "30 7 * * 1" # Mondays 07:30 UTC (offset from catalog-autopilot 07:00)
  workflow_dispatch: {}

permissions:
  contents: write # commit updated seed-sources.yaml + autopilot-log.jsonl
  actions: write  # dispatch publish.yml after commit

concurrency:
  group: source-autopilot
  cancel-in-progress: false

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6

      - name: Install uv
        uses: astral-sh/setup-uv@v8.2.0

      - name: Set up Python
        run: uv python install 3.12

      - name: Install package
        run: uv venv && uv pip install -e .

      - name: Promote sustained-momentum trending repos
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: uv run radar trending promote --root . --limit 3

      # Belt-and-suspenders: the catalog must still load with unique ids.
      # promote validates-or-aborts before writing, so reaching here means good.
      - name: Source catalog integrity gate
        run: |
          uv run python -c "
          from pathlib import Path
          from radar.storage.config import load_config
          config = load_config(Path('config/seed-sources.yaml'))
          ids = [s.id for s in config.sources]
          assert len(ids) == len(set(ids)), 'duplicate source ids'
          print(f'catalog OK: {len(ids)} sources, ids unique')
          "

      - name: Commit catalog changes (if any)
        id: commit
        run: |
          if git diff --quiet -- config/seed-sources.yaml; then
            echo "No new sources this week — nothing to commit."
            echo "changed=false" >> "$GITHUB_OUTPUT"
          else
            git config user.name "radar-bot"
            git config user.email "github-actions[bot]@users.noreply.github.com"
            git add config/seed-sources.yaml
            git add -f data/autopilot-log.jsonl || true
            git commit -m "chore(sources): autopilot additions $(date -u +%F)"
            git push
            echo "changed=true" >> "$GITHUB_OUTPUT"
          fi

      - name: Dispatch publish to refresh live site
        if: steps.commit.outputs.changed == 'true'
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: gh workflow run publish.yml --ref main
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_source_autopilot_workflow.py -v`
Expected: PASS (2 tests). If PyYAML parses `on:` as the boolean key `True`, the test already handles it (`wf.get("on") or wf.get(True)`).

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/source-autopilot.yml tests/test_source_autopilot_workflow.py
git commit -m "ci: weekly source autopilot (gated promotion + dispatch)"
```

---

### Task 5: README + CHANGELOG + full gates

**Files:**
- Modify: `README.md`, `CHANGELOG.md`
- Test: the full suite

- [ ] **Step 1: README**

Add to the CLI table, after the `radar trending list` row:

```markdown
| `radar trending promote [--limit N] [--dry-run]` | Auto-add sustained-momentum strict-lane repos (all gates passed) into `config/seed-sources.yaml`, tagged `auto-added`. |
```

Extend the 📈 Trending radar Highlights bullet with a second sentence:

```markdown
 A weekly **source autopilot** then auto-adds the strict-lane repos that clear every gate (sustained star momentum, size + permissive-license floors, a confident category, denylists) straight into the tracked catalog — the radar growing itself, with `auto-added` provenance and a committed audit log.
```

- [ ] **Step 2: CHANGELOG**

Under `## [Unreleased]` → `### Added`, at the top:

```markdown
- **Source autopilot** — `radar trending promote` auto-adds sustained-momentum
  strict-lane trending repos into `config/seed-sources.yaml` behind hard code
  gates (≥3 observation days over ≥5, ≥30 stars/day or ≥25% growth, ≥800
  stars, permissive-license allowlist, a confident deterministic category,
  org/repo denylists, weekly quota, validate-or-abort write). Fully offline —
  it reads the committed observation store (license/stars/topics already
  captured there). Every add is tagged `auto-added` and logged to
  `data/autopilot-log.jsonl`; a weekly `source-autopilot.yml` runs it and
  refreshes the live site. The broader lane never promotes; techniques stay
  human-gated.
```

- [ ] **Step 3: Full gates**

Run: `uv run pytest && uv run ruff check . && uv run mypy src/radar`
Expected: all pass, coverage ≥ 80%, ruff + mypy clean. Fix anything failing (implementation, not tests, unless a test is genuinely wrong).

- [ ] **Step 4: Commit**

```bash
git add README.md CHANGELOG.md
git commit -m "docs: source autopilot in README + CHANGELOG"
```

---

## Self-Review Notes (already applied)

- Spec §2 coverage: sustained-momentum gate (T1 `has_sustained_momentum`), size/license/classifier/denylist/dedup gates (T1 `is_promotable_source`), weekly quota + best-velocity-first + validate-or-abort + `auto-added` tag (T3), audit log (T2), weekly workflow + dispatch (T4). Strict-lane-only enforced in `is_promotable_source` (broader rejected) and re-filtered in the CLI.
- Offline promotion is the key win from sub-project 1 (license stored on observations) — recorded; no network in the promotion path, so T1/T3 are fully deterministic/testable.
- One deliberate spec narrowing recorded in T4's design note: the autopilot promotes from the committed store rather than running a fresh scan first (avoids observation-only commits + a network dependency; the daily publish keeps the store fresh). `backer: None` on auto-added sources also recorded (spec §2 unspecified).
- Type consistency: `TrendingObservation`/`Lane`/`momentum_stats`/`is_promotable_source`/`build_source`/`source_to_yaml_block` (T1) flow into T3; `AutopilotEntry`/`append_autopilot`/`load_autopilot` (T2) into T3; `_tracked_repos` reused from the sweep module.
