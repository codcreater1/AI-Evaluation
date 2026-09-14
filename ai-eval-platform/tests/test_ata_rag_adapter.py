"""Tests the real ATA RAG HTTP adapter against a mocked transport — no live
service needed. The response shape mocked here mirrors the real `AskResponse`
documented in app/adapters/ata_rag.py's docstring (PROJECT_PLAN.md §8), not
a guess.
"""

from __future__ import annotations

import httpx

from app.adapters.ata_rag import AtaRagAdapter
from app.core.schemas import EvaluationCase

_REAL_SHAPED_RESPONSE = {
    "answer": "Tuition for Computer Engineering in Warsaw is 2900-3500 EUR per year.",
    "sources": [
        {
            "n": 1,
            "title": "Tuition Fees 2026",
            "url": "https://ata.edu/tuition",
            "similarity": 0.87,
        },
    ],
    "confidence": 0.91,
    "answered": True,
    "latency_ms": 842,
    "query_id": "q-abc123",
    "cached": False,
}


def _case() -> EvaluationCase:
    return EvaluationCase(
        id="ata-rag-test",
        system="ata-rag",
        input={"question": "What is the tuition for Computer Engineering in Warsaw?"},
    )


async def test_adapter_normalizes_a_real_shaped_response(monkeypatch):
    def fake_handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/chat/ask"
        return httpx.Response(200, json=_REAL_SHAPED_RESPONSE)

    transport = httpx.MockTransport(fake_handler)

    original_client = httpx.AsyncClient

    def patched_client(*args, **kwargs):
        kwargs["transport"] = transport
        return original_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", patched_client)

    adapter = AtaRagAdapter({"base_url": "http://testserver"})
    execution = await adapter.run(_case())

    assert execution.error is None
    assert "2900" in execution.output["answer"]
    assert execution.output["sources"][0]["url"] == "https://ata.edu/tuition"
    assert execution.output["answered"] is True
    assert execution.output["cached"] is False


async def test_adapter_reports_missing_question_as_execution_error():
    adapter = AtaRagAdapter()
    case = _case()
    del case.input["question"]

    execution = await adapter.run(case)

    assert execution.error is not None
    assert "question" in execution.error


async def test_adapter_passes_through_optional_fields(monkeypatch):
    captured_payload = {}

    def fake_handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_payload
        import json

        captured_payload = json.loads(request.content)
        return httpx.Response(200, json=_REAL_SHAPED_RESPONSE)

    transport = httpx.MockTransport(fake_handler)
    original_client = httpx.AsyncClient

    def patched_client(*args, **kwargs):
        kwargs["transport"] = transport
        return original_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", patched_client)

    adapter = AtaRagAdapter()
    case = _case()
    case.input["top_k"] = 3
    case.input["language"] = "en"
    case.input["history"] = [{"role": "user", "content": "hi"}]

    await adapter.run(case)

    assert captured_payload["top_k"] == 3
    assert captured_payload["language"] == "en"
    assert captured_payload["history"] == [{"role": "user", "content": "hi"}]
