from __future__ import annotations

from datetime import timedelta

from radar.intelligence.source_health import SourceHealthService

from .lifecycle_helpers import NOW, lifecycle_repository


def test_five_failures_open_two_hour_circuit_and_success_resets(tmp_path) -> None:
    repository = lifecycle_repository(tmp_path)
    service = SourceHealthService(repository)

    for attempt in range(5):
        service.record_failure(
            "huggingface",
            f"failure {attempt}",
            NOW + timedelta(minutes=attempt),
        )

    opened_at = NOW + timedelta(minutes=4)
    assert service.should_skip("huggingface", opened_at) is True
    assert (
        service.should_skip(
            "huggingface",
            opened_at + timedelta(hours=2, seconds=1),
        )
        is False
    )

    service.record_success(
        "huggingface",
        latency_ms=120,
        items=42,
        now=opened_at + timedelta(hours=2, seconds=2),
    )
    state = repository.get_source_health("huggingface")
    assert state is not None
    assert state.consecutive_failures == 0
    assert state.items_count == 42
