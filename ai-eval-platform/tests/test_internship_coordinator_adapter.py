"""Tests the real HTTP adapter against a mocked transport — no live service
needed. The response shape mocked here mirrors an actual response captured
from a real run of codcreater1/Internship-report-reviewer (PROJECT_PLAN.md
§7), not a guess.
"""

from __future__ import annotations

import base64

import httpx
import pytest

from app.adapters.internship_coordinator import InternshipCoordinatorAdapter
from app.core.schemas import EvaluationCase

_REAL_SHAPED_RESPONSE = {
    "id": "abc123",
    "status": "request_clarification",
    "findings": [
        {
            "code": "DAYS_SHORT",
            "severity": "clarify",
            "message": "Only 18 attended working days could be verified; 20 are required.",
            "remedy": "Submit an attendance record showing at least 20 attended working days.",
            "document": "timesheet",
        }
    ],
    "student_name": "Zofia Wiśniewska",
    "student_id": "s24187",
    "company": "Nova Logistics Software Sp. z o.o.",
    "start_date": "2026-06-01",
    "end_date": "2026-07-10",
    "counted_working_days": 18,
    "total_hours": 144.0,
    "evaluation_score": 84,
    "report_word_count": 950,
    "max_similarity": 0.12,
    "similarity_match": None,
    "advisory": None,
}


def _case() -> EvaluationCase:
    pdf_bytes = b"%PDF-1.4 fake"
    b64 = base64.b64encode(pdf_bytes).decode("ascii")
    return EvaluationCase(
        id="ic-test",
        system="internship-coordinator",
        input={
            "intern_email": "student@example.edu",
            "attachments": [
                {"filename": "internship_report.pdf", "content_base64": b64},
                {"filename": "evaluation_form.pdf", "content_base64": b64},
                {"filename": "attendance_record.pdf", "content_base64": b64},
            ],
        },
    )


async def test_adapter_normalizes_a_real_shaped_response(monkeypatch):
    def fake_handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/reports/"
        return httpx.Response(201, json=_REAL_SHAPED_RESPONSE)

    transport = httpx.MockTransport(fake_handler)

    original_client = httpx.AsyncClient

    def patched_client(*args, **kwargs):
        kwargs["transport"] = transport
        return original_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", patched_client)

    adapter = InternshipCoordinatorAdapter({"base_url": "http://testserver"})
    execution = await adapter.run(_case())

    assert execution.error is None
    assert execution.output["status"] == "request_clarification"
    assert execution.output["findings"][0]["code"] == "DAYS_SHORT"
    assert execution.output["counted_working_days"] == 18


async def test_adapter_rejects_wrong_attachment_count():
    adapter = InternshipCoordinatorAdapter()
    case = _case()
    case.input["attachments"] = case.input["attachments"][:2]  # only 2, not 3

    execution = await adapter.run(case)

    assert execution.error is not None
    assert "3 PDFs" in execution.error


@pytest.mark.parametrize("missing", ["attachments"])
async def test_adapter_reports_missing_attachments_as_execution_error(missing):
    adapter = InternshipCoordinatorAdapter()
    case = _case()
    del case.input[missing]

    execution = await adapter.run(case)

    assert execution.error is not None
