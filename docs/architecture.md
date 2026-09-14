# Architecture

See `PROJECT_PLAN.md` at the repo root for the deadline plan and the list of
gaps found in the original requirements doc. This file covers the "how it
fits together" that spec §29.6 asks documentation to explain.

```
              AI Evaluation API (FastAPI, app/api)
                          |
        +-----------------+------------------+
        |                                     |
  Evaluation Engine                    Dataset Manager
  (app/core/experiment.py)             (app/core/dataset_manager.py)
        |
        +-- System Adapters (app/adapters/)  <-- not in the original spec,
        |     one per AI system, normalizes      added to bridge the engine
        |     "run this case" -> SystemExecution  to two different codebases
        |
        +-- Evaluators (app/evaluators/)
              deterministic/  — no LLM, pure functions over case+execution
              llm_judge/      — calls an LLM, returns structured score+reason
        |
        v
   Langfuse (app/integrations/langfuse_client.py)
   traces, scores, experiment metadata
```

## Adding a new AI system

1. Write a `SystemAdapter` subclass in `app/adapters/` implementing `_call()`.
   Decorate it with `@register_adapter("your-system-name")`.
2. Write a golden dataset at `datasets/your-system-name/v1.jsonl`.
3. Write a config file (copy `config/example.yaml`) naming your system,
   dataset, evaluators and thresholds.
4. No changes to `app/core/*` are needed — that's the whole point (spec §33).

## Adding a new evaluator

1. Subclass `Evaluator` (deterministic) or `LLMJudgeEvaluator` (LLM-based) in
   `app/evaluators/`. Decorate with `@register_evaluator("your_metric_name")`.
2. Add it to the `import` list in `app/evaluators/__init__.py`.
3. Reference it by name in a config file's `evaluators:` list.

## Why datasets are files, not database rows

See PROJECT_PLAN.md §4.4. Short version: they're small, need to be
git-diffable in PRs, and don't need Postgres's relational features the way
experiment/run metadata does.

## What's still a stub

- `app/adapters/ata_rag.py` and `internship_coordinator.py`: `_call()` raises
  `NotImplementedError` — wire these to the real systems first.
- `LLMJudgeEvaluator.call_model()`: needs a real LLM provider client.
- `app/integrations/langfuse_client.py`: works with real Langfuse keys in
  `.env`; degrades to inert no-ops without them, so tests never need network
  access or credentials.
