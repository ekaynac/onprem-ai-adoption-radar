"""Tests for paper-related models."""

import pytest
from pydantic import ValidationError

from radar.models import EnrichmentConfig, PaperRef, ProjectEvidence, SourceConfig


def test_paper_ref_is_frozen():
    ref = PaperRef(title="FlashInfer-2", url="https://arxiv.org/abs/2506.1", published_at="2026-06-10")
    with pytest.raises(ValidationError):
        ref.title = "x"  # type: ignore[misc]


def test_source_config_paper_query_defaults_none():
    src = SourceConfig(
        id="github-vllm", type="github_repo", project="vLLM",
        category="model_serving", url="https://github.com/vllm-project/vllm",
    )
    assert src.paper_query is None
    src2 = src.model_copy(update={"paper_query": '"vLLM"'})
    assert src2.paper_query == '"vLLM"'


def test_enrichment_config_arxiv_defaults_true():
    assert EnrichmentConfig().arxiv is True


def test_project_evidence_carries_papers_and_count():
    ev = ProjectEvidence(
        paper_mentions=3,
        papers=[PaperRef(title="P", url="https://arxiv.org/abs/1", published_at="2026-06-10")],
    )
    assert ev.paper_mentions == 3
    assert ev.papers[0].title == "P"
    assert ProjectEvidence().papers == []
