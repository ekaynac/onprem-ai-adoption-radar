"""``config/pulse-questions.yaml``: provider-agnostic triage questions per lane."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from radar.pulse.items import Lane


class Question(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal["choice", "score", "noul"]
    instructions: str = Field(min_length=1)
    criteria: dict[str, str] | list[str]

    @model_validator(mode="after")
    def _criteria_fit_type(self) -> Question:
        if self.type == "score":
            if not isinstance(self.criteria, list) or not 2 <= len(self.criteria) <= 10:
                raise ValueError("score questions need 2-10 ordered levels")
        elif not isinstance(self.criteria, dict):
            raise ValueError(f"{self.type} questions need a criteria mapping")
        elif self.type == "noul" and set(self.criteria) != {"true", "false"}:
            raise ValueError("noul criteria must be exactly 'true' and 'false'")
        elif self.type == "choice" and not 2 <= len(self.criteria) <= 255:
            raise ValueError("choice questions need 2-255 options")
        return self

    def as_payload(self) -> dict[str, Any]:
        return self.model_dump()


class QuestionSet(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: int = Field(ge=1)
    lanes: dict[Lane, dict[str, Question]]

    def for_lane(self, lane: Lane) -> dict[str, Question]:
        return self.lanes.get(lane, {})


def load_questions(path: Path) -> QuestionSet:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: expected a mapping at the top level")
    return QuestionSet.model_validate(raw)
