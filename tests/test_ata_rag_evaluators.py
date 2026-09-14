"""Cross-checks the real, ported v1 golden dataset against its own
evaluators.

For every case in datasets/ata-rag/v1.jsonl (ported 1:1 from ata-rag's own
backend/eval/cases.json — see PROJECT_PLAN.md §8), build a SystemExecution
whose "answer" is constructed to satisfy that case's own expected_output
checks, and assert the ported evaluators (app/evaluators/deterministic/
ata_rag_checks.py) score it as a pass. This is a consistency check between
the dataset/evaluators and the checks' own semantics, not a claim that the
real chatbot currently answers this way for every case.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.dataset_manager import DatasetManager
from app.core.evaluator import build_evaluators
from app.core.schemas import SystemExecution

DATASET_ROOT = Path(__file__).resolve().parent.parent / "datasets"

# Ported language sample words (app/evaluators/deterministic/ata_rag_checks.py
# _LANG_WORDS) — enough of each language's function words to satisfy the
# same detector under test.
_LANG_SAMPLE = {
    "en": "The answer is for you and this year.",
    "pl": "To jest dla studia na uniwersytecie i w tym roku.",
    "tr": "Bu üniversite için gerekli olan bir başvuru ücreti.",
    "uk": "Це відповідь про навчання в університеті.",
}

_REFUSAL_TEXT = "I can only help with questions about ATA University admissions and programmes."


def _load_cases():
    return DatasetManager(DATASET_ROOT).load("ata-rag", "v1")


def _answer_satisfying(checks: dict) -> str:
    if checks.get("refused"):
        return _REFUSAL_TEXT

    parts = []
    lang = checks.get("lang")
    if lang:
        parts.append(_LANG_SAMPLE.get(lang, _LANG_SAMPLE["en"]))
    else:
        parts.append(_LANG_SAMPLE["en"])

    parts.extend(checks.get("contains_all", []))
    contains_any = checks.get("contains_any", [])
    if contains_any:
        parts.append(contains_any[0])

    return " ".join(parts)


def _execution_matching_expectation(case) -> SystemExecution:
    checks = case.expected_output or {}
    answer = _answer_satisfying(checks)
    answered = checks.get("answered", not checks.get("refused", False))
    return SystemExecution(
        case_id=case.id,
        system="ata-rag",
        output={
            "answer": answer,
            "answered": answered,
            "sources": [],
        },
    )


def test_v1_dataset_has_twenty_six_cases_ported_from_the_real_repo():
    cases = _load_cases()
    assert len(cases) == 26
    categories = {c.metadata.get("category") for c in cases}
    assert categories == {
        "tuition",
        "admissions",
        "programmes",
        "multilingual",
        "scope",
        "gate",
        "injection",
    }


@pytest.mark.parametrize("case", _load_cases(), ids=lambda c: c.id)
async def test_answered_correctness_passes_against_its_own_expectation(case):
    (evaluator,) = build_evaluators(["answered_correctness"])
    execution = _execution_matching_expectation(case)

    result = await evaluator.evaluate(case, execution)

    assert result.passed in (True, None)


@pytest.mark.parametrize("case", _load_cases(), ids=lambda c: c.id)
async def test_keyword_requirements_passes_against_its_own_expectation(case):
    (evaluator,) = build_evaluators(["keyword_requirements"])
    execution = _execution_matching_expectation(case)

    result = await evaluator.evaluate(case, execution)

    assert result.passed in (True, None)


@pytest.mark.parametrize(
    "case",
    [c for c in _load_cases() if (c.expected_output or {}).get("lang")],
    ids=lambda c: c.id,
)
async def test_language_correctness_passes_against_its_own_expectation(case):
    (evaluator,) = build_evaluators(["language_correctness"])
    execution = _execution_matching_expectation(case)

    result = await evaluator.evaluate(case, execution)

    assert result.passed is True


async def test_answered_correctness_catches_a_refusal_regression():
    """A case that expects a real answer (e.g. a tuition question) must fail
    if the system regresses into refusing it."""
    (evaluator,) = build_evaluators(["answered_correctness"])
    cases = {c.id: c for c in _load_cases()}
    case = cases["ata-rag-tuition-ce-warsaw"]

    regressed_execution = SystemExecution(
        case_id=case.id,
        system="ata-rag",
        output={"answer": _REFUSAL_TEXT, "answered": False},
    )

    result = await evaluator.evaluate(case, regressed_execution)

    assert result.passed is False


async def test_keyword_requirements_catches_a_missing_required_figure():
    (evaluator,) = build_evaluators(["keyword_requirements"])
    cases = {c.id: c for c in _load_cases()}
    case = cases["ata-rag-tuition-ce-warsaw"]  # requires both 2900 and 3500

    incomplete_execution = SystemExecution(
        case_id=case.id,
        system="ata-rag",
        output={"answer": "Tuition is around 2900 EUR per year.", "answered": True},
    )

    result = await evaluator.evaluate(case, incomplete_execution)

    assert result.passed is False
    assert result.score is not None and result.score < 1.0
