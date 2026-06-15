from datetime import UTC
from pathlib import Path

from fastapi.testclient import TestClient

from radar.models import (
    Backer,
    BackerType,
    Category,
    DecisionCard,
    OnPremAssessment,
    Ring,
)
from radar.storage.database import RadarDatabase
from radar.web.app import create_app


def test_dashboard_shows_backer_badge_and_filter(tmp_path: Path):
    db = RadarDatabase(tmp_path / "data" / "radar.db")
    db.initialize()
    db.upsert_cards(
        [
            DecisionCard(
                project="vLLM",
                category=Category.MODEL_SERVING,
                backer=Backer(name="NVIDIA", type=BackerType.BIG_TECH),
                ring=Ring.ADOPT,
                summary="fast inference",
                workflow_fit={},
                risk_level="low",
            )
        ]
    )

    response = TestClient(create_app(tmp_path)).get("/")

    assert response.status_code == 200
    assert "Backed by" in response.text  # column header
    assert "NVIDIA" in response.text  # backer name badge
    assert 'class="backer backer-big_tech"' in response.text
    assert 'id="filter-backer"' in response.text  # backer filter control
    assert 'data-backer-type="big_tech"' in response.text  # row attr for JS filter


def test_dashboard_lists_cards(tmp_path: Path):
    db_path = tmp_path / "data" / "radar.db"
    db = RadarDatabase(db_path)
    db.initialize()
    db.upsert_cards(
        [
            DecisionCard(
                project="Cline",
                category=Category.CODING_AGENTS,
                ring=Ring.PILOT,
                summary="Coding agent",
                workflow_fit={"personal_dev": "high"},
                risk_level="medium",
            )
        ]
    )

    client = TestClient(create_app(tmp_path))
    response = client.get("/")

    assert response.status_code == 200
    assert "Cline" in response.text
    assert "pilot" in response.text


def test_brand_logo_served_and_referenced(tmp_path: Path):
    db = RadarDatabase(tmp_path / "data" / "radar.db")
    db.initialize()
    client = TestClient(create_app(tmp_path))

    # The dashboard references the real Mega logo (absolute /static path).
    html = client.get("/").text
    assert 'class="brand-logo"' in html
    assert "/static/brand/mega-logo-white.svg" in html

    # And the assets (vector logo + bundled font) are actually served.
    asset = client.get("/static/brand/mega-logo-white.svg")
    assert asset.status_code == 200
    assert "svg" in asset.headers["content-type"]
    font = client.get("/static/brand/fonts/hanken-grotesk-400.woff2")
    assert font.status_code == 200


def test_history_jsonl_download_route(tmp_path: Path):
    db = RadarDatabase(tmp_path / "data" / "radar.db")
    db.initialize()
    log = tmp_path / "data" / "history.jsonl"
    log.write_text('{"event": "demo"}\n', encoding="utf-8")

    client = TestClient(create_app(tmp_path))
    ok = client.get("/history.jsonl")
    assert ok.status_code == 200
    assert ok.text == '{"event": "demo"}\n'


def test_history_jsonl_download_404_when_absent(tmp_path: Path):
    db = RadarDatabase(tmp_path / "data" / "radar.db")
    db.initialize()
    client = TestClient(create_app(tmp_path))
    assert client.get("/history.jsonl").status_code == 404


def test_dashboard_renders_hero_stats_and_download_link(tmp_path: Path):
    db = RadarDatabase(tmp_path / "data" / "radar.db")
    db.initialize()
    db.upsert_cards(
        [
            DecisionCard(
                project="Cline", category=Category.CODING_AGENTS, ring=Ring.PILOT,
                summary="Coding agent", workflow_fit={}, risk_level="low",
            )
        ]
    )
    text = TestClient(create_app(tmp_path)).get("/").text
    assert 'class="hero"' in text
    assert 'class="stats"' in text
    assert 'href="/history.jsonl"' in text  # footer download link


