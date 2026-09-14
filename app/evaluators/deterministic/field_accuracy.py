"""Extracted-field accuracy for the Internship Coordinator.

The real system returns identity/attendance/evaluation facts as top-level
fields on its response (student_name, student_id, company,
counted_working_days, evaluation_score — see ReportSubmissionResponse in
the real repo), not a nested "extracted_fields" dict as originally guessed
before it was inspected (PROJECT_PLAN.md §4.7). Compares whichever of those
fields a golden case's expected_output declares values for.
"""

from __future__ import annotations

from app.core.evaluator import Evaluator, register_evaluator
from app.core.schemas import EvaluationCase, EvaluationResult, SystemExecution

_DEFAULT_FIELDS = [
    "student_name",
    "student_id",
    "company",
    "counted_working_days",
    "evaluation_score",
]


@register_evaluator("document_field_accuracy")
class DocumentFieldAccuracyEvaluator(Evaluator):
    async def evaluate(self, case: EvaluationCase, execution: SystemExecution) -> EvaluationResult:
        expected = case.expected_output or {}
        fields = self.config.get("fields", _DEFAULT_FIELDS)
        checkable = [f for f in fields if f in expected]
        if not checkable:
            return EvaluationResult(
                evaluator=self.name, passed=None, reason="No expected field values on case."
            )

        correct = sum(1 for f in checkable if execution.output.get(f) == expected.get(f))
        total = len(checkable)
        score = correct / total
        minimum = self.config.get("minimum", 0.9)
        return EvaluationResult(
            evaluator=self.name,
            score=score,
            passed=score >= minimum,
            metadata={"correct": correct, "total": total, "fields": checkable},
        )
