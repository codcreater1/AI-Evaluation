"""Config-driven experiment definitions. Spec §24.

Loads a YAML file like config/example.yaml into a typed object. Nothing here
should ever need editing when a team member adds an evaluator or a system —
only new YAML files and new evaluator/adapter files should be needed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class MetricThreshold(BaseModel):
    minimum: float | None = None
    max_relative_drop: float | None = None  # e.g. 0.02 == "don't drop by more than 2%"
    max_absolute_drop: float | None = None


class ExperimentConfig(BaseModel):
    system: str
    dataset: str
    evaluators: list[str]
    thresholds: dict[str, MetricThreshold] = Field(default_factory=dict)
    llm_judge: dict[str, Any] = Field(default_factory=dict)
    adapter: dict[str, Any] = Field(default_factory=dict)
    concurrency: int = 5

    @classmethod
    def from_yaml(cls, path: str | Path) -> ExperimentConfig:
        data = yaml.safe_load(Path(path).read_text())
        return cls.model_validate(data)
