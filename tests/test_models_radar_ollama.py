from __future__ import annotations

import pytest

from radar.models_radar.collectors.ollama import (
    bits_for_tag,
    fetch_ollama_quants,
    param_billions,
    tag_param_billions,
)


# Global catalog response — contains entries for multiple models
GLOBAL_CATALOG_JSON = {"models": [
    {
        "name": "llama3.1:8b-instruct-q4_K_M",
        "size": 4_900_000_000,
        "details": {"quantization_level": "Q4_K_M", "parameter_size": "8B"},
    },
    {
        "name": "llama3.1:8b-instruct-q8_0",
        "size": 8_500_000_000,
        "details": {"quantization_level": "Q8_0", "parameter_size": "8B"},
    },
    {
        "name": "llama3.1",
        "size": 4_900_000_000,
        "details": {"quantization_level": "Q4_K_M", "parameter_size": "8B"},
    },
    # "latest" entries must be skipped
    {"name": "latest", "size": 4_900_000_000, "details": {}},
    # Different model — must not appear in llama3.1 results
    {
        "name": "mistral:7b-q4_K_M",
        "size": 4_100_000_000,
        "details": {"quantization_level": "Q4_K_M", "parameter_size": "7B"},
    },
]}


class FakeResp:
    def __init__(self, p): self._p = p
    def raise_for_status(self): pass
    def json(self): return self._p


class FakeClient:
    def __init__(self, payload): self.payload = payload
    async def get(self, url, **kw): return FakeResp(self.payload)


def test_bits_for_tag_known_quants():
    assert bits_for_tag("8b-q4_K_M") == 4.5
    assert bits_for_tag("8b-q8_0") == 8.0
    assert bits_for_tag("fp16") == 16.0
    assert bits_for_tag("weird-unknown") == 4.5  # default to Q4-class


@pytest.mark.asyncio
async def test_fetch_ollama_quants_filters_by_model_name():
    quants = await fetch_ollama_quants("llama3.1", FakeClient(GLOBAL_CATALOG_JSON))
    by_tag = {q.tag: q for q in quants}
    # Must include llama3.1-prefixed entries
    assert "llama3.1:8b-instruct-q4_K_M" in by_tag
    assert "llama3.1:8b-instruct-q8_0" in by_tag
    # Must NOT include the other model
    assert not any("mistral" in t for t in by_tag)
    # "latest" must be skipped
    assert "latest" not in by_tag


def test_param_billions_parses_labels():
    assert param_billions("8B") == 8.0
    assert param_billions("30.5B") == 30.5
    assert param_billions("350M") == 0.35
    assert param_billions(None) is None
    assert param_billions("") is None
    assert param_billions("unknown") is None


def test_tag_param_billions_parses_variant():
    assert tag_param_billions("qwen3:8b-q4_K_M") == 8.0
    assert tag_param_billions("qwen3:30b-a3b-q4_K_M") == 30.0  # total, not the 3B active
    assert tag_param_billions("gemma3:12b") == 12.0
    assert tag_param_billions("gemma3") is None  # family digit not mistaken for a size
    assert tag_param_billions("model:q4_K_M") is None


@pytest.mark.asyncio
async def test_fetch_ollama_quants_captures_param_label():
    quants = await fetch_ollama_quants("llama3.1", FakeClient(GLOBAL_CATALOG_JSON))
    by_tag = {q.tag: q for q in quants}
    assert by_tag["llama3.1:8b-instruct-q4_K_M"].param_label == "8B"


@pytest.mark.asyncio
async def test_fetch_ollama_quants_bits_from_quantization_level():
    quants = await fetch_ollama_quants("llama3.1", FakeClient(GLOBAL_CATALOG_JSON))
    by_tag = {q.tag: q for q in quants}
    assert by_tag["llama3.1:8b-instruct-q4_K_M"].bits_per_weight == 4.5
    assert by_tag["llama3.1:8b-instruct-q8_0"].bits_per_weight == 8.0


@pytest.mark.asyncio
async def test_fetch_ollama_quants_size_parsed():
    quants = await fetch_ollama_quants("llama3.1", FakeClient(GLOBAL_CATALOG_JSON))
    by_tag = {q.tag: q for q in quants}
    assert by_tag["llama3.1:8b-instruct-q4_K_M"].size_gb == pytest.approx(4.9, abs=0.1)


@pytest.mark.asyncio
async def test_fetch_ollama_quants_degrades_to_empty():
    class Boom:
        async def get(self, url, **kw): raise RuntimeError("down")
    assert await fetch_ollama_quants("x", Boom()) == []
