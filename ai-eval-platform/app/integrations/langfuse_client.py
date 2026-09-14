"""Thin Langfuse wrapper. Spec: "use Langfuse as the primary observability
and evaluation infrastructure" — the platform should not build a parallel
tracing system (spec §27).

Kept as a small, mockable module so:
  - tests never need real Langfuse credentials (LANGFUSE_ENABLED=false or no
    keys set -> everything below becomes a no-op that still returns fake ids)
  - every other module only ever imports `get_client()` / `trace_run()` /
    `score_trace()` from here, never the langfuse SDK directly
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import uuid4

_client: Any = None
_enabled = bool(os.getenv("LANGFUSE_PUBLIC_KEY")) and bool(os.getenv("LANGFUSE_SECRET_KEY"))


def is_enabled() -> bool:
    return _enabled


def get_client() -> Any:
    global _client
    if not _enabled:
        return None
    if _client is None:
        from langfuse import Langfuse  # imported lazily so the dependency is optional in tests

        _client = Langfuse(
            public_key=os.environ["LANGFUSE_PUBLIC_KEY"],
            secret_key=os.environ["LANGFUSE_SECRET_KEY"],
            host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com"),
        )
    return _client


@contextmanager
def trace_case_execution(
    *, system: str, case_id: str, experiment_id: str | None = None
) -> Iterator[str]:
    """Wraps one case's system-execution + evaluation. Yields a trace id that
    should be stored on SystemExecution.trace_id so reports/dashboards can
    deep-link straight to it (spec §13 requires this for every run)."""
    client = get_client()
    if client is None:
        yield f"disabled-{uuid4()}"
        return

    trace = client.trace(
        name=f"evaluation:{system}",
        metadata={"case_id": case_id, "experiment_id": experiment_id},
    )
    try:
        yield trace.id
    finally:
        client.flush()


def score_trace(
    trace_id: str, *, name: str, value: float | bool, comment: str | None = None
) -> None:
    """Attach an evaluator's score to a trace. No-ops cleanly when disabled
    so the evaluation engine's own tests don't require Langfuse."""
    client = get_client()
    if client is None or trace_id.startswith("disabled-"):
        return
    client.score(trace_id=trace_id, name=name, value=value, comment=comment)
