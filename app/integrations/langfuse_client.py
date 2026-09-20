"""Thin Langfuse wrapper. Spec: "use Langfuse as the primary observability
and evaluation infrastructure" — the platform should not build a parallel
tracing system (spec §27).

Kept as a small, mockable module so:
  - tests never need real Langfuse credentials (no keys set -> everything
    below becomes a no-op that still returns fake ids)
  - every other module only ever imports `get_client()` / `trace_case_execution()`
    / `score_trace()` from here, never the langfuse SDK directly

Written against the modern (v3+, observations-first) Python SDK — see
https://langfuse.com/docs/observability/sdk/python — not the old v2 API
(`client.trace(...)`, `client.score(...)`), which `pip install` no longer
resolves to and which this code will NOT work against. If a future SDK
major version renames `start_as_current_observation` / `create_score` again,
this is the one place that needs updating.
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
            # `host` is the deprecated name for `base_url` but is still
            # accepted, and matches the LANGFUSE_HOST var this project's
            # .env.example documents — no need to rename either.
            host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com"),
        )
    return _client


class _DisabledSpan:
    """Stand-in yielded when Langfuse isn't configured, so callers can use
    the same `.trace_id` / `.update(output=...)` interface either way
    instead of branching on whether tracing is enabled."""

    def __init__(self, trace_id: str) -> None:
        self.trace_id = trace_id

    def update(self, **_kwargs: Any) -> None:
        pass


@contextmanager
def trace_case_execution(
    *, system: str, case_id: str, experiment_id: str | None = None, input: Any = None
) -> Iterator[Any]:
    """Wraps one case's system-execution + evaluation. Yields an object with
    a `.trace_id` (stored on SystemExecution.trace_id so reports/dashboards
    can deep-link straight to it — spec §13) and an `.update(output=...)`
    the caller invokes once the system's actual output is known.

    `input` is set at span-creation time since the case input is already
    known then; `output` is not, so it has to arrive via `.update()` after
    the adapter call inside the `with` block returns — previously nothing
    set either, so every trace in Langfuse showed input=null/output=undefined
    despite the case data being right there."""
    client = get_client()
    if client is None:
        yield _DisabledSpan(f"disabled-{uuid4()}")
        return

    with client.start_as_current_observation(
        as_type="span",
        name=f"evaluation:{system}",
        input=input,
        metadata={"case_id": case_id, "experiment_id": experiment_id},
    ) as span:
        try:
            yield span
        finally:
            client.flush()


def score_trace(
    trace_id: str, *, name: str, value: float | bool, comment: str | None = None
) -> None:
    """Attach an evaluator's score to a trace. No-ops cleanly when disabled
    so the evaluation engine's own tests don't require Langfuse. Uses
    `create_score` (not `span.score_trace`) because a score is often
    attached well after the span that produced the trace has already
    closed — an evaluator runs after the system call it's judging."""
    client = get_client()
    if client is None or trace_id.startswith("disabled-"):
        return
    client.create_score(trace_id=trace_id, name=name, value=value, comment=comment)