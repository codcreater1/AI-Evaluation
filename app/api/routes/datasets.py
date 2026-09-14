from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.core.dataset_manager import DatasetManager

router = APIRouter(prefix="/datasets", tags=["datasets"])
_datasets = DatasetManager()


@router.get("")
def list_datasets(system: str) -> dict:
    return {"system": system, "versions": _datasets.list_versions(system)}


@router.get("/{system}/{version}")
def get_dataset(system: str, version: str) -> dict:
    try:
        cases = _datasets.load(system, version)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"system": system, "version": version, "case_count": len(cases), "cases": cases}
