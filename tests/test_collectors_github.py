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
    client = FakeClient(payload)
    collector = GitHubCollector([source], client=client)

    signals = await collector.fetch(datetime(2026, 6, 9, tzinfo=timezone.utc))

    assert len(signals) == 1
    assert signals[0].id == "github:github-openclaw:release:101"
    assert signals[0].project == "OpenClaw"
    assert signals[0].title == "OpenClaw released v1.2.3"
    assert signals[0].metadata["tag"] == "v1.2.3"
    assert client.urls == [
        "https://api.github.com/repos/openclaw/openclaw/releases?per_page=10"
    ]
