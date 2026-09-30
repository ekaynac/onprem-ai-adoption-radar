"""Deterministic, explainable ranking over triage facts and source signals.

The classifier answers "what is this"; this module decides "how much does an
AI developer care", in plain rules anyone can read and argue with. Every
entry carries its reasons, so a surprising order is debuggable.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

from radar.pulse.classify import Label
from radar.pulse.items import Lane, PulseItem


class Bucket(StrEnum):
    TOP = "top"  # shown in the lane
    UNCERTAIN = "uncertain"  # shown separately: the classifier was not sure
    HIDDEN = "hidden"  # kept for audit, never shown


CONFIDENT = 0.5

NEWS_EVENT_WEIGHT = {
    "model-release": 5.0,
    "tool-release": 4.0,
    "security": 4.0,
    "research": 3.0,
    "benchmark": 3.0,
    "tutorial-opinion": 1.0,
    "business-policy": 0.5,
}
NEWS_HIDDEN_EVENTS = frozenset({"customer-story", "unrelated"})
# Source authority. The 2026-09-30 live run ranked HN "Show HN" hobby posts
# (unfiltered keyword searches) level with official lab launches, because the
# event type alone cannot tell a frontier release from a weekend project.
NEWS_SOURCE_WEIGHT = {
    "openai-news": 1.5,
    "deepmind-blog": 1.5,
    "google-ai-blog": 1.3,
    "mistral-news": 1.5,
    "hf-blog": 1.3,
    "vllm-blog": 1.3,
    "ollama-blog": 1.3,
    "nvidia-dev-blog": 1.1,
    "msr-blog": 1.1,
    "github-blog-ai": 1.1,
    "simonwillison": 1.2,
    "latent-space": 1.2,
    "hn-llm-top": 1.0,  # already filtered to >100 points
}
NEWS_DEFAULT_SOURCE_WEIGHT = 0.6  # unfiltered HN keyword searches and unknowns
REPO_KEPT_KINDS = frozenset({"tool", "framework", "model"})
PAPER_TOPIC_BONUS = {
    "inference-efficiency": 1.0,
    "agents-tools": 1.0,
    "retrieval": 0.5,
    "training": 0.5,
}
MODEL_BASE = {"original": 5.0, "unknown": 3.0}


@dataclass(frozen=True)
class RankedItem:
    item: PulseItem
    score: float
    bucket: Bucket
    reasons: tuple[str, ...]
    engine: str | None = None


def rank(items: list[PulseItem], labels: dict[str, Label]) -> list[RankedItem]:
    ranked = [_rank_one(item, labels.get(item.id)) for item in items]
    return sorted(ranked, key=lambda r: (r.bucket != Bucket.TOP, -r.score, r.item.key))


def _rank_one(item: PulseItem, label: Label | None) -> RankedItem:
    scorer = {
        Lane.MODEL: _model,
        Lane.PAPER: _paper,
        Lane.REPO: _repo,
        Lane.NEWS: _news,
    }[item.lane]
    score, bucket, reasons = scorer(item, label)
    return RankedItem(item, round(score, 2), bucket, tuple(reasons), _engine(item, label))


def _engine(item: PulseItem, label: Label | None) -> str | None:
    """Who decided: a classifier label, deterministic lineage, or nobody yet."""
    if label is not None:
        return label.engine
    if item.lane is Lane.MODEL and item.kind != "unknown":
        return "lineage"  # settled from HF base_model tags; never needed a classifier
    return None


def _log(value: float) -> float:
    return math.log10(1.0 + max(value, 0.0))


def _answer(label: Label | None, key: str) -> tuple[str | float | None, float]:
    if label is None or key not in label.answers:
        return None, 0.0
    answer = label.answers[key]
    return answer.value, answer.confidence or 0.0


def _model(item: PulseItem, label: Label | None):
    kind = item.kind or "unknown"
    if kind not in MODEL_BASE:
        return 0.0, Bucket.HIDDEN, [f"{kind} of {item.parent or 'another model'}"]
    reasons = [kind]
    bucket = Bucket.TOP
    if kind == "unknown":
        value, confidence = _answer(label, "new_model")
        if not isinstance(value, float) or value < 0.5:
            return 0.0, Bucket.HIDDEN, ["unknown origin, not judged a new model"]
        reasons.append(f"judged a new model ({value:.2f})")
        if confidence < CONFIDENT:
            bucket = Bucket.UNCERTAIN
    likes, downloads = item.signals.get("likes", 0.0), item.signals.get("downloads", 0.0)
    score = MODEL_BASE[kind] + _log(likes) + 0.5 * _log(downloads)
    reasons.append(f"{int(likes)} likes, {int(downloads)} downloads")
    return score, bucket, reasons


def _paper(item: PulseItem, label: Label | None):
    upvotes = item.signals.get("upvotes", 0.0)
    score = 2.0 * _log(upvotes)
    reasons = [f"{int(upvotes)} upvotes"]
    topic, _ = _answer(label, "topic")
    if isinstance(topic, str):
        score += PAPER_TOPIC_BONUS.get(topic, 0.0)
        reasons.append(topic)
    usable, _ = _answer(label, "usable_now")
    if isinstance(usable, float) and usable >= 0.5:
        score += 1.0
        reasons.append("releases code/weights")
    return score, Bucket.TOP, reasons


def _repo(item: PulseItem, label: Label | None):
    kind, confidence = _answer(label, "kind")
    if isinstance(kind, str) and kind not in REPO_KEPT_KINDS:
        bucket = Bucket.HIDDEN if confidence >= CONFIDENT else Bucket.UNCERTAIN
        return 0.0, bucket, [kind]
    velocity = item.signals.get("stars_per_day", 0.0)
    reasons = [f"{velocity:g} stars/day"] + ([kind] if isinstance(kind, str) else [])
    bucket = Bucket.TOP if confidence >= CONFIDENT else Bucket.UNCERTAIN
    return 2.0 * _log(velocity), bucket, reasons


def _news(item: PulseItem, label: Label | None):
    event, confidence = _answer(label, "event")
    if not isinstance(event, str):
        return 0.0, Bucket.UNCERTAIN, ["not triaged yet"]
    if event in NEWS_HIDDEN_EVENTS:
        bucket = Bucket.HIDDEN if confidence >= CONFIDENT else Bucket.UNCERTAIN
        return 0.0, bucket, [event]
    authority = NEWS_SOURCE_WEIGHT.get(item.source, NEWS_DEFAULT_SOURCE_WEIGHT)
    score = NEWS_EVENT_WEIGHT.get(event, 0.0) * max(confidence, 0.3) * authority
    bucket = Bucket.TOP if confidence >= CONFIDENT else Bucket.UNCERTAIN
    return score, bucket, [f"{event} ({confidence:.2f})", f"{item.source} x{authority:g}"]
