"""Ollama library collector: local-runnable quant tags + sizes."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol


logger = logging.getLogger(__name__)

OLLAMA_TAGS_URL = "https://ollama.com/api/tags"
_BITS_BY_QUANT = {
    "q2": 2.6, "q3": 3.4, "q4": 4.5, "q5": 5.5, "q6": 6.6, "q8": 8.0,
    "fp16": 16.0, "f16": 16.0,
}


class _AsyncClient(Protocol):
    async def get(self, url: str, **kwargs: Any) -> Any: ...


@dataclass(frozen=True)
class OllamaQuant:
    tag: str
    size_gb: float | None
    bits_per_weight: float


def bits_for_tag(tag: str) -> float:
    """Effective bits-per-weight for an Ollama quant tag (default Q4-class)."""
    low = tag.lower()
    for key, bits in _BITS_BY_QUANT.items():
        if key in low:
            return bits
    return 4.5


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
        ))
    return quants
