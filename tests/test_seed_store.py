"""Tests for seed (source) management: the shared core behind CLI and UI."""

from __future__ import annotations

from pathlib import Path

import pytest

from radar.models import Category, SourceConfig, SourceType
from radar.storage.config import load_config
from radar.storage.seed_store import SeedError, add_seed, add_source, save_config


def _write_config(path: Path) -> None:
    path.write_text(
        """
version: "1.0"
sources:
  - id: github-openclaw
    type: github_repo
    enabled: true
    project: OpenClaw
    category: general_agents
    url: https://github.com/openclaw/openclaw
    tags: [general-agent, open-source]
quotas:
  coding_agents: 4
scoring:
  default_ring: watch
""",
        encoding="utf-8",
    )


def _source(**overrides) -> SourceConfig:
    base = dict(
        id="rss-new-feed",
        type=SourceType.RSS,
        enabled=True,
        project="New Feed",
        category=Category.MODEL_SERVING,
        url="https://example.com/feed.xml",
        tags=["vendor-blog"],
    )
    base.update(overrides)
    return SourceConfig(**base)


# ── add_source: pure, immutable ───────────────────────────────────────────────


def test_add_source_returns_new_config_without_mutating_original(tmp_path: Path):
    cfg_path = tmp_path / "config.yaml"
    _write_config(cfg_path)
    config = load_config(cfg_path)

    updated = add_source(config, _source())

    assert len(config.sources) == 1  # original untouched
    assert len(updated.sources) == 2
    assert updated.sources[-1].id == "rss-new-feed"
    assert config is not updated


def test_add_source_rejects_duplicate_id(tmp_path: Path):
    cfg_path = tmp_path / "config.yaml"
    _write_config(cfg_path)
    config = load_config(cfg_path)

    with pytest.raises(SeedError) as exc:
        add_source(config, _source(id="github-openclaw"))

    assert "already exists" in str(exc.value)


# ── save_config + round-trip ──────────────────────────────────────────────────


def test_save_config_round_trips_through_load(tmp_path: Path):
    cfg_path = tmp_path / "config.yaml"
    _write_config(cfg_path)
    config = load_config(cfg_path)

    updated = add_source(config, _source())
    save_config(updated, cfg_path)
    reloaded = load_config(cfg_path)

    assert {s.id for s in reloaded.sources} == {"github-openclaw", "rss-new-feed"}
    assert reloaded.sources[-1].type == SourceType.RSS


# ── add_seed: load -> validate -> add -> persist (the boundary API) ────────────


def test_add_seed_persists_and_returns_added_source(tmp_path: Path):
    cfg_path = tmp_path / "config.yaml"
    _write_config(cfg_path)

    added = add_seed(
        cfg_path,
        {
            "id": "rss-nvidia",
            "type": "rss",
            "project": "NVIDIA Dev Blog",
            "category": "ai_infrastructure",
            "url": "https://developer.nvidia.com/blog/feed/",
            "tags": ["vendor-blog"],
        },
    )

    assert added.id == "rss-nvidia"
    reloaded = load_config(cfg_path)
    assert any(s.id == "rss-nvidia" for s in reloaded.sources)


def test_add_seed_rejects_invalid_input(tmp_path: Path):
    cfg_path = tmp_path / "config.yaml"
    _write_config(cfg_path)

    with pytest.raises(SeedError):
        add_seed(
            cfg_path,
            {
                "id": "bad",
                "type": "not_a_real_type",
                "project": "X",
                "category": "model_serving",
                "url": "https://example.com/feed.xml",
            },
        )

    # config must be unchanged on failure
    assert len(load_config(cfg_path).sources) == 1
