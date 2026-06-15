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

from radar.mcp_server.queries import TRY_THIS_WEEK_RINGS, RadarQueryService


def build_mcp_server(root: Path) -> FastMCP:
    """Build a FastMCP server backed by the radar state under ``root``."""
    service = RadarQueryService(root)
    mcp = FastMCP("onprem-ai-adoption-radar")

    @mcp.tool()
    def list_recommendations(
        rings: list[str] | None = None,
        detail: str = "compact",
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """List current decision cards (highest score first), to BROWSE.

        Returns a compact, context-cheap card per project so you can scan many
        at once: project, category, backer, ring, score, risk_level, trend,
        upgrade_risk, pinned, summary, and one `headline` evidence line. Then
        call `get_project(<name>)` for the full card (evidence notes, risks,
        try-next steps, source URLs, history).

        - `rings`: filter, e.g. ["adopt", "pilot"]. Unknown rings are ignored.
        - `limit`: cap the number returned (top-N by score).
        - `detail`: "compact" (default) or "full" for every field at once
          (heavy — prefer compact + get_project).
        """
        return service.recommendations(rings=rings, detail=detail, limit=limit)

    @mcp.tool()
    def try_this_week(
        detail: str = "compact", limit: int | None = None
    ) -> list[dict[str, Any]]:
        """The projects worth trying now (adopt + pilot), highest score first.

        Compact by default for cheap browsing — each card carries ring, backer,
        risk, trend, upgrade_risk and a `headline` evidence line. Use `limit`
        for just the top picks, `detail="full"` for every field, or
        `get_project(<name>)` to drill into one.
        """
        return service.recommendations(
            rings=list(TRY_THIS_WEEK_RINGS), detail=detail, limit=limit
        )

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

    return mcp


def run(root: Path) -> None:
    """Run the MCP server over stdio (blocking)."""
    build_mcp_server(root).run()
