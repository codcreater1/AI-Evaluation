# Contributing

## Setup

```bash
python -m venv .venv
pip install -e ".[dev]"
cp .env.example .env
```

## Before opening a PR

```bash
ruff check .
pytest
```

## Conventions

- Line length is 100, target Python 3.12 (see `pyproject.toml`).
- New AI systems are added as adapters in `app/adapters/` (see `docs/architecture.md`).
- New evaluators live in `app/evaluators/` and must be registered in the evaluator registry.
- Keep dataset changes in `datasets/` and regenerate via the scripts in `scripts/` where possible.
