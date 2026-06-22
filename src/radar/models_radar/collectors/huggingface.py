"""Hugging Face Hub collector: model specs, popularity, quant detection."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Protocol


logger = logging.getLogger(__name__)

HF_MODEL_URL = "https://huggingface.co/api/models/{repo}"
HF_CONFIG_URL = "https://huggingface.co/{repo}/raw/main/config.json"
_GGUF_RE = re.compile(r"(Q\d[\w]*|F16|BF16|F32)\.gguf$", re.IGNORECASE)


class _AsyncClient(Protocol):
    async def get(self, url: str, **kwargs: Any) -> Any: ...


@dataclass(frozen=True)
class HFModelData:
    params_total: int | None = None
    num_layers: int | None = None
    hidden_size: int | None = None
    context_length: int | None = None
    license: str | None = None
    modality_tag: str | None = None
    downloads: int | None = None
    likes: int | None = None
    last_modified: str | None = None
    quant_formats: list[str] = field(default_factory=list)


def quant_formats_from_siblings(filenames: list[str]) -> list[str]:
    """Map GGUF filenames to canonical quant format labels."""
    formats: list[str] = []
    for name in filenames:
        m = _GGUF_RE.search(name)
        if m:
            label = f"GGUF {m.group(1).upper()}"
            if label not in formats:
                formats.append(label)
    return formats


async def fetch_hf_model(hf_repo: str, client: _AsyncClient) -> HFModelData | None:
    """Fetch model metadata + config. Returns None on any failure."""
    try:
        meta_resp = await client.get(HF_MODEL_URL.format(repo=hf_repo))
        meta_resp.raise_for_status()
        meta = meta_resp.json()
    except Exception as exc:
        logger.warning("HF model fetch failed (%s): %s", hf_repo, exc)
        return None

    siblings = [s.get("rfilename", "") for s in meta.get("siblings") or []]
    card = meta.get("cardData") or {}
    safet = meta.get("safetensors") or {}

    num_layers = hidden = context = None
    try:
        cfg_resp = await client.get(HF_CONFIG_URL.format(repo=hf_repo))
        cfg_resp.raise_for_status()
        cfg = cfg_resp.json()
        num_layers = cfg.get("num_hidden_layers")
        hidden = cfg.get("hidden_size")
        context = cfg.get("max_position_embeddings")
    except Exception as exc:
        logger.warning("HF config fetch failed (%s): %s", hf_repo, exc)

    return HFModelData(
        params_total=safet.get("total"),
        num_layers=num_layers,
        hidden_size=hidden,
        context_length=context,
        license=card.get("license") or meta.get("license"),
        modality_tag=meta.get("pipeline_tag"),
        downloads=meta.get("downloads"),
        likes=meta.get("likes"),
        last_modified=meta.get("lastModified"),
        quant_formats=quant_formats_from_siblings(siblings),
    )
