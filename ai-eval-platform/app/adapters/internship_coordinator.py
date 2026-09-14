"""Adapter for the real Internship Coordinator
(github.com/codcreater1/Internship-report-reviewer).

Grounded in the actual system, not a guess: cloned the repo, ran its 95-test
suite (passed clean), started the service locally, ran its own synthetic
document generator (testdocs/tool/completion_docs.py) through all 9
scenarios, and inspected the real request/response shapes. See
PROJECT_PLAN.md §4.7 for what that changed versus the original stub.

Real contract:
  POST {base_url}/reports/  multipart/form-data
    intern_email: str (required)
    application_id: str (optional, opaque passthrough)
    files: exactly 3 PDFs — role is detected by content, filenames are never
           trusted by the target system, so this adapter doesn't try to name
           them meaningfully either.

  Response body (ReportSubmissionResponse): status, findings[] (code,
  severity, message, remedy, document), student_name, student_id, company,
  counted_working_days, evaluation_score, report_word_count, max_similarity,
  advisory (present only when the target system has an LLM configured — it
  is explicitly non-authoritative there and must stay that way in evaluation
  too).

Important operational caveat (do not skip): the originality/plagiarism check
keeps a shared, mutable corpus (SQLite + in-memory TF-IDF) across
submissions. Two cases in the same dataset can affect each other's results
depending on run order. See PROJECT_PLAN.md's "shared corpus state" finding
before running an experiment against a long-lived instance.
"""

from __future__ import annotations

import base64

import httpx

from app.adapters.base import SystemAdapter, register_adapter
from app.core.schemas import EvaluationCase

DEFAULT_BASE_URL = "http://127.0.0.1:8000"


@register_adapter("internship-coordinator")
class InternshipCoordinatorAdapter(SystemAdapter):
    @property
    def base_url(self) -> str:
        return self.config.get("base_url", DEFAULT_BASE_URL)

    @property
    def timeout(self) -> float:
        return self.config.get("timeout_s", 60)

    async def _call(self, case: EvaluationCase) -> dict:
        intern_email = case.input.get("intern_email", "eval-case@example.edu")
        application_id = case.input.get("application_id", case.id)
        attachments = case.input.get("attachments")
        if not attachments or len(attachments) != 3:
            raise ValueError(
                "case.input.attachments must contain exactly 3 PDFs "
                "(report, evaluation, timesheet — order does not matter, "
                "the target system classifies by content)"
            )

        files = [
            (
                "files",
                (
                    a.get("filename", f"attachment_{i}.pdf"),
                    base64.b64decode(a["content_base64"]),
                    "application/pdf",
                ),
            )
            for i, a in enumerate(attachments)
        ]
        data = {"intern_email": intern_email, "application_id": application_id}

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(f"{self.base_url}/reports/", data=data, files=files)
            response.raise_for_status()
            body = response.json()

        return {
            "submission_id": body.get("id"),
            "status": body.get("status"),
            "findings": body.get("findings", []),
            "student_name": body.get("student_name"),
            "student_id": body.get("student_id"),
            "company": body.get("company"),
            "start_date": body.get("start_date"),
            "end_date": body.get("end_date"),
            "counted_working_days": body.get("counted_working_days"),
            "total_hours": body.get("total_hours"),
            "evaluation_score": body.get("evaluation_score"),
            "report_word_count": body.get("report_word_count"),
            "max_similarity": body.get("max_similarity"),
            "similarity_match": body.get("similarity_match"),
            "advisory": body.get("advisory"),
        }
