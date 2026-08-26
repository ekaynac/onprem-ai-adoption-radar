"""The Desk brief: what happened → what it means → a falsifiable call.

Deterministic weekly analyst brief assembled from the radar's own
append-only stores. Every item states what happened, why an on-prem
operator should care, a verdict (act / evaluate / ignore) produced by
the documented rules below, and receipts. Verdict rules are code, not
vibes — the same inputs always produce the same brief, and every
act/evaluate verdict lands in the public calls ledger to be scored.

Verdict rules (v1):
- Ring promoted to adopt → act ("start a production pilot path").
- Ring promoted to pilot / new at pilot+ → evaluate.
- Ring demoted → act when leaving adopt (review usage), else evaluate.
- Benchmark consensus moved ≥ 3 points on an independent source →
  evaluate (up: challenger; down: regression check).
- New (< 14 days) trending repo with star velocity ≥ 200/day in the
  on-prem lane → evaluate; below → ignore (recorded, so the miss is
  scoreable too).
- Newsroom item classified ``breaking`` → evaluate (an operator must
  assess exposure); ``improvement``/``informational`` stay newsroom-only.
- Newsroom item classified ``hardware-launch`` → evaluate (a new
  platform is a hardware-catalog candidate; curation stays human).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)

BRIEF_VERSION = "brief-v1"
BENCHMARK_MOVE_POINTS = 3.0
TRENDING_VELOCITY_THRESHOLD = 200.0

# A new repo must show serving-stack signal in its description to earn an
# "evaluate" verdict — raw star velocity alone promotes agent apps and
# consumer tools into operator queues. Cold-start terms below; the live
# gate merges in the learned vocabulary (radar.knowledge) so recognized
# components evolve without code changes.
_SERVING_SIGNAL_TERMS = (
    "vllm", "llama.cpp", "llama-cpp", "ollama", "tgi", "sglang",
    "tensorrt", "lmdeploy", "inference", "serving", "quantiz", "gguf",
    "awq", "gptq", "fine-tun", "finetun", "lora", "rag", "embedding",
    "gpu", "vram", "self-host", "on-prem", "local llm", "local-llm",
    "kv-cache", "speculative", "benchmark", "tokens per second",
)


def _serving_stack_signal(description: str | None, extra_terms: list[str] | None = None) -> bool:
    if not description:
        return True  # no evidence either way — keep legacy behavior
    haystack = description.lower()
    for term in extra_terms or ():
        if term.lower() in haystack:
            return True
    return any(term in haystack for term in _SERVING_SIGNAL_TERMS)
_WINDOW_DAYS = 7
_SPOTLIGHT_TASKS = ("coding", "general-chat", "reasoning", "rag")
_SPOTLIGHT_DEVICES = ("rtx-4090-24gb", "a100-80gb", "h100-80gb", "mac-128gb")


def brief_id_for(now: datetime) -> str:
    year, week, _ = now.isocalendar()
    return f"brief-{year}-W{week:02d}"


def _slug(value: str) -> str:
    return "".join(
        character if character.isalnum() else "-"
        for character in value.casefold()
    ).strip("-")


def _item(
    brief_id: str,
    section: str,
    subject: str,
    what_happened: str,
    why_it_matters: str,
    verdict: str,
    rationale: str,
    receipts: list[str],
    observed_at: str | None,
) -> dict[str, Any]:
    return {
        "id": f"call:{brief_id}:{section}:{_slug(subject)}",
        "section": section,
        "subject": subject,
        "what_happened": what_happened,
        "why_it_matters": why_it_matters,
        "verdict": verdict,
        "rationale": rationale,
        "receipts": receipts,
        "observed_at": observed_at,
    }


def _ring_move_items(
    brief_id: str,
    root: Path,
    cutoff: datetime,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []

    def verdict_for(change_type: str, ring: str, previous: str | None):
        if change_type == "promoted" and ring == "adopt":
            return "act", "Promotion into adopt: start a production pilot path"
        if change_type == "demoted" and previous == "adopt":
            return "act", "Left adopt: review current usage before upgrading"
        if change_type in {"promoted", "new"} and ring in {"adopt", "pilot"}:
            return "evaluate", f"Entered {ring}: worth a scoped evaluation"
        return "evaluate", f"Ring changed to {ring}: reassess posture"

    try:
        from radar.models_radar.history import load_model_events

        for event in load_model_events(root / "data" / "model-history.jsonl"):
            if event.observed_at < cutoff:
                continue
            ring = event.ring.value
            previous = event.previous_ring.value if event.previous_ring else None
            verdict, rationale = verdict_for(
                event.change_type.value, ring, previous
            )
            arrow = f"{previous} → {ring}" if previous else f"new → {ring}"
            items.append(
                _item(
                    brief_id,
                    "ring-moves",
                    event.model_id,
                    f"Model ring {arrow} ({event.change_type.value})",
                    "Curated rings are the radar's deterministic adoption "
                    "verdicts; a move is a change in deployment advice",
                    verdict,
                    rationale,
                    ["data/model-history.jsonl"],
                    event.observed_at.isoformat(),
                )
            )
    except Exception as exc:
        logger.warning("Brief: model ring-move scan failed: %s", exc)
    try:
        from radar.storage.history_log import load_events

        for project_event in load_events(root / "data" / "history.jsonl"):
            if project_event.observed_at < cutoff:
                continue
            ring = project_event.ring.value
            previous = (
                project_event.previous_ring.value
                if project_event.previous_ring
                else None
            )
            verdict, rationale = verdict_for(
                project_event.change_type.value, ring, previous
            )
            arrow = f"{previous} → {ring}" if previous else f"new → {ring}"
            items.append(
                _item(
                    brief_id,
                    "ring-moves",
                    project_event.project,
                    f"Project ring {arrow} ({project_event.change_type.value})",
                    "Project rings track the serving/tooling stack around "
                    "the models",
                    verdict,
                    rationale,
                    ["data/history.jsonl"],
                    project_event.observed_at.isoformat(),
                )
            )
    except Exception as exc:
        logger.warning("Brief: project ring-move scan failed: %s", exc)
    return items


def _benchmark_move_items(
    brief_id: str,
    root: Path,
    cutoff: datetime,
) -> list[dict[str, Any]]:
    try:
        from radar.storage.benchmark_observations_log import (
            load_benchmark_observations,
        )

        observations = load_benchmark_observations(
            root / "data" / "benchmark-observations.jsonl"
        )
    except Exception as exc:
        logger.warning("Brief: benchmark observations unreadable: %s", exc)
        return []
    by_key: dict[tuple[str, str, str], list[Any]] = {}
    for observation in observations:
        by_key.setdefault(
            (
                observation.model_id,
                observation.benchmark,
                observation.source_id,
            ),
            [],
        ).append(observation)
    items: list[dict[str, Any]] = []
    for (model_id, benchmark, source_id), rows in sorted(by_key.items()):
        rows.sort(key=lambda row: row.observed_at)
        latest = rows[-1]
        if latest.observed_at < cutoff or len(rows) < 2:
            continue
        previous = rows[-2]
        delta = round(latest.score - previous.score, 2)
        if abs(delta) < BENCHMARK_MOVE_POINTS:
            continue
        direction = "up" if delta > 0 else "down"
        items.append(
            _item(
                brief_id,
                "benchmark-moves",
                f"{model_id} · {benchmark}",
                f"{benchmark} moved {delta:+g} points on {source_id} "
                f"({previous.score:g} → {latest.score:g})",
                "Independent benchmark movement changes the capability "
                "ranking the Answer Machine uses",
                "evaluate",
                (
                    "Re-rank candidates for affected tasks"
                    if direction == "up"
                    else "Check for a regression or methodology change"
                ),
                [latest.source_url],
                latest.observed_at.isoformat(),
            )
        )
    return items


def _trending_items(
    brief_id: str,
    root: Path,
    now: datetime,
) -> list[dict[str, Any]]:
    try:
        from radar.discovery.trending_detect import build_trending
        from radar.knowledge import load_learned_terms
        from radar.storage.trending_observations_log import load_observations

        learned_terms = load_learned_terms(root)
        entries = build_trending(
            load_observations(root / "data" / "trending-observations.jsonl"),
            now,
        )
    except Exception as exc:
        logger.warning("Brief: trending derivation failed: %s", exc)
        return []
    items: list[dict[str, Any]] = []
    for entry in entries:
        if not entry.is_new or entry.lane.value != "onprem":
            continue
        velocity = entry.velocity_per_day
        if velocity is None:
            continue
        significant = velocity >= TRENDING_VELOCITY_THRESHOLD
        serving_signal = _serving_stack_signal(
            entry.description, extra_terms=learned_terms
        )
        if significant and not serving_signal:
            significant = False
            velocity_note = (
                f"Velocity ≥ {TRENDING_VELOCITY_THRESHOLD:g}/day but no "
                "serving-stack signal in the description — demoted to "
                "ignore so agent apps don't queue operators"
            )
            rationale = velocity_note
            summary = entry.description or "Newly created on-prem-lane repository"
        elif significant:
            rationale = (
                f"Velocity ≥ {TRENDING_VELOCITY_THRESHOLD:g}/day: "
                "look before the crowd arrives"
            )
            summary = entry.description or "Newly created on-prem-lane repository"
        else:
            rationale = (
                f"Velocity below {TRENDING_VELOCITY_THRESHOLD:g}/day "
                "threshold — recorded so the miss is scoreable"
            )
            summary = entry.description or "Newly created on-prem-lane repository"
        items.append(
            _item(
                brief_id,
                "new-repos",
                entry.repo,
                f"New repo at {velocity:+g} stars/day ({entry.stars} total)",
                summary,
                "evaluate" if significant else "ignore",
                rationale,
                [f"https://github.com/{entry.repo}"],
                None,
            )
        )
    items.sort(key=lambda item: item["verdict"] != "evaluate")
    return items[:8]


def _news_items(
    brief_id: str,
    root: Path,
    cutoff: datetime,
) -> list[dict[str, Any]]:
    try:
        from radar.storage.news_log import (
            load_news_classifications,
            load_news_items,
        )

        items_by_id = {
            item.id: item
            for item in load_news_items(
                root / "data" / "news-observations.jsonl"
            )
        }
        classifications = load_news_classifications(
            root / "data" / "news-classified.jsonl"
        )
    except Exception as exc:
        logger.warning("Brief: news classifications unreadable: %s", exc)
        return []
    rows: list[dict[str, Any]] = []
    for classification in classifications:
        if not classification.relevant:
            continue
        is_breaking = classification.operational_impact == "breaking"
        is_hardware = classification.event_type == "hardware-launch"
        if not (is_breaking or is_hardware):
            continue
        item = items_by_id.get(classification.news_id)
        if item is None:
            continue
        observed = item.published_at or classification.classified_at
        if observed < cutoff:
            continue
        if is_breaking:
            section = "news"
            why = (
                "Classified as breaking for on-prem operators: action may "
                "be required on "
                + ", ".join(classification.components or ["the stack"])
            )
            rationale = "Assess exposure before the next upgrade window"
        else:
            section = "hardware"
            why = (
                "A newly launched platform is a hardware-catalog "
                "candidate; specs enter the catalog only with a verifiable "
                "source"
            )
            rationale = "Review for the device catalog (curation stays human)"
        rows.append(
            _item(
                brief_id,
                section,
                item.title,
                classification.summary,
                why,
                "evaluate",
                rationale,
                [classification.citation or item.url],
                observed.isoformat(),
            )
        )
    rows.sort(key=lambda row: row["observed_at"] or "", reverse=True)
    return rows[:12]


def _spotlight(brief_id: str, root: Path, now: datetime) -> dict[str, Any] | None:
    try:
        from radar.models_radar.advisor import TASKS, build_answers
        from radar.web.public_context import load_public_model_profiles

        _, week, _ = now.isocalendar()
        task = _SPOTLIGHT_TASKS[week % len(_SPOTLIGHT_TASKS)]
        device = _SPOTLIGHT_DEVICES[week % len(_SPOTLIGHT_DEVICES)]
        answer = build_answers(
            load_public_model_profiles(root),
            device,
            task,
            limit=3,
        )
        if not answer["candidates"]:
            return None
        top = answer["candidates"][0]
        return {
            "task": task,
            "task_label": TASKS[task]["label"],
            "device": device,
            "top_candidate": {
                "model_id": top["model_id"],
                "name": top["name"],
                "ring": top["ring"],
                "fit_verdict": top["fit"]["verdict"],
                "reasons": top["reasons"],
            },
            "note": (
                f"This week's worked answer: {TASKS[task]['label']} on "
                f"{device} → {top['name']}"
            ),
        }
    except Exception as exc:
        logger.warning("Brief: advisor pick for task=%s failed: %s", task, exc)
        return None


def build_brief(root: Path, now: datetime | None = None) -> dict[str, Any]:
    current = now or datetime.now(UTC)
    cutoff = current - timedelta(days=_WINDOW_DAYS)
    brief_id = brief_id_for(current)
    items = [
        *_ring_move_items(brief_id, root, cutoff),
        *_benchmark_move_items(brief_id, root, cutoff),
        *_trending_items(brief_id, root, current),
        *_news_items(brief_id, root, cutoff),
    ]
    verdict_counts = {"act": 0, "evaluate": 0, "ignore": 0}
    for item in items:
        verdict_counts[item["verdict"]] += 1
    return {
        "version": BRIEF_VERSION,
        "id": brief_id,
        "generated_at": current.isoformat(),
        "window_days": _WINDOW_DAYS,
        "items": items,
        "verdict_counts": verdict_counts,
        "spotlight": _spotlight(brief_id, root, current),
        "verdict_rules": (
            "Deterministic v1 rules: adopt-promotions and adopt-exits are "
            "act; pilot entries, ≥3-point independent benchmark moves, "
            "new on-prem repos at ≥200 stars/day, news classified as "
            "breaking, and hardware-launch news (catalog candidates) are "
            "evaluate; slower new repos are ignore (recorded, so misses "
            "score too)"
        ),
    }
