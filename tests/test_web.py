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


# ---------------------------------------------------------------------------
# Models catalog + per-model live routes (Task 6)
# ---------------------------------------------------------------------------

from radar.storage.run_store import RunStore  # noqa: E402


def _seed_models(root: Path):
    from radar.models import Ring
    from radar.models_radar.entities import (
        HardwareTier,
        Modality,
        ModelEntry,
        Openness,
        Platform,
        QuantVariant,
    )
    rs = RunStore(root / "data" / "runs")
    rid = rs.create_run()
    e = ModelEntry(id="qwen3-8b", name="Qwen3 8B", family="Qwen3", params_total=8_000_000_000,
                   openness=Openness.OPEN_PERMISSIVE, hardware_tier=HardwareTier.LAPTOP,
                   ring=Ring.ADOPT, score=4.0, modality=Modality.TEXT,
                   quants=[QuantVariant(format="Q4_K_M", bits_per_weight=4.5,
                                        est_memory_gb_4k=8.0, platform=Platform.GENERIC, source="hf:x")])
    rs.save_stage(rid, "model_cards", [e.model_dump(mode="json")])
    rs.update_meta(rid, {"kind": "models", "model_count": 1})


def test_models_route_lists_models(tmp_path):
    (tmp_path / "data").mkdir(parents=True)
    _seed_models(tmp_path)
    client = TestClient(create_app(tmp_path))
    r = client.get("/models")
    assert r.status_code == 200 and "qwen3-8b" in r.text and "laptop" in r.text


def test_model_detail_route(tmp_path):
    (tmp_path / "data").mkdir(parents=True)
    _seed_models(tmp_path)
    client = TestClient(create_app(tmp_path))
    r = client.get("/model/qwen3-8b")
    assert r.status_code == 200 and "Q4_K_M" in r.text


def test_models_route_empty_when_no_scan(tmp_path):
    (tmp_path / "data").mkdir(parents=True)
    client = TestClient(create_app(tmp_path))
    assert client.get("/models").status_code == 200  # renders "no models yet", no crash


def test_models_route_links_to_live_model_paths(tmp_path):
    """Live /models catalog must link to /model/<id>, not model_*.html."""
    (tmp_path / "data").mkdir(parents=True)
    _seed_models(tmp_path)
    client = TestClient(create_app(tmp_path))
    r = client.get("/models")
    assert r.status_code == 200
    assert 'href="/model/' in r.text
    assert "model_qwen3-8b.html" not in r.text


def test_model_detail_route_back_link_is_live(tmp_path):
    """Live /model/<id> detail page must link back to /models, not models.html."""
    (tmp_path / "data").mkdir(parents=True)
    _seed_models(tmp_path)
    client = TestClient(create_app(tmp_path))
    r = client.get("/model/qwen3-8b")
    assert r.status_code == 200
    assert 'href="/models"' in r.text
    assert 'href="models.html"' not in r.text


def test_model_detail_route_unknown_returns_404(tmp_path):
    (tmp_path / "data").mkdir(parents=True)
    client = TestClient(create_app(tmp_path))
    assert client.get("/model/does-not-exist").status_code == 404


def test_models_page_is_styled_and_filterable(tmp_path):
    """Live /models page must have the shell, filter bar, and richer table."""
    (tmp_path / "data").mkdir(parents=True)
    _seed_models(tmp_path)
    client = TestClient(create_app(tmp_path))
    r = client.get("/models")
    assert r.status_code == 200
    assert "models-table" in r.text
    assert "mfilter-family" in r.text
    assert "ring-pill" in r.text
    assert "Use case" in r.text
    assert "Context" in r.text
    # Sortable headers + sort script on the live page too
    assert "function modelsSort" in r.text
    assert 'data-key="min-memory-gb" data-type="num"' in r.text


