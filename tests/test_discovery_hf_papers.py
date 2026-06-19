# tests/test_discovery_hf_papers.py
import pytest

from radar.discovery.hf_papers import discover_from_hf_papers, map_category
from radar.models import Category, SourceConfig, SourceType


class FakeResp:
    def __init__(self, payload): self._p = payload
    def raise_for_status(self): return None
    def json(self): return self._p


class FakeClient:
    """Routes daily_papers JSON + per-repo GitHub lookups by URL substring."""
    def __init__(self, routes): self.routes = routes
    async def get(self, url, **kw):
        for frag, payload in self.routes.items():
            if frag in url:
                return FakeResp(payload)
        raise AssertionError(f"unexpected URL {url}")


DAILY = [
    {"paper": {"title": "Fast serving", "githubRepo": "https://github.com/acme/fastserve",
               "tags": ["model-serving"]}},
    {"paper": {"title": "No repo paper", "tags": ["nlp"]}},               # skipped: no repo
    {"paper": {"title": "Tracked already", "githubRepo": "https://github.com/vllm-project/vllm"}},
]
REPO = {"stargazers_count": 1200, "description": "fast", "topics": ["llm", "serving"],
        "full_name": "acme/fastserve", "name": "fastserve", "html_url": "https://github.com/acme/fastserve"}


def _tracked():
    return [SourceConfig(id="github-vllm", type=SourceType.GITHUB_REPO, project="vLLM",
                         category=Category.MODEL_SERVING, url="https://github.com/vllm-project/vllm")]


@pytest.mark.asyncio
async def test_proposes_repo_linked_paper_above_floor():
    client = FakeClient({"daily_papers": DAILY, "api.github.com/repos": REPO})
    proposals = await discover_from_hf_papers(_tracked(), client, min_stars=500)
    assert [p.suggested_id for p in proposals] == ["github-fastserve"]
    assert proposals[0].stars == 1200
    assert proposals[0].category == Category.MODEL_SERVING


@pytest.mark.asyncio
async def test_below_floor_is_dropped():
    low = dict(REPO, stargazers_count=10)
    client = FakeClient({"daily_papers": DAILY, "api.github.com/repos": low})
    assert await discover_from_hf_papers(_tracked(), client, min_stars=500) == []


def test_map_category_falls_back_to_triage():
    _cat, triage = map_category(["totally-unknown-topic"])
    assert triage is True
    cat2, triage2 = map_category(["mcp-server"])
    assert cat2 == Category.MCP_TOOLING and triage2 is False