def _init_project(tmp_path: Path) -> None:
    from radar.init_project import initialize_project

    initialize_project(tmp_path)


def test_sources_page_shows_add_form(tmp_path: Path):
    _init_project(tmp_path)

    client = TestClient(create_app(tmp_path))
    response = client.get("/sources")

    assert response.status_code == 200
    assert "<form" in response.text
    # existing seed sources are listed
    assert "github" in response.text.lower()


def test_post_source_adds_seed_and_persists(tmp_path: Path):
    _init_project(tmp_path)

    client = TestClient(create_app(tmp_path))
    response = client.post(
        "/sources",
        data={
            "id": "rss-web-feed",
            "type": "rss",
            "project": "Web Feed",
            "category": "model_serving",
            "url": "https://example.com/feed.xml",
            "tags": "vendor-blog, inference",
        },
        follow_redirects=False,
    )

    # redirect back to the sources page after a successful add
    assert response.status_code in (302, 303)

    from radar.storage.config import load_config
    config = load_config(tmp_path / "data" / "config.yaml")
    assert any(s.id == "rss-web-feed" for s in config.sources)


def test_compare_page_renders_matrix(tmp_path: Path):
    from radar.models import Category, Ring
    from radar.storage.database import RadarDatabase

    db_path = tmp_path / "data" / "radar.db"
    db = RadarDatabase(db_path)
    db.initialize()
    db.upsert_cards(
        [
            DecisionCard(
                project="Cline", category=Category.CODING_AGENTS, ring=Ring.PILOT,
                summary="x", workflow_fit={}, risk_level="medium",
            ),
            DecisionCard(
                project="Aider", category=Category.CODING_AGENTS, ring=Ring.ADOPT,
                summary="x", workflow_fit={}, risk_level="low",
            ),
        ]
    )

    client = TestClient(create_app(tmp_path))
    response = client.get("/compare", params={"category": "coding_agents"})

    assert response.status_code == 200
    assert "Cline" in response.text
    assert "Aider" in response.text
    assert "adopt" in response.text


def test_history_page_renders_recorded_events(tmp_path: Path):
    from datetime import datetime

    from radar.models import Category, Ring
    from radar.pipeline.delta import CardDelta, ChangeType
    from radar.storage.history_store import HistoryStore

    _init_project(tmp_path)
    history = HistoryStore(tmp_path / "data" / "radar.db")
    history.initialize()
    card = DecisionCard(
        project="Ollama",
        category=Category.MODEL_SERVING,
        ring=Ring.PILOT,
        summary="x",
        workflow_fit={},
        risk_level="medium",
    )
    history.record_deltas(
        [
            CardDelta(
                project="Ollama",
                category=Category.MODEL_SERVING,
                change_type=ChangeType.NEW,
                current_ring=Ring.PILOT,
                previous_ring=None,
                reasons=["New on the radar."],
                card=card,
            )
        ],
        run_id="run-1",
        observed_at=datetime(2026, 6, 10, tzinfo=UTC),
    )

    client = TestClient(create_app(tmp_path))
    response = client.get("/history")

    assert response.status_code == 200
    assert "Ollama" in response.text
    assert "2026-06-10" in response.text


def test_post_source_rejects_duplicate_with_message(tmp_path: Path):
    _init_project(tmp_path)
    client = TestClient(create_app(tmp_path))
    form = {
        "id": "rss-web-dup", "type": "rss", "project": "Dup",
        "category": "model_serving", "url": "https://example.com/feed.xml",
        "tags": "",
    }
    client.post("/sources", data=form, follow_redirects=False)

    response = client.post("/sources", data=form, follow_redirects=False)

    assert response.status_code == 200
    assert "already exists" in response.text


