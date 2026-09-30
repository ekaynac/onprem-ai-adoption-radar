"""TypeSafe Jev client: typed decisions (choice / score / noul) over one input.

Jev (released 2026-09-15) never writes text; it answers questions whose
outputs are fixed up front and returns calibrated probabilities. That is the
whole of Pulse triage, at $0.042 per million input tokens.

API reference: https://docs.typesafe.ai/api.md. The key is read from
``TYPESAFE_API_KEY`` (environment or the git-ignored project ``.env``) and is
never logged.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from radar.enrichment.retry import post_with_retry
from radar.huggingface_auth import _load_dotenv


JEV_URL = "https://api.typesafe.ai/v1/systemone"
JEV_MODEL = "jev-latest"
API_KEY_ENV = "TYPESAFE_API_KEY"


class JevError(RuntimeError):
    """Jev was unreachable or answered something we cannot trust."""


class JevAnswer(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    type: Literal["choice", "score", "noul"]
    choice: str | None = None
    score: float | None = None
    noul: float | None = Field(default=None, ge=0.0, le=1.0)
    probabilities: dict[str, float] = Field(default_factory=dict)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class _Usage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    input_tokens: int = Field(default=0, ge=0)


class JevResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    model: str
    answers: dict[str, JevAnswer]
    usage: _Usage = _Usage()


def jev_api_key(root: Path | None = None) -> str | None:
    _load_dotenv(root)
    key = os.environ.get(API_KEY_ENV, "").strip()
    return key or None


async def ask_jev(
    client: Any,
    api_key: str,
    state: str,
    questions: dict[str, dict[str, Any]],
    model: str = JEV_MODEL,
) -> JevResult:
    """One POST: every question is evaluated against the same ``state``."""
    try:
        response = await post_with_retry(
            client, JEV_URL, label="jev",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": model, "state": state, "questions": questions},
        )
    except Exception as exc:
        # httpx puts the request (never the headers) in its message; the key
        # cannot leak through this string.
        raise JevError(f"Jev request failed: {type(exc).__name__}: {exc}") from exc
    try:
        result = JevResult.model_validate(response.json())
    except (ValueError, ValidationError) as exc:
        raise JevError(f"Jev returned an unexpected body: {exc}") from exc
    missing = questions.keys() - result.answers.keys()
    if missing:
        raise JevError(f"Jev skipped questions: {sorted(missing)}")
    return result
