"""Tests guarding the shipped seed-source config."""

from __future__ import annotations

from pathlib import Path

from radar.models import Backer, BackerType, PackageRef
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


def test_every_source_has_a_curated_backer():
    # Provenance is a first-class column on the dashboard, so the shipped seed
    # must classify every project's backer (no blank "—" rows out of the box).
    config = load_config(SEED_CONFIG)
    for source in config.sources:
        assert isinstance(source.backer, Backer), f"{source.project} lacks a backer"
        assert source.backer.name.strip()
        assert isinstance(source.backer.type, BackerType)


def test_seed_has_paper_queries_for_distinctive_tools():
    import yaml

    _REPO_ROOT = Path(__file__).resolve().parents[1]

    raw = yaml.safe_load((_REPO_ROOT / "config" / "seed-sources.yaml").read_text())
    by_id = {s["id"]: s for s in raw["sources"]}
    # Distinctively-named, high-value tools get a curated query.
    for sid in ("github-vllm", "github-sglang", "github-llama-cpp"):
        assert by_id[sid].get("paper_query"), f"{sid} missing paper_query"
    # Ambiguous names stay off until curated.
    assert by_id["github-ray"].get("paper_query") is None
