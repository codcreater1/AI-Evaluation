"""Exact-match evaluator. Spec §7.1 — deterministic, no LLM involved.

Compares one field of the system's output against the same field of
case.expected_output. Which field is configurable so this one class serves
both systems (e.g. "recommendation" for Internship Coordinator, "answer"
for a system where you want strict wording match).
"""

from __future__ import annotations

from app.core.evaluator import Evaluator, register_evaluator
from app.core.schemas import EvaluationCase, EvaluationResult, SystemExecution


@register_evaluator("exact_match")
class ExactMatchEvaluator(Evaluator):
    async def evaluate(self, case: EvaluationCase, execution: SystemExecution) -> EvaluationResult:
        field = self.config.get("field", "answer")

        if case.expected_output is None or field not in case.expected_output:
            return EvaluationResult(
                evaluator=self.name,
                passed=None,
                reason=f"No expected value for field {field!r}; case not usable for exact_match.",
            )

        expected = case.expected_output[field]
        actual = execution.output.get(field)
        passed = actual == expected
        return EvaluationResult(
            evaluator=self.name,
            score=1.0 if passed else 0.0,
            passed=passed,
            reason=None if passed else f"Expected {expected!r}, got {actual!r}",
            metadata={"field": field},
        )
