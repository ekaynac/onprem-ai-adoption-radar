"""Triage engines behind one protocol: Jev when available, rules always.

Every label records which engine produced it, so a page can show when Pulse
fell back to rules instead of pretending nothing changed.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from radar.pulse.items import Lane, PulseItem
from radar.pulse.jev import ask_jev
from radar.pulse.questions import Question


class Answer(BaseModel):
    model_config = ConfigDict(frozen=True)

    value: str | float
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class Label(BaseModel):
    model_config = ConfigDict(frozen=True)

    item_id: str
    content_hash: str
    question_version: int
    engine: str  # "jev" | "rules"
    model: str | None = None
    answers: dict[str, Answer]
    input_tokens: int = 0
    labeled_at: datetime


class Engine(Protocol):
    name: str

    async def answer(
        self, item: PulseItem, questions: dict[str, Question],
    ) -> tuple[dict[str, Answer], str | None, int]:
        """Return ``(answers, model, input_tokens)``; raise on failure."""
        ...


def item_state(item: PulseItem) -> str:
    """The text an engine sees: stable, bounded, no volatile metrics."""
    lines = [f"Title: {item.title}", f"Source: {item.source}", f"URL: {item.url}"]
    if item.lane is Lane.MODEL:
        lines.append(f"Hugging Face repo: {item.key}")
    if item.tags:
        lines.append(f"Tags: {', '.join(item.tags[:12])}")
    if item.summary:
        lines.append(f"Summary: {item.summary}")
    return "\n".join(lines)


def content_hash(item: PulseItem) -> str:
    return hashlib.sha256(item_state(item).encode("utf-8")).hexdigest()[:16]


class JevEngine:
    name = "jev"

    def __init__(self, client: Any, api_key: str):
        self._client = client
        self._api_key = api_key

    async def answer(
        self, item: PulseItem, questions: dict[str, Question],
    ) -> tuple[dict[str, Answer], str | None, int]:
        result = await ask_jev(
            self._client, self._api_key, item_state(item),
            {key: q.as_payload() for key, q in questions.items()},
        )
        answers = {}
        for key, raw in result.answers.items():
            if key not in questions:
                continue
            value = {"choice": raw.choice, "score": raw.score, "noul": raw.noul}[raw.type]
            if value is None:
                raise ValueError(f"Jev answered {key} without a {raw.type} value")
            confidence = raw.confidence if raw.type != "noul" else abs(raw.noul - 0.5) * 2  # type: ignore[operator]
            answers[key] = Answer(value=value, confidence=confidence)
        return answers, result.model, result.usage.input_tokens


# --- Rules: the fallback that is always there. Deliberately low confidence. ---

_RULES_CONFIDENCE = 0.3
_RELEASE_WORDS = re.compile(
    r"\b(introduc\w*|announc\w*|releas\w*|launch\w*|now available|unveil\w*|v\d+(?:\.\d+)+)\b",
    re.IGNORECASE,
)
_MODEL_WORDS = re.compile(
    r"\b(model|llm|gpt|gemini|claude|llama|qwen|mistral|deepseek|glm|kimi|gemma|phi|weights)\b",
    re.IGNORECASE,
)
_NEWS_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("security", re.compile(r"\b(cve-\d+|vulnerab\w*|exploit\w*|security advisory)\b", re.I)),
    ("research", re.compile(r"arxiv\.org|\b(paper|preprint)\b", re.I)),
    ("benchmark", re.compile(r"\b(benchmark\w*|leaderboard|evals?)\b", re.I)),
    ("customer-story", re.compile(r"\b(customers?|boosts|cuts .* cost|saves \d+|how \w+ uses)\b", re.I)),
    ("business-policy", re.compile(r"\b(funding|raises|partner\w*|policy|regulat\w*|pricing)\b", re.I)),
)
_LIST_REPO = re.compile(
    r"\b(awesome|interview|course|roadmap|cheat ?sheet|prompts?|curated list|tutorials?)\b", re.I,
)
_PAPER_TOPICS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("inference-efficiency", re.compile(r"\b(quantiz\w*|inference|serving|kv cache|speculative|long[- ]context|compress\w*)\b", re.I)),
    ("agents-tools", re.compile(r"\b(agent\w*|tool[- ]use|coding|planning)\b", re.I)),
    ("retrieval", re.compile(r"\b(retriev\w*|rag|memory|search)\b", re.I)),
    ("embodied", re.compile(r"\b(robot\w*|embodied|world model|driving|manipulation)\b", re.I)),
    ("multimodal", re.compile(r"\b(vision|image|video|audio|speech|multimodal|diffusion)\b", re.I)),
    ("safety", re.compile(r"\b(safety|alignment|jailbreak|interpretab\w*|red[- ]team\w*)\b", re.I)),
    ("evaluation", re.compile(r"\b(benchmark\w*|evaluat\w*)\b", re.I)),
    ("training", re.compile(r"\b(training|fine[- ]tun\w*|reinforcement|rl|pre-?train\w*|scaling)\b", re.I)),
)


class RulesEngine:
    name = "rules"

    async def answer(
        self, item: PulseItem, questions: dict[str, Question],
    ) -> tuple[dict[str, Answer], str | None, int]:
        text = f"{item.title} {item.summary or ''} {item.url}"
        guesses: dict[str, str | float] = {}
        if item.lane is Lane.NEWS:
            guesses["event"] = _news_event(item.title, text)
        elif item.lane is Lane.REPO:
            guesses["kind"] = "list-course" if _LIST_REPO.search(text) else "tool"
        elif item.lane is Lane.PAPER:
            guesses["topic"] = next(
                (topic for topic, pattern in _PAPER_TOPICS if pattern.search(text)), "other",
            )
            guesses["usable_now"] = item.signals.get("has_code", 0.0)
        elif item.lane is Lane.MODEL:
            guesses["new_model"] = 0.5  # rules cannot tell; stays undecided
        answers = {
            key: Answer(value=value, confidence=_RULES_CONFIDENCE)
            for key, value in guesses.items() if key in questions
        }
        return answers, None, 0


def _news_event(title: str, text: str) -> str:
    if _RELEASE_WORDS.search(title):
        return "model-release" if _MODEL_WORDS.search(title) else "tool-release"
    return next((event for event, pattern in _NEWS_PATTERNS if pattern.search(text)),
                "tutorial-opinion")
