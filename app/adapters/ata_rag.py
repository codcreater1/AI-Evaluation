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

import asyncio
import time
from typing import Any

import httpx

from app.adapters.base import SystemAdapter, register_adapter
from app.core.schemas import EvaluationCase

DEFAULT_BASE_URL = "http://127.0.0.1:8000"

# ATA RAG rate-limits at 20 requests / 60 seconds per client IP (see
# PROJECT_PLAN.md sec.8 and backend/app/core/cache.py). A full sequential
# experiment run (concurrency: 1) sends 50 requests back-to-back with no
# gap, which trips that limit partway through even on a "cold" run with no
# prior traffic - confirmed empirically on 2026-09-20 (a clean run failed 6
# cases, an immediate retry failed 12). Pacing requests at least this far
# apart keeps every run safely under the limit instead of gambling on
# timing. 3.5s gives a small safety margin over the exact 3.0s (60s/20req)
# boundary.
MIN_REQUEST_INTERVAL_S = 3.5


@register_adapter("ata-rag")
class AtaRagAdapter(SystemAdapter):
    @property
    def base_url(self) -> str:
        return self.config.get("base_url", DEFAULT_BASE_URL)

    @property
    def timeout(self) -> float:
        return self.config.get("timeout_s", 90)  # cold model calls can be slow

    @property
    def min_request_interval(self) -> float:
        return self.config.get("min_request_interval_s", MIN_REQUEST_INTERVAL_S)

    async def _wait_for_rate_limit(self) -> None:
        """Pace requests so a sequential run never exceeds ATA RAG's own
        20-requests/60-seconds limit, regardless of how fast each answer
        comes back or how recently a previous experiment ran."""
        lock: asyncio.Lock | None = getattr(self, "_pacing_lock", None)
        if lock is None:
            lock = asyncio.Lock()
            self._pacing_lock = lock
        async with lock:
            last_call_at: float | None = getattr(self, "_last_call_at", None)
            if last_call_at is not None:
                elapsed = time.monotonic() - last_call_at
                remaining = self.min_request_interval - elapsed
                if remaining > 0:
                    await asyncio.sleep(remaining)
            self._last_call_at = time.monotonic()

    async def _call(self, case: EvaluationCase) -> dict[str, Any]:
        question = case.input.get("question")
        if not question:
            raise ValueError("case.input.question is required for the ATA RAG system")

        await self._wait_for_rate_limit()

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