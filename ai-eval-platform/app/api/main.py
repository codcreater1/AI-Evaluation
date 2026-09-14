"""FastAPI entrypoint. Spec §23 — suggested endpoints, exact design left to
the team. Run with: uvicorn app.api.main:app --reload
"""

from __future__ import annotations

from fastapi import FastAPI

import app.bootstrap as _bootstrap  # noqa: F401 - side-effect import registers evaluators + adapters
from app.api.routes import datasets, experiments, systems

app = FastAPI(
    title="AI Evaluation Platform",
    description="Reusable evaluation infrastructure for AI applications, built on Langfuse.",
    version="0.1.0",
)

app.include_router(datasets.router)
app.include_router(experiments.router)
app.include_router(systems.router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
