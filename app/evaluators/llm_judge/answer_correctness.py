"""Answer correctness judge for ATA RAG. Spec §8.

There is no Internship Coordinator equivalent here on purpose: once the real
system was inspected (PROJECT_PLAN.md §4.7), its decision path turned out to
be fully deterministic by design — "deterministic checks decide everything;
the LLM decides nothing" is the system's own stated principle. Judging that
decision with an LLM would contradict the thing being evaluated. See
app/evaluators/deterministic/status_correctness.py and
finding_codes.py for its real evaluators, and llm_judge/advisory_quality.py
for the one part of that system an LLM judge legitimately applies to.
"""

from __future__ import annotations

from app.core.evaluator import register_evaluator
from app.core.schemas import EvaluationCase, SystemExecution
from app.evaluators.llm_judge.base import JUDGE_RESPONSE_SCHEMA_HINT, LLMJudgeEvaluator

_PROMPT = """You are grading an AI system's answer for correctness against a
reference (expected) answer. Be strict about factual correctness but lenient
about wording differences.

User question:
{question}

Expected answer:
{expected}

Actual answer:
{actual}
{schema_hint}"""


@register_evaluator("answer_correctness")
class AnswerCorrectnessEvaluator(LLMJudgeEvaluator):
    prompt_version = "v1"

    def build_prompt(self, case: EvaluationCase, execution: SystemExecution) -> str:
        return _PROMPT.format(
            question=case.input.get("question", ""),
            expected=(case.expected_output or {}).get("answer", "(none provided)"),
            actual=execution.output.get("answer", ""),
            schema_hint=JUDGE_RESPONSE_SCHEMA_HINT,
        )
