"""Tests for the enrichment collectors (OSV, Hacker News, downloads)."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from radar.enrichment.downloads import fetch_weekly_downloads
from radar.enrichment.hackernews import fetch_hn_mentions
from radar.enrichment.osv import fetch_recent_advisories
from radar.enrichment.runner import run_enrichment
from radar.models import Category, EnrichmentConfig, PackageRef, SourceConfig, SourceType
from radar.storage.metrics_store import ProjectMetrics


NOW = datetime(2026, 6, 13, tzinfo=UTC)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload
        # When the payload is a plain string (e.g. Atom/XML), expose it via
        # .text so arXiv-style consumers can call response.text.  JSON routes
        # continue using .json() which returns the original object unchanged.
        self.text = payload if isinstance(payload, str) else ""

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeClient:
    """Maps URL substrings to payloads; records requested URLs."""

    def __init__(self, routes: dict[str, object]):
        self.routes = routes
        self.requests: list[tuple[str, str, object]] = []

    def _match(self, url: str):
        for fragment, payload in self.routes.items():
            if fragment in url:
                return payload
        raise AssertionError(f"Unexpected URL: {url}")

    async def get(self, url, params=None, **kwargs):
        self.requests.append(("GET", url, params))
        return FakeResponse(self._match(url))

    async def post(self, url, json=None, **kwargs):
        self.requests.append(("POST", url, json))
        return FakeResponse(self._match(url))


class FailingClient:
    async def get(self, url, **kwargs):
        raise RuntimeError("network down")

    async def post(self, url, **kwargs):
        raise RuntimeError("network down")


@pytest.mark.asyncio
async def test_osv_returns_recent_advisories_only():
    payload = {
        "vulns": [
            {  # recent, HIGH
                "id": "GHSA-recent",
                "modified": "2026-06-01T00:00:00Z",
                "summary": "RCE in parser",
                "database_specific": {"severity": "HIGH"},
            },
            {  # too old
                "id": "GHSA-ancient",
                "modified": "2024-01-01T00:00:00Z",
                "summary": "old bug",
                "database_specific": {"severity": "CRITICAL"},
            },
            {  # withdrawn
                "id": "GHSA-withdrawn",
                "modified": "2026-06-02T00:00:00Z",
                "withdrawn": "2026-06-03T00:00:00Z",
                "summary": "false alarm",
            },
        ]
    }
    client = FakeClient({"api.osv.dev/v1/query": payload})

    advisories = await fetch_recent_advisories(
        PackageRef(ecosystem="PyPI", name="vllm"), client, now=NOW, window_days=90
    )

    assert [a.id for a in advisories] == ["GHSA-recent"]
    assert advisories[0].severity == "HIGH"


@pytest.mark.asyncio
async def test_hn_mentions_counts_hits_with_quoted_query():
    client = FakeClient({"hn.algolia.com": {"nbHits": 12}})

    count = await fetch_hn_mentions("vLLM", client, since=datetime(2026, 6, 6, tzinfo=UTC))

    assert count == 12
    _method, _url, params = client.requests[0]
    assert params["query"] == '"vLLM"'
    assert "created_at_i>" in params["numericFilters"]


@pytest.mark.asyncio
async def test_downloads_pypi_and_npm():
    client = FakeClient(
        {
            "pypistats.org/api/packages/vllm/recent": {"data": {"last_week": 240_000}},
            "api.npmjs.org/downloads/point/last-week/foo": {"downloads": 9000},
        }
    )

    pypi = await fetch_weekly_downloads(PackageRef(ecosystem="PyPI", name="vllm"), client)
    npm = await fetch_weekly_downloads(PackageRef(ecosystem="npm", name="foo"), client)

    assert pypi == 240_000
    assert npm == 9000


@pytest.mark.asyncio
async def test_downloads_unknown_ecosystem_returns_none():
    assert await fetch_weekly_downloads(
        PackageRef(ecosystem="crates.io", name="x"), FakeClient({})
    ) is None


class _StatusResponse:
    def __init__(self, status_code, payload=None, retry_after=None):
        self.status_code = status_code
        self.payload = payload or {}
        self.headers = {"Retry-After": str(retry_after)} if retry_after else {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self.payload


class _SequenceClient:
    """Returns queued responses in order, recording how many GETs happened."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    async def get(self, url, **kwargs):
        self.calls += 1
        return self._responses.pop(0)


