"""Experiment tracking + runner. Spec §15.

An Experiment = one AI-system version evaluated against one dataset version,
with the full set of things the spec insists must be recorded: dataset
version, model, prompt version, config, evaluator versions, timestamp,
aggregate scores (§15's example table).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from app.adapters.base import SystemAdapter
from app.core.config import ExperimentConfig
from app.core.dataset_manager import DatasetManager
from app.core.evaluator import Evaluator
from app.core.schemas import EvaluationCase, EvaluationResult, SystemExecution
from app.integrations.langfuse_client import score_trace, trace_case_execution


class CaseRecord(BaseModel):
    """Everything computed for one case, kept for §22 "inspect failed cases"
    and §16 comparison drill-down."""

    case_id: str
    execution: SystemExecution
    results: list[EvaluationResult]

    @property
    def passed(self) -> bool:
        return all(r.passed is not False for r in self.results)


class Experiment(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    system: str
    dataset_version: str
    model: str | None = None
    prompt_version: str | None = None
    application_version: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    evaluator_versions: dict[str, str] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    case_count: int = 0
    aggregate_scores: dict[str, float] = Field(default_factory=dict)
    pass_rate: dict[str, float] = Field(default_factory=dict)
    cases: list[CaseRecord] = Field(default_factory=list)

    def failed_cases(self) -> list[CaseRecord]:
        return [c for c in self.cases if not c.passed]


class ExperimentStore:
    """MVP persistence: one JSON file per experiment under experiments/.
    Swap for a Postgres table later without touching the runner — the
    runner only depends on `save()`."""

    def __init__(self, root: str | Path = "experiments") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, experiment: Experiment) -> Path:
        # encoding="utf-8" is required, not decorative: real case data (names,
        # source text) is routinely non-ASCII (Polish "ś", Turkish "ı", etc.),
        # and Path.write_text()'s platform default on Windows is the system
        # ANSI code page, not UTF-8 — this raised a real UnicodeEncodeError
        # the first time this ran against real captured data.
        path = self.root / f"{experiment.id}.json"
        path.write_text(experiment.model_dump_json(indent=2), encoding="utf-8")
        return path

    def load(self, experiment_id: str) -> Experiment:
        path = self.root / f"{experiment_id}.json"
        return Experiment.model_validate_json(path.read_text(encoding="utf-8"))

    def list_experiments(self, system: str | None = None) -> list[Experiment]:
        results = []
        for path in self.root.glob("*.json"):
            try:
                results.append(Experiment.model_validate_json(path.read_text(encoding="utf-8")))
            except ValueError as exc:
                # A run that got killed mid-write (Ctrl+C, a crashed uvicorn
                # reload, disk full) can leave an empty or truncated JSON file
                # behind. One bad file shouldn't take down the whole listing
                # (or the /report page) - skip it, but say so on stderr so
                # it's still discoverable rather than silently dropped.
                print(f"Skipping unreadable experiment file {path}: {exc}")
        if system:
            results = [e for e in results if e.system == system]
        return sorted(results, key=lambda e: e.created_at)


class ExperimentRunner:
    def __init__(
        self,
        adapter: SystemAdapter,
        evaluators: list[Evaluator],
        dataset_manager: DatasetManager | None = None,
        store: ExperimentStore | None = None,
    ) -> None:
        self.adapter = adapter
        self.evaluators = evaluators
        self.datasets = dataset_manager or DatasetManager()
        self.store = store or ExperimentStore()

    async def _run_case(self, case: EvaluationCase, experiment_id: str) -> CaseRecord:
        with trace_case_execution(
            system=case.system, case_id=case.id, experiment_id=experiment_id, input=case.input
        ) as span:
            execution = await self.adapter.run(case)
            execution.trace_id = span.trace_id
            span.update(output=execution.output)

            results = []
            for evaluator in self.evaluators:
                result = await evaluator.evaluate(case, execution)
                results.append(result)
                if result.score is not None:
                    score_trace(
                        span.trace_id, name=result.evaluator, value=result.score, comment=result.reason
                    )
                elif result.passed is not None:
                    score_trace(
                        span.trace_id, name=result.evaluator, value=result.passed, comment=result.reason
                    )

        return CaseRecord(case_id=case.id, execution=execution, results=results)

    async def run(
        self,
        *,
        name: str,
        config: ExperimentConfig,
        model: str | None = None,
        prompt_version: str | None = None,
        application_version: str | None = None,
    ) -> Experiment:
        # NOTE: dataset names in config are "system-golden-v3" style (spec §14);
        # DatasetManager keys by bare version ("v3"). Resolve that mapping here
        # once, rather than teaching DatasetManager about naming conventions.
        version = config.dataset.rsplit("-", 1)[-1]
        cases = self.datasets.load(config.system, version)

        experiment_id = str(uuid4())
        semaphore = asyncio.Semaphore(config.concurrency)

        async def _bounded(case: EvaluationCase) -> CaseRecord:
            async with semaphore:
                return await self._run_case(case, experiment_id=experiment_id)

        records = await asyncio.gather(*(_bounded(c) for c in cases))

        experiment = Experiment(
            id=experiment_id,
            name=name,
            system=config.system,
            dataset_version=version,
            model=model,
            prompt_version=prompt_version,
            application_version=application_version,
            config=config.model_dump(),
            evaluator_versions={e.name: e.version for e in self.evaluators},
            case_count=len(records),
            cases=list(records),
        )
        experiment.aggregate_scores = _aggregate_scores(records)
        experiment.pass_rate = _pass_rates(records)

        self.datasets.lock(config.system, version)  # spec §14: immutable once used
        self.store.save(experiment)
        return experiment


def _aggregate_scores(records: list[CaseRecord]) -> dict[str, float]:
    by_evaluator: dict[str, list[float]] = {}
    for record in records:
        for result in record.results:
            if result.score is not None:
                by_evaluator.setdefault(result.evaluator, []).append(result.score)
    return {name: mean(scores) for name, scores in by_evaluator.items() if scores}


def _pass_rates(records: list[CaseRecord]) -> dict[str, float]:
    by_evaluator: dict[str, list[bool]] = {}
    for record in records:
        for result in record.results:
            if result.passed is not None:
                by_evaluator.setdefault(result.evaluator, []).append(result.passed)
    return {name: sum(vals) / len(vals) for name, vals in by_evaluator.items() if vals}