def test_dashboard_surfaces_evidence_and_flags(tmp_path: Path):
    db = RadarDatabase(tmp_path / "data" / "radar.db")
    db.initialize()
    db.upsert_cards(
        [
            DecisionCard(
                project="vLLM",
                category=Category.MODEL_SERVING,
                ring=Ring.AVOID,
                summary="fast inference",
                workflow_fit={},
                risk_level="high",
                trend="rising",
                evidence_notes=["Recent CRITICAL security advisory GHSA-xxxx: RCE."],
                upgrade_risk="high",
                pinned=True,
                pinned_reason="failed review",
                computed_ring=Ring.WATCH,
            )
        ]
    )

    client = TestClient(create_app(tmp_path))
    text = client.get("/").text

    assert "GHSA-xxxx" in text  # evidence note shown
    assert "upgrade risk" in text  # upgrade-risk badge
    assert "pinned" in text  # pin badge
    assert "↑" in text  # rising trend arrow


def _rich_card_for_detail():
    return DecisionCard(
        project="vLLM",
        category=Category.MODEL_SERVING,
        ring=Ring.AVOID,
        score=2.71,
        summary="fast inference",
        workflow_fit={"personal_dev": "high"},
        risk_level="high",
        on_prem_fit="strong: strongest in local offline runnability.",
        on_prem_rubric={
            "local_offline_runnability": OnPremAssessment(
                score=5, reason="runs fully offline via local models"
            )
        },
        evidence=["https://github.com/vllm-project/vllm"],
        evidence_notes=["Recent CRITICAL security advisory GHSA-xxxx: RCE."],
        upgrade_risk="high",
        upgrade_risk_notes=["BREAKING CHANGE: engine API moved."],
        trend="rising",
        pinned=True,
        pinned_reason="failed internal review",
        computed_ring=Ring.WATCH,
    )


def test_project_page_renders_full_card(tmp_path: Path):
    db = RadarDatabase(tmp_path / "data" / "radar.db")
    db.initialize()
    db.upsert_cards([_rich_card_for_detail()])

    client = TestClient(create_app(tmp_path))
    text = client.get("/project/vLLM").text

    assert "vLLM" in text
    assert "fast inference" in text
    assert "runs fully offline via local models" in text  # rubric reason
    assert "GHSA-xxxx" in text  # evidence note
    assert "BREAKING CHANGE: engine API moved." in text  # upgrade-risk note
    assert "failed internal review" in text  # pin reason


def test_project_page_case_insensitive(tmp_path: Path):
    db = RadarDatabase(tmp_path / "data" / "radar.db")
    db.initialize()
    db.upsert_cards(
        [
            DecisionCard(
                project="Ollama", category=Category.MODEL_SERVING, ring=Ring.PILOT,
                summary="local models", workflow_fit={}, risk_level="low",
            )
        ]
    )

    client = TestClient(create_app(tmp_path))
    resp = client.get("/project/ollama")

    assert resp.status_code == 200
    assert "Ollama" in resp.text


def test_project_page_unknown_returns_404(tmp_path: Path):
    db = RadarDatabase(tmp_path / "data" / "radar.db")
    db.initialize()

    client = TestClient(create_app(tmp_path))
    resp = client.get("/project/DoesNotExist")

    assert resp.status_code == 404


def test_project_page_shows_metrics_and_history(tmp_path: Path):
    from datetime import datetime

    from radar.pipeline.delta import CardDelta, ChangeType
    from radar.storage.history_store import HistoryStore
    from radar.storage.metrics_store import MetricsStore, ProjectMetrics

    db = RadarDatabase(tmp_path / "data" / "radar.db")
    db.initialize()
    db.upsert_cards(
        [
            DecisionCard(
                project="vLLM", category=Category.MODEL_SERVING, ring=Ring.ADOPT,
                summary="s", workflow_fit={}, risk_level="low",
            )
        ]
    )
    metrics = MetricsStore(tmp_path / "data" / "radar.db")
    metrics.initialize()
    metrics.record(
        [
            ProjectMetrics(
                project="vLLM", run_id="run-1",
                observed_at=datetime(2026, 6, 10, tzinfo=UTC), stars=54321,
            )
        ]
    )
    history = HistoryStore(tmp_path / "data" / "radar.db")
    history.initialize()
    history.record_deltas(
        [
            CardDelta(
                project="vLLM", category=Category.MODEL_SERVING,
                change_type=ChangeType.NEW, current_ring=Ring.ADOPT,
                previous_ring=None, reasons=["New on the radar."],
                card=DecisionCard(
                    project="vLLM", category=Category.MODEL_SERVING, ring=Ring.ADOPT,
                    summary="s", workflow_fit={}, risk_level="low",
                ),
            )
        ],
        run_id="run-1",
        observed_at=datetime(2026, 6, 10, tzinfo=UTC),
    )

    client = TestClient(create_app(tmp_path))
    text = client.get("/project/vLLM").text

    assert "54,321" in text or "54321" in text  # metric value
    assert "2026-06-10" in text  # history event date


