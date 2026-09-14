"""System Adapter layer.

This is the piece the spec's architecture diagram assumes exists but never
names (PROJECT_PLAN.md §4.1): something that takes an EvaluationCase and
actually runs it through Internship Coordinator or the ATA RAG chatbot,
returning a normalized SystemExecution. Without this, the Evaluation Engine
would need to know how to call two completely different codebases directly.

Adding a third AI system later means writing one adapter here and one
config file — the engine, evaluators and dataset manager never change.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Any, ClassVar

from app.core.schemas import EvaluationCase, SystemExecution


class SystemAdapter(ABC):
    name: ClassVar[str]

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}

    @abstractmethod
    async def _call(self, case: EvaluationCase) -> dict:
        """Do the actual work: call the target system and return its raw
        output as a dict. Subclasses implement only this."""
        raise NotImplementedError

    async def run(self, case: EvaluationCase) -> SystemExecution:
        """Wraps `_call` with timing + error handling so every adapter
        produces a consistent SystemExecution, including on failure."""
        start = time.perf_counter()
        try:
            output = await self._call(case)
            latency_ms = (time.perf_counter() - start) * 1000
            return SystemExecution(
                case_id=case.id,
                system=self.name,
                output=output,
                latency_ms=latency_ms,
            )
        except Exception as exc:  # noqa: BLE001 - deliberately broad: a system
            # under test failing must not crash the evaluation run.
            latency_ms = (time.perf_counter() - start) * 1000
            return SystemExecution(
                case_id=case.id,
                system=self.name,
                output={},
                latency_ms=latency_ms,
                error=f"{type(exc).__name__}: {exc}",
            )


_ADAPTER_REGISTRY: dict[str, type[SystemAdapter]] = {}


def register_adapter(name: str):
    def _wrap(cls: type[SystemAdapter]) -> type[SystemAdapter]:
        cls.name = name
        _ADAPTER_REGISTRY[name] = cls
        return cls

    return _wrap


def get_adapter(name: str, config: dict[str, Any] | None = None) -> SystemAdapter:
    try:
        return _ADAPTER_REGISTRY[name](config)
    except KeyError as exc:
        known = ", ".join(sorted(_ADAPTER_REGISTRY)) or "(none registered yet)"
        raise KeyError(f"No adapter registered as {name!r}. Known: {known}") from exc


def list_registered_adapters() -> list[str]:
    return sorted(_ADAPTER_REGISTRY)
