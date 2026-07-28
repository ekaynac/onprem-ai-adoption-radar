"""Auto-promote sustained-momentum trending repos into the source catalog.

Pure and offline: every gate reads only the committed observation store
(sub-project 1 stored each repo's license, stars, topics, description on its
observations), so promotion needs no network. Strict-lane repos only —
the broader lane is content, never catalog. Mirror of model_promotion.py.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import yaml
from pydantic import BaseModel, ConfigDict

from radar.discovery.trending_entities import Lane, TrendingObservation
from radar.models import Backer, BackerType, Category, SourceConfig, SourceType
from radar.web.slugs import project_slug


MIN_OBSERVATION_DAYS = 3
MIN_SPAN_DAYS = 5
MIN_AVG_VELOCITY = 30.0
MIN_TOTAL_GROWTH_PCT = 25.0
PROMOTE_MIN_STARS = 800
MAX_TAGS = 4
MOMENTUM_WINDOW_DAYS = 14

LICENSE_ALLOWLIST: frozenset[str] = frozenset(
    {"apache-2.0", "mit", "bsd-2-clause", "bsd-3-clause", "mpl-2.0"}
)
ORG_DENYLIST: frozenset[str] = frozenset({"awesome", "collections"})
REPO_DENYLIST: frozenset[str] = frozenset()
NAME_DENY_PREFIXES = ("awesome-", "awesome_")
TOPIC_DENYLIST: frozenset[str] = frozenset({"awesome", "awesome-list", "cheatsheet", "roadmap"})

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


def momentum_stats(rows: list[TrendingObservation], now: datetime) -> MomentumStats | None:
    """Momentum over one repo's recent (<= MOMENTUM_WINDOW_DAYS) observation rows."""
    recent = [r for r in rows if r.observed_at >= now - timedelta(days=MOMENTUM_WINDOW_DAYS)]
    if len(recent) < 2:
        return None
    ordered = sorted(recent, key=lambda r: r.observed_at)
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


def has_sustained_momentum(rows: list[TrendingObservation], now: datetime) -> bool:
    stats = momentum_stats(rows, now)
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
    now: datetime,
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
    name = repo.split("/")[-1]
    if org in ORG_DENYLIST or repo.lower() in REPO_DENYLIST:
        return False
    if name.lower().startswith(NAME_DENY_PREFIXES):
        return False
    if any(t.lower() in TOPIC_DENYLIST for t in latest.topics):
        return False
    onprem_rows = [r for r in rows if r.lane == Lane.ONPREM]
    if not has_sustained_momentum(onprem_rows, now):
        return False
    if classify_category(latest.topics, latest.description) is None:
        return False
    return (
        f"github-{project_slug(name)}" not in existing_ids
        and name.lower() not in {p.lower() for p in existing_projects}
    )


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
    # Every tracked source must carry a backer (test_seed_config pins this).
    # The sweep can't tell a person from a company, so auto-adds default to
    # the repo owner as `community` — curators refine the type later.
    owner = repo.split("/")[0]
    return SourceConfig(
        id=candidate, type=SourceType.GITHUB_REPO, enabled=True, project=name,
        category=category, url=f"https://github.com/{repo}", tags=tags,
        backer=Backer(name=owner, type=BackerType.COMMUNITY),
    )


def _yaml_str(s: str) -> str:
    """YAML-safe scalar via safe_dump (quotes colons etc.) — mirror of model_promotion."""
    dumped = yaml.safe_dump({"_": s}, default_flow_style=False)
    return dumped.split("_: ", 1)[1].strip()


def source_to_yaml_block(source: SourceConfig) -> str:
    """Render one SourceConfig as a hand-authored-style YAML list item."""
    tags = ", ".join(_yaml_str(t) for t in source.tags)
    lines = [
        f"  - id: {_yaml_str(source.id)}",
        f"    type: {source.type.value}",
        f"    enabled: {'true' if source.enabled else 'false'}",
        f"    project: {_yaml_str(source.project)}",
        f"    category: {source.category.value}",
        f"    url: {source.url}",
        f"    tags: [{tags}]",
    ]
    if source.backer is not None:
        lines.append(
            "    backer: {name: "
            f"{_yaml_str(source.backer.name)}, type: {source.backer.type.value}}}"
        )
    lines.append("")
    return "\n".join(lines)


def splice_into_sources(old_text: str, block_text: str) -> str:
    """Insert rendered source block(s) at the end of the top-level ``sources:``
    list, before any following top-level section (quotas/scoring/…). The seed
    file has sections after ``sources:``, so appending at EOF would be invalid
    YAML — this keeps the new entries inside the sources list.
    """
    lines = old_text.splitlines(keepends=True)
    insert_at = len(lines)
    seen_sources = False
    for i, line in enumerate(lines):
        if not seen_sources:
            if line.rstrip("\n") == "sources:":
                seen_sources = True
            continue
        # first non-indented, non-blank, non-comment line ends the sources block
        if line.strip() and not line[0].isspace() and not line.lstrip().startswith("#"):
            insert_at = i
            break
    head = "".join(lines[:insert_at]).rstrip("\n")
    tail = "".join(lines[insert_at:])
    spliced = head + "\n" + block_text.strip("\n") + "\n"
    return spliced + tail if tail else spliced
