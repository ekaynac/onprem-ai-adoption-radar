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


def test_export_writes_static_site(tmp_path):
    from radar.models import Category, Ring
    from radar.storage.database import RadarDatabase

    db = RadarDatabase(tmp_path / "data" / "radar.db")
    db.initialize()
    from radar.models import DecisionCard

    db.upsert_cards(
        [
            DecisionCard(
                project="vLLM", category=Category.MODEL_SERVING, ring=Ring.ADOPT,
                summary="fast inference", workflow_fit={}, risk_level="low",
            ),
            DecisionCard(
                project="Ollama", category=Category.MODEL_SERVING, ring=Ring.PILOT,
                summary="local models", workflow_fit={}, risk_level="low",
            ),
        ]
    )

    out = tmp_path / "_site"
    runner = CliRunner()
    result = runner.invoke(
        app, ["export", "--root", str(tmp_path), "--out", str(out)]
    )

    assert result.exit_code == 0, result.stdout
    index = out / "index.html"
    assert index.exists()
    html = index.read_text(encoding="utf-8")
    assert "vLLM" in html
    assert "adopt" in html

    # The published site is complete: compare + history pages with relative nav.
    compare = out / "compare.html"
    history = out / "history.html"
    assert compare.exists() and history.exists()
    assert 'href="compare.html"' in html  # relative cross-links, not "/compare"
    assert 'href="history.html"' in html
    # Compare page shows the two model_serving projects side by side.
    comp_html = compare.read_text(encoding="utf-8")
    assert "vLLM" in comp_html and "Ollama" in comp_html


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


def test_seed_list_shows_configured_sources(tmp_path):
    runner = CliRunner()
    runner.invoke(app, ["init", "--root", str(tmp_path)])

    result = runner.invoke(app, ["seed", "list", "--root", str(tmp_path)])

    assert result.exit_code == 0, result.stdout
    # The default seed list ships github + rss sources; spot-check known ids.
    assert "github-vllm" in result.stdout
    assert "model_serving" in result.stdout


def test_seed_list_without_config_explains_init(tmp_path):
    runner = CliRunner()

    result = runner.invoke(app, ["seed", "list", "--root", str(tmp_path)])

    assert result.exit_code != 0
    assert "radar init" in result.stdout


def test_report_json_outputs_machine_readable_cards(tmp_path):
    import json

    from radar.models import Category, DecisionCard, Ring
    from radar.storage.database import RadarDatabase

    db = RadarDatabase(tmp_path / "data" / "radar.db")
    db.initialize()
    db.upsert_cards(
        [
            DecisionCard(
                project="vLLM", category=Category.MODEL_SERVING, ring=Ring.ADOPT,
                summary="fast inference", workflow_fit={}, risk_level="low",
            ),
        ]
    )
    runner = CliRunner()

    result = runner.invoke(app, ["report", "--root", str(tmp_path), "--json"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload[0]["project"] == "vLLM"
    assert payload[0]["ring"] == "adopt"
