from __future__ import annotations

from datetime import UTC, datetime

import pytest

from radar.discovery.benchmark_sweep import (
    BenchmarkSourceConfig,
    BenchmarkSourcesConfig,
    load_benchmark_sources,
    sweep_benchmarks,
)
from radar.models_radar.entities import ModelSeed


NOW = datetime(2026, 8, 4, 9, tzinfo=UTC)

SEEDS = [
    ModelSeed(id="qwen3-32b", name="Qwen3-32B", family="Qwen3", hf_repo="Qwen/Qwen3-32B"),
    ModelSeed(id="deepseek-r1", name="DeepSeek R1", family="DeepSeek", hf_repo="deepseek-ai/DeepSeek-R1"),
    ModelSeed(id="no-repo-model", name="No Repo", family="Test"),
]


def ollb_source(**overrides) -> BenchmarkSourceConfig:
    values = {
        "id": "open-llm-leaderboard",
        "kind": "hf-datasets-filter",
        "enabled": True,
        "join": "hf_repo",
        "url": "https://datasets-server.example/filter",
        "column_map": {"MMLU-PRO": "mmlu-pro", "IFEval": "ifeval"},
    }
    values.update(overrides)
    return BenchmarkSourceConfig.model_validate(values)


def aider_source(**overrides) -> BenchmarkSourceConfig:
    values = {
        "id": "aider-polyglot",
        "kind": "yaml-rows",
        "enabled": True,
        "join": "alias",
        "url": "https://aider.example/leaderboard.yml",
        "row_key": "model",
        "column_map": {"pass_rate_2": "aider-polyglot"},
        "aliases": {"deepseek-r1": ["DeepSeek R1"], "qwen3-32b": ["Qwen3 32B"]},
    }
    values.update(overrides)
    return BenchmarkSourceConfig.model_validate(values)


def config_for(*sources) -> BenchmarkSourcesConfig:
    return BenchmarkSourcesConfig(
        version="1.0",
        triangulation_gap_points=5.0,
        sources=list(sources),
    )


class _Resp:
    def __init__(self, payload=None, text: str = ""):
        self._payload = payload
        self.text = text

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _Client:
    """Routes by URL substring; can fail requests matching fail_substr."""

    def __init__(self, routes: dict[str, _Resp], fail_substr: str | None = None):
        self.routes = routes
        self.fail_substr = fail_substr
        self.calls: list[tuple[str, dict]] = []

    async def get(self, url: str, **kwargs):
        self.calls.append((url, kwargs.get("params") or {}))
        if self.fail_substr and self.fail_substr in url:
            raise RuntimeError("boom")
        for substr, response in self.routes.items():
            if substr in url:
                return response
        raise AssertionError(f"Unrouted url: {url}")


def ollb_row(repo: str, mmlu_pro: float) -> dict:
    return {"rows": [{"row": {"fullname": repo, "MMLU-PRO": mmlu_pro, "IFEval": None}}]}


@pytest.mark.asyncio
async def test_openllm_joins_by_hf_repo_and_skips_absent_models() -> None:
    client = _Client({"datasets-server.example": _Resp(payload=ollb_row("Qwen/Qwen3-32B", 63.2))})

    class _PerRepoClient(_Client):
        async def get(self, url: str, **kwargs):
            params = kwargs.get("params") or {}
            self.calls.append((url, params))
            if "Qwen3-32B" in params.get("where", ""):
                return _Resp(payload=ollb_row("Qwen/Qwen3-32B", 63.2))
            return _Resp(payload={"rows": []})  # absent from the leaderboard

    client = _PerRepoClient({})
    result = await sweep_benchmarks(SEEDS, config_for(ollb_source()), client, NOW)

    assert [obs.model_id for obs in result.observations] == ["qwen3-32b"]
    observation = result.observations[0]
    assert observation.benchmark == "mmlu-pro"
    assert observation.score == 63.2
    assert observation.hf_repo == "Qwen/Qwen3-32B"
    # None cells skipped per-cell; absence (deepseek) is not a failure.
    assert result.outcomes["open-llm-leaderboard"] == {"count": 1, "status": "ok"}
    # Seeds without hf_repo are never queried.
    assert all("no-repo" not in str(call) for call in client.calls)


