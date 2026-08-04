"""Claude Code CLI adapter for news classification (no API key needed).

An operator machine with a Claude subscription can run the
classification stage through the local ``claude`` CLI in headless mode:
this adapter exposes the same ``client.messages.create`` surface
``classify_news`` already consumes, so budget, validation, and the
fail-closed contract are shared with the API engine verbatim. The CLI
cannot enforce structured outputs server-side, so the schema is put in
the prompt and the existing pydantic validation stays the only gate —
malformed output still lands on the failures list, never on the site.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any


CLAUDE_CLI_TIMEOUT_SECONDS = 240


class _TextBlock:
    type = "text"

    def __init__(self, text: str):
        self.text = text


class _Response:
    stop_reason = "end_turn"

    def __init__(self, text: str):
        self.content = [_TextBlock(text)]


def _strip_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        first_newline = stripped.find("\n")
        if first_newline != -1:
            stripped = stripped[first_newline + 1 :]
        if stripped.rstrip().endswith("```"):
            stripped = stripped.rstrip()[:-3]
    return stripped.strip()


class _ClaudeCliMessages:
    def __init__(self, binary: str):
        self._binary = binary

    def create(
        self,
        *,
        model: str,
        max_tokens: int,  # accepted for interface parity; the CLI manages output length
        system: str,
        output_config: dict[str, Any],
        messages: list[dict[str, Any]],
    ) -> _Response:
        schema = output_config["format"]["schema"]
        prompt = (
            f"{system}\n\n{messages[0]['content']}\n\n"
            "Respond with ONLY one JSON object matching this JSON schema — "
            "no markdown fences, no prose before or after:\n"
            f"{json.dumps(schema)}"
        )
        process = subprocess.run(
            [
                self._binary,
                "-p",
                "--output-format",
                "json",
                "--model",
                model,
            ],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=CLAUDE_CLI_TIMEOUT_SECONDS,
        )
        if process.returncode != 0:
            raise RuntimeError(
                f"claude CLI exited {process.returncode}: "
                f"{process.stderr.strip()[:300]}"
            )
        payload = json.loads(process.stdout)
        result = payload.get("result") if isinstance(payload, dict) else None
        if not isinstance(result, str) or not result.strip():
            raise ValueError("claude CLI returned no result text")
        return _Response(_strip_fences(result))


class ClaudeCliClient:
    """Duck-typed stand-in for ``anthropic.Anthropic`` in classify_news."""

    def __init__(self, binary: str = "claude"):
        self.messages = _ClaudeCliMessages(binary)


def build_claude_cli_client() -> ClaudeCliClient | None:
    """Client when a ``claude`` binary is on PATH; None otherwise."""
    binary = shutil.which("claude")
    return ClaudeCliClient(binary) if binary else None
