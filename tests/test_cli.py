from typer.testing import CliRunner

from radar.cli import app


def test_version_command_prints_version():
    runner = CliRunner()

    result = runner.invoke(app, ["version"])

    assert result.exit_code == 0
    assert "onprem-ai-adoption-radar" in result.stdout
    assert "0.1.0" in result.stdout


def test_app_has_help_text():
    runner = CliRunner()

    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "Agent/tooling adoption radar" in result.stdout


def test_init_command_writes_config(tmp_path):
    runner = CliRunner()

    result = runner.invoke(app, ["init", "--root", str(tmp_path)])

    assert result.exit_code == 0
    assert (tmp_path / "data" / "config.yaml").exists()


def test_seed_add_appends_source_to_config(tmp_path):
    runner = CliRunner()
    runner.invoke(app, ["init", "--root", str(tmp_path)])

    result = runner.invoke(
        app,
        [
            "seed", "add",
            "--root", str(tmp_path),
            "--id", "rss-cli-feed",
            "--type", "rss",
            "--project", "CLI Feed",
            "--category", "model_serving",
            "--url", "https://example.com/feed.xml",
            "--tags", "vendor-blog,inference",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert "rss-cli-feed" in result.stdout

    from radar.storage.config import load_config
    config = load_config(tmp_path / "data" / "config.yaml")
    assert any(s.id == "rss-cli-feed" for s in config.sources)


def test_history_command_shows_recorded_timeline(tmp_path):
    runner = CliRunner()
    runner.invoke(app, ["init", "--root", str(tmp_path)])
    (tmp_path / "data" / "config.yaml").write_text(
        """
version: "1.0"
sources:
  - id: mcp-docs
    type: manual
    enabled: true
    project: Model Context Protocol
    category: mcp_tooling
    url: https://modelcontextprotocol.io/docs/getting-started/intro
    tags: [mcp]
quotas:
  mcp_tooling: 4
scoring:
  default_ring: watch
""",
        encoding="utf-8",
    )
    runner.invoke(app, ["scan", "--root", str(tmp_path), "--days", "2"])

    result = runner.invoke(app, ["history", "--root", str(tmp_path)])

    assert result.exit_code == 0, result.stdout
    assert "Model Context Protocol" in result.stdout


def test_seed_add_reports_error_on_duplicate(tmp_path):
    runner = CliRunner()
    runner.invoke(app, ["init", "--root", str(tmp_path)])
    args = [
        "seed", "add", "--root", str(tmp_path),
        "--id", "rss-dup", "--type", "rss", "--project", "Dup",
        "--category", "model_serving", "--url", "https://example.com/feed.xml",
    ]
    runner.invoke(app, args)

    result = runner.invoke(app, args)

    assert result.exit_code != 0
    assert "already exists" in result.stdout
