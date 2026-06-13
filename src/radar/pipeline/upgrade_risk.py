"""Deterministic upgrade-risk scanning of release-note text.

Flags releases whose notes mention breaking changes, required migrations, or
security fixes, so a card can warn "upgrading this is not routine" without any
LLM. Pure keyword matching over the lines the collectors already extracted.
"""

from __future__ import annotations

import re


_HIGH_RISK = re.compile(
    r"breaking change|breaking:|\bBREAKING\b|migration required|must migrate"
    r"|removed support|security fix|security release|\bCVE-\d{4}-\d+\b",
    re.IGNORECASE,
)
_LOW_RISK = re.compile(
    r"\bdeprecat(?:ed|ion|es)\b|migration guide|\brenamed\b|will be removed",
    re.IGNORECASE,
)


def assess_upgrade_risk(lines: list[str]) -> tuple[str, list[str]]:
    """Return ("high"|"low"|"none", matching lines) for release-note lines.

    A line matching a high-risk phrase wins over low-risk matches; each
    matching line is quoted once, at the highest severity it matched.
    """
    high_notes: list[str] = []
    low_notes: list[str] = []
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        if _HIGH_RISK.search(line):
            high_notes.append(line)
        elif _LOW_RISK.search(line):
            low_notes.append(line)
    if high_notes:
        return "high", _dedupe(high_notes)
    if low_notes:
        return "low", _dedupe(low_notes)
    return "none", []


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = value.lower()
        if key not in seen:
            seen.add(key)
            result.append(value)
    return result
