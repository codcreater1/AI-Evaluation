#!/usr/bin/env python3
"""Convert ata-rag's own golden set into datasets/ata-rag/v1.jsonl.

Why conversion instead of a fresh dataset (PROJECT_PLAN.md §8): the real
ata-rag repo already ships backend/eval/cases.json — 26 real, well-designed
cases covering tuition, admissions, programmes, all four reply languages,
the scope guardrail and the prompt-injection defence — plus its own harness
(backend/eval/run_eval.py) that already golden-tests this exact system.
Re-inventing that would be worse than what already exists; this script just
reshapes it into this platform's EvaluationCase schema so it also gets
versioning, experiment tracking, regression detection and Langfuse tracing,
none of which the source repo's one-off harness does.

Usage:
    python scripts/convert_ata_rag_dataset.py \\
        --source-repo /path/to/ata-rag \\
        --out datasets/ata-rag/v1.jsonl
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-repo", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=Path("datasets/ata-rag/v1.jsonl"))
    args = parser.parse_args()

    source = args.source_repo / "backend" / "eval" / "cases.json"
    cases = json.loads(source.read_text(encoding="utf-8"))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as f:
        for case in cases:
            converted = {
                "id": f"ata-rag-{case['id']}",
                "system": "ata-rag",
                "input": {"question": case["question"]},
                # The source's "checks" block maps directly onto this
                # platform's expected_output — see app/evaluators/
                # deterministic/ata_rag_checks.py, which ports the same
                # checking logic the source repo's own harness uses.
                "expected_output": case["checks"],
                "metadata": {
                    "category": case["category"],
                    "source": "ported from ata-rag's own backend/eval/cases.json",
                },
            }
            f.write(json.dumps(converted, ensure_ascii=False) + "\n")

    print(f"Wrote {len(cases)} cases to {args.out}")


if __name__ == "__main__":
    main()
