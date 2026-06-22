from __future__ import annotations

from pathlib import Path

import pytest

from radar.models_radar.scan import run_model_scan


class FakeResp:
    def __init__(self, p): self._p = p
    def raise_for_status(self): pass
    def json(self): return self._p


class FakeClient:
    def __init__(self, routes): self.routes = routes
    async def get(self, url, **kw):
        for frag, payload in self.routes.items():
            if frag in url:
                return FakeResp(payload)
        raise AssertionError(f"unexpected {url}")


@pytest.mark.asyncio
async def test_scan_assembles_entries_for_seed(tmp_path: Path):
    seed = tmp_path / "model-seed.yaml"
    seed.write_text(
        "models:\n"
        "  - id: llama-3.1-8b\n    name: Llama 3.1 8B\n    family: Llama\n"
        "    hf_repo: meta-llama/Llama-3.1-8B\n",
        encoding="utf-8",
    )
    client = FakeClient({
        "api/models/meta-llama/Llama-3.1-8B": {
            "downloads": 100, "likes": 5, "safetensors": {"total": 8000000000},
            "cardData": {"license": "apache-2.0"}, "pipeline_tag": "text-generation",
            "siblings": [{"rfilename": "model.Q4_K_M.gguf"}],
        },
        "raw/main/config.json": {"num_hidden_layers": 32, "hidden_size": 4096,
                                 "max_position_embeddings": 131072},
    })
    entries = await run_model_scan(seed, client)
    assert len(entries) == 1
    m = entries[0]
    assert m.id == "llama-3.1-8b" and m.params_total == 8000000000
    assert m.quants and m.hardware_tier.value == "laptop"
