"""Generic operational-metric thresholds: latency, cost, token usage.
Spec §7.1 ("latency threshold", "token/cost threshold") and §10 (Operational).

One class, config-selected metric, so `latency_threshold` and `cost_threshold`
in a config file both resolve here without duplicated code.
"""

from __future__ import annotations

from app.core.evaluator import Evaluator, register_evaluator
from app.core.schemas import EvaluationCase, EvaluationResult, SystemExecution

_METRIC_FIELDS = {
    "latency_ms": "latency_ms",
    "cost_usd": "cost_usd",
    "prompt_tokens": "prompt_tokens",
    "completion_tokens": "completion_tokens",
}


@register_evaluator("threshold")
class ThresholdEvaluator(Evaluator):
    """config: {"metric": "latency_ms", "max": 2000}"""

    async def evaluate(self, case: EvaluationCase, execution: SystemExecution) -> EvaluationResult:
        metric = self.config.get("metric", "latency_ms")
        field = _METRIC_FIELDS.get(metric)
        if field is None:
            return EvaluationResult(
                evaluator=self.name, passed=None, reason=f"Unknown metric {metric!r}"
            )

        value = getattr(execution, field)
        if value is None:
            return EvaluationResult(
                evaluator=self.name, passed=None, reason=f"No {metric} recorded for this execution."
            )

        max_value = self.config["max"]
        passed = value <= max_value
        return EvaluationResult(
            evaluator=self.name,
            score=value,
            passed=passed,
            reason=None if passed else f"{metric}={value} exceeds max={max_value}",
            metadata={"metric": metric, "max": max_value},
        )
