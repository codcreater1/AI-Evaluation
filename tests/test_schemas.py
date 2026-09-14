from app.core.schemas import EvaluationCase, EvaluationResult, SystemExecution


def test_evaluation_case_minimal():
    case = EvaluationCase(id="rag-001", system="ata-rag", input={"question": "?"})
    assert case.expected_output is None
    assert case.metadata == {}


def test_system_execution_records_error_without_raising():
    execution = SystemExecution(case_id="rag-001", system="ata-rag", error="TimeoutError: ...")
    assert execution.error is not None
    assert execution.output == {}


def test_evaluation_result_supports_all_result_kinds():
    # Spec §6: numeric, boolean, categorical and textual all need to fit.
    numeric = EvaluationResult(evaluator="answer_correctness", score=0.92)
    boolean = EvaluationResult(evaluator="citation_exists", passed=True)
    categorical = EvaluationResult(evaluator="failure_type", category="hallucination")
    assert numeric.score == 0.92
    assert boolean.passed is True
    assert categorical.category == "hallucination"
