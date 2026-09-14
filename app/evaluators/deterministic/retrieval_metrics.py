"""Retrieval Recall@K / Precision@K. Spec §7.1 and §10.

Expects:
  case.expected_output["relevant_document_ids"]: list[str]
  execution.output["retrieved_documents"]: list[{"id": str, ...}]  (order matters — top K used)

Two separate evaluator classes (rather than one parameterized class) so both
show up distinctly in reports and can have independent thresholds, matching
how the spec's config example (§24) lists them separately.

Known limitation (PROJECT_PLAN.md §8): not currently wired to either real
system. The real ata-rag adapter's `sources` field is shaped
`{n, title, url, similarity}` — no `"id"` key — so these evaluators would
score every case 0 against it as-is; that's why neither is in
`config/example.yaml`'s default list. Using this against ata-rag would need
either normalizing `url` (or `title`) into an `id` field in the adapter, or
rewriting `_retrieved_ids` here to read `url`. Left as a documented gap
rather than silently guessed at, since we don't have a ground-truth
"relevant document" mapping for the ported 26-case dataset either.
"""

from __future__ import annotations

from app.core.evaluator import Evaluator, register_evaluator
from app.core.schemas import EvaluationCase, EvaluationResult, SystemExecution


def _retrieved_ids(execution: SystemExecution, k: int) -> list[str]:
    docs = execution.output.get("retrieved_documents", [])
    ids: list[str] = []
    for doc in docs[:k]:
        doc_id = doc.get("id") if isinstance(doc, dict) else None
        if doc_id:
            ids.append(doc_id)
    return ids


def _relevant_ids(case: EvaluationCase) -> list[str] | None:
    if not case.expected_output:
        return None
    return case.expected_output.get("relevant_document_ids")


@register_evaluator("retrieval_recall_at_k")
class RecallAtKEvaluator(Evaluator):
    async def evaluate(self, case: EvaluationCase, execution: SystemExecution) -> EvaluationResult:
        k = self.config.get("k", 5)
        relevant = _relevant_ids(case)
        if not relevant:
            return EvaluationResult(
                evaluator=self.name, passed=None, reason="No relevant_document_ids on case."
            )

        retrieved = set(_retrieved_ids(execution, k))
        hits = len(retrieved & set(relevant))
        score = hits / len(relevant)
        return EvaluationResult(
            evaluator=self.name,
            score=score,
            passed=score >= self.config.get("minimum", 0.0),
            metadata={"k": k, "hits": hits, "relevant_count": len(relevant)},
        )


@register_evaluator("retrieval_precision_at_k")
class PrecisionAtKEvaluator(Evaluator):
    async def evaluate(self, case: EvaluationCase, execution: SystemExecution) -> EvaluationResult:
        k = self.config.get("k", 5)
        relevant = _relevant_ids(case)
        if relevant is None:
            return EvaluationResult(
                evaluator=self.name, passed=None, reason="No relevant_document_ids on case."
            )

        retrieved = _retrieved_ids(execution, k)
        if not retrieved:
            return EvaluationResult(
                evaluator=self.name, score=0.0, passed=False, reason="Nothing retrieved."
            )

        hits = len(set(retrieved) & set(relevant))
        score = hits / len(retrieved)
        return EvaluationResult(
            evaluator=self.name,
            score=score,
            passed=score >= self.config.get("minimum", 0.0),
            metadata={"k": k, "hits": hits, "retrieved_count": len(retrieved)},
        )
