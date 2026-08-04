"""FastMCP adapter exposing the radar to agents.

Thin wrapper over :class:`RadarQueryService` — each tool is a few lines that
delegate to the query service and return JSON-serializable data. No scan is
triggered; tools answer from the latest persisted run. This lets Claude/Codex/
OpenClaw ask the radar "what should I try this week?" directly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from radar.intelligence.bootstrap import build_intelligence_repository
from radar.intelligence.services.container import build_services_for_root
from radar.mcp_server.capacity_queries import CapacityQueryService
from radar.mcp_server.intelligence_queries import IntelligenceQueryService
from radar.mcp_server.model_queries import ModelQueryService
from radar.mcp_server.queries import RadarQueryService
from radar.mcp_server.technique_queries import TechniqueQueryService
from radar.mcp_server.trending_queries import TrendingQueryService


def build_mcp_server(root: Path) -> FastMCP:
    """Build a FastMCP server backed by the radar state under ``root``."""
    service = RadarQueryService(root)
    models = ModelQueryService(root)
    techniques = TechniqueQueryService(root)
    trending = TrendingQueryService(root)
    capacity = CapacityQueryService(root)
    _database, intelligence_repository = build_intelligence_repository(root)
    intelligence = IntelligenceQueryService(
        build_services_for_root(root, intelligence_repository),
        intelligence_repository,
    )
    mcp = FastMCP("onprem-ai-adoption-radar")

    @mcp.tool()
    def list_recommendations(
        rings: list[str] | None = None,
        detail: str = "compact",
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """List current decision cards (highest score first), to BROWSE.

        Returns a compact, context-cheap card per project: project, category,
        backer, ring, score, risk_level, trend, summary, and one `headline`
        evidence line. Non-default fields (`upgrade_risk`, `pinned`) are only
        present when they carry signal. Call `get_project(<name>)` for the full
        card (evidence notes, risks, try-next steps, source URLs, history).

        - `rings`: filter by ring, e.g. ["adopt", "pilot"] for actionable picks.
          Unknown rings are ignored.
        - `limit`: cap the number returned (top-N by score).
        - `detail`: "compact" (default) or "full" for every field at once
          (heavy — prefer compact + get_project).
        """
        return service.recommendations(rings=rings, detail=detail, limit=limit)

    @mcp.tool()
    def get_project(project: str) -> dict[str, Any] | None:
        """Get a single project's current card plus its observation history.

        The card includes observed evidence (`evidence_notes`, `upgrade_risk`,
        `trend`) and any human override (`pinned`, `pinned_reason`,
        `computed_ring`); `history` is the chronological ring-change timeline.
        """
        return service.get_project(project)

    @mcp.tool()
    def list_tracked_projects() -> list[dict[str, Any]]:
        """List all tracked projects with their category and current ring."""
        return service.list_projects()

    @mcp.tool()
    def compare(
        projects: list[str] | None = None,
        category: str | None = None,
    ) -> dict[str, Any]:
        """Compare projects side by side (ring, risk, on-prem rubric).

        Provide exactly one of: a list of project names, or a category
        (e.g. "coding_agents"). Returns a matrix or {"error": ...}.
        """
        return service.compare(projects=projects, category=category)

    @mcp.tool()
    def sandbox_plan(project: str) -> dict[str, Any] | None:
        """Get a safe, disposable trial recipe (steps, teardown, cautions)."""
        return service.sandbox_plan(project)

    @mcp.tool()
    def list_models(
        max_memory_gb: float | None = None,
        hardware_tier: str | None = None,
        family: str | None = None,
        modality: str | None = None,
        detail: str = "compact",
        profile: str | None = None,
    ) -> list[dict]:
        """List tracked local models, optionally filtered by fit/family/modality.

        `profile`: rescore through an alternate lens before filtering/shaping
        (e.g. "datacenter-first" weights single/multi-node deployability
        instead of penalizing it). Persisted rings are unaffected — this is
        a view. Omit for the default (persisted) scoring.
        """
        return models.list_models(max_memory_gb, hardware_tier, family, modality, detail, profile)

    @mcp.tool()
    def get_model(model_id: str) -> dict | None:
        """Full spec + quant table + ring + recent history/momentum for one model."""
        return models.get_model(model_id)

    @mcp.tool()
    def model_movers() -> list[dict]:
        """Models trending up/down (ring changes or download growth)."""
        return models.model_movers()

    @mcp.tool()
    def list_devices() -> list[dict]:
        """List built-in device presets (GPU/Apple/CPU) with usable memory."""
        return models.list_devices()

    @mcp.tool()
    def can_run(model_id: str, device: str | dict, context_tokens: int = 4096) -> dict | None:
        """Whether a model fits a device (preset id or {kind,total_memory_gb,gpu_count}) + best quant."""
        return models.can_run(model_id, device, context_tokens)

    @mcp.tool()
    def fit_report(device: str | dict, context_tokens: int = 4096) -> list[dict]:
        """Per-model fit verdicts for a device (preset id or custom spec)."""
        return models.device_fit_report(device, context_tokens)

    @mcp.tool()
    def get_platform_support(platform: str | None = None, feature: str | None = None) -> list[dict]:
        """Which serving engines (vLLM, SGLang, TensorRT-LLM, ...) support a
        hardware/feature key — every claim cited from the engine's own docs.

        No args: full row per engine. `platform`: one engine's full row.
        `feature`: one {platform, feature, support, sources} row per engine
        for that single hardware or feature key (e.g. "nvidia", "mla",
        "disaggregated_prefill").
        """
        return models.get_platform_support(platform=platform, feature=feature)

    @mcp.tool()
    def list_techniques(
        ring: str | None = None,
        domain: str | None = None,
        category: str | None = None,
        detail: str = "compact",
    ) -> list[dict]:
        """Research techniques with rings (compact rows; detail='full' for everything)."""
        return techniques.list_techniques(ring=ring, domain=domain,
                                          category=category, detail=detail)

    @mcp.tool()
    def get_technique(technique_id: str) -> dict | None:
        """One technique: score breakdown, papers, implementations, history, momentum."""
        return techniques.get_technique(technique_id)

    @mcp.tool()
    def technique_movers() -> list[dict]:
        """Recent technique ring changes, newest first."""
        return techniques.technique_movers()

    @mcp.tool()
    def list_trending(lane: str | None = None, limit: int = 20) -> list[dict]:
        """Trending/newly-created GitHub repos by star velocity (lane: onprem | broader)."""
        return trending.list_trending(lane=lane, limit=limit)

    @mcp.tool()
    def recommend(
        task: str,
        device: str,
        allowed_licenses: list[str] | None = None,
        min_context: int | None = None,
        limit: int = 5,
    ) -> dict[str, Any]:
        """What should I run? Ranked, cited candidates for a task on a device.

        Tasks: coding, general-chat, reasoning, rag, vision. Each candidate
        carries fit (capacity engine), tracked-set task percentile, license
        gate, curated ring, and the factor list behind its rank; exclusions
        come back with reasons. `allowed_licenses` filters to a policy;
        `min_context` raises the working-context requirement.
        """
        from radar.models_radar.advisor import build_answers
        from radar.web.public_context import load_public_model_profiles

        return build_answers(
            load_public_model_profiles(root),
            device,
            task,
            allowed_licenses=allowed_licenses,
            min_context=min_context,
            limit=limit,
        )

    @mcp.tool()
    def plan_capacity(
        model_id: str,
        device: str,
        concurrent_requests: int,
        avg_context_tokens: int,
        target_tps_per_user: float | None = None,
        quant: str | None = None,
        kv_dtype: str = "fp16",
        engine: str = "vllm",
    ) -> dict[str, Any] | None:
        """Smallest GPU count (+ layout) that serves a workload, or why it can't.

        Every answer is an ESTIMATE, not a measurement: the returned
        `assumptions.lines` disclose exactly what was assumed (quant
        fallback, the TP/PP layout heuristic, engine efficiency constants,
        ...) — those engine throughput constants in particular are
        documented estimates pending real-world calibration, not benchmarked
        numbers. Memory figures are in GB; decode/prefill throughput is in
        tokens/sec (aggregate and per-user).

        `device`: a preset id (see `list_devices`). Returns `None` only for
        an unknown `model_id`. A bad device/quant/kv_dtype/engine, or a
        workload nothing fits, never raises — both come back as
        `{"feasible": False, "reasons": [...]}` instead.
        """
        return capacity.plan_capacity(
            model_id, device, concurrent_requests, avg_context_tokens,
            target_tps_per_user=target_tps_per_user, quant=quant,
            kv_dtype=kv_dtype, engine=engine,
        )

    @mcp.tool()
    def max_workload(
        model_id: str,
        device: str,
        n_gpus: int,
        avg_context_tokens: int,
        quant: str | None = None,
        kv_dtype: str = "fp16",
        engine: str = "vllm",
    ) -> dict[str, Any] | None:
        """Largest concurrency a fixed GPU fleet can serve at a context length.

        Same honesty contract as `plan_capacity`: an ESTIMATE whose
        `assumptions.lines` disclose every assumption, including that engine
        efficiency constants are documented estimates — not measurements —
        pending calibration. Memory in GB, throughput in tokens/sec/user.

        Returns `None` only for an unknown `model_id`. Infeasible or invalid
        inputs (bad device/quant/kv_dtype/engine) come back as
        `{"feasible": False, "reasons": [...]}`, never a raised exception.
        """
        return capacity.max_workload(
            model_id, device, n_gpus, avg_context_tokens,
            quant=quant, kv_dtype=kv_dtype, engine=engine,
        )

    @mcp.tool()
    def compare_devices(
        model_id: str,
        devices: list[str],
        concurrent_requests: int,
        avg_context_tokens: int,
        target_tps_per_user: float | None = None,
        quant: str | None = None,
        kv_dtype: str = "fp16",
        engine: str = "vllm",
    ) -> list[dict[str, Any]] | None:
        """Plan the same workload across several devices, side by side.

        One row per requested device id, in the order given — each solved
        independently and carrying its own `device` id and `feasible`
        verdict (with `reasons` when infeasible, or when the device id
        itself is unrecognized — never a raised exception for a bad id in
        the list). Same honesty contract as `plan_capacity`: estimates only,
        assumptions disclosed per row, memory in GB, throughput in
        tokens/sec/user; engine efficiency constants are documented
        estimates pending calibration.

        Returns `None` only for an unknown `model_id`.
        """
        return capacity.compare_devices(
            model_id, devices, concurrent_requests, avg_context_tokens,
            target_tps_per_user=target_tps_per_user, quant=quant,
            kv_dtype=kv_dtype, engine=engine,
        )

    @mcp.tool()
    def search_intelligence(
        query: str,
        workspace_id: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Search the unified model/release catalog with compact results."""
        return intelligence.search(
            query,
            workspace_id=workspace_id,
            limit=limit,
        )

    @mcp.tool()
    def list_releases(
        since: str | None = None,
        limit: int = 20,
        workspace_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Browse recent releases with freshness and citation counts."""
        return intelligence.list_releases(since, limit, workspace_id)

    @mcp.tool()
    def explain_intelligence(
        entity_id: str,
        workspace_id: str | None = None,
    ) -> dict[str, Any]:
        """Explain one release with full citations and recommendation logic."""
        return intelligence.explain(entity_id, workspace_id)

    @mcp.tool()
    def compare_intelligence(
        entity_ids: list[str],
        workspace_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Compare canonical releases using the shared intelligence contract."""
        return intelligence.compare(entity_ids, workspace_id)

    @mcp.tool()
    def find_for_workspace(
        query: str,
        workspace_id: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Find releases adjusted for a local architecture workspace."""
        return intelligence.search(
            query,
            workspace_id=workspace_id,
            limit=limit,
        )

    @mcp.tool()
    def get_source_health() -> list[dict[str, Any]]:
        """Return source failures, circuit state, and last successful counts."""
        return intelligence.source_health()

    @mcp.tool()
    def list_review_exceptions(
        open_only: bool = True,
    ) -> list[dict[str, Any]]:
        """List automated-review exceptions without mutating them."""
        return intelligence.review_exceptions(open_only)

    return mcp


def run(root: Path) -> None:
    """Run the MCP server over stdio (blocking)."""
    build_mcp_server(root).run()
