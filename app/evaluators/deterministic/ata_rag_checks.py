"""Deterministic checks for ATA RAG, ported from the real system's own
evaluation harness (backend/eval/run_eval.py in codcreater1/ata-rag), not
reinvented. That harness already golden-tests this exact system with 26
real cases (datasets/ata-rag/v1.jsonl is those cases, converted — see
PROJECT_PLAN.md §8) and its checking logic already handles real edge cases
worth keeping rather than re-guessing: thousands-separator spaces in
tuition figures, function-word-based language detection that isn't fooled
by a place name's diacritics, and known refusal phrasings across all four
reply languages.

Three evaluators instead of one combined check (unlike the source
`_check` function) so the platform can report each dimension separately —
"language accuracy: 96%" versus "keyword accuracy: 90%" — which is the kind
of per-metric visibility spec §10/§22 ask for.
"""

from __future__ import annotations

import re

from app.core.evaluator import Evaluator, register_evaluator
from app.core.schemas import EvaluationCase, EvaluationResult, SystemExecution

# Ported verbatim from ata-rag/backend/eval/run_eval.py — real refusal
# phrasings this system actually uses across its four reply languages.
_REFUSAL_MARKERS = (
    "only help with questions about",
    "could not find",
    "contact the university",
    "nie znalazłem",
    "bulamadım",
    "не знайшов",
    "temporarily overloaded",
)

# Ported from the same source: function words are language-pure (unlike
# diacritics, not dragged in by a place name), so an English answer
# mentioning "Wrocław" still scores as English.
_LANG_WORDS = {
    "en": {
        "the",
        "is",
        "are",
        "for",
        "and",
        "of",
        "to",
        "you",
        "with",
        "per",
        "or",
        "a",
        "an",
        "in",
        "on",
        "this",
        "your",
        "can",
        "year",
        "semester",
    },
    "pl": {
        "na",
        "dla",
        "jest",
        "są",
        "oraz",
        "wynosi",
        "czesne",
        "roku",
        "lub",
        "przy",
        "się",
        "które",
        "można",
        "dokumenty",
        "studia",
        "w",
        "z",
        "i",
    },
    "tr": {
        "ve",
        "için",
        "ile",
        "bir",
        "bu",
        "olan",
        "göre",
        "veya",
        "öğrenim",
        "başvuru",
        "gerekli",
        "ücret",
        "belgeler",
        "kampüs",
        "üniversite",
    },
}


def _answer_language(text: str) -> str:
    t = text.lower()
    if len(re.findall(r"[а-яіїєґ]", t)) >= 3:
        return "uk"
    words = set(re.findall(r"\w+", t))
    scores = {lang: len(ws & words) for lang, ws in _LANG_WORDS.items()}
    best = max(scores, key=lambda k: scores[k])
    return best if scores[best] else "en"


def _normalize(answer: str) -> str:
    # Collapses a space *between digits* so "2 900" (thin/nbsp thousands
    # separator) still matches a keyword check for "2900".
    return re.sub(r"(?<=\d)\s(?=\d)", "", answer.lower())


@register_evaluator("answered_correctness")
class AnsweredCorrectnessEvaluator(Evaluator):
    """Checks `answered` (did it answer vs. decline) and, separately,
    `refused` (declined via a known refusal phrasing) — a case declares
    whichever of the two applies to it."""

    async def evaluate(self, case: EvaluationCase, execution: SystemExecution) -> EvaluationResult:
        checks = case.expected_output or {}
        if "answered" not in checks and not checks.get("refused"):
            return EvaluationResult(
                evaluator=self.name, passed=None, reason="No answered/refused expectation on case."
            )

        answer = execution.output.get("answer", "") or ""
        low = _normalize(answer)
        reasons = []

        if "answered" in checks:
            actual = bool(execution.output.get("answered"))
            if actual != checks["answered"]:
                reasons.append(f"answered={actual}, expected {checks['answered']}")

        if checks.get("refused"):
            refused = not execution.output.get("answered") or any(
                m in low for m in _REFUSAL_MARKERS
            )
            if not refused:
                reasons.append("expected a refusal, got an answer")

        passed = not reasons
        return EvaluationResult(
            evaluator=self.name,
            score=1.0 if passed else 0.0,
            passed=passed,
            reason="; ".join(reasons) or None,
        )


@register_evaluator("language_correctness")
class LanguageCorrectnessEvaluator(Evaluator):
    async def evaluate(self, case: EvaluationCase, execution: SystemExecution) -> EvaluationResult:
        expected_lang = (case.expected_output or {}).get("lang")
        if expected_lang is None:
            return EvaluationResult(
                evaluator=self.name, passed=None, reason="No expected language on case."
            )

        answer = execution.output.get("answer", "") or ""
        actual_lang = _answer_language(answer)
        passed = actual_lang == expected_lang
        return EvaluationResult(
            evaluator=self.name,
            score=1.0 if passed else 0.0,
            passed=passed,
            reason=None
            if passed
            else f"answer language={actual_lang!r}, expected {expected_lang!r}",
        )


@register_evaluator("keyword_requirements")
class KeywordRequirementsEvaluator(Evaluator):
    """contains_all / contains_any / not_contains, as fractions of the
    declared requirements satisfied (not all-or-nothing), so a partial
    tuition-figure miss is visible in the score rather than collapsing to 0."""

    async def evaluate(self, case: EvaluationCase, execution: SystemExecution) -> EvaluationResult:
        checks = case.expected_output or {}
        contains_all = checks.get("contains_all", [])
        contains_any = checks.get("contains_any", [])
        not_contains = checks.get("not_contains", [])
        if not (contains_all or contains_any or not_contains):
            return EvaluationResult(
                evaluator=self.name, passed=None, reason="No keyword expectations on case."
            )

        low = _normalize(execution.output.get("answer", "") or "")
        reasons = []
        total_checks = 0
        satisfied = 0

        for kw in contains_all:
            total_checks += 1
            if kw.lower() in low:
                satisfied += 1
            else:
                reasons.append(f"missing required '{kw}'")

        if contains_any:
            total_checks += 1
            if any(kw.lower() in low for kw in contains_any):
                satisfied += 1
            else:
                reasons.append(f"none of {contains_any} present")

        for kw in not_contains:
            total_checks += 1
            if kw.lower() not in low:
                satisfied += 1
            else:
                reasons.append(f"forbidden '{kw}' present")

        score = satisfied / total_checks if total_checks else None
        passed = not reasons
        return EvaluationResult(
            evaluator=self.name,
            score=score,
            passed=passed,
            reason="; ".join(reasons) or None,
        )
