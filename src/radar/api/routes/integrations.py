"""Integration capability endpoint."""

from fastapi import APIRouter


router = APIRouter(tags=["integrations"])


@router.get("/integrations")
def integrations() -> dict[str, list[str]]:
    return {
        "sources": [
            "huggingface",
            "github_releases",
            "official_feeds",
            "announcement_pages",
            "json_registries",
            "evidence",
        ],
        "transports": ["rest", "mcp", "rss", "atom", "webhooks"],
    }
