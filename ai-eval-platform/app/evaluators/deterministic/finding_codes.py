"""Finding-code correctness for the Internship Coordinator.

Real system output carries a `findings` list of {code, severity, message,
remedy, document} (see PROJECT_PLAN.md §7) — nothing like the generic
"missing_documents" shape originally guessed before the real repo was
inspected.

A golden case declares the finding codes it expects via
`must_include_finding_codes` in its expected_output (an empty list is a real,
meaningful expectation — "no findings at all", as for an approved case — and
is distinguished from "this case declares no expectation" by whether the key
is present at all). By default this is an *exact-set* comparison: any code
that fires beyond what's expected also fails the case, not only a missing
one. That default matters here specifically — PROJECT_PLAN.md §7 documents a
real failure mode where an unrelated originality finding (`REPORT_NOT_ORIGINAL`)
appeared alongside a case's intended finding, and a subset-only check would
have silently let that through. A case can allowlist genuinely
inconsequential extras (e.g. an `info`-severity finding not worth asserting
on) via `allowed_extra_finding_codes`.
"""

from __future__ import annotations

from app.core.evaluator import Evaluator, register_evaluator
from app.core.schemas import EvaluationCase, EvaluationResult, SystemExecution


@register_evaluator("finding_codes_correctness")
class FindingCodesCorrectnessEvaluator(Evaluator):
    async def evaluate(self, case: EvaluationCase, execution: SystemExecution) -> EvaluationResult:
        expected = case.expected_output or {}
        if "must_include_finding_codes" not in expected:
            return EvaluationResult(
                evaluator=self.name,
                passed=None,
                reason="Case declares no finding-code expectation.",
            )

        expected_codes = set(expected["must_include_finding_codes"])
        allowed_extra = set(expected.get("allowed_extra_finding_codes", []))
        actual_codes = {f.get("code") for f in execution.output.get("findings", [])}

        missing = expected_codes - actual_codes
        unexpected = actual_codes - expected_codes - allowed_extra

        passed = not missing and not unexpected
        reasons = []
        if missing:
            reasons.append(f"missing expected findings: {sorted(missing)}")
        if unexpected:
            reasons.append(f"unexpected findings fired: {sorted(unexpected)}")

        return EvaluationResult(
            evaluator=self.name,
            score=1.0 if passed else 0.0,
            passed=passed,
            reason="; ".join(reasons) or None,
            metadata={"actual_codes": sorted(actual_codes)},
        )
