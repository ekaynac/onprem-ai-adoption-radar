"""Shared frozen types for the capacity engine (spec §6)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


DTYPE_BYTES: dict[str, float] = {"fp16": 2.0, "bf16": 2.0, "fp8": 1.0, "int8": 1.0, "fp4": 0.5}


class Workload(BaseModel):
    """What the deployment must serve."""

    model_config = ConfigDict(frozen=True)

    concurrent_requests: int = Field(ge=1)
    avg_context_tokens: int = Field(ge=1)
    target_tokens_per_sec_per_user: float | None = None  # None = memory-only planning


class Parallelism(BaseModel):
    """A candidate sharding layout."""

    model_config = ConfigDict(frozen=True)

    tensor_parallel: int = 1
    pipeline_parallel: int = 1
    expert_parallel: int = 1

    @property
    def world_size(self) -> int:
        return self.tensor_parallel * self.pipeline_parallel * self.expert_parallel


class AssumptionSheet(BaseModel):
    """Every estimate's honesty ledger — rendered with every answer."""

    model_config = ConfigDict(frozen=True)

    lines: tuple[str, ...] = ()

    def plus(self, *notes: str) -> AssumptionSheet:
        return AssumptionSheet(lines=self.lines + notes)
