"""Core data contracts for the evaluation platform.

These three models are the whole vocabulary the rest of the system speaks:

- EvaluationCase   — one item in a golden dataset (spec §5)
- SystemExecution  — what a System Adapter got back from running a case (fills
                      a gap the spec leaves implicit — see PROJECT_PLAN.md §4.1)
- EvaluationResult — what an Evaluator produces for one (case, execution) pair (spec §6)

Deliberately generic: `input`, `expected_output` and `output` are all plain
dicts so the same schema covers a RAG chatbot and a document-review system
without either one being a special case.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class EvaluationCase(BaseModel):
    """One row of a golden dataset. Spec §5."""

    id: str
    system: str
    input: dict[str, Any] = Field(default_factory=dict)
    expected_output: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SystemExecution(BaseModel):
    """The result of actually running an AI system against a case.

    This sits between EvaluationCase and EvaluationResult. The spec's example
    evaluator signature — evaluate(self, case, result) — never says what
    "result" is; we make it explicit here so evaluators don't need to know
    how the underlying system was invoked (HTTP call, in-process import,
    whatever the adapter does).
    """

    case_id: str
    system: str
    output: dict[str, Any] = Field(default_factory=dict)
    latency_ms: float | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    cost_usd: float | None = None
    trace_id: str | None = None  # Langfuse trace id, when tracing is enabled
    error: str | None = None  # set if the system itself errored/timed out
    raw: Any | None = None  # unprocessed adapter output, for debugging


class EvaluationResult(BaseModel):
    """Standardized output of a single evaluator on a single case. Spec §6."""

    evaluator: str
    score: float | None = None
    passed: bool | None = None
    category: str | None = None
    reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class HumanEvaluation(BaseModel):
    """A person's review of an AI result. Spec §20. Stored alongside, and
    linked to, the original trace — never replacing the automated result."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    case_id: str
    trace_id: str | None = None
    reviewer: str
    score: float | None = None
    passed: bool | None = None
    category: str | None = None
    explanation: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


ComparisonStatus = Literal["improved", "regressed", "unchanged", "new_failure", "new_pass"]
