"""FastAPI entrypoint. Spec §23 — suggested endpoints, exact design left to
the team. Run with: uvicorn app.api.main:app --reload
"""

from __future__ import annotations

from fastapi import FastAPI

try:
    from dotenv import load_dotenv

    # Loads .env into the real process environment *before* app.bootstrap
    # imports anything that reads os.environ at import time (notably
    # app.integrations.langfuse_client, which decides is_enabled() at
    # module load). Without this, LANGFUSE_PUBLIC_KEY/SECRET_KEY in .env are
    # silently ignored unless someone exported them into the shell first —
    # a real gap found while wiring this up against a live deployment, not
    # a hypothetical one.
    load_dotenv()
except ImportError:  # pragma: no cover - python-dotenv is a dev convenience, not a hard dependency
    pass

import app.bootstrap as _bootstrap  # noqa: F401,E402 - side-effect import registers evaluators + adapters
from app.api.routes import datasets, experiments, systems  # noqa: E402

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