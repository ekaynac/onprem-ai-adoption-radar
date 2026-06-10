from pathlib import Path

import pytest

from radar.models import Config, Ring, SourceType
from radar.storage.config import ConfigError, expand_env_vars, load_config


def test_expand_env_vars_replaces_set_values(monkeypatch):
    monkeypatch.setenv("TOKEN", "abc123")

    value = {"headers": ["Bearer ${TOKEN}"], "plain": "${MISSING}"}

    assert expand_env_vars(value) == {
        "headers": ["Bearer abc123"],
        "plain": "${MISSING}",
    }


def test_load_config_validates_yaml(tmp_path: Path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
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

    config = load_config(config_path)

    assert isinstance(config, Config)
    assert config.sources[0].id == "github-openclaw"
    assert config.sources[0].type == SourceType.GITHUB_REPO
    assert config.scoring.default_ring == Ring.WATCH


def test_load_config_reports_yaml_error(tmp_path: Path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("sources: [", encoding="utf-8")

    with pytest.raises(ConfigError) as exc:
        load_config(config_path)

    assert "Invalid YAML" in str(exc.value)


def test_load_config_reports_validation_error(tmp_path: Path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("version: '1.0'\nsources: []\n", encoding="utf-8")

    with pytest.raises(ConfigError) as exc:
        load_config(config_path)

    assert "Configuration validation failed" in str(exc.value)
