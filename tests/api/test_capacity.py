import json


def _seed_models_run(tmp_path) -> None:
    run = tmp_path / "data" / "runs" / "run-models"
    run.mkdir(parents=True, exist_ok=True)
    (run / "meta.json").write_text('{"run_id": "run-models", "kind": "models"}')
    (run / "model_cards.json").write_text(
        json.dumps(
            [
                {
                    "id": "kimi-k3",
                    "name": "Kimi K3",
                    "family": "Kimi",
                    "params_total": 8_000_000_000,
                    "num_layers": 32,
                    "hidden_size": 4096,
                    "context_length": 32768,
                    "quants": [
                        {
                            "format": "GGUF Q4_K_M",
                            "bits_per_weight": 4.5,
                            "source": "hf:kimi/kimi-k3-gguf",
                        },
                        {
                            "format": "FP16",
                            "bits_per_weight": 16.0,
                            "source": "manual",
                        },
                    ],
                }
            ]
        )
    )


def test_capacity_devices_lists_presets(api_client) -> None:
    response = api_client.get("/api/v1/capacity/devices")

    assert response.status_code == 200
    devices = response.json()
    assert devices
    assert {"id", "name", "usable_gb", "gpu_count"} <= set(devices[0])


def test_capacity_fit_returns_verdict_for_seeded_model(
    api_client,
    tmp_path,
) -> None:
    _seed_models_run(tmp_path)

    response = api_client.post(
        "/api/v1/capacity/fit",
        json={"model_id": "kimi-k3", "device": "rtx-4090-24gb", "context_tokens": 4096},
    )

    assert response.status_code == 200
    verdict = response.json()
    assert verdict["model_id"] == "kimi-k3"
    assert "verdict" in verdict


def test_capacity_plan_solves_for_seeded_model(api_client, tmp_path) -> None:
    _seed_models_run(tmp_path)

    response = api_client.post(
        "/api/v1/capacity/plan",
        json={
            "model_id": "kimi-k3",
            "device": "h100-80gb",
            "concurrent_requests": 8,
            "avg_context_tokens": 4096,
        },
    )

    assert response.status_code == 200
    plan = response.json()
    assert plan["feasible"] is True
    assert plan["n_gpus"] >= 1


def test_capacity_unknown_model_is_404(api_client) -> None:
    response = api_client.post(
        "/api/v1/capacity/fit",
        json={"model_id": "release:missing", "device": "rtx-4090-24gb"},
    )

    assert response.status_code == 404
