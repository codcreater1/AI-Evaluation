"""LLM-as-Judge base class. Spec §8.

The spec requires every LLM judge to:
  - receive question / expected answer / retrieved context / actual answer
  - produce a structured score + explanation
  - record the evaluator prompt version AND the model used (§8, last two lines)

Subclasses only provide a prompt template and a `metric` name; this base
class handles calling the model, parsing the structured response, and
stamping prompt_version/model into EvaluationResult.metadata so that's never
accidentally forgotten by a new judge someone adds later.
"""

from __future__ import annotations

import json
from abc import abstractmethod
from typing import Any

from app.core.evaluator import Evaluator
from app.core.schemas import EvaluationCase, EvaluationResult, SystemExecution

JUDGE_RESPONSE_SCHEMA_HINT = """
Respond with ONLY a JSON object of this exact shape, no other text:
{"score": <float 0.0-1.0>, "passed": <true|false>, "reason": "<one or two sentences>"}
"""


class LLMJudgeEvaluator(Evaluator):
    uses_llm = True
    prompt_version: str = "v1"

    @abstractmethod
    def build_prompt(self, case: EvaluationCase, execution: SystemExecution) -> str:
        """Return the full prompt, including JUDGE_RESPONSE_SCHEMA_HINT."""
        raise NotImplementedError

    async def call_model(self, prompt: str) -> str:
        """TODO(team): wire this to the actual LLM provider (spec §25 —
        "LLM provider API"). Kept as a single override point so every judge
        evaluator automatically picks up whichever client the team settles
        on, and so tests can monkeypatch just this one method."""
        raise NotImplementedError(
            "Connect LLMJudgeEvaluator.call_model to a real LLM provider before running judges."
        )

    def _model_name(self) -> str:
        return self.config.get("model", "unconfigured-model")

    async def evaluate(self, case: EvaluationCase, execution: SystemExecution) -> EvaluationResult:
        if execution.error:
            return EvaluationResult(
                evaluator=self.name,
                passed=False,
                reason=f"System execution errored, cannot judge: {execution.error}",
                metadata={"prompt_version": self.prompt_version, "model": self._model_name()},
            )

        prompt = self.build_prompt(case, execution)
        try:
            raw = await self.call_model(prompt)
            parsed: dict[str, Any] = json.loads(raw)
        except NotImplementedError:
            raise
        except Exception as exc:  # noqa: BLE001 - a malformed judge response is a
            # data problem, not a reason to crash the whole experiment.
            return EvaluationResult(
                evaluator=self.name,
                passed=None,
                reason=f"Could not parse judge response: {exc}",
                metadata={"prompt_version": self.prompt_version, "model": self._model_name()},
            )

        return EvaluationResult(
            evaluator=self.name,
            score=parsed.get("score"),
            passed=parsed.get("passed"),
            reason=parsed.get("reason"),
            metadata={"prompt_version": self.prompt_version, "model": self._model_name()},
        )
