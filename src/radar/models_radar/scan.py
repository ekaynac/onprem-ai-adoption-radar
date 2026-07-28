"""Run the model collectors over the seed and assemble ModelEntry list."""

from __future__ import annotations

from typing import Any

from radar.models_radar.assemble import build_model_entry
from radar.models_radar.collectors.huggingface import fetch_hf_model
from radar.models_radar.collectors.ollama import fetch_ollama_quants
from radar.models_radar.entities import ModelEntry, ModelSeed


async def run_model_scan(seeds: list[ModelSeed], client: Any) -> list[ModelEntry]:
    """Collect + assemble one ModelEntry per enabled seed. Best-effort per model.

    Callers load the seed file and filter out quarantined seeds (see
    ``radar.models_radar.validate``) before calling this — invalid seeds must
    never reach collection or scoring.
    """
    entries: list[ModelEntry] = []
    for seed in seeds:
        if not seed.enabled:
            continue
        hf = await fetch_hf_model(seed.hf_repo, client) if seed.hf_repo else None
        ollama = await fetch_ollama_quants(seed.ollama_name, client) if seed.ollama_name else []
        entries.append(build_model_entry(seed, hf, ollama))
    return sorted(entries, key=lambda m: m.id)
