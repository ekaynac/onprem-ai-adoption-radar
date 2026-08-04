"""Event-vs-profile matcher: alerts are changes diffed against a stack.

The differentiator is silence — an operator only hears about events
that touch a component they actually run. Matching is deterministic
(term intersection with dash-prefix family matching, e.g. profile model
``qwen3-32b`` matches the classified component ``qwen3``), never fuzzy.

Sources matched (v1): classified newsroom items (breaking → act,
improvement → evaluate, informational → silence) and curated model
ring moves for models in the profile. OSV advisories are deliberately
absent: OSV evidence attaches to tracked *projects* in the enrichment
layer and carries no stack-component key to diff against; the
``security-advisory`` news taxonomy covers that lane with a citation.
"""

from __future__ import annotations

import contextlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from radar.intelligence.workspaces import WorkspaceDevice, WorkspaceStack


ALERTS_VERSION = "alerts-v1"


class DemoProfile(BaseModel):
    """The public demo profile shipped in config/stack-profile-demo.yaml."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str
    name: str
    devices: list[WorkspaceDevice] = Field(default_factory=list)
    stack: WorkspaceStack = Field(default_factory=WorkspaceStack)


def load_demo_profile(path: Path) -> DemoProfile:
    import yaml

    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return DemoProfile.model_validate(payload)
DEFAULT_ALERT_WINDOW_DAYS = 14
_ALERT_LIMIT = 40


def profile_terms(
    devices: list[WorkspaceDevice], stack: WorkspaceStack
) -> set[str]:
    """Normalized component terms an event can match against."""
    terms: set[str] = set()
    for engine in stack.engines:
        terms.add(engine.name)
    for model in stack.models:
        terms.add(model)
    for quant in stack.quant_formats:
        terms.add(quant)
    for device in devices:
        if device.device_id:
            terms.add(device.device_id.strip().casefold())
    return {term for term in terms if term}


def _matches(component: str, terms: set[str]) -> str | None:
    """Return the matched profile term, honoring dash-prefix families."""
    candidate = component.strip().casefold()
    if not candidate:
        return None
    if candidate in terms:
        return candidate
    for term in terms:
        if term.startswith(f"{candidate}-") or candidate.startswith(
            f"{term}-"
        ):
            return term
    return None


def _news_alerts(
    root: Path, terms: set[str], cutoff: datetime
) -> list[dict[str, Any]]:
    from radar.storage.news_log import (
        load_news_classifications,
        load_news_items,
    )

    items_by_id = {
        item.id: item
        for item in load_news_items(root / "data" / "news-observations.jsonl")
    }
    alerts: list[dict[str, Any]] = []
    for classification in load_news_classifications(
        root / "data" / "news-classified.jsonl"
    ):
        if not classification.relevant:
            continue
        if classification.operational_impact == "informational":
            continue  # silence: informational is newsroom-only
        item = items_by_id.get(classification.news_id)
        if item is None:
            continue
        observed = item.published_at or classification.classified_at
        if observed < cutoff:
            continue
        matched = sorted(
            {
                hit
                for component in classification.components
                if (hit := _matches(component, terms)) is not None
            }
        )
        if not matched:
            continue  # silence: does not touch this stack
        verdict = (
            "act"
            if classification.operational_impact == "breaking"
            else "evaluate"
        )
        alerts.append(
            {
                "id": f"alert:news:{item.id}",
                "source": "news",
                "verdict": verdict,
                "subject": item.title,
                "what_happened": classification.summary,
                "matched_components": matched,
                "event_type": classification.event_type,
                "receipts": [classification.citation or item.url],
                "observed_at": observed.isoformat(),
            }
        )
    return alerts


def _ring_move_alerts(
    root: Path, terms: set[str], cutoff: datetime
) -> list[dict[str, Any]]:
    try:
        from radar.models_radar.history import load_model_events
    except Exception:
        return []
    alerts: list[dict[str, Any]] = []
    for event in load_model_events(root / "data" / "model-history.jsonl"):
        if event.observed_at < cutoff:
            continue
        matched = _matches(event.model_id, terms)
        if matched is None:
            continue
        ring = event.ring.value
        previous = event.previous_ring.value if event.previous_ring else None
        demoted_from_adopt = (
            event.change_type.value == "demoted" and previous == "adopt"
        )
        verdict = "act" if demoted_from_adopt else "evaluate"
        arrow = f"{previous} → {ring}" if previous else f"new → {ring}"
        alerts.append(
            {
                "id": f"alert:ring:{event.model_id}:{event.observed_at.isoformat()}",
                "source": "ring-move",
                "verdict": verdict,
                "subject": event.model_id,
                "what_happened": (
                    f"Ring {arrow} ({event.change_type.value}) for a model "
                    "in your stack"
                ),
                "matched_components": [matched],
                "event_type": "ring-move",
                "receipts": ["data/model-history.jsonl"],
                "observed_at": event.observed_at.isoformat(),
            }
        )
    return alerts


def build_alerts(
    root: Path,
    *,
    devices: list[WorkspaceDevice],
    stack: WorkspaceStack,
    now: datetime,
    window_days: int = DEFAULT_ALERT_WINDOW_DAYS,
) -> dict[str, Any]:
    """Diff the last ``window_days`` of events against one profile."""
    terms = profile_terms(devices, stack)
    cutoff = now - timedelta(days=window_days)
    alerts: list[dict[str, Any]] = []
    if terms:
        # Additive, never fatal — a corrupt store must not break alerts.
        with contextlib.suppress(Exception):
            alerts.extend(_news_alerts(root, terms, cutoff))
        with contextlib.suppress(Exception):
            alerts.extend(_ring_move_alerts(root, terms, cutoff))
    # Newest first within each verdict group; act before evaluate.
    alerts.sort(key=lambda alert: alert["observed_at"], reverse=True)
    alerts.sort(key=lambda alert: alert["verdict"] != "act")
    alerts = alerts[:_ALERT_LIMIT]
    return {
        "version": ALERTS_VERSION,
        "generated_at": now.isoformat(),
        "window_days": window_days,
        "profile_terms": sorted(terms),
        "alerts": alerts,
        "counts": {
            "act": sum(1 for alert in alerts if alert["verdict"] == "act"),
            "evaluate": sum(
                1 for alert in alerts if alert["verdict"] == "evaluate"
            ),
        },
    }
