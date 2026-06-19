from __future__ import annotations

import pytest

from radar.models_radar.collectors.ollama import bits_for_tag, fetch_ollama_quants


TAGS_JSON = {"models": [
    {"tag": "8b-instruct-q4_K_M", "size": 4_900_000_000},
    {"tag": "8b-instruct-q8_0", "size": 8_500_000_000},
    {"tag": "latest", "size": 4_900_000_000},
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
async def test_fetch_ollama_quants_parses_tags_and_sizes():
    quants = await fetch_ollama_quants("llama3.1", FakeClient(TAGS_JSON))
    by_tag = {q.tag: q for q in quants}
    assert by_tag["8b-instruct-q4_K_M"].size_gb == pytest.approx(4.9, abs=0.1)
    assert by_tag["8b-instruct-q4_K_M"].bits_per_weight == 4.5
    assert by_tag["8b-instruct-q8_0"].bits_per_weight == 8.0


@pytest.mark.asyncio
async def test_fetch_ollama_quants_degrades_to_empty():
    class Boom:
        async def get(self, url, **kw): raise RuntimeError("down")
    assert await fetch_ollama_quants("x", Boom()) == []
