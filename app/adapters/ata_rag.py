"""Adapter for the real ATA RAG chatbot (github.com/codcreater1/ata-rag).

Grounded in the actual system: read its README, its FastAPI router
(app/routers/chat.py) and — importantly — its own evaluation harness
(backend/eval/run_eval.py + cases.json), which already golden-tests this
exact system. See PROJECT_PLAN.md §8 for what that changed versus the
original stub, and datasets/ata-rag/v1.jsonl's provenance.

Real contract:
  POST {base_url}/chat/ask   application/json
    question: str (required)
    top_k: int | None
    language: "auto" | "en" | "pl" | "uk" | "tr" | None
    history: [{"role": "user"|"assistant", "content": str}, ...]

  Response (AskResponse): answer, sources[] ({n, title, url, similarity}),
  confidence (None in BM25-only fallback mode), answered, latency_ms,
  query_id, cached.

Known gap (documented, not silently worked around): the public API returns
*cited sources* (title + url) but not the retrieved passage text itself, so
a true groundedness check (does the answer's wording match the retrieved
context) can't be done from this adapter's vantage point alone — the
system's own eval harness has the same constraint in its default `--api`
mode and works around it with keyword/language checks instead, which is
what the ported evaluators here do too. Deeper groundedness checking would
need either an eval-only endpoint that also returns chunk text, or an
in-process adapter mode importing `app.services.rag` directly the way this
repo's own `eval/run_eval.py --local` (no --api) mode does.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.adapters.base import SystemAdapter, register_adapter
from app.core.schemas import EvaluationCase

DEFAULT_BASE_URL = "http://127.0.0.1:8000"


@register_adapter("ata-rag")
class AtaRagAdapter(SystemAdapter):
    @property
    def base_url(self) -> str:
        return self.config.get("base_url", DEFAULT_BASE_URL)

    @property
    def timeout(self) -> float:
        return self.config.get("timeout_s", 90)  # cold model calls can be slow

    async def _call(self, case: EvaluationCase) -> dict[str, Any]:
        question = case.input.get("question")
        if not question:
            raise ValueError("case.input.question is required for the ATA RAG system")

        payload = {
            "question": question,
            "top_k": case.input.get("top_k"),
            "language": case.input.get("language"),
            "history": case.input.get("history", []),
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(f"{self.base_url}/chat/ask", json=payload)
            response.raise_for_status()
            body = response.json()

        return {
            "answer": body.get("answer", ""),
            "sources": body.get("sources", []),
            "confidence": body.get("confidence"),
            "answered": body.get("answered"),
            "reported_latency_ms": body.get("latency_ms"),
            "query_id": body.get("query_id"),
            "cached": body.get("cached", False),
        }