@pytest.mark.asyncio
async def test_downloads_retries_then_succeeds_on_429(monkeypatch):
    slept: list[float] = []

    async def fake_sleep(delay):
        slept.append(delay)

    monkeypatch.setattr("radar.enrichment.downloads.asyncio.sleep", fake_sleep)
    client = _SequenceClient(
        [
            _StatusResponse(429, retry_after=1),
            _StatusResponse(200, {"data": {"last_week": 12_345}}),
        ]
    )

    result = await fetch_weekly_downloads(PackageRef(ecosystem="PyPI", name="ray"), client)

    assert result == 12_345
    assert client.calls == 2
    assert slept == [1.0]  # honored Retry-After


@pytest.mark.asyncio
async def test_downloads_persistent_429_degrades_to_none(monkeypatch):
    async def fake_sleep(delay):
        return None

    monkeypatch.setattr("radar.enrichment.downloads.asyncio.sleep", fake_sleep)
    client = _SequenceClient([_StatusResponse(429) for _ in range(5)])

    # The final attempt raises via raise_for_status; the runner's _safe wrapper
    # is what turns that into None in production. Here we assert it raises so the
    # degradation contract is explicit.
    with pytest.raises(RuntimeError):
        await fetch_weekly_downloads(PackageRef(ecosystem="PyPI", name="ray"), client)

    # 1 initial + DOWNLOADS_MAX_RETRIES retries.
    assert client.calls == 4


@pytest.mark.asyncio
async def test_runner_merges_enrichment_into_metrics():
    sources = [
        SourceConfig(
            id="github-vllm",
            type=SourceType.GITHUB_REPO,
            project="vLLM",
            category=Category.MODEL_SERVING,
            url="https://github.com/vllm-project/vllm",
            package=PackageRef(ecosystem="PyPI", name="vllm"),
        )
    ]
    metrics = {
        "vLLM": ProjectMetrics(project="vLLM", run_id="run-1", observed_at=NOW, stars=100)
    }
    client = FakeClient(
        {
            "api.osv.dev/v1/query": {
                "vulns": [
                    {
                        "id": "GHSA-1",
                        "modified": "2026-06-01T00:00:00Z",
                        "database_specific": {"severity": "HIGH"},
                        "summary": "bad",
                    }
                ]
            },
            "hn.algolia.com": {"nbHits": 7},
            "pypistats.org": {"data": {"last_week": 1000}},
        }
    )

    result = await run_enrichment(
        EnrichmentConfig(),
        sources=sources,
        metrics=metrics,
        since=datetime(2026, 6, 6, tzinfo=UTC),
        now=NOW,
        client=client,
    )

    enriched = result.metrics["vLLM"]
    assert enriched.hn_mentions == 7
    assert enriched.downloads_weekly == 1000
    assert enriched.advisories_open == 1
    assert enriched.advisories_max_severity == "HIGH"
    assert [a.id for a in result.advisories["vLLM"]] == ["GHSA-1"]
    # Original input is not mutated (immutability).
    assert metrics["vLLM"].hn_mentions is None


