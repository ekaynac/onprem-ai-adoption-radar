"""Read-only parity checks between legacy sources and canonical projections."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from radar.models_radar.platform_matrix import load_platform_matrix
from radar.models_radar.seed import load_model_seed


@dataclass(frozen=True)
class ShadowDifference:
    entity: str
    field: str
    legacy_value: object
    canonical_value: object
    accepted_reason: str | None = None


@dataclass(frozen=True)
class ShadowReport:
    legacy_models: int
    canonical_models: int
    legacy_platforms: int
    canonical_platforms: int
    differences: tuple[ShadowDifference, ...]

    @property
    def is_equivalent(self) -> bool:
        return not self.differences


def compare_legacy_projection(root: Path, repository) -> ShadowReport:
    legacy_models = len(load_model_seed(root / "config" / "model-seed.yaml"))
    legacy_platforms = len(
        load_platform_matrix(root / "config" / "platform-matrix.yaml")
    )
    canonical_models = repository.count_releases()
    canonical_platforms = repository.count_platforms()
    differences: list[ShadowDifference] = []
    if legacy_models != canonical_models:
        differences.append(
            ShadowDifference(
                entity="models",
                field="count",
                legacy_value=legacy_models,
                canonical_value=canonical_models,
            )
        )
    if legacy_platforms != canonical_platforms:
        differences.append(
            ShadowDifference(
                entity="platforms",
                field="count",
                legacy_value=legacy_platforms,
                canonical_value=canonical_platforms,
            )
        )
    return ShadowReport(
        legacy_models=legacy_models,
        canonical_models=canonical_models,
        legacy_platforms=legacy_platforms,
        canonical_platforms=canonical_platforms,
        differences=tuple(differences),
    )
