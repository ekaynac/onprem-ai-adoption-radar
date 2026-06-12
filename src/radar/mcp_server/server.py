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
    def list_recommendations(rings: list[str] | None = None) -> list[dict[str, Any]]:
        """List current decision cards, optionally filtered by ring.

        Pass rings like ["adopt", "pilot"] for this week's actionable picks.
        With no rings, returns every tracked project's current card.
        """
        return service.recommendations(rings=rings)

    @mcp.tool()
    def try_this_week() -> list[dict[str, Any]]:
        """List the projects worth trying now (adopt + pilot rings)."""
        return service.recommendations(rings=list(TRY_THIS_WEEK_RINGS))

    @mcp.tool()
    def get_project(project: str) -> dict[str, Any] | None:
        """Get a single project's current card plus its observation history."""
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
