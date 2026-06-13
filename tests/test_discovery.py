"""Tests for GitHub trending auto-discovery of candidate seed sources."""

from __future__ import annotations

from pathlib import Path

import pytest

from radar.discovery.github_trending import discover_trending
from radar.discovery.proposals import SeedProposal, load_proposals, write_proposals
from radar.models import Category, SourceConfig, SourceType


def _source(id_: str, url: str) -> SourceConfig:
    return SourceConfig(
        id=id_, type=SourceType.GITHUB_REPO, project=id_,
        category=Category.CODING_AGENTS, url=url,
    )


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeClient:
    """Returns repo items per query; records the queries it saw."""

    def __init__(self, items_by_topic: dict[str, list[dict]]):
        self.items_by_topic = items_by_topic
        self.queries: list[str] = []

    async def get(self, url, params=None, headers=None, **kwargs):
        query = params["q"]
        self.queries.append(query)
        # Find which topic this query targets.
        for topic, items in self.items_by_topic.items():
            if f"topic:{topic}" in query:
                return FakeResponse({"items": items})
        return FakeResponse({"items": []})


def _repo(name: str, full_name: str, stars: int) -> dict:
    return {
        "name": name,
        "full_name": full_name,
        "html_url": f"https://github.com/{full_name}",
        "stargazers_count": stars,
        "description": f"{name} description",
        "topics": ["agent"],
    }


@pytest.mark.asyncio
async def test_discovers_untracked_repos_above_min_stars():
    tracked = [_source("github-cline", "https://github.com/cline/cline")]
    client = FakeClient(
        {
            "ai-agents": [
                _repo("cline", "cline/cline", 5000),  # already tracked -> excluded
                _repo("newagent", "acme/newagent", 1200),  # new -> proposed
                _repo("tiny", "acme/tiny", 50),  # below min stars -> excluded
            ]
        }
    )

    proposals = await discover_trending(
        tracked,
        client,
        categories=[Category.CODING_AGENTS],
        min_stars=500,
        since_days=30,
        topics_by_category={Category.CODING_AGENTS: ["ai-agents"]},
    )

    names = [p.project for p in proposals]
    assert "newagent" in names
    assert "cline" not in names  # already tracked
    assert "tiny" not in names  # below threshold


@pytest.mark.asyncio
async def test_proposals_are_deduped_across_topics():
    client = FakeClient(
        {
            "ai-agents": [_repo("dup", "acme/dup", 900)],
            "llm": [_repo("dup", "acme/dup", 900)],
        }
    )

    proposals = await discover_trending(
        [],
        client,
        categories=[Category.CODING_AGENTS],
        min_stars=500,
        since_days=30,
        topics_by_category={Category.CODING_AGENTS: ["ai-agents", "llm"]},
    )

    assert [p.url for p in proposals].count("https://github.com/acme/dup") == 1


@pytest.mark.asyncio
async def test_proposals_sorted_by_stars_desc():
    client = FakeClient(
        {"ai-agents": [_repo("small", "a/small", 600), _repo("big", "a/big", 9000)]}
    )

    proposals = await discover_trending(
        [],
        client,
        categories=[Category.CODING_AGENTS],
        min_stars=500,
        since_days=30,
        topics_by_category={Category.CODING_AGENTS: ["ai-agents"]},
    )

    assert [p.project for p in proposals] == ["big", "small"]


@pytest.mark.asyncio
async def test_discovery_degrades_on_failure(caplog):
    import logging

    class FailingClient:
        async def get(self, *a, **k):
            raise RuntimeError("rate limited")

    with caplog.at_level(logging.WARNING):
        proposals = await discover_trending(
            [],
            FailingClient(),
            categories=[Category.CODING_AGENTS],
            min_stars=500,
            since_days=30,
            topics_by_category={Category.CODING_AGENTS: ["ai-agents"]},
        )

    assert proposals == []
    assert caplog.records


def test_write_and_load_proposals_round_trip(tmp_path: Path):
    path = tmp_path / "proposed-seeds.yaml"
    proposals = [
        SeedProposal(
            project="newagent",
            category=Category.CODING_AGENTS,
            url="https://github.com/acme/newagent",
            stars=1200,
            description="A new agent",
            suggested_id="github-newagent",
            suggested_tags=["agent"],
        )
    ]

    write_proposals(path, proposals)
    loaded = load_proposals(path)

    assert loaded[0].project == "newagent"
    assert loaded[0].suggested_id == "github-newagent"


def test_load_missing_proposals_file_is_empty(tmp_path: Path):
    assert load_proposals(tmp_path / "nope.yaml") == []


def test_discover_cli_writes_proposals(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    import radar.cli as cli_module
    from radar.init_project import initialize_project

    initialize_project(tmp_path)

    async def fake_discover(*args, **kwargs):
        return [
            SeedProposal(
                project="newagent",
                category=Category.CODING_AGENTS,
                url="https://github.com/acme/newagent",
                stars=1200,
                suggested_id="github-newagent",
            )
        ]

    monkeypatch.setattr(
        "radar.discovery.github_trending.discover_trending", fake_discover
    )

    runner = CliRunner()
    result = runner.invoke(
        cli_module.app, ["discover", "--root", str(tmp_path), "--category", "coding_agents"]
    )

    assert result.exit_code == 0, result.stdout
    assert "newagent" in result.stdout
    proposals = load_proposals(tmp_path / "data" / "proposed-seeds.yaml")
    assert proposals[0].project == "newagent"


def test_discover_cli_unknown_category_errors(tmp_path):
    from typer.testing import CliRunner

    import radar.cli as cli_module
    from radar.init_project import initialize_project

    initialize_project(tmp_path)
    runner = CliRunner()

    result = runner.invoke(
        cli_module.app, ["discover", "--root", str(tmp_path), "--category", "nope"]
    )

    assert result.exit_code != 0
    assert "Unknown category" in result.stdout
