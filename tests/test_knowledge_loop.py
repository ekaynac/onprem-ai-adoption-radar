"""The evolving knowledge loop: classifications teach the gates.

Guarantees under test:
- relevant classifications' component slugs land in data/knowledge/vocab.jsonl
  exactly once, noise never does;
- learned terms sharpen both gates (news ranking + desk serving signal)
  without any code change;
- defaults still work when nothing has been learned yet.
"""

from __future__ import annotations

from datetime import UTC, datetime

from radar.discovery.news_gate import rank_by_relevance, relevance_score
from radar.knowledge import (
    learn_from_classifications,
    load_learned_terms,
    merge_terms,
    vocabulary_path,
)
from radar.reports.brief import _serving_stack_signal
from radar.storage.news_log import NewsClassification


NOW = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)


def classification(
    news_id: str,
    components: list[str],
    *,
    relevant: bool = True,
) -> NewsClassification:
    return NewsClassification(
        news_id=news_id,
        relevant=relevant,
        event_type="release",
        components=components,
        operational_impact="improvement",
        summary="s",
        citation="https://x/1",
        model="claude-opus-5",
        classified_at=NOW,
    )


def test_relevant_components_are_learned_once_noise_never(tmp_path) -> None:
    learned = learn_from_classifications(
        tmp_path,
        [
            classification("n1", ["vllm", "Dynamo"]),
            classification("n2", ["dynamo"]),  # duplicate — no second row
            classification("n3", ["consumer-app"], relevant=False),
        ],
        now=NOW,
    )
    assert learned == 2  # vllm + dynamo are both new to the store
    # Re-learning an already-known term is a no-op.
    again = learn_from_classifications(
        tmp_path, [classification("n4", ["dynamo"])], now=NOW
    )
    assert again == 0
    terms = load_learned_terms(tmp_path)
    assert terms == ["dynamo", "vllm"]  # newest first
    assert vocabulary_path(tmp_path).exists()


def test_learned_terms_sharpen_news_ranking() -> None:
    from radar.storage.news_log import NewsItem

    def item(title: str) -> NewsItem:
        return NewsItem(
            id=f"news:{title}",
            source_id="hn",
            title=title,
            url="https://x/1",
            observed_at=NOW,
        )

    new_engine = item("Nvidia Dynamo 2.0 doubles serving throughput")
    unrelated = item("Startup raises $80M Series B")

    # Cold start: no learned terms, defaults may not catch "Dynamo".
    base_score = relevance_score(new_engine, learned_serving_terms=[])
    sharp = relevance_score(
        new_engine, learned_serving_terms=["dynamo"]
    )
    assert sharp > base_score

    ranked = rank_by_relevance(
        [unrelated, new_engine], learned_serving_terms=["dynamo"]
    )
    assert ranked[0] is new_engine


def test_learned_terms_unlock_desk_evaluate_verdict() -> None:
    # Deliberately free of bundled-default terms: "dynamo" alone is unknown
    # to the cold-start vocabulary.
    description = "Nvidia Dynamo 2.0: disaggregated prefill for multi-node runs"
    cold = _serving_stack_signal(description, extra_terms=[])
    # After the analyst classified a Dynamo release, its slug is known.
    warm = _serving_stack_signal(description, extra_terms=["dynamo"])
    assert not cold and warm


def test_merge_puts_learned_first_and_dedupes() -> None:
    merged = merge_terms(["dynamo", "vllm"], ["VLLM", "ollama"])
    assert merged == ["dynamo", "vllm", "ollama"]


def test_task_suite_overrides_extend_advisor_mapping(tmp_path) -> None:
    from radar.knowledge import learn_task_suite, load_task_suite_overrides
    from radar.models_radar.advisor import TASKS, build_answers

    assert load_task_suite_overrides(tmp_path) == {}
    assert learn_task_suite(tmp_path, "coding", "ollb-average")
    assert not learn_task_suite(
        tmp_path, "coding", "ollb-average"
    )  # exactly-once

    overrides = load_task_suite_overrides(tmp_path)
    assert overrides == {"coding": ["ollb-average"]}
    assert "ollb-average" not in TASKS["coding"]["benchmarks"]

    profiles = {
        "dual-suite": {
            "id": "dual-suite",
            "name": "Dual Suite",
            "family": "Dual",
            "modality": "text",
            "ring": "adopt",
            "score": 4.0,
            "license": "apache-2.0",
            "params_total": 8_000_000_000,
            "num_layers": 32,
            "hidden_size": 4096,
            "context_length": 32768,
            "quants": [{"format": "GGUF Q4_K_M", "bits_per_weight": 4.5, "source": "manual"}],
            "benchmark_aggregates": [
                {"benchmark": "aider-polyglot", "percentile": 60},
                {"benchmark": "ollb-average", "percentile": 70},
            ],
        }
    }
    answer = build_answers(profiles, "rtx-4090-24gb", "coding", root=tmp_path)
    first = answer["candidates"][0]
    # The taught suite counts toward the two-source evidence bar: without
    # the override this candidate is single-source.
    assert first["evidence_tier"] == "sufficient"
