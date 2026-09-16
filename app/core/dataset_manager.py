"""Versioned dataset storage. Spec §14.

Deliberate MVP choice (documented, per spec's "team may propose alternatives
if reasoning is documented"): datasets are stored as JSONL files under
datasets/<system>/<version>.jsonl rather than in Postgres. They're small,
human-diffable in a PR, and this sidesteps building DB migrations in week 1.
Postgres (per spec §25) is reserved for experiment/run metadata, which is
genuinely relational and query-heavy. See PROJECT_PLAN.md §4.4.

"Immutable once used in a released experiment" (spec §14) is enforced with a
sidecar `.locked` marker file, written the first time an experiment runs
against that version.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.core.schemas import EvaluationCase

_VERSION_RE = re.compile(r"^v(\d+)$")


class DatasetVersionLockedError(RuntimeError):
    """Raised when trying to mutate a dataset version an experiment already used."""


class DatasetManager:
    def __init__(self, root: str | Path = "datasets") -> None:
        self.root = Path(root)

    def _system_dir(self, system: str) -> Path:
        d = self.root / system
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _path(self, system: str, version: str) -> Path:
        return self._system_dir(system) / f"{version}.jsonl"

    def _lock_path(self, system: str, version: str) -> Path:
        return self._system_dir(system) / f"{version}.locked"

    @staticmethod
    def _version_sort_key(version: str) -> int:
        match = _VERSION_RE.match(version)
        return int(match.group(1)) if match else -1

    def list_versions(self, system: str) -> list[str]:
        versions = [p.stem for p in self._system_dir(system).glob("*.jsonl")]
        return sorted(versions, key=self._version_sort_key)

    def latest_version(self, system: str) -> str | None:
        versions = self.list_versions(system)
        return versions[-1] if versions else None

    def is_locked(self, system: str, version: str) -> bool:
        return self._lock_path(system, version).exists()

    def lock(self, system: str, version: str) -> None:
        """Call this the first time an experiment runs against a version."""
        self._lock_path(system, version).touch()

    def load(self, system: str, version: str) -> list[EvaluationCase]:
        path = self._path(system, version)
        if not path.exists():
            raise FileNotFoundError(f"No dataset {system}/{version}")
        cases = []
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    cases.append(EvaluationCase.model_validate_json(line))
        return cases

    def save_new_version(
        self, system: str, cases: list[EvaluationCase], version: str | None = None
    ) -> str:
        """Write a brand-new version. Refuses to overwrite a locked version."""
        if version is None:
            existing = self.list_versions(system)
            next_n = 1
            for v in existing:
                m = _VERSION_RE.match(v)
                if m:
                    next_n = max(next_n, int(m.group(1)) + 1)
            version = f"v{next_n}"

        if self.is_locked(system, version):
            raise DatasetVersionLockedError(
                f"{system}/{version} was already used by a released experiment; "
                "create a new version instead of editing it."
            )

        # Guard against accidentally clobbering distinct case IDs across systems.
        for case in cases:
            if case.system != system:
                raise ValueError(
                    f"Case {case.id!r} has system={case.system!r}, expected {system!r}"
                )

        path = self._path(system, version)
        with path.open("w", encoding="utf-8") as f:
            for case in cases:
                f.write(case.model_dump_json() + "\n")
        return version

    def append_draft_case(self, system: str, case: EvaluationCase) -> str:
        """Feedback-loop entry point (spec §19): a production failure becomes a
        new evaluation case. If the latest version is still an unreleased
        draft (never locked), it's extended in place; if it's already locked
        by a released experiment, a fresh draft version is started on top of
        it instead — so a released version is never mutated."""
        latest = self.latest_version(system)
        if latest is None:
            return self.save_new_version(system, [case])

        cases = self.load(system, latest)
        if self.is_locked(system, latest):
            return self.save_new_version(system, [*cases, case])
        return self.save_new_version(system, [*cases, case], version=latest)
