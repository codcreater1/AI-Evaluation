"""Pluggable evaluator interface. Spec §7.

Design decisions worth flagging (see PROJECT_PLAN.md §4.2):
- `evaluate()` is async. LLM-as-judge evaluators and some deterministic ones
  (retrieval metrics that re-query a store) do I/O; making everything async
  from day one avoids a breaking rewrite later when datasets grow past a
  handful of cases.
- Evaluators register themselves via `@register_evaluator("name")` so a
  config file (config/example.yaml) can select evaluators by name — adding
  one never means touching the runner (spec §24).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar

from app.core.schemas import EvaluationCase, EvaluationResult, SystemExecution


class Evaluator(ABC):
    """Base class for every evaluator, deterministic or LLM-based."""

    name: ClassVar[str]
    uses_llm: ClassVar[bool] = False
    version: ClassVar[str] = "v1"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}

    @abstractmethod
    async def evaluate(self, case: EvaluationCase, execution: SystemExecution) -> EvaluationResult:
        """Score one case/execution pair. Must not raise for expected failure
        modes (missing fields, empty output, etc.) — return a failed
        EvaluationResult with a `reason` instead, so one bad case doesn't
        abort a whole experiment run."""
        raise NotImplementedError


_EVALUATOR_REGISTRY: dict[str, type[Evaluator]] = {}


def register_evaluator(name: str):
    """Class decorator: makes an evaluator selectable by name from config."""

    def _wrap(cls: type[Evaluator]) -> type[Evaluator]:
        cls.name = name
        _EVALUATOR_REGISTRY[name] = cls
        return cls

    return _wrap


def get_evaluator_class(name: str) -> type[Evaluator]:
    try:
        return _EVALUATOR_REGISTRY[name]
    except KeyError as exc:
        known = ", ".join(sorted(_EVALUATOR_REGISTRY)) or "(none registered yet)"
        raise KeyError(f"No evaluator registered as {name!r}. Known: {known}") from exc


def build_evaluators(names: list[str], config: dict[str, Any] | None = None) -> list[Evaluator]:
    """Instantiate evaluators listed in a config's `evaluators:` block."""
    return [get_evaluator_class(name)(config) for name in names]


def list_registered_evaluators() -> list[str]:
    return sorted(_EVALUATOR_REGISTRY)
