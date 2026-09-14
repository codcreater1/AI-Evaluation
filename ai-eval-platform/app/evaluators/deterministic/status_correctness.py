"""Deterministic decision-correctness check for the Internship Coordinator.

Grounded in the real system (PROJECT_PLAN.md §4.7, app/adapters/
internship_coordinator.py): its whole decision path — status and findings —
is deterministic by design ("deterministic checks decide everything; the LLM
decides nothing," per its own README). The right way to grade "did it reach
the correct decision" is therefore an exact comparison against a golden
case's expected status, not an LLM judge — there's nothing fuzzy to ask a
model about.
"""

from __future__ import annotations

from app.core.evaluator import Evaluator, register_evaluator
from app.core.schemas import EvaluationCase, EvaluationResult, SystemExecution


@register_evaluator("status_correctness")
class StatusCorrectnessEvaluator(Evaluator):
    async def evaluate(self, case: EvaluationCase, execution: SystemExecution) -> EvaluationResult:
        expected_status = (case.expected_output or {}).get("status")
        if expected_status is None:
            return EvaluationResult(
                evaluator=self.name, passed=None, reason="No expected status on case."
            )

        actual_status = execution.output.get("status")
        passed = actual_status == expected_status
        return EvaluationResult(
            evaluator=self.name,
            score=1.0 if passed else 0.0,
            passed=passed,
            reason=None
            if passed
            else f"Expected status={expected_status!r}, got {actual_status!r}",
        )
