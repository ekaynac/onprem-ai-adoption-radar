"""URL/file slugging for project pages.

A single source of truth so the static export's filenames and the index's links
always agree, even when two project names slug to the same base.
"""

from __future__ import annotations

import re


def project_slug(name: str) -> str:
    """Lowercase, hyphenated, filesystem/URL-safe slug for a project name."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def build_slug_map(projects: list[str]) -> dict[str, str]:
    """Map each project to a unique slug, resolving collisions deterministically.

    Names are processed in sorted order so the assignment is stable regardless
    of input order; a colliding slug gets a ``-2``, ``-3``, … suffix.
    """
    slugs: dict[str, str] = {}
    used: set[str] = set()
    for project in sorted(projects):
        base = project_slug(project) or "project"
        candidate = base
        n = 2
        while candidate in used:
            candidate = f"{base}-{n}"
            n += 1
        used.add(candidate)
        slugs[project] = candidate
    return slugs
