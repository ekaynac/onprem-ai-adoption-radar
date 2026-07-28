from __future__ import annotations

import pytest

from radar.models_radar.collectors.huggingface import (
    fetch_hf_model,
    quant_formats_from_siblings,
)


MODEL_JSON = {
    "downloads": 123456, "likes": 789, "lastModified": "2026-06-01T00:00:00.000Z",
    "pipeline_tag": "text-generation",
    "cardData": {"license": "apache-2.0"},
    "safetensors": {"total": 8030000000},
    "siblings": [
        {"rfilename": "model-00001-of-00002.safetensors"},
        {"rfilename": "config.json"},
    ],
}
CONFIG_JSON = {"num_hidden_layers": 32, "hidden_size": 4096, "max_position_embeddings": 131072}


class FakeResp:
    def __init__(self, payload): self._p = payload
    def raise_for_status(self): pass
    def json(self): return self._p


class FakeClient:
    def __init__(self, routes): self.routes = routes
    async def get(self, url, **kw):
        for frag, payload in self.routes.items():
            if frag in url:
                return FakeResp(payload)
        raise AssertionError(f"unexpected url {url}")


def test_quant_formats_from_siblings_detects_gguf_and_mlx():
    fmts = quant_formats_from_siblings([
        "model.Q4_K_M.gguf", "model.Q8_0.gguf", "model.safetensors",
        "model.fp16.gguf", "mlx-4bit/weights.npz",
    ])
    assert "GGUF Q4_K_M" in fmts and "GGUF Q8_0" in fmts


@pytest.mark.asyncio
async def test_fetch_hf_model_parses_specs():
    client = FakeClient({
        "api/models/meta-llama/Llama-3.1-8B": MODEL_JSON,
        "raw/main/config.json": CONFIG_JSON,
    })
    data = await fetch_hf_model("meta-llama/Llama-3.1-8B", client)
    assert data is not None
    assert data.params_total == 8030000000
    assert data.num_layers == 32 and data.hidden_size == 4096
    assert data.context_length == 131072
    assert data.license == "apache-2.0"
    assert data.downloads == 123456 and data.likes == 789


@pytest.mark.asyncio
async def test_fetch_hf_model_degrades_to_none_on_error():
    class Boom:
        async def get(self, url, **kw): raise RuntimeError("network down")
    assert await fetch_hf_model("x/y", Boom()) is None


@pytest.mark.asyncio
async def test_fetch_parses_architecture_and_quant_format():
    """Test that architecture and quant format are parsed from config."""
    config = {
        "num_hidden_layers": 32, "hidden_size": 4096,
        "num_attention_heads": 32, "num_key_value_heads": 8,
        "max_position_embeddings": 131072,
        "quantization_config": {"quant_method": "fp8"},
    }
    meta = {"downloads": 5, "siblings": []}
    client = FakeClient({
        "api/models/org/model": meta,
        "raw/main/config.json": config,
    })
    data = await fetch_hf_model("org/model", client)

    assert data is not None
    assert data.architecture is not None
    assert data.architecture.num_key_value_heads == 8
    assert data.architecture.attention_kind.value == "gqa"
    assert data.repo_quant_format == "FP8"
    assert data.gated is False


@pytest.mark.asyncio
async def test_fetch_parses_gated_flag():
    """Test that gated flag is parsed from meta response."""
    config = {"num_hidden_layers": 32}
    meta_gated = {"gated": "manual", "siblings": []}
    meta_not_gated = {"gated": False, "siblings": []}
    meta_missing_gated = {"siblings": []}

    # Test gated=True from "manual" string
    client = FakeClient({
        "api/models/org/model": meta_gated,
        "raw/main/config.json": config,
    })
    data = await fetch_hf_model("org/model", client)
    assert data is not None
    assert data.gated is True

    # Test gated=False from false value
    client = FakeClient({
        "api/models/org/model": meta_not_gated,
        "raw/main/config.json": config,
    })
    data = await fetch_hf_model("org/model", client)
    assert data is not None
    assert data.gated is False

    # Test gated=False from missing key
    client = FakeClient({
        "api/models/org/model": meta_missing_gated,
        "raw/main/config.json": config,
    })
    data = await fetch_hf_model("org/model", client)
    assert data is not None
    assert data.gated is False
