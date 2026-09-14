"""Experiment comparison + regression detection. Spec §16, §17.

`compare()` implements the exact table shape from §16 (baseline vs candidate
per metric) and the fail/pass gate from §17 (configurable thresholds,
absolute minimums, and relative or absolute drop limits — see
PROJECT_PLAN.md §4.6 for why both drop kinds are supported rather than just
the doc's single "%" example).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.core.config import MetricThreshold
from app.core.experiment import Experiment
from app.core.schemas import ComparisonStatus


class MetricComparison(BaseModel):
    metric: str
    baseline: float | None
    candidate: float | None
    delta: float | None
    status: ComparisonStatus


class ComparisonReport(BaseModel):
    baseline_experiment_id: str
    candidate_experiment_id: str
    metrics: list[MetricComparison] = Field(default_factory=list)
    newly_failing_case_ids: list[str] = Field(default_factory=list)
    newly_passing_case_ids: list[str] = Field(default_factory=list)
    overall_pass: bool = True
    failure_reasons: list[str] = Field(default_factory=list)

    @property
    def regressions(self) -> list[MetricComparison]:
        return [m for m in self.metrics if m.status == "regressed"]

    @property
    def improvements(self) -> list[MetricComparison]:
        return [m for m in self.metrics if m.status == "improved"]


_STATUS_EPSILON = 1e-9


def _classify(delta: float | None) -> ComparisonStatus:
    if delta is None:
        return "unchanged"
    if delta > _STATUS_EPSILON:
        return "improved"
    if delta < -_STATUS_EPSILON:
        return "regressed"
    return "unchanged"


def compare(
    baseline: Experiment,
    candidate: Experiment,
    thresholds: dict[str, MetricThreshold] | None = None,
) -> ComparisonReport:
    thresholds = thresholds or {}
    report = ComparisonReport(
        baseline_experiment_id=baseline.id, candidate_experiment_id=candidate.id
    )

    all_metrics = set(baseline.aggregate_scores) | set(candidate.aggregate_scores)
    for metric in sorted(all_metrics):
        b = baseline.aggregate_scores.get(metric)
        c = candidate.aggregate_scores.get(metric)
        delta = (c - b) if (b is not None and c is not None) else None
        comparison = MetricComparison(
            metric=metric, baseline=b, candidate=c, delta=delta, status=_classify(delta)
        )
        report.metrics.append(comparison)

        threshold = thresholds.get(metric)
        if threshold is None or c is None:
            continue

        if threshold.minimum is not None and c < threshold.minimum:
            report.overall_pass = False
            report.failure_reasons.append(
                f"{metric}={c:.4f} is below minimum {threshold.minimum:.4f}"
            )
        if threshold.max_relative_drop is not None and b:
            relative_drop = (b - c) / b
            if relative_drop > threshold.max_relative_drop:
                report.overall_pass = False
                report.failure_reasons.append(
                    f"{metric} dropped {relative_drop:.2%}, exceeding max_relative_drop "
                    f"{threshold.max_relative_drop:.2%} ({b:.4f} -> {c:.4f})"
                )
        if threshold.max_absolute_drop is not None and b is not None:
            absolute_drop = b - c
            if absolute_drop > threshold.max_absolute_drop:
                report.overall_pass = False
                report.failure_reasons.append(
                    f"{metric} dropped {absolute_drop:.4f}, exceeding max_absolute_drop "
                    f"{threshold.max_absolute_drop:.4f} ({b:.4f} -> {c:.4f})"
                )

    baseline_by_id = {c.case_id: c.passed for c in baseline.cases}
    candidate_by_id = {c.case_id: c.passed for c in candidate.cases}
    for case_id, candidate_passed in candidate_by_id.items():
        baseline_passed = baseline_by_id.get(case_id)
        if baseline_passed is True and candidate_passed is False:
            report.newly_failing_case_ids.append(case_id)
        elif baseline_passed is False and candidate_passed is True:
            report.newly_passing_case_ids.append(case_id)

    if report.newly_failing_case_ids:
        report.overall_pass = False
        preview = report.newly_failing_case_ids[:5]
        suffix = "..." if len(report.newly_failing_case_ids) > 5 else ""
        report.failure_reasons.append(
            f"{len(report.newly_failing_case_ids)} case(s) newly failing: {preview}{suffix}"
        )

    return report