def _seed_techniques_run(root: Path) -> None:
    from radar.models import Category as _Cat
    from radar.models import Ring as _Ring
    from radar.research_radar.entities import (
        OnPremImpact as _Imp,
    )
    from radar.research_radar.entities import (
        PaperLink as _PL,
    )
    from radar.research_radar.entities import (
        TechniqueDomain as _Dom,
    )
    from radar.research_radar.entities import (
        TechniqueEntry as _TE,
    )
    from radar.storage.run_store import RunStore as _RS

    (root / "data").mkdir(parents=True, exist_ok=True)
    entry = _TE(
        id="speculative-decoding", name="Speculative Decoding",
        category=_Cat.MODEL_SERVING, domain=_Dom.INFERENCE,
        onprem_impact=_Imp.REDUCES_LATENCY, ring=_Ring.ADOPT, score=4.3,
        citation_count=1697,
        papers=[_PL(arxiv_id="2211.17192", title="Fast Inference", published="2022-11")],
    )
    store = _RS(root / "data" / "runs")
    run_id = store.create_run()
    store.save_stage(run_id, "technique_cards", [entry.model_dump(mode="json")])
    store.update_meta(run_id, {"kind": "research", "technique_count": 1})


def test_research_route_lists_techniques(tmp_path):
    _seed_techniques_run(tmp_path)
    client = TestClient(create_app(tmp_path))

    r = client.get("/research")

    assert r.status_code == 200
    assert "Speculative Decoding" in r.text
    assert "inference" in r.text
    assert 'href="/technique/speculative-decoding"' in r.text


def test_research_route_empty_without_scan(tmp_path):
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    client = TestClient(create_app(tmp_path))

    r = client.get("/research")

    assert r.status_code == 200
    assert "No research scan yet" in r.text


def test_technique_detail_route_shows_timeline_and_papers(tmp_path):
    _seed_techniques_run(tmp_path)
    client = TestClient(create_app(tmp_path))

    r = client.get("/technique/speculative-decoding")

    assert r.status_code == 200
    assert "2211.17192" in r.text
    assert "canonical paper" in r.text
    assert 'href="/research"' in r.text  # live back-link, not techniques.html


def test_technique_detail_unknown_returns_404(tmp_path):
    _seed_techniques_run(tmp_path)
    client = TestClient(create_app(tmp_path))

    assert client.get("/technique/nope").status_code == 404


def test_index_shows_research_summary_and_nav(tmp_path):
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    _seed_techniques_run(tmp_path)
    client = TestClient(create_app(tmp_path))

    r = client.get("/")

    assert "Research: 1 techniques" in r.text
    assert 'href="/research"' in r.text


def test_scan_health_survives_a_later_research_run(tmp_path):
    """A models/research scan after the tool scan must not blank scan health."""
    from radar.storage.run_store import RunStore as _RS

    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    store = _RS(tmp_path / "data" / "runs")
    tool_run = store.create_run()
    store.update_meta(tool_run, {"collector_warnings": ["github: rate limited"]})
    research_run = store.create_run()
    store.save_stage(research_run, "technique_cards", [])
    store.update_meta(research_run, {"kind": "research", "technique_count": 0})

    client = TestClient(create_app(tmp_path))
    r = client.get("/")

    assert "rate limited" in r.text


def _card(project: str, ring: Ring) -> DecisionCard:
    return DecisionCard(
        project=project, category=Category.MODEL_SERVING, ring=ring,
        summary=f"{project} summary", workflow_fit={}, risk_level="low",
    )


def _seed_pedigree_research_run(root: Path, tool_ref: str) -> None:
    from radar.models import Category as _Cat
    from radar.models import Ring as _Ring
    from radar.research_radar.entities import (
        ImplKind as _IK,
    )
    from radar.research_radar.entities import (
        OnPremImpact as _Imp,
    )
    from radar.research_radar.entities import (
        ResolvedImplementation as _RI,
    )
    from radar.research_radar.entities import (
        TechniqueDomain as _Dom,
    )
    from radar.research_radar.entities import (
        TechniqueEntry as _TE,
    )
    from radar.storage.run_store import RunStore as _RS

    entry = _TE(
        id="spec-dec", name="Speculative Decoding", category=_Cat.MODEL_SERVING,
        domain=_Dom.INFERENCE, onprem_impact=_Imp.REDUCES_LATENCY, ring=_Ring.ADOPT,
        citation_count=1697,
        resolved_implementations=[
            _RI(kind=_IK.TOOL, ref=tool_ref, ring=None),
            _RI(kind=_IK.MODEL, ref="llama-3.3-70b", ring=None),
        ],
    )
    store = _RS(root / "data" / "runs")
    run_id = store.create_run()
    store.update_meta(run_id, {"kind": "research"})
    store.save_stage(run_id, "technique_cards", [entry.model_dump(mode="json")])


