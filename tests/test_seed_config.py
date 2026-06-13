"""Tests guarding the shipped seed-source config."""

from __future__ import annotations

from pathlib import Path

from radar.models import PackageRef
from radar.storage.config import load_config


SEED_CONFIG = Path(__file__).resolve().parent.parent / "config" / "seed-sources.yaml"


def test_seed_sources_yaml_parses():
    # extra="forbid" on the models means a typo like `pacakge:` fails here.
    config = load_config(SEED_CONFIG)
    assert len(config.sources) > 0


def test_mapped_sources_have_valid_package_refs():
    config = load_config(SEED_CONFIG)
    mapped = [s for s in config.sources if s.package is not None]

    assert mapped  # at least some sources carry a package mapping
    for source in mapped:
        assert isinstance(source.package, PackageRef)
        assert source.package.ecosystem in {"PyPI", "npm"}
        assert source.package.name.strip()