@pytest.mark.asyncio
async def test_runner_respects_disable_flags():
    sources = [
        SourceConfig(
            id="github-vllm",
            type=SourceType.GITHUB_REPO,
            project="vLLM",
            category=Category.MODEL_SERVING,
            url="https://github.com/vllm-project/vllm",
            package=PackageRef(ecosystem="PyPI", name="vllm"),
        )
    ]
    metrics = {
        "vLLM": ProjectMetrics(project="vLLM", run_id="run-1", observed_at=NOW)
    }
    client = FakeClient({})  # any request would raise AssertionError

    result = await run_enrichment(
        EnrichmentConfig(osv=False, hackernews=False, downloads=False),
        sources=sources,
        metrics=metrics,
        since=NOW,
        now=NOW,
        client=client,
    )

    assert result.metrics["vLLM"].hn_mentions is None
    assert result.advisories == {}


@pytest.mark.asyncio
async def test_runner_degrades_gracefully_on_network_failure(caplog):
    import logging

    sources = [
        SourceConfig(
            id="github-vllm",
            type=SourceType.GITHUB_REPO,
            project="vLLM",
            category=Category.MODEL_SERVING,
            url="https://github.com/vllm-project/vllm",
            package=PackageRef(ecosystem="PyPI", name="vllm"),
        )
    ]
    metrics = {
        "vLLM": ProjectMetrics(project="vLLM", run_id="run-1", observed_at=NOW)
    }

    with caplog.at_level(logging.WARNING):
        result = await run_enrichment(
            EnrichmentConfig(),
            sources=sources,
            metrics=metrics,
            since=NOW,
            now=NOW,
            client=FailingClient(),
        )

    assert result.metrics["vLLM"].hn_mentions is None
    assert caplog.records  # failures logged, never raised


def test_package_ref_parses_from_config_yaml():
    source = SourceConfig.model_validate(
        json.loads(
            json.dumps(
                {
                    "id": "github-vllm",
                    "type": "github_repo",
                    "project": "vLLM",
                    "category": "model_serving",
                    "url": "https://github.com/vllm-project/vllm",
                    "package": {"ecosystem": "PyPI", "name": "vllm"},
                }
            )
        )
    )

    assert source.package is not None
    assert source.package.name == "vllm"


NOW2 = datetime(2026, 6, 19, tzinfo=UTC)
SINCE2 = datetime(2026, 6, 12, tzinfo=UTC)

ARXIV_ATOM = (
    '<feed xmlns="http://www.w3.org/2005/Atom">'
    '<entry><title>vLLM speedups</title><id>http://arxiv.org/abs/2506.9</id>'
    '<published>2026-06-15T00:00:00Z</published></entry></feed>'
)


def _src(sid, project, *, paper_query=None):
    return SourceConfig(id=sid, type=SourceType.GITHUB_REPO, project=project,
                        category=Category.MODEL_SERVING,
                        url=f"https://github.com/x/{sid}", paper_query=paper_query)


@pytest.mark.asyncio
async def test_arxiv_mentions_recorded_for_queried_projects():
    cfg = EnrichmentConfig(osv=False, hackernews=False, downloads=False, arxiv=True)
    sources = [_src("github-vllm", "vLLM", paper_query='"vLLM"')]
    metrics = {"vLLM": ProjectMetrics(project="vLLM", run_id="r1", observed_at=NOW2)}
    client = FakeClient({"export.arxiv.org": ARXIV_ATOM})  # FakeResponse must expose .text
    result = await run_enrichment(cfg, sources, metrics, since=SINCE2, now=NOW2, client=client)
    assert result.metrics["vLLM"].paper_mentions == 1
    assert result.papers["vLLM"][0].title == "vLLM speedups"


@pytest.mark.asyncio
async def test_arxiv_skipped_without_paper_query():
    cfg = EnrichmentConfig(osv=False, hackernews=False, downloads=False, arxiv=True)
    sources = [_src("github-ray", "Ray")]  # no paper_query
    metrics = {"Ray": ProjectMetrics(project="Ray", run_id="r1", observed_at=NOW2)}
    client = FakeClient({})  # any arXiv call would raise AssertionError (unexpected URL)
    result = await run_enrichment(cfg, sources, metrics, since=SINCE2, now=NOW2, client=client)
    assert result.metrics["Ray"].paper_mentions is None
    assert "Ray" not in result.papers
