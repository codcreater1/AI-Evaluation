"""Minimal coverage for scripts/ci_run_and_gate.py's pure logic. Unlike the
other one-off scripts/ files, this one *is* the CI regression gate — if it
silently breaks, PRs merge without a real check, so it gets tests unlike
its siblings.

The script isn't a package (scripts/ has no __init__.py, matching the rest
of the repo's one-off-script convention), so it's loaded by path rather
than imported normally. Its heavier path (actually running an experiment
against a live adapter) is intentionally NOT covered here — that was
verified for real, against a real running Internship Coordinator instance,
both for a clean pass and for a real caught regression (see PROJECT_PLAN.md
§9 / the CI workflow's own design notes) rather than mocked, since a mock
adapter would only prove the script agrees with itself.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from app.core.config import MetricThreshold
from app.core.experiment import CaseRecord, Experiment
from app.core.regression import compare
from app.core.schemas import EvaluationResult, SystemExecution

_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "ci_run_and_gate.py"
_spec = importlib.util.spec_from_file_location("ci_run_and_gate", _SCRIPT_PATH)
gate = importlib.util.module_from_spec(_spec)
sys.modules["ci_run_and_gate"] = gate
_spec.loader.exec_module(gate)


def _experiment(exp_id: str, scores: dict, case_pass: dict | None = None) -> Experiment:
    case_pass = case_pass or {}
    cases = [
        CaseRecord(
            case_id=cid,
            execution=SystemExecution(case_id=cid, system="ata-rag"),
            results=[EvaluationResult(evaluator="x", passed=passed)],
        )
        for cid, passed in case_pass.items()
    ]
    return Experiment(
        id=exp_id, name=exp_id, system="ata-rag", dataset_version="v1",
        aggregate_scores=scores, cases=cases,
    )


def test_load_baseline_missing_path_returns_empty_stand_in():
    result = gate._load_baseline(None)
    assert result.aggregate_scores == {}
    assert result.cases == []


def test_load_baseline_nonexistent_file_returns_empty_stand_in():
    result = gate._load_baseline(Path("/nonexistent/path/does-not-exist.json"))
    assert result.aggregate_scores == {}


def test_load_baseline_corrupt_file_degrades_gracefully(tmp_path):
    bad = tmp_path / "corrupt.json"
    bad.write_text("{not valid json", encoding="utf-8")
    result = gate._load_baseline(bad)
    assert result.aggregate_scores == {}


def test_load_baseline_real_file_round_trips(tmp_path):
    original = _experiment("baseline-1", {"answered_correctness": 0.95})
    path = tmp_path / "baseline.json"
    path.write_text(original.model_dump_json(), encoding="utf-8")

    loaded = gate._load_baseline(path)
    assert loaded.id == "baseline-1"
    assert loaded.aggregate_scores == {"answered_correctness": 0.95}


def test_empty_baseline_still_gates_on_configured_minimum():
    # No baseline (first-ever CI run) must still block a candidate that's
    # below its configured floor -- this is the whole point of the gate.
    candidate = _experiment("candidate", {"answered_correctness": 0.5})
    thresholds = {"answered_correctness": MetricThreshold(minimum=0.9)}

    report = compare(gate._EMPTY_BASELINE, candidate, thresholds)

    assert report.overall_pass is False
    assert any("below minimum" in r for r in report.failure_reasons)


def test_render_markdown_marks_failure_header_on_regression():
    baseline = _experiment("b", {"m": 0.9}, {"c1": True})
    candidate = _experiment("c", {"m": 0.5}, {"c1": False})
    thresholds = {"m": MetricThreshold(minimum=0.9)}
    report = compare(baseline, candidate, thresholds)

    class FakeConfig:
        system = "test-system"

    md = gate._render_markdown(report, FakeConfig(), candidate)
    assert "AI Evaluation Failed" in md
    assert "c1" in md  # newly-failing case id surfaced
    assert "regressed" in md


def test_render_markdown_marks_pass_header_when_clean():
    candidate = _experiment("c", {"m": 1.0})
    thresholds = {"m": MetricThreshold(minimum=0.9)}
    report = compare(gate._EMPTY_BASELINE, candidate, thresholds)

    class FakeConfig:
        system = "test-system"

    md = gate._render_markdown(report, FakeConfig(), candidate)
    assert "AI Evaluation Passed" in md
