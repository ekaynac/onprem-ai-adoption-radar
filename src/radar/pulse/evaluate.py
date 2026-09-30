"""The owner's gold set: the only ground truth for "should I have seen this?".

Claude's 2,487 newsroom labels answer an older question (relevance to on-prem
operators), so they are a silver check at best. The gold set is a Markdown
checklist the owner ticks in any editor; ``evaluate`` scores a ranking's TOP
bucket against those ticks, per lane.
"""

from __future__ import annotations

import random
import re
from collections.abc import Iterable
from dataclasses import dataclass

from radar.pulse.items import Lane, PulseItem
from radar.pulse.rank import Bucket, RankedItem


GOLD_LINE = re.compile(r"^- \[(?P<mark>[ xX])\] .*<!-- (?P<id>[a-z]+:[^ ]+) -->\s*$")
DEFAULT_PER_LANE = {Lane.NEWS: 50, Lane.PAPER: 25, Lane.REPO: 25, Lane.MODEL: 20}


def sample_gold(
    items: Iterable[PulseItem],
    per_lane: dict[Lane, int],
    seed: int,
) -> list[PulseItem]:
    """Stratified random sample per lane, independent of any classifier output."""
    rng = random.Random(seed)
    by_lane: dict[Lane, list[PulseItem]] = {}
    for item in sorted(items, key=lambda i: i.id):
        by_lane.setdefault(item.lane, []).append(item)
    chosen: list[PulseItem] = []
    for lane in Lane:
        pool = by_lane.get(lane, [])
        chosen.extend(rng.sample(pool, min(per_lane.get(lane, 0), len(pool))))
    return chosen


def render_gold(items: list[PulseItem], title: str) -> str:
    lines = [
        f"# {title}",
        "",
        "Tick `[x]` every item you would have wanted to see in your weekly AI",
        "radar. Leave the rest unticked. Do not edit the `<!-- id -->` comments.",
        "",
    ]
    for lane in Lane:
        lane_items = [i for i in items if i.lane is lane]
        if not lane_items:
            continue
        lines += [f"## {lane.value}", ""]
        for item in lane_items:
            context = f" — {item.summary[:140]}" if item.summary else ""
            name = item.key if item.lane is Lane.MODEL else item.title  # keep the org visible
            lines.append(f"- [ ] [{_one_line(name)}]({item.url}){_one_line(context)}"
                         f" <!-- {item.id} -->")
        lines.append("")
    return "\n".join(lines)


def parse_gold(text: str) -> dict[str, bool]:
    marks: dict[str, bool] = {}
    for line in text.splitlines():
        match = GOLD_LINE.match(line.strip())
        if match:
            marks[match["id"]] = match["mark"] in {"x", "X"}
    return marks


@dataclass(frozen=True)
class LaneScore:
    lane: str
    labelled: int
    wanted: int
    shown: int
    hits: int

    @property
    def precision(self) -> float:
        return self.hits / self.shown if self.shown else 0.0

    @property
    def recall(self) -> float:
        return self.hits / self.wanted if self.wanted else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if p + r else 0.0


def evaluate(ranked: Iterable[RankedItem], gold: dict[str, bool]) -> list[LaneScore]:
    """Score "shown in TOP" against the owner's ticks, per lane."""
    buckets: dict[str, list[tuple[bool, bool]]] = {}
    for entry in ranked:
        wanted = gold.get(entry.item.id)
        if wanted is None:
            continue
        buckets.setdefault(entry.item.lane.value, []).append(
            (wanted, entry.bucket is Bucket.TOP)
        )
    return [
        LaneScore(
            lane=lane,
            labelled=len(rows),
            wanted=sum(w for w, _ in rows),
            shown=sum(s for _, s in rows),
            hits=sum(w and s for w, s in rows),
        )
        for lane, rows in sorted(buckets.items())
    ]


def _one_line(text: str) -> str:
    return " ".join(text.replace("<!--", "").replace("-->", "").split())
