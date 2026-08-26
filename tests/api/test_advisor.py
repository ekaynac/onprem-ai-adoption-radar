import json


def _seed_models_run(tmp_path) -> None:
    run = tmp_path / "data" / "runs" / "run-advisor"
    run.mkdir(parents=True, exist_ok=True)
    (run / "meta.json").write_text('{"run_id": "run-advisor", "kind": "models"}')
    (run / "model_cards.json").write_text(
        json.dumps(
            [
                {
                    "id": "kimi-k3-mini",
                    "name": "Kimi K3 Mini",
                    "family": "Kimi",
                    "modality": "text",
                    "ring": "adopt",
                    "score": 4.2,
                    "license": "apache-2.0",
                    "params_total": 8_000_000_000,
                    "num_layers": 32,
                    "hidden_size": 4096,
                    "context_length": 32768,
                    "quants": [
                        {
                            "format": "GGUF Q4_K_M",
                            "bits_per_weight": 4.5,
                            "source": "manual",
                        }
                    ],
                }
            ]
        )
    )


def test_recommend_returns_cited_shortlist(api_client, tmp_path) -> None:
    _seed_models_run(tmp_path)

    response = api_client.post(
        "/api/v1/recommend",
        json={"task": "coding", "device": "rtx-4090-24gb"},
    )

    assert response.status_code == 200
    answer = response.json()
    assert answer["task"] == "coding"
    # The seeded card has no task benchmarks: excluded by default under the
    # evidence-honesty policy, surfaced when explicitly opted in.
    assert answer["candidates"] == []
    assert any("Insufficient evidence" in e["reason"] for e in answer["excluded"])

    opted_in = api_client.post(
        "/api/v1/recommend",
        json={
            "task": "coding",
            "device": "rtx-4090-24gb",
            "include_unverified": True,
        },
    )
    first = opted_in.json()["candidates"][0]
    assert first["model_id"] == "kimi-k3-mini"
    assert first["evidence_tier"] == "none"
    assert first["fit"]["verdict"] in {"fits", "fits_tight", "fits_quantized"}
    assert first["reasons"]
    assert answer["cost"]["note"].startswith("Device-level")


def test_recommend_policy_excludes_with_reasons(api_client, tmp_path) -> None:
    _seed_models_run(tmp_path)

    response = api_client.post(
        "/api/v1/recommend",
        json={
            "task": "coding",
            "device": "rtx-4090-24gb",
            "allowed_licenses": ["mit"],
        },
    )

    assert response.status_code == 200
    answer = response.json()
    assert answer["candidates"] == []
    assert any(
        "not in policy" in row["reason"] for row in answer["excluded"]
    )


def test_recommend_rejects_unknown_task_and_device(api_client) -> None:
    bad_task = api_client.post(
        "/api/v1/recommend",
        json={"task": "alchemy", "device": "rtx-4090-24gb"},
    )
    assert bad_task.status_code == 400
    assert "Unknown task" in bad_task.json()["detail"]

    bad_device = api_client.post(
        "/api/v1/recommend",
        json={"task": "coding", "device": "abacus-9000"},
    )
    assert bad_device.status_code == 400
