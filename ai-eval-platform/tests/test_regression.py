"""Tests built directly from the spec's own worked example (§16-17), so a
passing test suite doubles as confirmation the numbers in the doc make sense
under the implementation."""

from app.core.config import MetricThreshold
from app.core.experiment import CaseRecord, Experiment
from app.core.regression import compare
from app.core.schemas import EvaluationResult, SystemExecution


def _experiment(
    exp_id: str, scores: dict[str, float], case_pass: dict[str, bool] | None = None
) -> Experiment:
    case_pass = case_pass or {}
    cases = [
        CaseRecord(
            case_id=cid,
            execution=SystemExecution(case_id=cid, system="ata-rag"),
            results=[EvaluationResult(evaluator="answer_correctness", passed=passed)],
        )
        for cid, passed in case_pass.items()
    ]
    return Experiment(
        id=exp_id,
        name=exp_id,
        system="ata-rag",
        dataset_version="v1",
        aggregate_scores=scores,
        cases=cases,
    )


def test_spec_section_16_example_flags_improvements_correctly():
    # doc's table: Correctness 91.2% -> 94.6%, Groundedness 95.1% -> 96.0%, all improved
    baseline = _experiment("baseline", {"correctness": 0.912, "groundedness": 0.951})
    candidate = _experiment("candidate", {"correctness": 0.946, "groundedness": 0.960})

    report = compare(baseline, candidate)

    statuses = {m.metric: m.status for m in report.metrics}
    assert statuses["correctness"] == "improved"
    assert statuses["groundedness"] == "improved"
    assert report.overall_pass is True


def test_spec_section_17_regression_threshold_example():
    # doc's example: 92.4% -> 86.7% is a "regression" that should block deployment.
    baseline = _experiment("baseline", {"answer_correctness": 0.924})
    candidate = _experiment("candidate", {"answer_correctness": 0.867})

    thresholds = {"answer_correctness": MetricThreshold(minimum=0.90, max_relative_drop=0.02)}
    report = compare(baseline, candidate, thresholds)

    assert report.overall_pass is False
    assert any("answer_correctness" in reason for reason in report.failure_reasons)


def test_newly_failing_cases_are_detected_even_if_aggregate_holds():
    baseline = _experiment(
        "baseline", {"answer_correctness": 0.90}, case_pass={"c1": True, "c2": True}
    )
    candidate = _experiment(
        "candidate", {"answer_correctness": 0.90}, case_pass={"c1": True, "c2": False}
    )

    report = compare(baseline, candidate)

    assert report.newly_failing_case_ids == ["c2"]
    assert report.overall_pass is False
