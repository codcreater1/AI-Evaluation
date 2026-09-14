"""Import this once at process startup (API, CLI, tests) to populate the
evaluator and adapter registries via their `@register_*` decorators.

Kept separate from app/api/main.py so that module doesn't need dotted
`import app.adapters...` statements, which bind the name `app` in that
module's namespace and collide with the FastAPI instance conventionally
also named `app` — harmless at runtime, but real enough that mypy flags it,
so it's better avoided than explained away.
"""

from __future__ import annotations

import app.adapters.ata_rag as _ata_rag  # noqa: F401
import app.adapters.internship_coordinator as _internship_coordinator  # noqa: F401
import app.evaluators as _evaluators  # noqa: F401
