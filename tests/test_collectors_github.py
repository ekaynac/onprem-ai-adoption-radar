import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from radar.collectors.github import GitHubCollector
from radar.models import Category, SourceConfig, SourceType


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeClient:
    def __init__(self, payload):
        self.payload = payload
        self.urls = []

    async def get(self, url, headers=None, follow_redirects=True):
        self.urls.append(url)
        if isinstance(self.payload, dict):
            return FakeResponse(self.payload[url])
        return FakeResponse(self.payload)


@pytest.mark.asyncio
async def test_github_collector_fetches_repo_releases():
    payload = json.loads(Path("tests/fixtures/github_releases.json").read_text())
    source = SourceConfig(
        id="github-openclaw",
        type=SourceType.GITHUB_REPO,
        enabled=True,
        project="OpenClaw",
        category=Category.GENERAL_AGENTS,
        url="https://github.com/openclaw/openclaw",
        tags=["general-agent"],
    )
    repo_payload = {
        "html_url": "https://github.com/openclaw/openclaw",
        "stargazers_count": 1200,
        "forks_count": 80,
        "open_issues_count": 12,
        "pushed_at": "2026-06-11T08:00:00Z",
        "license": {"spdx_id": "MIT"},
        "topics": ["agents", "mcp", "self-hosted"],
    }
    client = FakeClient(
        {
            "https://api.github.com/repos/openclaw/openclaw": repo_payload,
            "https://api.github.com/repos/openclaw/openclaw/releases?per_page=10": payload,
        }
    )
    collector = GitHubCollector([source], client=client)

    signals = await collector.fetch(datetime(2026, 6, 9, tzinfo=UTC))

    assert len(signals) == 2
    snapshot = next(signal for signal in signals if signal.signal_type == "github_repo_snapshot")
    release = next(signal for signal in signals if signal.signal_type == "github_release")
    assert release.id == "github:github-openclaw:release:101"
    assert release.project == "OpenClaw"
    assert release.title == "OpenClaw released v1.2.3"
    assert release.metadata["tag"] == "v1.2.3"
    assert release.metadata["release_highlights"] == [
        "CLI onboarding and plugin list improvements."
    ]
    assert release.metadata["repo_snapshot"]["stars"] == 1200
    assert snapshot.metadata["license"] == "MIT"
    assert snapshot.metadata["topics"] == ["agents", "mcp", "self-hosted"]
    assert client.urls == [
        "https://api.github.com/repos/openclaw/openclaw",
        "https://api.github.com/repos/openclaw/openclaw/releases?per_page=10",
    ]


def test_release_highlights_strip_markdown_noise():
    body = """
## What's Changed
* Added local provider routing for Ollama and LM Studio.
* Fixed audit logging for tool calls.

### Full Changelog
https://github.com/example/project/compare/v1...v2
"""

    highlights = GitHubCollector.extract_release_highlights(body)

    assert highlights == [
        "Added local provider routing for Ollama and LM Studio.",
        "Fixed audit logging for tool calls.",
    ]


def test_release_highlights_drop_inline_full_changelog_and_urls():
    body = """Fixed - Complete provider fix for local Node runtime. **Full Changelog**: https://github.com/example/project/compare/v1...v2"""

    highlights = GitHubCollector.extract_release_highlights(body)

    assert highlights == ["Fixed - Complete provider fix for local Node runtime."]


