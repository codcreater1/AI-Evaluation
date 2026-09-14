"""Cross-checks the real v1 golden dataset against its own evaluators.

For every case in datasets/internship-coordinator/v1.jsonl, build the
SystemExecution that a system reproducing the case's own expected_output
exactly would produce, and assert the evaluators built around that schema
score it as a pass. This is a consistency check between the dataset (built
from real, verified runs — see PROJECT_PLAN.md §7) and the evaluators, not a
claim that the real system currently behaves this way for every case.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.dataset_manager import DatasetManager
from app.core.evaluator import build_evaluators
from app.core.schemas import SystemExecution

DATASET_ROOT = Path(__file__).resolve().parent.parent / "datasets"


def _load_cases():
    return DatasetManager(DATASET_ROOT).load("internship-coordinator", "v1")


def _execution_matching_expectation(case) -> SystemExecution:
    expected = case.expected_output or {}
    findings = [{"code": code} for code in expected.get("must_include_finding_codes", [])]
    return SystemExecution(
        case_id=case.id,
        system="internship-coordinator",
        output={
            "status": expected.get("status"),
            "findings": findings,
            "student_name": expected.get("student_name"),
            "student_id": expected.get("student_id"),
            "company": expected.get("company"),
            "advisory": None,  # no LLM configured in these captured runs
        },
    )


def test_v1_dataset_has_nine_cases_from_real_runs():
    cases = _load_cases()
    assert len(cases) == 9
    assert {c.id for c in cases} == {
        "ic-clean",
        "ic-short-days",
        "ic-name-mismatch",
        "ic-unsigned",
        "ic-thin-report",
        "ic-weekend-pad",
        "ic-future-dates",
        "ic-scan",
        "ic-copied",
    }


@pytest.mark.parametrize("case", _load_cases(), ids=lambda c: c.id)
async def test_status_correctness_passes_against_its_own_expectation(case):
    (evaluator,) = build_evaluators(["status_correctness"])
    execution = _execution_matching_expectation(case)

    result = await evaluator.evaluate(case, execution)

    assert result.passed is True


@pytest.mark.parametrize("case", _load_cases(), ids=lambda c: c.id)
async def test_finding_codes_correctness_passes_against_its_own_expectation(case):
    (evaluator,) = build_evaluators(["finding_codes_correctness"])
    execution = _execution_matching_expectation(case)

    result = await evaluator.evaluate(case, execution)

    assert result.passed is True


async def test_finding_codes_correctness_catches_a_real_regression_shape():
    """The exact shape observed when running all 9 scenarios against one
    shared, unreset instance (PROJECT_PLAN.md §7): an extra REPORT_NOT_ORIGINAL
    finding appears alongside the case's real finding. This must fail."""
    (evaluator,) = build_evaluators(["finding_codes_correctness"])
    cases = {c.id: c for c in _load_cases()}
    case = cases["ic-short-days"]

    contaminated_execution = SystemExecution(
        case_id=case.id,
        system="internship-coordinator",
        output={
            "status": "rejected",  # REPORT_NOT_ORIGINAL escalates it to rejected
            "findings": [{"code": "DAYS_SHORT"}, {"code": "REPORT_NOT_ORIGINAL"}],
        },
    )

    result = await evaluator.evaluate(case, contaminated_execution)

    assert result.passed is False
    assert "REPORT_NOT_ORIGINAL" in result.reason


async def test_advisory_quality_reports_not_applicable_without_advisory():
    (evaluator,) = build_evaluators(["advisory_quality"], {"model": "test-model"})
    cases = _load_cases()
    execution = _execution_matching_expectation(
        cases[0]
    )  # advisory=None, matches these captured runs

    result = await evaluator.evaluate(cases[0], execution)

    assert result.passed is None
    assert "advisory" in result.reason.lower()
