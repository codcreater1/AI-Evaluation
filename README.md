# AI Evaluation Platform

Reusable evaluation infrastructure for AI-powered applications, built on
Langfuse. Initially supports two systems: the **Internship Coordinator** and
the **ATA RAG Chatbot**.

Read **`PROJECT_PLAN.md`** first — it maps this repo's structure to the real
project deadlines and flags several gaps in the original requirements doc.
Read **`docs/architecture.md`** for how to add a new AI system or evaluator.

## Setup

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # fill in Langfuse + LLM provider keys when available
pytest -q              # runs fully offline — no Langfuse/LLM keys required
```

## Quick tour

```
app/core/         schemas, Evaluator interface, dataset manager, experiment runner, regression logic
app/adapters/      one class per AI system under test (stubs — wire up before running real experiments)
app/evaluators/    deterministic/ (no LLM) and llm_judge/ (LLM-as-judge) evaluators
app/integrations/  Langfuse wrapper
app/api/           FastAPI app (uvicorn app.api.main:app --reload)
config/            YAML experiment configs — this is what you edit to add an evaluation, not app/core
datasets/          versioned golden datasets (JSONL), one folder per system
tests/             pytest suite; runs standalone, no live systems or LLM calls needed
```

## Status

This is a working scaffold, not a finished platform: the two system adapters
and the LLM-judge model call are intentionally left as `NotImplementedError`
stubs with the expected input/output shapes documented inline — wiring those
up to the real Internship Coordinator, ATA RAG chatbot, and an LLM provider
is the team's first task. Everything else (schemas, evaluator registry,
dataset versioning, experiment runner, regression detection, Langfuse
tracing, API stubs) runs today; see `pytest -q`.