@pytest.mark.asyncio
async def test_alias_join_flags_missing_expected_models_as_partial() -> None:
    yaml_text = "- model: DeepSeek R1\n  pass_rate_2: 56.9\n- model: Untracked Thing\n  pass_rate_2: 10\n"
    client = _Client({"aider.example": _Resp(text=yaml_text)})

    result = await sweep_benchmarks(SEEDS, config_for(aider_source()), client, NOW)

    assert [obs.model_id for obs in result.observations] == ["deepseek-r1"]
    assert result.observations[0].benchmark == "aider-polyglot"
    assert result.observations[0].score == 56.9
    # qwen3-32b was expected via aliases but absent → visible, partial.
    assert result.skipped["aider-polyglot"] == ["qwen3-32b"]
    assert result.outcomes["aider-polyglot"]["status"] == "partial"


@pytest.mark.asyncio
async def test_csv_source_and_one_source_down_does_not_abort_sweep() -> None:
    csv_text = "model,code_generation,code_completion\ndeepseek-r1,52.5,41.0\n"
    livebench = BenchmarkSourceConfig.model_validate(
        {
            "id": "livebench",
            "kind": "csv",
            "enabled": True,
            "join": "alias",
            "url": "https://livebench.example/table.csv",
            "row_key": "model",
            "column_map": {"code_generation": "livebench-coding"},
            "aliases": {"deepseek-r1": ["deepseek-r1"]},
        }
    )
    client = _Client(
        {"livebench.example": _Resp(text=csv_text)},
        fail_substr="aider.example",
    )

    result = await sweep_benchmarks(
        SEEDS,
        config_for(aider_source(), livebench),
        client,
        NOW,
    )

    assert result.outcomes["aider-polyglot"] == {"count": 0, "status": "error"}
    assert result.outcomes["livebench"] == {"count": 1, "status": "ok"}
    assert result.observations[0].benchmark == "livebench-coding"
    assert result.observations[0].score == 52.5


@pytest.mark.asyncio
async def test_disabled_source_is_never_fetched() -> None:
    client = _Client({})

    result = await sweep_benchmarks(
        SEEDS,
        config_for(aider_source(enabled=False)),
        client,
        NOW,
    )

    assert client.calls == []
    assert result.outcomes == {}


def test_config_loader_rejects_unknown_canonical_key(tmp_path) -> None:
    path = tmp_path / "benchmark-sources.yaml"
    path.write_text(
        """
version: "1.0"
triangulation_gap_points: 5.0
sources:
  - id: bad
    kind: csv
    enabled: true
    join: alias
    url: "https://x.example"
    column_map: {col: not-a-real-benchmark}
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unknown canonical keys"):
        load_benchmark_sources(path)


def test_cli_scan_writes_store_and_source_health(tmp_path, monkeypatch) -> None:
    import shutil
    from pathlib import Path as _Path

    from typer.testing import CliRunner

    from radar.cli import app
    from radar.storage.benchmark_observations_log import (
        load_benchmark_observations,
    )
    from radar.storage.source_health_log import load_source_health

    (tmp_path / "config").mkdir()
    shutil.copy2("config/model-seed.yaml", tmp_path / "config" / "model-seed.yaml")
    (tmp_path / "config" / "benchmark-sources.yaml").write_text(
        """
version: "1.0"
triangulation_gap_points: 5.0
sources:
  - id: aider-polyglot
    kind: yaml-rows
    enabled: true
    join: alias
    url: "https://aider.example/leaderboard.yml"
    row_key: model
    column_map: {pass_rate_2: aider-polyglot}
    aliases: {deepseek-r1: ["DeepSeek R1"]}
""",
        encoding="utf-8",
    )

    yaml_text = "- model: DeepSeek R1\n  pass_rate_2: 56.9\n"

    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return _Client({"aider.example": _Resp(text=yaml_text)})

        async def __aexit__(self, *exc):
            return False

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)

    result = CliRunner().invoke(
        app, ["models", "benchmarks", "scan", "--root", str(tmp_path)]
    )

    assert result.exit_code == 0, result.output
    observations = load_benchmark_observations(
        _Path(tmp_path) / "data" / "benchmark-observations.jsonl"
    )
    assert [obs.benchmark for obs in observations] == ["aider-polyglot"]
    health = load_source_health(_Path(tmp_path) / "data" / "source-health.jsonl")
    assert "benchmarks:aider-polyglot" in health[-1].sources
    assert health[-1].sources["benchmarks:aider-polyglot"].status == "ok"


def test_repo_config_file_loads_and_targets_canonical_keys() -> None:
    from pathlib import Path

    config = load_benchmark_sources(Path("config/benchmark-sources.yaml"))

    assert {source.id for source in config.sources} == {
        "open-llm-leaderboard",
        "aider-polyglot",
        "livebench",
    }
    assert all(source.enabled for source in config.sources)
