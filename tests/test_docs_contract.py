"""Docs stay in step with the shipped configuration and commands."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from radar.pulse.telegram import DIGEST_PER_LANE


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_readme_is_about_pulse_and_links_live_docs() -> None:
    readme = _read("README.md")

    assert readme.startswith("# AI Radar Pulse")
    assert "every two hours" in readme.casefold()
    for link in re.findall(r"\]\(((?:docs|deploy)/[^)#]+)\)", readme):
        assert Path(link).exists(), link
    for command in re.findall(r"radar pulse ([a-z-]+)", readme):
        assert command in {"collect", "triage", "top", "export", "telegram", "watchdog"}, command


def test_jev_doc_matches_the_shipped_configuration() -> None:
    doc = _read("docs/jev.md")
    pulse = yaml.safe_load(_read("config/pulse.yaml"))
    questions = yaml.safe_load(_read("config/pulse-questions.yaml"))

    assert f"{pulse['triage']['token_budget_per_run']:,}" in doc  # "300,000"
    assert "config/pulse-questions.yaml" in doc
    for lane, keys in questions["lanes"].items():
        for key in keys:
            assert f"`{key}`" in doc, f"{lane}.{key} undocumented"


def test_pulse_doc_matches_digest_caps_and_sources() -> None:
    doc = _read("docs/pulse.md")
    counts = DIGEST_PER_LANE
    assert (f"top {counts['model']} models, {counts['paper']} papers, "
            f"{counts['repo']} repos and {counts['news']} news items") in doc
    pulse = yaml.safe_load(_read("config/pulse.yaml"))
    assert f"{len(pulse['news']['sources'])} news feeds" in doc
    assert f"{len(pulse['repos']['topics'])} GitHub topics" in doc
    assert "data/pulse.v1.json" in doc and "data/pulse/health.json" in doc
