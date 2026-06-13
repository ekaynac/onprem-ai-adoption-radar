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


def test_movers_command_shows_directions(tmp_path):
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

    result = runner.invoke(app, ["movers", "--root", str(tmp_path)])

    assert result.exit_code == 0, result.stdout
    assert "Model Context Protocol" in result.stdout


def test_movers_without_history_explains_scan(tmp_path):
    runner = CliRunner()
    runner.invoke(app, ["init", "--root", str(tmp_path)])

    result = runner.invoke(app, ["movers", "--root", str(tmp_path)])

    assert result.exit_code != 0
    assert "radar scan" in result.stdout


MANUAL_CONFIG = """
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
profiles:
  security-first:
    security_posture: 3.0
  solo-dev:
    laptop_runnability: 2.5
"""


def _scan_manual(tmp_path):
    runner = CliRunner()
    runner.invoke(app, ["init", "--root", str(tmp_path)])
    (tmp_path / "data" / "config.yaml").write_text(MANUAL_CONFIG, encoding="utf-8")
    runner.invoke(app, ["scan", "--root", str(tmp_path), "--days", "2"])
    return runner


def test_override_pins_card_and_journals_change(tmp_path):
    runner = _scan_manual(tmp_path)

    result = runner.invoke(
        app,
        [
            "override", "--root", str(tmp_path),
            "--project", "Model Context Protocol",
            "--ring", "avoid", "--reason", "failed internal review",
        ],
    )

    assert result.exit_code == 0, result.stdout
    report = runner.invoke(app, ["report", "--root", str(tmp_path)])
    assert "avoid" in report.stdout
    assert "failed internal review" in report.stdout
    # The pin landed in the durable timeline.
    history = (tmp_path / "data" / "history.jsonl").read_text(encoding="utf-8")
    assert "override-" in history


def test_override_requires_reason(tmp_path):
    runner = _scan_manual(tmp_path)

    result = runner.invoke(
        app,
        ["override", "--root", str(tmp_path), "--project", "X", "--ring", "avoid"],
    )

    assert result.exit_code != 0
    assert "reason" in result.stdout.lower()


def test_override_clear_restores_computed_ring(tmp_path):
    runner = _scan_manual(tmp_path)
    runner.invoke(
        app,
        [
            "override", "--root", str(tmp_path),
            "--project", "Model Context Protocol",
            "--ring", "avoid", "--reason", "temp",
        ],
    )

    result = runner.invoke(
        app,
        ["override", "--root", str(tmp_path), "--project", "Model Context Protocol", "--clear"],
    )

    assert result.exit_code == 0, result.stdout
    report = runner.invoke(app, ["report", "--root", str(tmp_path), "--json"])
    import json as json_module

    cards = json_module.loads(report.stdout)
    card = next(c for c in cards if c["project"] == "Model Context Protocol")
    assert card["pinned"] is False
    assert card["ring"] != "avoid"


def test_trial_records_outcome_in_journal_and_timeline(tmp_path):
    runner = _scan_manual(tmp_path)

    result = runner.invoke(
        app,
        [
            "trial", "--root", str(tmp_path),
            "--project", "Model Context Protocol",
            "--outcome", "adopted", "--notes", "worked great locally",
        ],
    )

    assert result.exit_code == 0, result.stdout
    overrides = (tmp_path / "data" / "overrides.yaml").read_text(encoding="utf-8")
    assert "adopted" in overrides
    history = (tmp_path / "data" / "history.jsonl").read_text(encoding="utf-8")
    assert "worked great locally" in history


def test_trial_rejects_invalid_outcome(tmp_path):
    runner = _scan_manual(tmp_path)

    result = runner.invoke(
        app,
        ["trial", "--root", str(tmp_path), "--project", "X", "--outcome", "meh"],
    )

    assert result.exit_code != 0


def test_report_profile_reranks_view(tmp_path):
    runner = _scan_manual(tmp_path)

    result = runner.invoke(
        app, ["report", "--root", str(tmp_path), "--profile", "security-first"]
    )

    assert result.exit_code == 0, result.stdout
    assert "security-first profile" in result.stdout


def test_report_unknown_profile_errors(tmp_path):
    runner = _scan_manual(tmp_path)

    result = runner.invoke(
        app, ["report", "--root", str(tmp_path), "--profile", "does-not-exist"]
    )

    assert result.exit_code != 0
    assert "Unknown profile" in result.stdout


def test_scan_with_profile_records_it_in_meta(tmp_path):
    import json as json_module

    runner = _scan_manual(tmp_path)
    result = runner.invoke(
        app, ["scan", "--root", str(tmp_path), "--days", "2", "--profile", "solo-dev"]
    )

    assert result.exit_code == 0, result.stdout
    run_line = next(line for line in result.stdout.splitlines() if line.startswith("Run:"))
    run_id = run_line.split("Run:", 1)[1].strip()
    meta = json_module.loads(
        (tmp_path / "data" / "runs" / run_id / "meta.json").read_text()
    )
    assert meta["profile"] == "solo-dev"


