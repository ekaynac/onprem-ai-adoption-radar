import json
from datetime import UTC, datetime

from intelligence.lifecycle_helpers import lifecycle_repository
from intelligence.test_recommendations import seed_recommendable_release
from radar.intelligence.services.container import build_services
from radar.web.intelligence_snapshot import (
    build_public_snapshot,
    write_public_snapshot,
)


def test_public_snapshot_is_deterministic_and_has_no_workspace_data(
    tmp_path,
) -> None:
    repository = lifecycle_repository(tmp_path)
    seed_recommendable_release(repository)
    repository.import_platform(
        platform_id="platform:vllm",
        name="vLLM",
        repo_url="https://github.com/vllm-project/vllm",
        verified_at="2026-07-30",
        payload={"features": {"tensor_parallel": True}},
    )
    generated_at = datetime(2026, 7, 30, 10, 0, tzinfo=UTC)
    snapshot = build_public_snapshot(build_services(repository), generated_at)

    path = write_public_snapshot(snapshot, tmp_path / "_site")
    first = path.read_bytes()
    write_public_snapshot(snapshot, tmp_path / "_site")

    assert path.read_bytes() == first
    payload = json.loads(first)
    assert payload["schema_version"] == "1.0"
    assert payload["releases"]
    assert set(payload) == {
        "schema_version",
        "generated_at",
        "releases",
        "models",
        "platforms",
        "hardware",
        "research",
        "events",
        "source_health",
    }
    assert payload["platforms"][0]["name"] == "vLLM"
    assert "workspace" not in first.decode().casefold()
