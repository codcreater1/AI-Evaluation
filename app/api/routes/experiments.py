from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.adapters.base import get_adapter
from app.core.config import ExperimentConfig
from app.core.evaluator import build_evaluators
from app.core.experiment import ExperimentRunner, ExperimentStore

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
