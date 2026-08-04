"""Sweep public leaderboards into benchmark observations (config-driven).

Three adapters, one sweep: the Open LLM Leaderboard (joined by
``hf_repo``), the Aider polyglot leaderboard (YAML, joined by explicit
display-name aliases), and LiveBench (CSV, alias-joined). A source that
fails degrades to an ``error`` outcome without aborting the others; a
model whose expected alias vanished from a source lands on that source's
skipped list and drops its health to ``partial`` — never silent.
"""

from __future__ import annotations

import asyncio
import csv
import io
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from radar.models_radar.benchmarks import CANONICAL_BENCHMARKS, normalize_score
from radar.models_radar.entities import ModelSeed
from radar.storage.benchmark_observations_log import BenchmarkObservation


logger = logging.getLogger(__name__)

OPENLLM_FILTER_CONCURRENCY = 8


class BenchmarkSourceConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    kind: Literal["hf-datasets-filter", "yaml-rows", "csv"]
    enabled: bool
    join: Literal["hf_repo", "alias"]
    url: str
    row_key: str | None = None
    column_map: dict[str, str]
    aliases: dict[str, list[str]] = Field(default_factory=dict)

    @field_validator("column_map")
    @classmethod
    def _canonical_keys_only(cls, value: dict[str, str]) -> dict[str, str]:
        unknown = sorted(set(value.values()) - set(CANONICAL_BENCHMARKS))
        if unknown:
            raise ValueError(
                f"column_map targets unknown canonical keys: {unknown}"
            )
        return value


class BenchmarkSourcesConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str
    triangulation_gap_points: float
    sources: list[BenchmarkSourceConfig]


def load_benchmark_sources(path: Path) -> BenchmarkSourcesConfig:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return BenchmarkSourcesConfig.model_validate(payload)


@dataclass
class BenchmarkSweepResult:
    observations: list[BenchmarkObservation] = field(default_factory=list)
    outcomes: dict[str, dict[str, Any]] = field(default_factory=dict)
    skipped: dict[str, list[str]] = field(default_factory=dict)


def _score_value(raw: Any) -> float | None:
    if isinstance(raw, bool) or raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value != value:  # NaN
        return None
    return value


def _emit_row(
    row: dict[str, Any],
    source: BenchmarkSourceConfig,
    model_id: str,
    hf_repo: str | None,
    now: datetime,
) -> list[BenchmarkObservation]:
    observations = []
    for column, canonical in source.column_map.items():
        value = _score_value(row.get(column))
        if value is None:
            continue
        observations.append(
            BenchmarkObservation(
                model_id=model_id,
                hf_repo=hf_repo,
                benchmark=canonical,
                score=normalize_score(canonical, value),
                source_id=source.id,
                source_url=source.url,
                observed_at=now,
            )
        )
    return observations


async def _fetch_openllm(
    seeds: list[ModelSeed],
    source: BenchmarkSourceConfig,
    client: Any,
    now: datetime,
    health: dict[str, int],
) -> list[BenchmarkObservation]:
    from urllib.parse import parse_qsl, urlsplit

    tracked = [seed for seed in seeds if seed.hf_repo]
    semaphore = asyncio.Semaphore(OPENLLM_FILTER_CONCURRENCY)
    # httpx `params=` REPLACES any query string already in the URL, so the
    # dataset/config/split parameters must be re-merged explicitly.
    split_url = urlsplit(source.url)
    base_url = source.url.split("?", 1)[0]
    base_params = dict(parse_qsl(split_url.query))

    async def fetch_one(seed: ModelSeed) -> list[BenchmarkObservation]:
        where = f"\"fullname\"='{seed.hf_repo}'"
        async with semaphore:
            health["requests"] = health.get("requests", 0) + 1
            try:
                response = await client.get(
                    base_url,
                    params={
                        **base_params,
                        "where": where,
                        "offset": 0,
                        "length": 5,
                    },
                )
                response.raise_for_status()
                payload = response.json()
            except Exception as exc:
                health["failures"] = health.get("failures", 0) + 1
                logger.warning(
                    "OLLB fetch failed for %s: %s", seed.hf_repo, exc
                )
                return []
        rows = payload.get("rows") if isinstance(payload, dict) else None
        if not isinstance(rows, list) or not rows:
            # Absence is expected (the leaderboard lags new models); it is
            # neither a failure nor an observation.
            return []
        row = rows[0].get("row") if isinstance(rows[0], dict) else None
        if not isinstance(row, dict):
            return []
        return _emit_row(row, source, seed.id, seed.hf_repo, now)

    batches = await asyncio.gather(*(fetch_one(seed) for seed in tracked))
    return [observation for batch in batches for observation in batch]


def _alias_index(source: BenchmarkSourceConfig) -> dict[str, str]:
    index: dict[str, str] = {}
    for model_id, names in source.aliases.items():
        for name in names:
            index[name] = model_id
    return index


def _match_alias_rows(
    rows: list[dict[str, Any]],
    source: BenchmarkSourceConfig,
    seeds_by_id: dict[str, ModelSeed],
    now: datetime,
) -> tuple[list[BenchmarkObservation], list[str]]:
    alias_to_model = _alias_index(source)
    row_key = source.row_key or "model"
    observations: list[BenchmarkObservation] = []
    matched: set[str] = set()
    for row in rows:
        name = row.get(row_key)
        model_id = alias_to_model.get(str(name)) if name is not None else None
        if model_id is None:
            continue
        matched.add(model_id)
        seed = seeds_by_id.get(model_id)
        observations.extend(
            _emit_row(
                row,
                source,
                model_id,
                seed.hf_repo if seed else None,
                now,
            )
        )
    skipped = sorted(set(source.aliases) - matched)
    return observations, skipped


async def sweep_benchmarks(
    seeds: list[ModelSeed],
    config: BenchmarkSourcesConfig,
    client: Any,
    now: datetime,
) -> BenchmarkSweepResult:
    result = BenchmarkSweepResult()
    seeds_by_id = {seed.id: seed for seed in seeds}
    for source in config.sources:
        if not source.enabled:
            continue
        try:
            if source.kind == "hf-datasets-filter":
                health: dict[str, int] = {}
                observations = await _fetch_openllm(
                    seeds, source, client, now, health
                )
                failures = health.get("failures", 0)
                requests = health.get("requests", 0)
                status = (
                    "ok"
                    if failures == 0
                    else ("error" if failures == requests else "partial")
                )
                result.outcomes[source.id] = {
                    "count": len(observations),
                    "status": status,
                }
                result.observations.extend(observations)
                continue

            response = await client.get(source.url)
            response.raise_for_status()
            if source.kind == "yaml-rows":
                rows = yaml.safe_load(response.text)
            else:
                rows = list(csv.DictReader(io.StringIO(response.text)))
            if not isinstance(rows, list):
                raise ValueError(f"{source.id}: expected a list of rows")
            observations, skipped = _match_alias_rows(
                [row for row in rows if isinstance(row, dict)],
                source,
                seeds_by_id,
                now,
            )
            result.observations.extend(observations)
            if skipped:
                result.skipped[source.id] = skipped
            result.outcomes[source.id] = {
                "count": len(observations),
                "status": "partial" if skipped else "ok",
            }
        except Exception as exc:
            logger.warning("Benchmark source %s failed: %s", source.id, exc)
            result.outcomes[source.id] = {"count": 0, "status": "error"}
    return result
