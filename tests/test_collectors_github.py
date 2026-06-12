import json
from datetime import datetime, timezone
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

    signals = await collector.fetch(datetime(2026, 6, 9, tzinfo=timezone.utc))

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
