"""Label the items that need it, with Jev first and rules as the floor.

Nothing here is silent: every fallback, budget stop and circuit break lands
in the report, and every label says which engine made it.
"""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from radar.pulse.classify import Engine, Label, RulesEngine, content_hash
from radar.pulse.items import Lane, PulseItem
from radar.pulse.questions import QuestionSet


logger = logging.getLogger(__name__)

LABELS_PATH = Path("data") / "pulse" / "labels.jsonl"
MAX_CONCURRENCY = 8
CIRCUIT_BREAK_AFTER = 5  # consecutive primary failures before giving up this run


@dataclass
class TriageReport:
    labels: list[Label] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    input_tokens: int = 0
    budget_exhausted: bool = False
    circuit_open: bool = False

    @property
    def engine_counts(self) -> dict[str, int]:
        return dict(Counter(label.engine for label in self.labels))


def needs_triage(item: PulseItem) -> bool:
    # Deterministic lineage already settled everything but UNKNOWN models.
    return item.lane is not Lane.MODEL or item.kind == "unknown"


def pending(
    items: Iterable[PulseItem],
    questions: QuestionSet,
    existing: dict[str, Label],
    primary_available: bool,
) -> list[PulseItem]:
    todo = []
    for item in items:
        if not needs_triage(item) or not questions.for_lane(item.lane):
            continue
        label = existing.get(item.id)
        fresh = (
            label is not None
            and label.content_hash == content_hash(item)
            and label.question_version == questions.version
        )
        if not fresh or (primary_available and label is not None and label.engine == "rules"):
            todo.append(item)
    return todo


async def triage(
    items: list[PulseItem],
    questions: QuestionSet,
    primary: Engine | None,
    now: datetime,
    token_budget: int,
) -> TriageReport:
    report = TriageReport()
    rules = RulesEngine()
    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
    consecutive_failures = 0

    async def label_one(item: PulseItem) -> None:
        nonlocal consecutive_failures
        lane_questions = questions.for_lane(item.lane)
        async with semaphore:
            use_primary = (
                primary is not None
                and not report.circuit_open
                and not report.budget_exhausted
            )
            if use_primary:
                assert primary is not None
                try:
                    answers, model, tokens = await primary.answer(item, lane_questions)
                    consecutive_failures = 0
                    report.input_tokens += tokens
                    if report.input_tokens >= token_budget:
                        report.budget_exhausted = True
                    report.labels.append(_label(item, questions, primary.name, model,
                                                answers, tokens, now))
                    return
                except Exception as exc:
                    consecutive_failures += 1
                    report.errors.append(f"{item.id}: {type(exc).__name__}: {exc}")
                    if consecutive_failures >= CIRCUIT_BREAK_AFTER:
                        report.circuit_open = True
            answers, model, tokens = await rules.answer(item, lane_questions)
            report.labels.append(_label(item, questions, rules.name, model, answers, tokens, now))

    await asyncio.gather(*(label_one(item) for item in items))
    return report


def _label(item, questions, engine, model, answers, tokens, now) -> Label:
    return Label(
        item_id=item.id, content_hash=content_hash(item),
        question_version=questions.version, engine=engine, model=model,
        answers=answers, input_tokens=tokens, labeled_at=now,
    )


def load_labels(path: Path) -> dict[str, Label]:
    """Latest label per item; a Jev label is never replaced by a later rules one
    for the same content (a fallback run must not erase a better answer)."""
    latest: dict[str, Label] = {}
    if not path.exists():
        return latest
    with path.open(encoding="utf-8") as handle:
        for line_no, raw in enumerate(handle, start=1):
            if not raw.strip():
                continue
            try:
                label = Label.model_validate_json(raw)
            except ValidationError as exc:
                logger.warning("Skipping corrupt label line %d in %s: %s", line_no, path, exc)
                continue
            current = latest.get(label.item_id)
            downgrade = (
                current is not None
                and current.engine != "rules"
                and label.engine == "rules"
                and current.content_hash == label.content_hash
                and current.question_version == label.question_version
            )
            if not downgrade:
                latest[label.item_id] = label
    return latest


def append_labels(path: Path, labels: Iterable[Label]) -> None:
    rows = [label.model_dump_json() for label in labels]
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(rows) + "\n")


def prune_labels(path: Path, keep_ids: set[str]) -> None:
    """Rewrite the log with only the current label of live items."""
    latest = load_labels(path)
    kept = [label for item_id, label in latest.items() if item_id in keep_ids]
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("".join(label.model_dump_json() + "\n" for label in kept), encoding="utf-8")
    tmp.replace(path)
