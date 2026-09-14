"""Advisory-reading quality judge for the Internship Coordinator.

Grounded in the real system (PROJECT_PLAN.md §4.7): its decision (status +
findings) is 100% deterministic and never touches an LLM. The one place a
model is involved is the *advisory* reading — a summary, an inconsistency
list and coordinator questions that are explicitly non-authoritative
("nothing in the decision path consults it"). That is genuinely fuzzy,
natural-language output, so it's the right — and only — thing to point an
LLM judge at for this system.

Because the platform's API doesn't return full extracted document text
(only the verified structured facts: name, company, dates, working days,
evaluation score), this judge checks the advisory against those verified
facts rather than raw prose: does it stay consistent with what was actually
verified, without asserting something the record contradicts.
"""

from __future__ import annotations

from app.core.evaluator import register_evaluator
from app.core.schemas import EvaluationCase, EvaluationResult, SystemExecution
from app.evaluators.llm_judge.base import JUDGE_RESPONSE_SCHEMA_HINT, LLMJudgeEvaluator

_PROMPT = """You are checking an AI's advisory reading of an internship
completion report for consistency with the verified facts. This reading is
informational only — it never decided anything — but it should not assert
anything the verified record contradicts.

Verified facts (deterministically computed, authoritative):
  Student: {student_name} ({student_id})
  Company: {company}
  Period: {start_date} to {end_date}
  Verified working days: {counted_working_days}
  Employer evaluation score: {evaluation_score}/100
  Report word count: {report_word_count}

AI advisory summary:
{summary}

AI-flagged inconsistencies:
{inconsistencies}

AI questions for the coordinator:
{questions}
{schema_hint}"""


@register_evaluator("advisory_quality")
class AdvisoryQualityEvaluator(LLMJudgeEvaluator):
    prompt_version = "v1"

    def build_prompt(self, case: EvaluationCase, execution: SystemExecution) -> str:
        advisory = execution.output.get("advisory") or {}
        return _PROMPT.format(
            student_name=execution.output.get("student_name", "(unknown)"),
            student_id=execution.output.get("student_id", "(unknown)"),
            company=execution.output.get("company", "(unknown)"),
            start_date=execution.output.get("start_date", "(unknown)"),
            end_date=execution.output.get("end_date", "(unknown)"),
            counted_working_days=execution.output.get("counted_working_days", "(unknown)"),
            evaluation_score=execution.output.get("evaluation_score", "(unknown)"),
            report_word_count=execution.output.get("report_word_count", "(unknown)"),
            summary=advisory.get("summary", ""),
            inconsistencies=advisory.get("inconsistencies", []),
            questions=advisory.get("questions_for_coordinator", []),
            schema_hint=JUDGE_RESPONSE_SCHEMA_HINT,
        )

    async def evaluate(self, case: EvaluationCase, execution: SystemExecution) -> EvaluationResult:
        advisory = execution.output.get("advisory")
        if not advisory or not advisory.get("available"):
            # Matches the target system's own design: the advisory reading is
            # optional (dormant with no LLM configured) and never gates
            # anything. "Not applicable" here, not a failure.
            return EvaluationResult(
                evaluator=self.name,
                passed=None,
                reason=(
                    "No advisory reading available for this execution "
                    "(LLM not configured on the target system)."
                ),
                metadata={"prompt_version": self.prompt_version, "model": self._model_name()},
            )
        return await super().evaluate(case, execution)
