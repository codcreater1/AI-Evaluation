from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.adapters.base import get_adapter
from app.core.config import ExperimentConfig, MetricThreshold
from app.core.evaluator import build_evaluators
from app.core.experiment import ExperimentRunner, ExperimentStore
from app.core.regression import compare

router = APIRouter(prefix="/experiments", tags=["experiments"])
_store = ExperimentStore()


@router.post("")
async def run_experiment(config_path: str, name: str, model: str | None = None) -> dict:
    """POST /experiments — spec §23. Body kept as query params in this stub
    for brevity; swap for a proper request model when wiring the real API."""
    config = ExperimentConfig.from_yaml(config_path)
    adapter = get_adapter(config.system, config.adapter)
    evaluators = build_evaluators(config.evaluators, config.llm_judge)
    runner = ExperimentRunner(adapter, evaluators)
    experiment = await runner.run(name=name, config=config, model=model)
    return {"id": experiment.id, "aggregate_scores": experiment.aggregate_scores}


@router.get("/compare")
def compare_experiments(baseline_id: str, candidate_id: str) -> dict:
    """GET /experiments/compare?baseline_id=...&candidate_id=... — spec §16/§17.

    Wires app.core.regression.compare() into the API. That function (the
    baseline-vs-candidate metric table, newly-failing/newly-passing case
    ids, and the pass/fail gate against configured thresholds) already
    existed and was already tested, but nothing was calling it — Definition
    of Done items #7 "compare experiments" and #8 "detect regressions" were
    unmet at the API level despite the logic being done. Thresholds are
    read from the *candidate* experiment's own recorded config (not
    whatever config file happens to be on disk right now), so a comparison
    always reflects the regression policy that was actually in force when
    the candidate ran.

    Registered before /{experiment_id} deliberately — a dynamic path
    segment would otherwise swallow the literal "compare" segment first.
    """
    try:
        baseline = _store.load(baseline_id)
        candidate = _store.load(candidate_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Experiment not found") from exc

    raw_thresholds = candidate.config.get("thresholds", {})
    thresholds = {
        metric: threshold if isinstance(threshold, MetricThreshold) else MetricThreshold(**threshold)
        for metric, threshold in raw_thresholds.items()
    }
    report = compare(baseline, candidate, thresholds)
    return report.model_dump(mode="json")


@router.get("/{experiment_id}")
def get_experiment(experiment_id: str) -> dict:
    try:
        experiment = _store.load(experiment_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Experiment not found") from exc
    return experiment.model_dump(mode="json")


@router.get("")
def list_experiments(system: str | None = None) -> list[dict]:
    return [e.model_dump(mode="json", exclude={"cases"}) for e in _store.list_experiments(system)]