"""Importing this package registers every built-in evaluator.

app/api/main.py (and tests) import `app.evaluators` once at startup so the
registry in app.core.evaluator is populated before any config is resolved.
"""

from app.evaluators.deterministic import (
    ata_rag_checks,
    exact_match,
    field_accuracy,
    finding_codes,
    required_fields,
    retrieval_metrics,
    status_correctness,
    threshold,
)
from app.evaluators.llm_judge import advisory_quality, answer_correctness, groundedness

__all__ = [
    "ata_rag_checks",
    "exact_match",
    "field_accuracy",
    "finding_codes",
    "required_fields",
    "retrieval_metrics",
    "status_correctness",
    "threshold",
    "advisory_quality",
    "answer_correctness",
    "groundedness",
]
