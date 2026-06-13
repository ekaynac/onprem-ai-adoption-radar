"""Tests for deterministic upgrade-risk scanning of release notes."""

from __future__ import annotations

from radar.pipeline.upgrade_risk import assess_upgrade_risk


def test_breaking_change_is_high_risk():
    risk, notes = assess_upgrade_risk(
        [
            "BREAKING CHANGE: the config file format moved to TOML.",
            "Added a new dashboard widget.",
        ]
    )

    assert risk == "high"
    assert any("BREAKING" in note for note in notes)


def test_security_fix_and_cve_are_high_risk():
    risk, notes = assess_upgrade_risk(["This release contains a security fix for CVE-2026-1234."])

    assert risk == "high"
    assert notes


def test_deprecation_is_low_risk():
    risk, notes = assess_upgrade_risk(["The legacy API is deprecated and will be removed in v3."])

    assert risk == "low"
    assert any("deprecated" in note.lower() for note in notes)


def test_routine_release_is_no_risk():
    risk, notes = assess_upgrade_risk(["Improved logging output.", "Fixed a typo in docs."])

    assert risk == "none"
    assert notes == []


def test_high_wins_over_low():
    risk, _ = assess_upgrade_risk(["deprecated the old flag", "migration required for storage"])

    assert risk == "high"


def test_notes_quote_the_matching_line_once():
    risk, notes = assess_upgrade_risk(
        ["BREAKING: removed X. This is a breaking change for everyone."]
    )

    assert risk == "high"
    assert len(notes) == 1
