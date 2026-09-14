"""Groundedness judge for ATA RAG. Spec §8, §9.

(The Internship Coordinator's hallucination-style check moved to
llm_judge/advisory_quality.py once the real system was inspected — see
PROJECT_PLAN.md §4.7. Its "explanation" isn't free text to fact-check against
submitted documents; it's an optional, explicitly-advisory reading with its
own structured shape, and the checks against it need the verified structured
facts the system already computed, not the raw documents.)
"""

from __future__ import annotations

from app.core.evaluator import register_evaluator
from app.core.schemas import EvaluationCase, SystemExecution
from app.evaluators.llm_judge.base import JUDGE_RESPONSE_SCHEMA_HINT, LLMJudgeEvaluator

_GROUNDEDNESS_PROMPT = """You are checking whether an AI answer is fully
supported by the retrieved context (i.e. it does not state anything the
context doesn't support — no hallucination).

Retrieved context:
{context}

AI answer:
{answer}
{schema_hint}"""


@register_evaluator("groundedness")
class GroundednessEvaluator(LLMJudgeEvaluator):
    prompt_version = "v1"

    def build_prompt(self, case: EvaluationCase, execution: SystemExecution) -> str:
        docs = execution.output.get("retrieved_documents", [])
        context = "\n---\n".join(d.get("text", "") for d in docs if isinstance(d, dict))
        return _GROUNDEDNESS_PROMPT.format(
            context=context or "(no context retrieved)",
            answer=execution.output.get("answer", ""),
            schema_hint=JUDGE_RESPONSE_SCHEMA_HINT,
        )


@register_evaluator("citation_accuracy")
class CitationAccuracyEvaluator(LLMJudgeEvaluator):
    """Spec §7.1 lists "citation existence" as deterministic and §10 lists
    "citation/source correctness" as a scored metric — this judge covers the
    correctness half (does the cited source actually support the claim),
    while a simple existence check could be added as a deterministic
    evaluator if citations must always be non-empty."""

    prompt_version = "v1"

    _PROMPT = """You are checking whether an AI answer's citations correctly
support its claims.

Retrieved documents (id -> text):
{documents}

AI answer:
{answer}

Cited document ids:
{citations}
{schema_hint}"""

    def build_prompt(self, case: EvaluationCase, execution: SystemExecution) -> str:
        docs = execution.output.get("retrieved_documents", [])
        doc_lines = "\n".join(
            f"{d.get('id')}: {d.get('text', '')}" for d in docs if isinstance(d, dict)
        )
        return self._PROMPT.format(
            documents=doc_lines or "(none)",
            answer=execution.output.get("answer", ""),
            citations=execution.output.get("citations", []),
            schema_hint=JUDGE_RESPONSE_SCHEMA_HINT,
        )
