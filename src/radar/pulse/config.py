"""``config/pulse.yaml`` loader; fails fast on a malformed file."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field


class ModelsConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    lab_orgs: tuple[str, ...] = Field(min_length=1)
    per_org_limit: int = Field(default=20, ge=1, le=100)


class PapersConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    daily_papers_limit: int = Field(default=100, ge=1, le=500)


class TriageConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    # Hard ceiling on classifier input tokens per run; past it, rules take over.
    # 300k tokens = $0.0126 at Jev's $0.042/M; 12 runs/day caps spend near $0.15.
    token_budget_per_run: int = Field(default=300_000, ge=0)


class WatchdogConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    site_url: str = Field(min_length=1)
    repo: str = Field(pattern=r"^[\w.-]+/[\w.-]+$")
    publish_workflow: str = "publish.yml"


class PulseConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    window_days: int = Field(default=14, ge=1, le=90)
    models: ModelsConfig
    papers: PapersConfig = PapersConfig()
    triage: TriageConfig = TriageConfig()
    watchdog: WatchdogConfig | None = None

    @property
    def lab_org_set(self) -> frozenset[str]:
        return frozenset(self.models.lab_orgs)


def load_pulse_config(path: Path) -> PulseConfig:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: expected a mapping at the top level")
    return PulseConfig.model_validate(raw)
