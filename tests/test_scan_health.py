"""Tests for the pure scan-health summary over run meta."""

from __future__ import annotations

import pytest

from radar.web.scan_health import summarize_meta


def test_summarize_empty_meta_is_zeroed():
    health = summarize_meta({})

    assert health.last_run_at is None
    assert health.collector_warning_count == 0
    assert health.enrichment_warning_count == 0
    assert health.firehose_dropped_count == 0
    assert health.has_warnings is False


def test_summarize_counts_collector_and_enrichment_warnings():
    health = summarize_meta(
        {
            "collector_warnings": ["GitHubCollector: 403", "RSSCollector: timeout"],
            "enrichment_warnings": ["osv:vLLM failed"],
        }
    )

    assert health.collector_warning_count == 2
    assert health.enrichment_warning_count == 1
    assert health.has_warnings is True
    assert "GitHubCollector: 403" in health.collector_warnings


def test_summarize_reads_firehose_fields():
    health = summarize_meta(
        {
            "firehose_dropped_count": 15,
            "firehose_dropped_sample": ["Some blog post", "Another"],
            "firehose_llm_recovered": 3,
        }
    )

    assert health.firehose_dropped_count == 15
    assert health.firehose_llm_recovered == 3
    assert "Some blog post" in health.firehose_dropped_sample


def test_summarize_uses_timestamp_and_profile():
    health = summarize_meta(
        {"created_at": "2026-06-13T10:00:00+00:00", "updated_at": "2026-06-13T10:05:00+00:00", "profile": "security-first"}
    )

    assert health.last_run_at == "2026-06-13T10:05:00+00:00"  # prefers updated_at
    assert health.profile == "security-first"


def test_summarize_tolerates_malformed_meta():
    health = summarize_meta(
        {"collector_warnings": "not-a-list", "firehose_dropped_count": "lots"}
    )

    assert health.collector_warning_count == 0
    assert health.firehose_dropped_count == 0


def test_one_line_summary_format():
    clean = summarize_meta({"created_at": "2026-06-13T10:00:00+00:00"})
    assert "no warnings" in clean.one_line.lower()

    warned = summarize_meta(
        {
            "created_at": "2026-06-13T10:00:00+00:00",
            "collector_warnings": ["x"],
            "firehose_dropped_count": 15,
        }
    )
    assert "1 collector warning" in warned.one_line
    assert "15 firehose" in warned.one_line


def test_scan_health_is_immutable():
    from pydantic import ValidationError

    health = summarize_meta({})
    with pytest.raises(ValidationError):
        health.collector_warning_count = 5


def test_summarize_does_not_mutate_input():
    meta = {"collector_warnings": ["x"]}
    summarize_meta(meta)
    assert meta == {"collector_warnings": ["x"]}