def test_seed_list_flags_stale_sources(tmp_path):
    from datetime import UTC, datetime, timedelta

    from radar.storage.source_health_store import SourceHealthStore

    runner = CliRunner()
    runner.invoke(app, ["init", "--root", str(tmp_path)])

    # Simulate 3 consecutive scans where a known seed produced nothing.
    health = SourceHealthStore(tmp_path / "data" / "radar.db")
    health.initialize()
    base = datetime(2026, 6, 1, tzinfo=UTC)
    for day in range(3):
        health.record(f"run-{day}", base + timedelta(days=day), {"github-vllm": 0})

    result = runner.invoke(app, ["seed", "list", "--root", str(tmp_path)])

    assert result.exit_code == 0, result.stdout
    assert "1 stale" in result.stdout
    stale_line = next(
        line for line in result.stdout.splitlines() if "github-vllm" in line
    )
    assert "STALE?" in stale_line


def test_calibrate_report_runs_after_scan(tmp_path):
    runner = _scan_manual(tmp_path)

    result = runner.invoke(app, ["calibrate-report", "--root", str(tmp_path)])

    assert result.exit_code == 0, result.stdout
    assert "Scoring Calibration" in result.stdout
    assert "Ring distribution" in result.stdout


def test_calibrate_report_without_scan_explains(tmp_path):
    runner = CliRunner()
    runner.invoke(app, ["init", "--root", str(tmp_path)])

    result = runner.invoke(app, ["calibrate-report", "--root", str(tmp_path)])

    assert result.exit_code != 0
    assert "radar scan" in result.stdout


def test_export_writes_project_pages(tmp_path):
    runner = _scan_manual(tmp_path)

    result = runner.invoke(app, ["export", "--root", str(tmp_path), "--out", str(tmp_path / "_site")])

    assert result.exit_code == 0, result.stdout
    project_pages = list((tmp_path / "_site").glob("project_*.html"))
    assert project_pages
    index = (tmp_path / "_site" / "index.html").read_text(encoding="utf-8")
    assert 'href="project_' in index


def test_backtest_command_runs_after_scan(tmp_path):
    runner = _scan_manual(tmp_path)

    result = runner.invoke(app, ["backtest", "--root", str(tmp_path)])

    assert result.exit_code == 0, result.stdout
    assert "Scoring Backtest" in result.stdout


def test_backtest_profile_unknown_exits_1(tmp_path):
    runner = _scan_manual(tmp_path)

    result = runner.invoke(
        app, ["backtest", "--root", str(tmp_path), "--profile", "does-not-exist"]
    )

    assert result.exit_code != 0
    assert "Unknown profile" in result.stdout


def test_backtest_creates_no_new_run_dirs(tmp_path):
    runner = _scan_manual(tmp_path)
    runs_dir = tmp_path / "data" / "runs"
    before = sorted(p.name for p in runs_dir.iterdir())

    runner.invoke(app, ["backtest", "--root", str(tmp_path), "--profile", "security-first"])

    after = sorted(p.name for p in runs_dir.iterdir())
    assert after == before


def _seed_cards_for_calibration(tmp_path, rings):
    """Upsert cards with the given rings (and per-dim breakdowns) for calibrate tests."""
    from radar.models import Category, DecisionCard, Ring, ScoreBreakdown
    from radar.storage.database import RadarDatabase

    db = RadarDatabase(tmp_path / "data" / "radar.db")
    db.initialize()
    cards = []
    for i, ring in enumerate(rings):
        # Vary one dimension so scores aren't all identical.
        cards.append(
            DecisionCard(
                project=f"P{i}", category=Category.MODEL_SERVING, ring=Ring(ring),
                score=4.0, summary="s", workflow_fit={}, risk_level="low",
                score_breakdown=ScoreBreakdown(
                    workflow_impact=4, laptop_runnability=4, open_source_maturity=3 + (i % 3),
                    on_prem_relevance=4, security_posture=4, demo_value=4, setup_friction=4,
                ),
            )
        )
    db.upsert_cards(cards)


def test_calibrate_check_fails_when_not_discriminating(tmp_path):
    runner = CliRunner()
    _seed_cards_for_calibration(tmp_path, ["watch"] * 5)  # one ring → collapse

    result = runner.invoke(app, ["calibrate-report", "--root", str(tmp_path), "--check"])

    assert result.exit_code == 1
    assert "Scoring Calibration" in result.stdout  # report still printed for diagnosis


def test_calibrate_check_passes_when_discriminating(tmp_path):
    runner = CliRunner()
    _seed_cards_for_calibration(tmp_path, ["adopt", "pilot", "pilot", "watch", "avoid"])

    result = runner.invoke(app, ["calibrate-report", "--root", str(tmp_path), "--check"])

    assert result.exit_code == 0


def test_calibrate_without_check_exits_zero_even_if_collapsed(tmp_path):
    runner = CliRunner()
    _seed_cards_for_calibration(tmp_path, ["watch"] * 5)

    result = runner.invoke(app, ["calibrate-report", "--root", str(tmp_path)])

    assert result.exit_code == 0


def test_calibrate_check_no_cards_exits_one(tmp_path):
    runner = CliRunner()
    runner.invoke(app, ["init", "--root", str(tmp_path)])

    result = runner.invoke(app, ["calibrate-report", "--root", str(tmp_path), "--check"])

    assert result.exit_code != 0


def test_scan_prints_scan_health_line(tmp_path):
    runner = _scan_manual(tmp_path)
    # _scan_manual already scanned; scan again to capture stdout.
    result = runner.invoke(app, ["scan", "--root", str(tmp_path), "--days", "2"])

    assert result.exit_code == 0, result.stdout
    assert "Scan health:" in result.stdout
