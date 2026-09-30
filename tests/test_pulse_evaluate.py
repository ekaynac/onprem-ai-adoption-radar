"""Gold-set sampling, checklist round trip, and per-lane scoring."""

from __future__ import annotations

from datetime import UTC, datetime

from radar.pulse.evaluate import evaluate, parse_gold, render_gold, sample_gold
from radar.pulse.items import Lane, PulseItem
from radar.pulse.rank import Bucket, RankedItem


NOW = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)


def _item(lane: Lane, key: str, summary: str | None = None) -> PulseItem:
    return PulseItem(lane=lane, key=key, title=f"Title {key}", url=f"https://example.com/{key}",
                     source="s", first_seen=NOW, last_seen=NOW, summary=summary)


def test_sampling_is_stratified_and_reproducible() -> None:
    items = [_item(Lane.NEWS, f"n{i}") for i in range(30)] + [_item(Lane.PAPER, f"p{i}") for i in range(3)]

    first = sample_gold(items, {Lane.NEWS: 10, Lane.PAPER: 5}, seed=1)
    again = sample_gold(list(reversed(items)), {Lane.NEWS: 10, Lane.PAPER: 5}, seed=1)

    assert [i.id for i in first] == [i.id for i in again]
    assert sum(i.lane is Lane.NEWS for i in first) == 10
    assert sum(i.lane is Lane.PAPER for i in first) == 3  # pool smaller than quota


def test_rendered_checklist_round_trips_owner_ticks() -> None:
    items = [_item(Lane.NEWS, "a", summary="has --> arrow and <!-- comment"), _item(Lane.REPO, "o/r")]
    text = render_gold(items, "Gold")
    ticked = text.replace("- [ ] [Title a]", "- [x] [Title a]")

    assert parse_gold(text) == {"news:a": False, "repo:o/r": False}
    assert parse_gold(ticked) == {"news:a": True, "repo:o/r": False}


def test_evaluate_scores_top_bucket_against_ticks() -> None:
    items = {k: _item(Lane.NEWS, k) for k in "abcd"}
    ranked = [
        RankedItem(items["a"], 5.0, Bucket.TOP, ()),  # wanted, shown -> hit
        RankedItem(items["b"], 4.0, Bucket.TOP, ()),  # not wanted, shown -> false positive
        RankedItem(items["c"], 0.0, Bucket.HIDDEN, ()),  # wanted, hidden -> miss
        RankedItem(items["d"], 0.0, Bucket.HIDDEN, ()),  # not wanted, hidden -> correct
    ]
    gold = {"news:a": True, "news:b": False, "news:c": True, "news:d": False}

    [score] = evaluate(ranked, gold)

    assert (score.labelled, score.wanted, score.shown, score.hits) == (4, 2, 2, 1)
    assert score.precision == 0.5 and score.recall == 0.5 and score.f1 == 0.5
