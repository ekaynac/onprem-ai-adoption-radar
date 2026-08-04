"""Claude CLI adapter: headless invocation, fence stripping, fail-closed."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from radar.discovery.news_classify import classify_news
from radar.discovery.news_claude_cli import (
    ClaudeCliClient,
    _strip_fences,
    build_claude_cli_client,
)
from radar.discovery.news_sweep import NewsClassificationConfig
from radar.storage.news_log import NewsItem, news_id_for


NOW = datetime(2026, 8, 4, 10, 0, tzinfo=UTC)

_VALID = json.dumps(
    {
        "relevant": True,
        "event_type": "release",
        "components": ["vllm"],
        "operational_impact": "improvement",
        "summary": "New vLLM release worth adopting.",
        "citation": "https://blog.vllm.ai/v0-10",
    }
)


class _Proc:
    def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def _config() -> NewsClassificationConfig:
    return NewsClassificationConfig(
        enabled=True,
        model="claude-opus-5",
        max_items_per_run=25,
        max_output_tokens=1024,
    )


def _item() -> NewsItem:
    return NewsItem(
        id=news_id_for("https://blog.vllm.ai/v0-10"),
        source_id="vllm-blog",
        title="vLLM v0.10 released",
        url="https://blog.vllm.ai/v0-10",
        summary="Release notes",
        published_at=NOW,
        observed_at=NOW,
    )


def test_adapter_invokes_claude_headless_and_returns_text(monkeypatch):
    captured: dict[str, object] = {}

    def _fake_run(args, **kwargs):
        captured["args"] = args
        captured["input"] = kwargs["input"]
        return _Proc(stdout=json.dumps({"result": _VALID}))

    monkeypatch.setattr("subprocess.run", _fake_run)
    client = ClaudeCliClient()

    result = classify_news([_item()], _config(), client, NOW)

    assert result.failures == []
    assert result.classifications[0].event_type == "release"
    args = captured["args"]
    assert args[0] == "claude"
    assert "-p" in args and "--output-format" in args
    assert args[args.index("--model") + 1] == "claude-opus-5"
    # The schema travels in the prompt since the CLI has no output_config.
    assert "additionalProperties" in str(captured["input"])


def test_adapter_strips_markdown_fences(monkeypatch):
    fenced = f"```json\n{_VALID}\n```"
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **k: _Proc(stdout=json.dumps({"result": fenced})),
    )
    result = classify_news([_item()], _config(), ClaudeCliClient(), NOW)
    assert result.failures == []
    assert result.classifications[0].operational_impact == "improvement"


def test_adapter_failures_stay_unclassified(monkeypatch):
    outcomes = [
        _Proc(returncode=1, stderr="not logged in"),
        _Proc(stdout=json.dumps({"result": "not json"})),
        _Proc(stdout=json.dumps({"is_error": True})),
    ]
    monkeypatch.setattr(
        "subprocess.run", lambda *a, **k: outcomes.pop(0)
    )
    items = [_item(), _item(), _item()]
    result = classify_news(items, _config(), ClaudeCliClient(), NOW)
    assert result.classifications == []
    assert len(result.failures) == 3


def test_build_client_requires_binary(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _name: None)
    assert build_claude_cli_client() is None
    monkeypatch.setattr("shutil.which", lambda _name: "/usr/local/bin/claude")
    assert build_claude_cli_client() is not None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("{}", "{}"),
        ("```json\n{}\n```", "{}"),
        ("```\n{}\n```", "{}"),
        ("  {}  ", "{}"),
    ],
)
def test_strip_fences(raw, expected):
    assert _strip_fences(raw) == expected


def test_cli_auto_engine_falls_back_to_claude_cli(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from radar.cli import app
    from radar.storage.news_log import append_news_items

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    append_news_items(
        tmp_path / "data" / "news-observations.jsonl", [_item()]
    )
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **k: _Proc(stdout=json.dumps({"result": _VALID})),
    )
    monkeypatch.setattr(
        "shutil.which", lambda _name: "/usr/local/bin/claude"
    )
    runner = CliRunner()

    result = runner.invoke(
        app, ["news", "classify", "--root", str(tmp_path), "--limit", "1"]
    )

    assert result.exit_code == 0
    assert "Engine: claude-cli" in result.stdout
    assert "Classified 1 item(s)" in result.stdout