def _write_pedigree_config(root: Path, source_id: str, project: str) -> None:
    (root / "data").mkdir(parents=True, exist_ok=True)
    (root / "data" / "config.yaml").write_text(
        f"""
sources:
  - id: {source_id}
    type: github_repo
    project: {project}
    category: model_serving
    url: https://github.com/vllm-project/vllm
""",
        encoding="utf-8",
    )


def test_project_page_shows_research_pedigree(tmp_path: Path):
    db = RadarDatabase(tmp_path / "data" / "radar.db")
    db.initialize()
    db.upsert_cards([_card("vLLM", Ring.ADOPT)])
    _write_pedigree_config(tmp_path, "github-vllm", "vLLM")
    _seed_pedigree_research_run(tmp_path, "github-vllm")

    text = TestClient(create_app(tmp_path)).get("/project/vLLM").text

    assert "Research techniques" in text
    assert "Speculative Decoding" in text
    assert 'href="/technique/spec-dec"' in text


def test_project_page_without_research_run_has_no_pedigree_section(tmp_path: Path):
    db = RadarDatabase(tmp_path / "data" / "radar.db")
    db.initialize()
    db.upsert_cards([_card("vLLM", Ring.ADOPT)])

    text = TestClient(create_app(tmp_path)).get("/project/vLLM").text

    assert "Research techniques" not in text


def _seed_pedigree_research_run_for_model(root: Path, model_ref: str) -> None:
    from radar.research_radar.entities import (
        ImplKind as _IK,
    )
    from radar.research_radar.entities import (
        OnPremImpact as _Imp,
    )
    from radar.research_radar.entities import (
        ResolvedImplementation as _RI,
    )
    from radar.research_radar.entities import (
        TechniqueDomain as _Dom,
    )
    from radar.research_radar.entities import (
        TechniqueEntry as _TE,
    )
    from radar.storage.run_store import RunStore as _RS

    entry = _TE(
        id="spec-dec", name="Speculative Decoding", category=Category.MODEL_SERVING,
        domain=_Dom.INFERENCE, onprem_impact=_Imp.REDUCES_LATENCY, ring=Ring.ADOPT,
        citation_count=1697,
        resolved_implementations=[_RI(kind=_IK.MODEL, ref=model_ref, ring=None)],
    )
    store = _RS(root / "data" / "runs")
    run_id = store.create_run()
    store.update_meta(run_id, {"kind": "research"})
    store.save_stage(run_id, "technique_cards", [entry.model_dump(mode="json")])


def test_model_page_shows_research_pedigree(tmp_path: Path):
    _seed_models(tmp_path)
    _seed_pedigree_research_run_for_model(tmp_path, "qwen3-8b")

    text = TestClient(create_app(tmp_path)).get("/model/qwen3-8b").text

    assert "Research techniques" in text
    assert "Speculative Decoding" in text
    assert 'href="/technique/spec-dec"' in text


def test_technique_page_links_implementations(tmp_path: Path):
    db = RadarDatabase(tmp_path / "data" / "radar.db")
    db.initialize()
    db.upsert_cards([_card("vLLM", Ring.ADOPT)])
    _write_pedigree_config(tmp_path, "github-vllm", "vLLM")
    _seed_pedigree_research_run(tmp_path, "github-vllm")

    text = TestClient(create_app(tmp_path)).get("/technique/spec-dec").text

    assert 'href="/project/vLLM"' in text          # tool impl linked
    assert 'href="/model/llama-3.3-70b"' in text   # model impl linked


def test_technique_page_unresolvable_impl_stays_plain(tmp_path: Path):
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    _seed_pedigree_research_run(tmp_path, "github-gone")  # no config → no id→project map

    text = TestClient(create_app(tmp_path)).get("/technique/spec-dec").text

    assert "github-gone" in text
    assert 'href="/project/' not in text
