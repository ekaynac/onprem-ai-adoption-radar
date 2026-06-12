from pathlib import Path

import pytest

from radar.models import Category, Config, Ring, SourceType
from radar.storage.config import ConfigError, expand_env_vars, load_config

_REPO_ROOT = Path(__file__).resolve().parents[1]


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


@pytest.mark.parametrize(
    "config_text",
    [
        """
version: "1.0"
unexpected: true
sources:
  - id: github-openclaw
    type: github_repo
    project: OpenClaw
    category: general_agents
    url: https://github.com/openclaw/openclaw
""",
        """
version: "1.0"
sources:
  - id: github-openclaw
    type: github_repo
    project: OpenClaw
    category: general_agents
    url: https://github.com/openclaw/openclaw
    poll_interval_hour: 12
""",
        """
version: "1.0"
sources:
  - id: github-openclaw
    type: github_repo
    project: OpenClaw
    category: general_agents
    url: https://github.com/openclaw/openclaw
scoring:
  default_rign: watch
""",
    ],
)
def test_load_config_rejects_unknown_config_fields(
    tmp_path: Path, config_text: str
):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(config_text, encoding="utf-8")

    with pytest.raises(ConfigError) as exc:
        load_config(config_path)

    assert "Configuration validation failed" in str(exc.value)


def test_load_config_wraps_read_errors(tmp_path: Path):
    with pytest.raises(ConfigError) as exc:
        load_config(tmp_path)

    assert "Configuration file could not be read" in str(exc.value)


def test_seed_sources_yaml_includes_new_categories():
    """Validate that the canonical seed config registers all three new categories."""
    config = load_config(_REPO_ROOT / "config" / "seed-sources.yaml")

    categories = {src.category for src in config.sources}
    assert Category.MODEL_SERVING in categories
    assert Category.AI_INFRASTRUCTURE in categories
    assert Category.PHYSICAL_AI_INFRASTRUCTURE in categories


def test_seed_sources_yaml_new_category_sources_parseable():
    """All new-category sources must have required fields and valid types."""
    config = load_config(_REPO_ROOT / "config" / "seed-sources.yaml")

    new_cats = {Category.MODEL_SERVING, Category.AI_INFRASTRUCTURE, Category.PHYSICAL_AI_INFRASTRUCTURE}
    new_sources = [src for src in config.sources if src.category in new_cats]

    assert len(new_sources) >= 6  # at least 4 model_serving + 2 infra
    for src in new_sources:
        assert src.id
        assert src.project
        assert src.url
        assert src.type in {SourceType.GITHUB_REPO, SourceType.MANUAL}


def test_category_quotas_yaml_includes_new_categories(tmp_path: Path):
    """Validate that category-quotas.yaml enumerates all new categories."""
    import yaml

    raw = yaml.safe_load((_REPO_ROOT / "config" / "category-quotas.yaml").read_text())
    assert "model_serving" in raw
    assert "ai_infrastructure" in raw
    assert "physical_ai_infrastructure" in raw
    assert all(isinstance(v, int) and v > 0 for v in raw.values())
