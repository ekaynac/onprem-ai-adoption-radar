import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

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


def test_export_restores_classic_projects_from_tracked_public_data(tmp_path):
    from radar.models import Category, Ring
    from radar.pipeline.delta import ChangeType
    from radar.storage.history_log import append_events
    from radar.storage.history_store import ProjectHistoryEvent

    snapshot = tmp_path / "data" / "intelligence" / "public-snapshot.v1.json"
    snapshot.parent.mkdir(parents=True)
    snapshot.write_text(
        json.dumps(
            {
                "generated_at": "2026-07-30T06:00:00Z",
                "projects": [
                    {
                        "project": "vLLM",
                        "category": "model_serving",
                        "ring": "adopt",
                        "score": 4.7,
                        "summary": "High-throughput model serving engine.",
                        "workflow_fit": {"serving": "strong"},
                        "risk_level": "medium",
                        "repository_url": "https://github.com/vllm-project/vllm",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    append_events(
        tmp_path / "data" / "history.jsonl",
        [
            ProjectHistoryEvent(
                project="vLLM",
                category=Category.MODEL_SERVING,
                change_type=ChangeType.NEW,
                ring=Ring.ADOPT,
                run_id="run-clean-checkout",
                observed_at=datetime(2026, 7, 31, tzinfo=UTC),
            )
        ],
    )

    out = tmp_path / "_site"
    result = CliRunner().invoke(
        app,
        ["export", "--root", str(tmp_path), "--out", str(out)],
    )

    assert result.exit_code == 0, result.stdout
    assert len(list(out.glob("project_*.html"))) == 1
    project_page = next(out.glob("project_*.html")).read_text(encoding="utf-8")
    index = (out / "index.html").read_text(encoding="utf-8")
    assert "last published baseline from 2026-07-30 06:00 UTC" in index
    assert "last published baseline from 2026-07-30 06:00 UTC" in project_page
    assert "Page generated" in index
    assert "vLLM" in (out / "history.html").read_text(encoding="utf-8")
    assert "vLLM" in (out / "changes.rss").read_text(encoding="utf-8")


def test_export_uses_curated_catalogs_when_scan_runs_are_absent(tmp_path):
    from radar.storage.database import RadarDatabase

    RadarDatabase(tmp_path / "data" / "radar.db").initialize()
    config = tmp_path / "config"
    config.mkdir()
    repository_root = Path(__file__).parents[1]
    shutil.copy2(repository_root / "config" / "model-seed.yaml", config)
    shutil.copy2(repository_root / "config" / "technique-seed.yaml", config)

    out = tmp_path / "_site"
    result = CliRunner().invoke(
        app,
        ["export", "--root", str(tmp_path), "--out", str(out)],
    )

    assert result.exit_code == 0, result.stdout
    assert (out / "models.html").is_file()
    assert (out / "techniques.html").is_file()


def test_export_base_url_makes_feed_self_urls_absolute(tmp_path):
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

    out = tmp_path / "_site"
    result = CliRunner().invoke(
        app,
        ["export", "--root", str(tmp_path), "--out", str(out),
         "--base-url", "https://acme.github.io/radar"],
    )

    assert result.exit_code == 0, result.stdout
    rss = (out / "changes.rss").read_text(encoding="utf-8")
    assert "https://acme.github.io/radar/changes.rss" in rss


def test_export_rejects_non_http_base_url(tmp_path):
    from radar.storage.database import RadarDatabase

    RadarDatabase(tmp_path / "data" / "radar.db").initialize()

    result = CliRunner().invoke(
        app,
        ["export", "--root", str(tmp_path), "--out", str(tmp_path / "_site"),
         "--base-url", "acme.github.io/radar"],  # missing scheme
    )

    assert result.exit_code != 0


def test_export_survives_corrupt_platform_matrix(tmp_path):
    """A hand-corrupted root-level platform-matrix.yaml must not fail the
    export — it should warn, finish normally, and simply skip platforms.html
    (mirrors the web-route guarded gateway in test_web.py's equivalent)."""
    from radar.storage.database import RadarDatabase

    RadarDatabase(tmp_path / "data" / "radar.db").initialize()

    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "platform-matrix.yaml").write_text(
        "not: [valid, - platform, matrix\n", encoding="utf-8"
    )

    out = tmp_path / "_site"
    result = CliRunner().invoke(
        app, ["export", "--root", str(tmp_path), "--out", str(out)]
    )

    assert result.exit_code == 0, result.stdout
    assert "platform matrix unreadable" in result.stdout
    assert (out / "index.html").exists()  # export still completes
    assert not (out / "platforms.html").exists()


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

    from radar.storage.source_health_store import (
        DEFAULT_STALE_WINDOW,
        SourceHealthStore,
    )

    runner = CliRunner()
    runner.invoke(app, ["init", "--root", str(tmp_path)])

    # Simulate a full stale window of consecutive scans producing nothing.
    health = SourceHealthStore(tmp_path / "data" / "radar.db")
    health.initialize()
    base = datetime(2026, 6, 1, tzinfo=UTC)
    for day in range(DEFAULT_STALE_WINDOW):
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


def test_discover_includes_hf_papers(tmp_path, monkeypatch):
    from radar.discovery.proposals import SeedProposal, load_proposals
    from radar.models import Category
    runner = CliRunner()
    runner.invoke(app, ["init", "--root", str(tmp_path)])

    async def fake_trending(*a, **k): return []
    async def fake_hf(*a, **k):
        return [SeedProposal(project="fastserve", category=Category.MODEL_SERVING,
                             url="https://github.com/acme/fastserve", stars=1200,
                             suggested_id="github-fastserve")]
    monkeypatch.setattr("radar.discovery.github_trending.discover_trending", fake_trending)
    monkeypatch.setattr("radar.discovery.hf_papers.discover_from_hf_papers", fake_hf)

    result = runner.invoke(app, ["discover", "--root", str(tmp_path)])
    assert result.exit_code == 0, result.stdout
    proposals = load_proposals(tmp_path / "data" / "proposed-seeds.yaml")
    assert any(p.suggested_id == "github-fastserve" for p in proposals)


def test_export_includes_research_pages_after_research_scan(tmp_path):
    from datetime import UTC, datetime

    from radar.models import Category, Ring
    from radar.research_radar.entities import OnPremImpact, TechniqueDomain, TechniqueEntry
    from radar.research_radar.history import TechniqueHistoryEvent, append_technique_events
    from radar.storage.history_store import ChangeType
    from radar.storage.run_store import RunStore

    runner = CliRunner()
    runner.invoke(app, ["init", "--root", str(tmp_path)])
    entry = TechniqueEntry(
        id="qlora", name="QLoRA", category=Category.AI_INFRASTRUCTURE,
        domain=TechniqueDomain.FINE_TUNING, onprem_impact=OnPremImpact.REDUCES_MEMORY,
        ring=Ring.WATCH,
    )
    store = RunStore(tmp_path / "data" / "runs")
    run_id = store.create_run()
    store.save_stage(run_id, "technique_cards", [entry.model_dump(mode="json")])
    store.update_meta(run_id, {"kind": "research", "technique_count": 1})
    append_technique_events(tmp_path / "data" / "technique-history.jsonl", [
        TechniqueHistoryEvent(
            technique_id="qlora", domain=TechniqueDomain.FINE_TUNING,
            change_type=ChangeType.NEW, ring=Ring.WATCH, run_id=run_id,
            observed_at=datetime(2026, 7, 3, 10, 0, tzinfo=UTC),
        ),
    ])

    result = runner.invoke(app, ["export", "--root", str(tmp_path),
                                 "--out", str(tmp_path / "_site")])

    assert result.exit_code == 0
    assert (tmp_path / "_site" / "techniques.html").exists()
    assert (tmp_path / "_site" / "technique-history.jsonl").exists()
    assert "Technique History (JSONL)" in (
        tmp_path / "_site" / "index.html").read_text(encoding="utf-8")
    assert "1 technique pages" in result.stdout


def test_export_scan_health_ignores_research_runs(tmp_path):
    from radar.storage.run_store import RunStore

    runner = CliRunner()
    runner.invoke(app, ["init", "--root", str(tmp_path)])
    store = RunStore(tmp_path / "data" / "runs")
    tool_run = store.create_run()
    store.update_meta(tool_run, {"collector_warnings": ["github: rate limited"]})
    research_run = store.create_run()
    store.save_stage(research_run, "technique_cards", [])
    store.update_meta(research_run, {"kind": "research", "technique_count": 0})

    result = runner.invoke(app, ["export", "--root", str(tmp_path),
                                 "--out", str(tmp_path / "_site")])

    assert result.exit_code == 0
    assert "rate limited" in (tmp_path / "_site" / "index.html").read_text(encoding="utf-8")


def test_export_survives_research_run_without_config(tmp_path):
    """Regression: export should degrade gracefully when config.yaml is missing during pedigree building."""
    from radar.models import Category, Ring
    from radar.research_radar.entities import OnPremImpact, TechniqueDomain, TechniqueEntry
    from radar.storage.database import RadarDatabase
    from radar.storage.run_store import RunStore

    runner = CliRunner()
    # Seed research run only — no init, no data/config.yaml
    # Create minimal database to satisfy export prerequisites.
    db = RadarDatabase(tmp_path / "data" / "radar.db")
    db.initialize()

    store = RunStore(tmp_path / "data" / "runs")
    run_id = store.create_run()
    entry = TechniqueEntry(
        id="test-technique", name="Test Technique", category=Category.AI_INFRASTRUCTURE,
        domain=TechniqueDomain.FINE_TUNING, onprem_impact=OnPremImpact.REDUCES_MEMORY,
        ring=Ring.WATCH,
    )
    store.save_stage(run_id, "technique_cards", [entry.model_dump(mode="json")])
    store.update_meta(run_id, {"kind": "research", "technique_count": 1})

    result = runner.invoke(app, ["export", "--root", str(tmp_path),
                                 "--out", str(tmp_path / "_site")])

    # Export succeeds despite missing config.yaml: pedigree maps degrade to empty.
    assert result.exit_code == 0, result.stdout
    assert (tmp_path / "_site" / "techniques.html").exists()


def test_export_survives_corrupt_research_run(tmp_path):
    from radar.storage.run_store import RunStore

    runner = CliRunner()
    runner.invoke(app, ["init", "--root", str(tmp_path)])
    store = RunStore(tmp_path / "data" / "runs")
    run_id = store.create_run()
    store.update_meta(run_id, {"kind": "research"})
    store.save_stage(run_id, "technique_cards", [{"bogus": True}])

    result = runner.invoke(app, ["export", "--root", str(tmp_path),
                                 "--out", str(tmp_path / "_site")])

    assert result.exit_code == 0
    assert (tmp_path / "_site" / "index.html").exists()
    assert not (tmp_path / "_site" / "techniques.html").exists()
    # A research run exists (kind=research, fresh created_at) but its
    # technique_cards.json is unreadable/schema-drifted -> the guarded gateway
    # treats it as empty entries, which the staleness check still flags.
    assert "research data is stale/missing" in result.output


def test_export_includes_trending_page(tmp_path):
    from datetime import UTC, datetime

    from radar.discovery.trending_entities import Lane, TrendingObservation
    from radar.storage.trending_observations_log import append_observations

    runner = CliRunner()
    runner.invoke(app, ["init", "--root", str(tmp_path)])
    append_observations(tmp_path / "data" / "trending-observations.jsonl", [
        TrendingObservation(
            repo="acme/rocket", lane=Lane.ONPREM, stars=stars,
            observed_at=datetime(2026, 7, day, 7, 0, tzinfo=UTC),
            repo_created_at=datetime(2026, 6, 1, tzinfo=UTC),
            description="d", topics=["llm"], license="MIT")
        for day, stars in ((1, 100), (4, 400))
    ])

    result = runner.invoke(app, ["export", "--root", str(tmp_path),
                                 "--out", str(tmp_path / "_site")])

    assert result.exit_code == 0
    assert (tmp_path / "_site" / "trending.html").exists()
    assert "acme/rocket" in (tmp_path / "_site" / "trending.html").read_text(encoding="utf-8")


def test_export_survives_naive_datetime_model_candidate(tmp_path):
    runner = CliRunner()
    runner.invoke(app, ["init", "--root", str(tmp_path)])

    # A hand-edited/merge-mangled line with no UTC offset, alongside a normal
    # tz-aware observation for the SAME repo, must not crash the daily
    # publish: build_model_candidates's sorted(rows, key=lambda r: r.observed_at)
    # used to raise "can't compare offset-naive and offset-aware datetimes"
    # once there were >=2 rows to actually compare.
    candidates_path = tmp_path / "data" / "model-candidate-observations.jsonl"
    candidates_path.parent.mkdir(parents=True, exist_ok=True)
    candidates_path.write_text(
        '{"hf_repo":"acme/naive","name":"naive","family":"acme","downloads":10,'
        '"likes":1,"observed_at":"2026-07-06T07:00:00"}\n'
        '{"hf_repo":"acme/naive","name":"naive","family":"acme","downloads":20,'
        '"likes":1,"observed_at":"2026-07-07T07:00:00+00:00"}\n',
        encoding="utf-8",
    )

    result = runner.invoke(app, ["export", "--root", str(tmp_path),
                                 "--out", str(tmp_path / "_site")])

    assert result.exit_code == 0
    assert (tmp_path / "_site" / "index.html").exists()


def test_export_warns_when_research_snapshot_missing(tmp_path):
    """No `radar research scan` has ever run: export must still succeed (the
    daily-publish invariant) but warn that the technique pages reflect no
    (or stale) research data."""
    from radar.storage.database import RadarDatabase

    RadarDatabase(tmp_path / "data" / "radar.db").initialize()

    result = CliRunner().invoke(
        app, ["export", "--root", str(tmp_path), "--out", str(tmp_path / "_site")]
    )

    assert result.exit_code == 0, result.stdout
    assert "research data is stale/missing" in result.output


def test_export_does_not_warn_for_fresh_research_snapshot(tmp_path):
    """A just-completed research scan with real entries must NOT trigger the
    staleness warning — only missing/empty/stale snapshots should."""
    from radar.models import Category, Ring
    from radar.research_radar.entities import OnPremImpact, TechniqueDomain, TechniqueEntry
    from radar.storage.run_store import RunStore

    runner = CliRunner()
    runner.invoke(app, ["init", "--root", str(tmp_path)])
    entry = TechniqueEntry(
        id="qlora", name="QLoRA", category=Category.AI_INFRASTRUCTURE,
        domain=TechniqueDomain.FINE_TUNING, onprem_impact=OnPremImpact.REDUCES_MEMORY,
        ring=Ring.WATCH,
    )
    store = RunStore(tmp_path / "data" / "runs")
    run_id = store.create_run()
    store.save_stage(run_id, "technique_cards", [entry.model_dump(mode="json")])
    store.update_meta(run_id, {"kind": "research", "technique_count": 1})

    result = runner.invoke(app, ["export", "--root", str(tmp_path),
                                 "--out", str(tmp_path / "_site")])

    assert result.exit_code == 0, result.stdout
    assert "research data is stale/missing" not in result.output


def test_export_warns_when_research_snapshot_stale(tmp_path):
    """A research run older than EXPORT_RESEARCH_STALE_DAYS must warn even
    though entries are present — the whole point is catching silent drift
    between the published snapshot and the current research state."""
    from datetime import UTC, datetime, timedelta

    from radar.models import Category, Ring
    from radar.research_radar.entities import OnPremImpact, TechniqueDomain, TechniqueEntry
    from radar.storage.run_store import RunStore

    runner = CliRunner()
    runner.invoke(app, ["init", "--root", str(tmp_path)])
    entry = TechniqueEntry(
        id="qlora", name="QLoRA", category=Category.AI_INFRASTRUCTURE,
        domain=TechniqueDomain.FINE_TUNING, onprem_impact=OnPremImpact.REDUCES_MEMORY,
        ring=Ring.WATCH,
    )
    store = RunStore(tmp_path / "data" / "runs")
    run_id = store.create_run()
    store.save_stage(run_id, "technique_cards", [entry.model_dump(mode="json")])
    store.update_meta(run_id, {"kind": "research", "technique_count": 1})

    # RunStore.update_meta always re-stamps "updated_at" to the current time,
    # so simulating an old run (real time can't be fast-forwarded here)
    # requires writing meta.json directly, bypassing that auto-stamp.
    import json

    meta_path = tmp_path / "data" / "runs" / run_id / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["updated_at"] = (datetime.now(UTC) - timedelta(days=10)).isoformat()
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    result = runner.invoke(app, ["export", "--root", str(tmp_path),
                                 "--out", str(tmp_path / "_site")])

    assert result.exit_code == 0, result.stdout
    assert "research data is stale/missing" in result.output


def test_export_survives_non_string_meta_timestamp(tmp_path):
    """A meta.json that is valid JSON but has a non-string updated_at/created_at
    (e.g. a number) must not crash export with a TypeError from
    datetime.fromisoformat — it should be treated like a missing/stale
    timestamp and just warn."""
    from radar.models import Category, Ring
    from radar.research_radar.entities import OnPremImpact, TechniqueDomain, TechniqueEntry
    from radar.storage.run_store import RunStore

    runner = CliRunner()
    runner.invoke(app, ["init", "--root", str(tmp_path)])
    entry = TechniqueEntry(
        id="qlora", name="QLoRA", category=Category.AI_INFRASTRUCTURE,
        domain=TechniqueDomain.FINE_TUNING, onprem_impact=OnPremImpact.REDUCES_MEMORY,
        ring=Ring.WATCH,
    )
    store = RunStore(tmp_path / "data" / "runs")
    run_id = store.create_run()
    store.save_stage(run_id, "technique_cards", [entry.model_dump(mode="json")])
    store.update_meta(run_id, {"kind": "research", "technique_count": 1})

    # Write meta.json directly with a non-string updated_at (a number), which
    # is valid JSON but not something datetime.fromisoformat can parse without
    # raising TypeError (as opposed to the ValueError a malformed string would
    # raise).
    import json

    meta_path = tmp_path / "data" / "runs" / run_id / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["updated_at"] = 12345
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    result = runner.invoke(app, ["export", "--root", str(tmp_path),
                                 "--out", str(tmp_path / "_site")])

    assert result.exit_code == 0, result.stdout
    assert "research data is stale/missing" in result.output


def test_research_scan_threads_metrics_log_path(tmp_path, monkeypatch):
    """Regression pin: `radar research scan` must thread metrics_log_path
    through to run_research_scan so technique momentum history keeps
    recording — a silent regression here would desync CI vs local runs."""
    captured: dict = {}

    async def _fake_scan(**kwargs):
        captured.update(kwargs)
        return ([], [])

    monkeypatch.setattr("radar.research_radar.pipeline.run_research_scan", _fake_scan)

    result = CliRunner().invoke(app, ["research", "scan", "--root", str(tmp_path)])

    assert result.exit_code == 0, result.stdout
    assert captured["metrics_log_path"].name == "technique-metrics.jsonl"
    assert captured["metrics_log_path"] == tmp_path / "data" / "technique-metrics.jsonl"


def test_scan_health_check_fails_on_degraded_run(tmp_path):
    from radar.storage.run_store import RunStore

    runner = CliRunner()
    store = RunStore(tmp_path / "data" / "runs")
    run_id = store.create_run()
    store.save_stage(run_id, "raw_signals", [])
    store.update_meta(run_id, {"degraded": True, "degraded_reason": "outage"})

    result = runner.invoke(app, ["scan-health", "--root", str(tmp_path), "--check"])
    assert result.exit_code == 1
    assert "degraded" in result.output.lower()
    assert "outage" in result.output


def test_scan_health_check_fails_below_signal_floor(tmp_path):
    from radar.storage.run_store import RunStore

    runner = CliRunner()
    store = RunStore(tmp_path / "data" / "runs")
    run_id = store.create_run()
    store.save_stage(run_id, "raw_signals", [{"id": "s1"}] * 5)

    result = runner.invoke(
        app, ["scan-health", "--root", str(tmp_path), "--check", "--min-signals", "20"]
    )
    assert result.exit_code == 1

    ok = runner.invoke(
        app, ["scan-health", "--root", str(tmp_path), "--check", "--min-signals", "3"]
    )
    assert ok.exit_code == 0


def test_scan_health_without_check_exits_zero_with_printed_problems(tmp_path):
    from radar.storage.run_store import RunStore

    runner = CliRunner()
    store = RunStore(tmp_path / "data" / "runs")
    run_id = store.create_run()
    store.save_stage(run_id, "raw_signals", [{"id": "s1"}])

    result = runner.invoke(
        app, ["scan-health", "--root", str(tmp_path), "--min-signals", "10"]
    )
    assert result.exit_code == 0
    assert "UNHEALTHY" in result.output
    assert "only 1 raw signals" in result.output


def test_scan_health_persisted_meta_contains_degraded_reason(tmp_path):
    import json as json_module

    from radar.storage.run_store import RunStore

    store = RunStore(tmp_path / "data" / "runs")
    run_id = store.create_run()
    store.save_stage(run_id, "raw_signals", [])
    store.update_meta(run_id, {"degraded": True, "degraded_reason": "network timeout"})

    meta_path = tmp_path / "data" / "runs" / run_id / "meta.json"
    meta = json_module.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["degraded_reason"] == "network timeout"


def test_scan_exits_code_2_when_degraded(tmp_path):
    """CLI-level test: radar scan exits 2 on degraded run with unreachable RSS source."""
    from radar.init_project import initialize_project

    initialize_project(tmp_path)
    # Unreachable RSS config trick: 1 dead RSS source creates degraded run
    (tmp_path / "data" / "config.yaml").write_text(
        """
version: "1.0"
sources:
  - id: rss-dead
    type: rss
    enabled: true
    project: DeadFeed
    category: model_serving
    url: http://127.0.0.1:1/feed.xml
    tags: []
quotas:
  model_serving: 4
scoring:
  default_ring: watch
""",
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(app, ["scan", "--root", str(tmp_path), "--days", "2"])

    assert result.exit_code == 2
    assert "degraded" in result.output.lower()
    # The degraded_reason should be in the output
    import json as json_module

    from radar.storage.run_store import RunStore

    store = RunStore(tmp_path / "data" / "runs")
    run_id = store.latest_run_of_kind(None)
    if run_id:
        meta = json_module.loads((tmp_path / "data" / "runs" / run_id / "meta.json").read_text())
        assert "degraded_reason" in meta
