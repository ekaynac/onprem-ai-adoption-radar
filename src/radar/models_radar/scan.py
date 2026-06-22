"""Run the model collectors over the seed and assemble ModelEntry list."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from radar.models_radar.assemble import build_model_entry
from radar.models_radar.collectors.huggingface import fetch_hf_model
from radar.models_radar.collectors.ollama import fetch_ollama_quants
from radar.models_radar.entities import ModelEntry
from radar.models_radar.seed import load_model_seed


async def run_model_scan(seed_path: Path, client: Any) -> list[ModelEntry]:
    """Collect + assemble one ModelEntry per enabled seed. Best-effort per model."""
    seeds = load_model_seed(seed_path)
    entries: list[ModelEntry] = []
    for seed in seeds:
        if not seed.enabled:
            continue
        hf = await fetch_hf_model(seed.hf_repo, client) if seed.hf_repo else None
        ollama = await fetch_ollama_quants(seed.ollama_name, client) if seed.ollama_name else []
        entries.append(build_model_entry(seed, hf, ollama))
    return sorted(entries, key=lambda m: m.id)
