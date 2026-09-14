import pytest

from app.core.evaluator import build_evaluators, get_evaluator_class, list_registered_evaluators
from app.core.schemas import EvaluationCase, SystemExecution


def test_built_in_evaluators_are_registered():
    names = list_registered_evaluators()
    for expected in [
        "exact_match",
        "required_fields",
        "retrieval_recall_at_k",
        "answer_correctness",
    ]:
        assert expected in names


def test_unknown_evaluator_raises_with_helpful_message():
    with pytest.raises(KeyError, match="No evaluator registered as 'does_not_exist'"):
        get_evaluator_class("does_not_exist")


async def test_exact_match_evaluator_passes_on_match():
    (evaluator,) = build_evaluators(["exact_match"], {"field": "answer"})
    case = EvaluationCase(id="c1", system="ata-rag", input={}, expected_output={"answer": "42"})
    execution = SystemExecution(case_id="c1", system="ata-rag", output={"answer": "42"})

    result = await evaluator.evaluate(case, execution)

    assert result.passed is True
    assert result.score == 1.0


async def test_exact_match_evaluator_fails_on_mismatch():
    (evaluator,) = build_evaluators(["exact_match"], {"field": "answer"})
    case = EvaluationCase(id="c1", system="ata-rag", input={}, expected_output={"answer": "42"})
    execution = SystemExecution(case_id="c1", system="ata-rag", output={"answer": "43"})

    result = await evaluator.evaluate(case, execution)

    assert result.passed is False
    assert "43" in result.reason


async def test_required_fields_reports_missing():
    (evaluator,) = build_evaluators(["required_fields"], {"required": ["eligible", "explanation"]})
    case = EvaluationCase(id="c1", system="internship-coordinator", input={})
    execution = SystemExecution(
        case_id="c1", system="internship-coordinator", output={"eligible": True}
    )

    result = await evaluator.evaluate(case, execution)

    assert result.passed is False
    assert "explanation" in result.metadata["missing"]
