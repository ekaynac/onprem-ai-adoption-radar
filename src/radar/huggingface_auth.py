"""Hugging Face authentication plumbing for outbound fetches.

Gated model cards (and some HF APIs) return 401 without a token. The radar
must self-evolve by ingesting those cards, so outbound HF calls read a token
from the environment (``HF_TOKEN`` / ``HUGGING_FACE_HUB_TOKEN``) or a local
``.env`` file at the project root — never from hardcoded secrets. When no
token is present the helpers degrade to anonymous requests; discovery and
benchmark ingestion simply cover fewer gated models.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


_DOTENV_LOADED = False


def _load_dotenv(root: Path | None = None) -> None:
    """Best-effort populate os.environ from a project-root ``.env``.

    Avoids a hard dependency on python-dotenv; a missing or malformed file is
    silently ignored so the rest of the pipeline is unaffected.
    """
    global _DOTENV_LOADED
    if _DOTENV_LOADED:
        return
    _DOTENV_LOADED = True
    candidate = (root or Path.cwd()) / ".env"
    if not candidate.is_file():
        return
    try:
        for raw in candidate.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip()
            # Strip surrounding quotes so HF_TOKEN="abc" works.
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]
            if key and key not in os.environ:
                os.environ[key] = value
    except OSError:
        return


def hf_token(root: Path | None = None) -> str | None:
    """Return the HF token from env or a local ``.env``, else ``None``."""
    _load_dotenv(root)
    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
    return token or None


def hf_auth_headers(root: Path | None = None) -> dict[str, str]:
    """Headers that authorize HF requests when a token is configured."""
    token = hf_token(root)
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}"}


def apply_hf_auth(client_kwargs: dict[str, Any], root: Path | None = None) -> dict[str, Any]:
    """Merge HF auth headers into an httpx client kwargs dict (returns a copy)."""
    kwargs = dict(client_kwargs)
    headers = dict(kwargs.get("headers") or {})
    headers.update(hf_auth_headers(root))
    kwargs["headers"] = headers
    return kwargs