@pytest.mark.asyncio
async def test_draft_and_malformed_releases_are_skipped_not_fatal():
    """Draft releases (null published_at), bad dates, and missing keys must not
    crash the collector — valid releases in the same payload still come through."""
    releases = [
        {  # draft release: GitHub returns null published_at
            "id": 1,
            "tag_name": "v9.9.9-draft",
            "html_url": "https://github.com/openclaw/openclaw/releases/tag/v9.9.9",
            "published_at": None,
            "body": "draft notes",
        },
        {  # malformed timestamp
            "id": 2,
            "tag_name": "v0.0.1",
            "html_url": "https://github.com/openclaw/openclaw/releases/tag/v0.0.1",
            "published_at": "not-a-date",
            "body": "",
        },
        {"published_at": "2026-06-10T00:00:00Z"},  # missing id/tag/html_url
        {  # the one valid release
            "id": 42,
            "tag_name": "v1.0.0",
            "html_url": "https://github.com/openclaw/openclaw/releases/tag/v1.0.0",
            "published_at": "2026-06-10T12:00:00Z",
            "body": "* Good release.",
        },
    ]
    repo_payload = {
        "html_url": "https://github.com/openclaw/openclaw",
        "stargazers_count": 10,
        "forks_count": 1,
        "open_issues_count": 0,
        "pushed_at": "2026-06-11T08:00:00Z",
        "license": {"spdx_id": "MIT"},
    }
    source = SourceConfig(
        id="github-openclaw",
        type=SourceType.GITHUB_REPO,
        enabled=True,
        project="OpenClaw",
        category=Category.GENERAL_AGENTS,
        url="https://github.com/openclaw/openclaw",
    )
    client = FakeClient(
        {
            "https://api.github.com/repos/openclaw/openclaw": repo_payload,
            "https://api.github.com/repos/openclaw/openclaw/releases?per_page=10": releases,
        }
    )

    signals = await GitHubCollector([source], client=client).fetch(
        datetime(2026, 6, 9, tzinfo=UTC)
    )

    release_signals = [s for s in signals if s.signal_type == "github_release"]
    assert [s.metadata["tag"] for s in release_signals] == ["v1.0.0"]


@pytest.mark.asyncio
async def test_malformed_pushed_at_does_not_crash_snapshot():
    repo_payload = {
        "html_url": "https://github.com/openclaw/openclaw",
        "stargazers_count": 10,
        "forks_count": 1,
        "open_issues_count": 0,
        "pushed_at": "garbage-timestamp",
        "license": {"spdx_id": "MIT"},
    }
    source = SourceConfig(
        id="github-openclaw",
        type=SourceType.GITHUB_REPO,
        enabled=True,
        project="OpenClaw",
        category=Category.GENERAL_AGENTS,
        url="https://github.com/openclaw/openclaw",
    )
    client = FakeClient(
        {
            "https://api.github.com/repos/openclaw/openclaw": repo_payload,
            "https://api.github.com/repos/openclaw/openclaw/releases?per_page=10": [],
        }
    )

    signals = await GitHubCollector([source], client=client).fetch(
        datetime(2026, 6, 9, tzinfo=UTC)
    )

    snapshot = next(s for s in signals if s.signal_type == "github_repo_snapshot")
    assert snapshot.project == "OpenClaw"


def test_release_highlights_drop_html_comments():
    body = """<!-- Release notes generated using configuration in .github/release.yml at v2-main -->

## What's Changed
* Real improvement to the local runtime.
"""

    highlights = GitHubCollector.extract_release_highlights(body)

    assert highlights == ["Real improvement to the local runtime."]


def test_release_highlights_keep_markdown_link_text():
    body = "* For details see the [release notes](https://example.com/notes) and the [Upgrade Guide](https://example.com/upgrade)."

    highlights = GitHubCollector.extract_release_highlights(body)

    assert highlights == ["For details see the release notes and the Upgrade Guide."]


def test_release_highlights_drop_pr_attribution_trailers():
    body = "* fix: include JSON instructions in followup prompt by @SomeUser in https://github.com/org/repo/pull/123"

    highlights = GitHubCollector.extract_release_highlights(body)

    assert highlights == ["fix: include JSON instructions in followup prompt"]


def test_release_highlights_drop_bot_attribution_trailers():
    body = "* chore: refresh npm lockfile after v0.5.5 by @github-actions[bot] in https://github.com/org/repo/pull/9"

    highlights = GitHubCollector.extract_release_highlights(body)

    assert highlights == ["chore: refresh npm lockfile after v0.5.5"]
