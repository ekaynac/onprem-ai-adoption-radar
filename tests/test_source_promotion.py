"""Source-promotion gates, classifier, builder, serializer (pure)."""

from __future__ import annotations

from datetime import UTC, datetime

from radar.discovery.source_promotion import (
    MomentumStats,
    build_source,
    classify_category,
    has_sustained_momentum,
    is_promotable_source,
    momentum_stats,
    source_to_yaml_block,
    splice_into_sources,
)
from radar.discovery.trending_entities import Lane, TrendingObservation
from radar.models import Category
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


# ── splice (promote-time YAML surgery) ──────────────────────────────────────

def test_splice_inserts_before_trailing_section(tmp_path):
    old = ("version: \"1.0\"\nsources:\n"
           "  - id: github-cline\n    type: github_repo\n    enabled: true\n"
           "    project: Cline\n    category: coding_agents\n"
           "    url: https://github.com/cline/cline\n    tags: [coding-agent]\n"
           "quotas:\n  coding_agents: 4\n")
    source = build_source("acme/rocket", _sustained("acme/rocket"), existing_ids=set())
    assert source is not None

    spliced = splice_into_sources(old, source_to_yaml_block(source))
    seed = tmp_path / "seed.yaml"
    seed.write_text(spliced, encoding="utf-8")

    config = load_config(seed)  # must be valid YAML
    assert {s.id for s in config.sources} == {"github-cline", "github-rocket"}
    assert config.quotas.get("coding_agents") == 4  # trailing section survived


def test_splice_appends_when_sources_is_last_section(tmp_path):
    old = ("version: \"1.0\"\nsources:\n"
           "  - id: github-cline\n    type: github_repo\n    enabled: true\n"
           "    project: Cline\n    category: coding_agents\n"
           "    url: https://github.com/cline/cline\n    tags: [coding-agent]\n")
    source = build_source("acme/rocket", _sustained("acme/rocket"), existing_ids=set())
    assert source is not None
    spliced = splice_into_sources(old, source_to_yaml_block(source))
    seed = tmp_path / "seed.yaml"
    seed.write_text(spliced, encoding="utf-8")

    assert {s.id for s in load_config(seed).sources} == {"github-cline", "github-rocket"}
