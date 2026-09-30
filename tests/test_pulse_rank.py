"""Deterministic ranking over triage facts; cases from the 2026-09-30 live run."""

from __future__ import annotations

from datetime import UTC, datetime

from radar.pulse.classify import Answer, Label
from radar.pulse.items import Lane, PulseItem
from radar.pulse.rank import Bucket, rank


NOW = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)


def _item(lane: Lane, key: str, source: str = "x", **extra) -> PulseItem:
    return PulseItem(lane=lane, key=key, title=key, url="https://example.com/" + key.replace("/", "-"),
                     source=source, first_seen=NOW, last_seen=NOW, **extra)


def _label(item: PulseItem, **answers: tuple[str | float, float]) -> Label:
    return Label(
        item_id=item.id, content_hash="h", question_version=1, engine="jev",
        answers={k: Answer(value=v, confidence=c) for k, (v, c) in answers.items()},
        labeled_at=NOW,
    )


def test_official_lab_launch_outranks_a_show_hn_hobby_release() -> None:
    launch = _item(Lane.NEWS, "Introducing GPT-6.1 Sol", source="openai-news")
    hobby = _item(Lane.NEWS, "I made an LLM using 521 Jev models", source="hn-vllm")
    labels = {
        launch.id: _label(launch, event=("model-release", 1.0)),
        hobby.id: _label(hobby, event=("model-release", 1.0)),
    }

    ranked = rank([hobby, launch], labels)

    assert [r.item.key for r in ranked] == [launch.key, hobby.key]
    assert any("openai-news" in reason for reason in ranked[0].reasons)


def test_customer_stories_are_hidden_and_low_confidence_is_uncertain() -> None:
    story = _item(Lane.NEWS, "Airbnb widens access to GPT-6 Astra", source="openai-news")
    unsure = _item(Lane.NEWS, "Maybe a release", source="hf-blog")
    labels = {
        story.id: _label(story, event=("customer-story", 0.9)),
        unsure.id: _label(unsure, event=("tool-release", 0.3)),
    }

    by_key = {r.item.key: r for r in rank([story, unsure], labels)}

    assert by_key[story.key].bucket is Bucket.HIDDEN
    assert by_key[unsure.key].bucket is Bucket.UNCERTAIN


def test_untriaged_news_is_uncertain_never_silently_top() -> None:
    item = _item(Lane.NEWS, "fresh", source="openai-news")

    assert rank([item], {})[0].bucket is Bucket.UNCERTAIN


def test_models_rank_originals_and_hide_repacks() -> None:
    release = _item(Lane.MODEL, "XiaomiMiMo/MiMo-V2.6-Pro-RL", kind="original",
                    signals={"likes": 603, "downloads": 78135})
    repack = _item(Lane.MODEL, "nvidia/DeepSeek-V4.1-Flash-NVFP4", kind="derivative",
                   parent="deepseek-ai/DeepSeek-V4.1-Flash", signals={"likes": 93})
    unknown_new = _item(Lane.MODEL, "newlab/Aurora-7B", kind="unknown", signals={"likes": 5})
    unknown_copy = _item(Lane.MODEL, "someone/copy-7B", kind="unknown", signals={"likes": 500})
    labels = {
        unknown_new.id: _label(unknown_new, new_model=(0.9, 0.8)),
        unknown_copy.id: _label(unknown_copy, new_model=(0.1, 0.8)),
    }

    by_key = {r.item.key: r for r in rank([repack, unknown_copy, unknown_new, release], labels)}

    assert by_key[release.key].bucket is Bucket.TOP
    assert by_key[unknown_new.key].bucket is Bucket.TOP
    assert by_key[repack.key].bucket is Bucket.HIDDEN
    assert "derivative of deepseek-ai/DeepSeek-V4.1-Flash" in by_key[repack.key].reasons
    assert by_key[unknown_copy.key].bucket is Bucket.HIDDEN
    assert by_key[release.key].score > by_key[unknown_new.key].score


def test_repos_hide_confident_lists_and_rank_tools_by_velocity() -> None:
    fast = _item(Lane.REPO, "yetone/magpie", signals={"stars_per_day": 477.2})
    slow = _item(Lane.REPO, "incoai/splash", signals={"stars_per_day": 80.1})
    listicle = _item(Lane.REPO, "pallavi/ai-interview-questions", signals={"stars_per_day": 134.7})
    labels = {
        fast.id: _label(fast, kind=("tool", 0.9)),
        slow.id: _label(slow, kind=("tool", 0.9)),
        listicle.id: _label(listicle, kind=("list-course", 0.95)),
    }

    ranked = rank([listicle, slow, fast], labels)

    assert [r.item.key for r in ranked if r.bucket is Bucket.TOP] == [fast.key, slow.key]
    assert ranked[-1].bucket is Bucket.HIDDEN


def test_papers_reward_upvotes_practical_topics_and_releases() -> None:
    usable = _item(Lane.PAPER, "2609.1", signals={"upvotes": 50})
    theory = _item(Lane.PAPER, "2609.2", signals={"upvotes": 50})
    labels = {
        usable.id: _label(usable, topic=("inference-efficiency", 0.9), usable_now=(0.9, 0.8)),
        theory.id: _label(theory, topic=("other", 0.9), usable_now=(0.1, 0.8)),
    }

    ranked = rank([theory, usable], labels)

    assert ranked[0].item.key == usable.key
    assert "releases code/weights" in ranked[0].reasons


def test_engine_reports_lineage_for_deterministic_models_and_none_when_untriaged() -> None:
    release = _item(Lane.MODEL, "Qwen/Qwen3.8-27B", kind="original")
    unknown = _item(Lane.MODEL, "newlab/Aurora-7B", kind="unknown")
    news = _item(Lane.NEWS, "fresh", source="openai-news")

    engines = {r.item.key: r.engine for r in rank([release, unknown, news], {})}

    assert engines == {"Qwen/Qwen3.8-27B": "lineage", "newlab/Aurora-7B": None, "fresh": None}