def test_index_links_to_project_page(tmp_path: Path):
    db = RadarDatabase(tmp_path / "data" / "radar.db")
    db.initialize()
    db.upsert_cards(
        [
            DecisionCard(
                project="vLLM", category=Category.MODEL_SERVING, ring=Ring.ADOPT,
                summary="s", workflow_fit={}, risk_level="low",
            )
        ]
    )

    client = TestClient(create_app(tmp_path))
    text = client.get("/").text

    assert "/project/vLLM" in text


def test_index_shows_scan_health_when_runs_exist(tmp_path: Path):

    from radar.storage.run_store import RunStore

    db = RadarDatabase(tmp_path / "data" / "radar.db")
    db.initialize()
    db.upsert_cards(
        [
            DecisionCard(
                project="vLLM", category=Category.MODEL_SERVING, ring=Ring.ADOPT,
                summary="s", workflow_fit={}, risk_level="low",
            )
        ]
    )
    rs = RunStore(tmp_path / "data" / "runs")
    run_id = rs.create_run()
    rs.update_meta(run_id, {"collector_warnings": ["GitHubCollector: 403"]})

    client = TestClient(create_app(tmp_path))
    text = client.get("/").text

    assert "scan-health" in text
    assert "collector warning" in text


def test_index_no_scan_health_block_when_empty(tmp_path: Path):
    db = RadarDatabase(tmp_path / "data" / "radar.db")
    db.initialize()

    client = TestClient(create_app(tmp_path))
    resp = client.get("/")

    assert resp.status_code == 200  # renders fine with no runs


def _two_category_cards():
    return [
        DecisionCard(
            project="vLLM", category=Category.MODEL_SERVING, ring=Ring.ADOPT,
            summary="fast inference", workflow_fit={}, risk_level="low",
        ),
        DecisionCard(
            project="Cline", category=Category.CODING_AGENTS, ring=Ring.PILOT,
            summary="coding agent", workflow_fit={}, risk_level="low",
        ),
    ]


def test_index_renders_filter_controls(tmp_path: Path):
    db = RadarDatabase(tmp_path / "data" / "radar.db")
    db.initialize()
    db.upsert_cards(_two_category_cards())

    text = TestClient(create_app(tmp_path)).get("/").text

    assert 'id="filter-text"' in text
    assert 'id="filter-category"' in text
    assert "radarFilter" in text  # the inline script
    assert 'id="radar-no-matches"' in text


def test_index_filter_options_match_present_categories(tmp_path: Path):
    db = RadarDatabase(tmp_path / "data" / "radar.db")
    db.initialize()
    db.upsert_cards(_two_category_cards())

    text = TestClient(create_app(tmp_path)).get("/").text

    assert '<option value="coding_agents">' in text
    assert '<option value="model_serving">' in text
    # A category not present must not appear as an option.
    assert '<option value="fun_experimental">' not in text


def test_index_rows_have_data_attributes(tmp_path: Path):
    db = RadarDatabase(tmp_path / "data" / "radar.db")
    db.initialize()
    db.upsert_cards(_two_category_cards())

    text = TestClient(create_app(tmp_path)).get("/").text

    assert 'data-project="vLLM"' in text
    assert 'data-category="coding_agents"' in text
