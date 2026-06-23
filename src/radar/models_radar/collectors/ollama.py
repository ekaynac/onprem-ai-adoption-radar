"""Ollama library collector: local-runnable quant tags + sizes."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Protocol


logger = logging.getLogger(__name__)

OLLAMA_TAGS_URL = "https://ollama.com/api/tags"
_BITS_BY_QUANT = {
    "q2": 2.6, "q3": 3.4, "q4": 4.5, "q5": 5.5, "q6": 6.6, "q8": 8.0,
    "fp16": 16.0, "f16": 16.0,
}
# Parameter-size label like "30.5B" / "8B" / "350M" → billions of params.
_PARAM_LABEL_RE = re.compile(r"(\d+(?:\.\d+)?)\s*([bm])", re.IGNORECASE)


class _AsyncClient(Protocol):
    async def get(self, url: str, **kwargs: Any) -> Any: ...


@dataclass(frozen=True)
class OllamaQuant:
    tag: str
    size_gb: float | None
    bits_per_weight: float
    param_label: str | None = None


def bits_for_tag(tag: str) -> float:
    """Effective bits-per-weight for an Ollama quant tag (default Q4-class)."""
    low = tag.lower()
    for key, bits in _BITS_BY_QUANT.items():
        if key in low:
            return bits
    return 4.5


def param_billions(label: str | None) -> float | None:
    """Parse an Ollama parameter-size label to billions of params (None if absent)."""
    if not label:
        return None
    match = _PARAM_LABEL_RE.search(label)
    if not match:
        return None
    value = float(match.group(1))
    return value / 1000 if match.group(2).lower() == "m" else value


def tag_param_billions(tag: str) -> float | None:
    """Billions of params from an Ollama tag's variant (e.g. ``qwen3:8b`` → 8.0).

    Parses only the part after the first ``:`` so a family name ending in a digit
    (``gemma3``) is never mistaken for a size; a leftmost match picks the *total*
    size from MoE tags like ``qwen3:30b-a3b`` (30, not the 3B active count). The
    parameter-size label, when the API supplies one, is the more reliable source.
    """
    variant = tag.split(":", 1)[1] if ":" in tag else ""
    return param_billions(variant)


async def fetch_ollama_quants(ollama_name: str, client: _AsyncClient) -> list[OllamaQuant]:
    """Quant tags for an Ollama model from the global catalog. Empty list on failure."""
    try:
        resp = await client.get(OLLAMA_TAGS_URL)
        resp.raise_for_status()
        items = resp.json().get("models") or []
    except Exception as exc:
        logger.warning("Ollama tags fetch failed (%s): %s", ollama_name, exc)
        return []
    quants: list[OllamaQuant] = []
    prefix = ollama_name + ":"
    for item in items:
        name = item.get("name") or ""
        if not name or name == "latest":
            continue
        if name != ollama_name and not name.startswith(prefix):
            continue
        size = item.get("size")
        details = item.get("details") or {}
        quant_level = details.get("quantization_level") or ""
        bits = bits_for_tag(quant_level) if quant_level else bits_for_tag(name)
        quants.append(OllamaQuant(
            tag=name,
            size_gb=round(size / 1e9, 1) if isinstance(size, (int, float)) else None,
            bits_per_weight=bits,
            param_label=details.get("parameter_size"),
        ))
    return quants
