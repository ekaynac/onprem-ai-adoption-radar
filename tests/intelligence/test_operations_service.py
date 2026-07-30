from __future__ import annotations

from radar.intelligence.services.container import build_services

from .lifecycle_helpers import NOW, lifecycle_repository


def test_operations_exposes_source_health_without_transport_logic(
    tmp_path,
) -> None:
    repository = lifecycle_repository(tmp_path)
    repository.increment_source_failure("huggingface", "timeout", NOW)
    services = build_services(repository)

    snapshot = services.operations.snapshot()

    assert snapshot.source_health[0].source_id == "huggingface"
    assert snapshot.source_health[0].consecutive_failures == 1
    assert snapshot.open_review_count == 0
