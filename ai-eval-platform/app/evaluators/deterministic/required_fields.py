"""Required-field validation. Spec §7.1 and §12 (required-field accuracy)."""

from __future__ import annotations

from app.core.evaluator import Evaluator, register_evaluator
from app.core.schemas import EvaluationCase, EvaluationResult, SystemExecution


@register_evaluator("required_fields")
class RequiredFieldsEvaluator(Evaluator):
    """Checks that every field listed in config["required"] is present and
    non-empty in the system's output. Falls back to the keys of
    case.expected_output when no explicit list is configured, so it works
    out of the box against a golden dataset."""

    async def evaluate(self, case: EvaluationCase, execution: SystemExecution) -> EvaluationResult:
        required = self.config.get("required")
        if required is None:
            required = list((case.expected_output or {}).keys())

        missing = [
            field
            for field in required
            if field not in execution.output or execution.output[field] in (None, "", [])
        ]
        passed = not missing
        return EvaluationResult(
            evaluator=self.name,
            score=1.0 - (len(missing) / len(required)) if required else None,
            passed=passed,
            reason=None if passed else f"Missing/empty required fields: {missing}",
            metadata={"required": required, "missing": missing},
        )
