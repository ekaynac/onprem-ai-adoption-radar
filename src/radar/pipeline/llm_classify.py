"""Optional LLM analyst for the firehose tail.

This runs ONLY on entries the deterministic matcher could not place, and ONLY
when explicitly enabled in config. It is a constrained *classifier*, not a
generator: given an entry and the list of tracked project names, it must return
exactly one of those names or NONE. That keeps it cheap (short output), bounded
(no invented projects), and safe to default-off. Any failure degrades to None,
so the deterministic result is never worsened by enabling the analyst.

The completion call is injected, so the prompt/parse logic is fully testable
offline. ``build_analyst`` wires the real OpenAI-compatible HTTP call.
"""

from __future__ import annotations

import logging
import os
from typing import Callable

from radar.models import LLMConfig

logger = logging.getLogger(__name__)

Complete = Callable[[str], str]

_PROMPT = """You categorize a tech news entry by which tracked project it is about.

Tracked projects:
{candidates}

Entry:
{text}

Reply with EXACTLY one project name from the list above, or NONE if the entry
is not specifically about any of them. Reply with only the name, nothing else."""


def _build_prompt(text: str, candidates: list[str], max_chars: int) -> str:
    listing = "\n".join(f"- {name}" for name in candidates)
    return _PROMPT.format(candidates=listing, text=text[:max_chars].strip())


def _parse_answer(raw: str, candidates: list[str]) -> str | None:
    """Map a model reply to a candidate name, or None.

    Tolerates surrounding prose ("Answer: vLLM") and case/whitespace, but never
    accepts a name outside the candidate list.
    """
    cleaned = raw.strip().lower()
    if not cleaned or "none" in cleaned.splitlines()[0]:
        # Only treat NONE as a no-match when it leads the answer.
        if cleaned.split() and cleaned.split()[0].strip(":.") == "none":
            return None
    # Prefer the longest candidate name that appears as a whole token, so
    # "TensorRT-LLM" wins over a shorter incidental substring.
    best: str | None = None
    for candidate in sorted(candidates, key=len, reverse=True):
        token = candidate.lower()
        if token in cleaned:
            best = candidate
            break
    return best


class LLMAnalyst:
    """Callable analyst: ``(text, candidates) -> project name | None``."""

    def __init__(self, complete: Complete, *, max_chars: int = 800):
        self._complete = complete
        self._max_chars = max_chars

    def __call__(self, text: str, candidates: list[str]) -> str | None:
        prompt = _build_prompt(text, candidates, self._max_chars)
        try:
            raw = self._complete(prompt)
        except Exception as exc:  # never let the tail-pass crash a scan
            logger.warning("LLM analyst call failed: %s", exc)
            return None
        return _parse_answer(raw, candidates)


def build_analyst(config: LLMConfig) -> LLMAnalyst | None:
    """Return a wired analyst when enabled, else None (deterministic only)."""
    if not config.enabled:
        return None
    api_key = os.getenv(config.api_key_env, "")
    complete = _openai_compatible_completer(
        base_url=config.base_url,
        model=config.model,
        api_key=api_key,
        timeout=config.timeout_seconds,
    )
    return LLMAnalyst(complete)


def _openai_compatible_completer(
    *, base_url: str, model: str, api_key: str, timeout: int
) -> Complete:
    """Build a completion function hitting an OpenAI-compatible chat endpoint."""

    def complete(prompt: str) -> str:
        import httpx  # local import: only needed when the analyst is enabled

        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        response = httpx.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers=headers,
            json={
                "model": model,
                "temperature": 0,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=timeout,
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]

    return complete
