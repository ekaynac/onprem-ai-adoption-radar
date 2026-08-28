"""HF auth plumbing for outbound fetches must read the token from the
environment or a local ``.env`` without hardcoding secrets.
"""

from __future__ import annotations

import pytest

from radar import huggingface_auth


@pytest.fixture(autouse=True)
def _clear_hf_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("HUGGING_FACE_HUB_TOKEN", raising=False)
    # Ensure the module-level dotenv cache does not leak between tests.
    monkeypatch.setattr(huggingface_auth, "_DOTENV_LOADED", False)


def test_no_token_yields_empty_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    assert huggingface_auth.hf_token() is None
    assert huggingface_auth.hf_auth_headers() == {}


def test_reads_hf_token_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HF_TOKEN", "secret-abc")
    assert huggingface_auth.hf_token() == "secret-abc"
    assert huggingface_auth.hf_auth_headers() == {"Authorization": "Bearer secret-abc"}


def test_falls_back_to_hub_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HUGGING_FACE_HUB_TOKEN", "hub-token")
    assert huggingface_auth.hf_token() == "hub-token"


def test_apply_hf_auth_merges_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HF_TOKEN", "tok")
    out = huggingface_auth.apply_hf_auth(
        {"timeout": 5, "headers": {"X-Other": "1"}}, None
    )
    assert out["timeout"] == 5
    assert out["headers"] == {"X-Other": "1", "Authorization": "Bearer tok"}


def test_loads_token_from_dotenv(tmp_path: object, monkeypatch: pytest.MonkeyPatch) -> None:
    from pathlib import Path

    root = Path(str(tmp_path))
    (root / ".env").write_text('HF_TOKEN="dotenv-tok"\n# comment\nFOO=bar\n')
    assert huggingface_auth.hf_token(root) == "dotenv-tok"
    # Existing os.environ values are not overwritten by .env.
    monkeypatch.setenv("HF_TOKEN", "env-wins")
    (root / ".env").write_text('HF_TOKEN="dotenv-tok"\n')
    assert huggingface_auth.hf_token(root) == "env-wins"
