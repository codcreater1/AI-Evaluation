from __future__ import annotations

from fastapi import APIRouter

from app.adapters.base import list_registered_adapters
from app.core.evaluator import list_registered_evaluators

router = APIRouter(tags=["systems"])


@router.get("/systems")
def list_systems() -> dict:
    return {"systems": list_registered_adapters()}


@router.get("/metrics")
def list_metrics() -> dict:
    return {"evaluators": list_registered_evaluators()}
