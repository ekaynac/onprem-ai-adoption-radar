"""Secrets from the environment, or a git-ignored project ``.env``.

Never hardcoded and never logged. Existing environment variables win over
``.env`` so CI secrets and systemd ``EnvironmentFile`` values are authoritative.
"""

from __future__ import annotations

import os
from pathlib import Path


def load_dotenv(root: Path | None = None) -> None:
    """Best effort: fill unset variables from ``<root>/.env`` (``KEY=value`` lines)."""
    path = (root or Path.cwd()) / ".env"
    if not path.is_file():
        return
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value


def secret(name: str, root: Path | None = None, *aliases: str) -> str | None:
    load_dotenv(root)
    for key in (name, *aliases):
        value = os.environ.get(key, "").strip()
        if value:
            return value
    return None


def hf_headers(root: Path | None = None) -> dict[str, str]:
    """Hugging Face auth (gated cards and lists return 401 without it)."""
    token = secret("HF_TOKEN", root, "HUGGING_FACE_HUB_TOKEN")
    return {"Authorization": f"Bearer {token}"} if token else {}


def github_headers(root: Path | None = None) -> dict[str, str]:
    """GitHub search is 10 requests/minute anonymous, 30 with a token."""
    headers = {"Accept": "application/vnd.github+json"}
    token = secret("GITHUB_TOKEN", root)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers
