"""Pulse triage: question config, Jev client, engines, caching and fallbacks."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from radar.enrichment import retry
from radar.pulse.classify import Answer, JevEngine, RulesEngine, content_hash
from radar.pulse.items import Lane, PulseItem
from radar.pulse.jev import JevError, ask_jev
from radar.pulse.questions import Question, load_questions
from radar.pulse.triage import (
    append_labels,
    load_labels,
    needs_triage,
    pending,
    prune_labels,
    triage,
)


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)
QUESTIONS = load_questions(ROOT / "config" / "pulse-questions.yaml")


@pytest.fixture(autouse=True)
def _no_backoff_sleep(monkeypatch):
    async def instant(_seconds: float) -> None:
        return None

    monkeypatch.setattr(retry.asyncio, "sleep", instant)


def _news(key: str, title: str) -> PulseItem:
    return PulseItem(
        lane=Lane.NEWS, key=key, title=title, url="https://openai.com/index/x",
        source="openai-news", first_seen=NOW, last_seen=NOW,
    )


def _jev_body(event: str = "model-release", confidence: float = 0.97) -> dict:
    return {
        "model": "jev-1.13.0",
        "answers": {"event": {"type": "choice", "choice": event,
                              "probabilities": {event: confidence}, "confidence": confidence}},
        "usage": {"input_tokens": 300, "output_tokens": 5},
    }


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# --- config ---------------------------------------------------------------

def test_shipped_question_config_is_valid_and_covers_every_lane() -> None:
    assert {lane for lane in Lane} == set(QUESTIONS.lanes)
    assert QUESTIONS.for_lane(Lane.NEWS)["event"].type == "choice"


@pytest.mark.parametrize(
    "raw",
    [
        {"type": "noul", "instructions": "x", "criteria": {"yes": "a", "no": "b"}},
        {"type": "score", "instructions": "x", "criteria": ["only-one"]},
        {"type": "choice", "instructions": "x", "criteria": ["not", "a", "mapping"]},
    ],
)
def test_malformed_questions_fail_fast(raw) -> None:
    with pytest.raises(ValueError):
        Question.model_validate(raw)


# --- Jev client -------------------------------------------------------------

def test_ask_jev_sends_bearer_and_parses_answers() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["Authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=_jev_body())

    async def run():
        async with _client(handler) as client:
            return await ask_jev(client, "test-key", "Title: x", {"event": {"type": "choice"}})

    result = asyncio.run(run())

    assert seen["auth"] == "Bearer test-key"
    assert seen["body"]["model"] == "jev-latest"
    assert result.answers["event"].choice == "model-release"
    assert result.usage.input_tokens == 300


def test_ask_jev_retries_overload_then_succeeds() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(529) if len(calls) == 1 else httpx.Response(200, json=_jev_body())

    async def run():
        async with _client(handler) as client:
            return await ask_jev(client, "k", "s", {"event": {"type": "choice"}})

    assert asyncio.run(run()).answers["event"].choice == "model-release"
    assert len(calls) == 2


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(401, json={"error": "invalid key"}),
        httpx.Response(200, json={"model": "jev", "answers": {}}),  # skipped question
        httpx.Response(200, text="not json"),
    ],
)
def test_ask_jev_raises_jev_error_on_untrustworthy_responses(response) -> None:
    async def run():
        async with _client(lambda _r: response) as client:
            return await ask_jev(client, "secret-key", "s", {"event": {"type": "choice"}})

    with pytest.raises(JevError) as excinfo:
        asyncio.run(run())
    assert "secret-key" not in str(excinfo.value)


# --- engines -----------------------------------------------------------------

def test_jev_engine_maps_choice_and_noul_confidence() -> None:
    body = {
        "model": "jev-1.13.0",
        "answers": {
            "topic": {"type": "choice", "choice": "training", "confidence": 0.8},
            "usable_now": {"type": "noul", "noul": 0.9},
        },
        "usage": {"input_tokens": 120},
    }

    async def run():
        async with _client(lambda _r: httpx.Response(200, json=body)) as client:
            paper = PulseItem(lane=Lane.PAPER, key="2609.00001", title="t",
                              url="https://arxiv.org/abs/2609.00001", source="hf",
                              first_seen=NOW, last_seen=NOW)
            return await JevEngine(client, "k").answer(paper, QUESTIONS.for_lane(Lane.PAPER))

    answers, model, tokens = asyncio.run(run())

    assert answers["topic"] == Answer(value="training", confidence=0.8)
    assert answers["usable_now"].value == 0.9
    assert answers["usable_now"].confidence == pytest.approx(0.8)
    assert (model, tokens) == ("jev-1.13.0", 120)


@pytest.mark.parametrize(
    ("title", "event"),
    [
        ("Introducing GPT-6.1 Sol", "model-release"),
        ("vLLM v0.21.0 released", "tool-release"),
        ("Harvey cuts drafting cost with GPT-6 Astra for customers", "customer-story"),
        ("Critical CVE-2026-1234 in inference server", "security"),
        ("I think you should almost never use AI to write", "tutorial-opinion"),
    ],
)
def test_rules_engine_news_heuristics(title: str, event: str) -> None:
    answers, model, tokens = asyncio.run(
        RulesEngine().answer(_news("n", title), QUESTIONS.for_lane(Lane.NEWS))
    )

    assert answers["event"].value == event
    assert answers["event"].confidence == 0.3
    assert (model, tokens) == (None, 0)


# --- triage orchestration ---------------------------------------------------------

class _FakeEngine:
    name = "jev"

    def __init__(self, fail: bool = False, tokens: int = 100):
        self.fail, self.tokens, self.calls = fail, tokens, 0

    async def answer(self, item, questions):
        self.calls += 1
        if self.fail:
            raise JevError("overloaded")
        return {"event": Answer(value="model-release", confidence=0.9)}, "jev-1.13.0", self.tokens


def test_only_unknown_models_need_triage() -> None:
    model = PulseItem(lane=Lane.MODEL, key="Qwen/X", title="X", url="https://huggingface.co/Qwen/X",
                      source="huggingface", first_seen=NOW, last_seen=NOW, kind="original")

    assert not needs_triage(model)
    assert needs_triage(model.model_copy(update={"kind": "unknown"}))
    assert needs_triage(_news("n", "t"))


def test_triage_uses_primary_and_records_engine() -> None:
    engine = _FakeEngine()

    report = asyncio.run(triage([_news("a", "x"), _news("b", "y")], QUESTIONS, engine, NOW, 10_000))

    assert report.engine_counts == {"jev": 2}
    assert report.input_tokens == 200
    assert not report.errors


def test_triage_falls_back_to_rules_and_opens_circuit() -> None:
    engine = _FakeEngine(fail=True)
    items = [_news(str(i), f"Introducing model {i}") for i in range(12)]

    report = asyncio.run(triage(items, QUESTIONS, engine, NOW, 10_000))

    assert report.engine_counts == {"rules": 12}
    assert report.circuit_open
    assert engine.calls < 12  # stopped calling once the breaker opened
    assert report.errors


def test_triage_stops_spending_at_the_budget() -> None:
    engine = _FakeEngine(tokens=600)
    items = [_news(str(i), "x") for i in range(20)]

    report = asyncio.run(triage(items, QUESTIONS, engine, NOW, token_budget=1_000))

    assert report.budget_exhausted
    assert report.engine_counts["rules"] > 0
    assert report.input_tokens < 1_000 + 600 * 8  # at most one concurrent wave over


def test_pending_skips_fresh_labels_and_upgrades_rules(tmp_path: Path) -> None:
    fresh, stale, rules_only = _news("a", "x"), _news("b", "y"), _news("c", "z")
    path = tmp_path / "labels.jsonl"
    old = asyncio.run(triage([fresh, rules_only], QUESTIONS, None, NOW, 0)).labels
    jev = asyncio.run(triage([fresh], QUESTIONS, _FakeEngine(), NOW, 10_000)).labels
    append_labels(path, [*old, *jev])
    existing = load_labels(path)

    assert existing[fresh.id].engine == "jev"
    todo = pending([fresh, stale, rules_only], QUESTIONS, existing, primary_available=True)
    assert [i.key for i in todo] == ["b", "c"]
    assert [i.key for i in pending([fresh, stale, rules_only], QUESTIONS, existing, False)] == ["b"]


def test_a_later_rules_label_never_overwrites_a_jev_label(tmp_path: Path) -> None:
    item = _news("a", "x")
    path = tmp_path / "labels.jsonl"
    append_labels(path, asyncio.run(triage([item], QUESTIONS, _FakeEngine(), NOW, 10_000)).labels)
    append_labels(path, asyncio.run(triage([item], QUESTIONS, None, NOW, 0)).labels)

    assert load_labels(path)[item.id].engine == "jev"
    assert load_labels(path)[item.id].content_hash == content_hash(item)


def test_prune_keeps_only_live_items(tmp_path: Path) -> None:
    path = tmp_path / "labels.jsonl"
    items = [_news("a", "x"), _news("b", "y")]
    append_labels(path, asyncio.run(triage(items, QUESTIONS, None, NOW, 0)).labels)

    prune_labels(path, {"news:a"})

    assert set(load_labels(path)) == {"news:a"}
