import json

from radar.api.export_openapi import export_openapi


def test_openapi_export_is_deterministic_and_versioned(tmp_path) -> None:
    output = tmp_path / "build" / "openapi.json"

    export_openapi(tmp_path, output)
    first = output.read_bytes()
    export_openapi(tmp_path, output)

    assert output.read_bytes() == first
    schema = json.loads(first)
    assert schema["info"]["version"] == "1.0.0"
    assert "/api/v1/releases" in schema["paths"]
