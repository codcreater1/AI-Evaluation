#!/usr/bin/env python3
"""CI regression gate — the 29.09 milestone's core piece (spec §17-18,
Definition of Done #8/#9).

Runs one real experiment (config_path), compares it against a baseline
experiment (if one is available), and exits non-zero if the comparison's
`overall_pass` is False — the same regression logic already wired into
GET /experiments/compare (app/api/routes/experiments.py), reused here
rather than reimplemented so the CI gate and the API can never disagree
about what counts as a regression.

Design notes:
  - No baseline available yet (first-ever run, or the previous run's
    artifact couldn't be fetched) is handled by comparing against an empty
    stand-in Experiment. app.core.regression.compare() still applies each
    metric's `minimum` threshold against the candidate in that case (it
    only skips the *baseline-relative* max_relative_drop/max_absolute_drop
    checks, which need a real baseline to mean anything) - so a PR with no
    baseline to diff against still can't merge below the configured floor.
  - Experiment result JSON files are intentionally not committed to this
    repo (see .gitignore: `experiments/*.json`) - datasets are versioned
    files, but run results are not, by design (PROJECT_PLAN.md §4). The
    workflow instead passes the previous run's JSON between CI runs as a
    GitHub Actions artifact - see .github/workflows/evaluate.yml.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from dotenv import load_dotenv

    load_dotenv()  # before app.bootstrap, same reasoning as app/api/main.py
except ImportError:
    pass

import app.bootstrap as _bootstrap  # noqa: F401,E402 - side-effect import registers evaluators + adapters
from app.adapters.base import get_adapter  # noqa: E402
from app.core.config import ExperimentConfig, MetricThreshold  # noqa: E402
from app.core.evaluator import build_evaluators  # noqa: E402
from app.core.experiment import Experiment, ExperimentRunner  # noqa: E402
from app.core.regression import compare  # noqa: E402

_EMPTY_BASELINE = Experiment(
    name="no-baseline", system="none", dataset_version="none", aggregate_scores={}, cases=[]
)


def _load_baseline(path: Path | None) -> Experiment:
    if path is None or not path.is_file():
        return _EMPTY_BASELINE
    try:
        return Experiment.model_validate_json(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        # A corrupt/partial artifact should degrade the gate to
        # threshold-only, not crash the whole CI job over something that
        # isn't even the PR's fault.
        print(f"::warning::Could not parse baseline at {path}: {exc}. Gating on thresholds only.")
        return _EMPTY_BASELINE


def _render_markdown(report, config: ExperimentConfig, candidate: Experiment) -> str:
    lines = ["| metric | baseline | candidate | delta | status |", "|---|---|---|---|---|"]
    for m in report.metrics:
        fmt = lambda v: f"{v:.4f}" if v is not None else "—"
        arrow = {"improved": "\U0001f7e2", "regressed": "\U0001f534", "unchanged": "⚪"}[m.status]
        lines.append(f"| {m.metric} | {fmt(m.baseline)} | {fmt(m.candidate)} | {fmt(m.delta)} | {arrow} {m.status} |")

    body = "\n".join(lines)
    header = "✅ AI Evaluation Passed" if report.overall_pass else "❌ AI Evaluation Failed"
    parts = [f"### {header} — `{config.system}`", "", body]
    if report.newly_failing_case_ids:
        parts += ["", f"**Newly failing cases:** {', '.join(report.newly_failing_case_ids)}"]
    if report.newly_passing_case_ids:
        parts += ["", f"**Newly passing cases:** {', '.join(report.newly_passing_case_ids)}"]
    if report.failure_reasons:
        parts += ["", "**Why:**"] + [f"- {r}" for r in report.failure_reasons]
    parts += ["", f"_{candidate.case_count} cases, experiment `{candidate.id}`_"]
    return "\n".join(parts)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="Path to an experiment config YAML")
    parser.add_argument("--name", required=True, help="Name to record on the resulting experiment")
    parser.add_argument("--base-url", default=None, help="Override adapter.base_url (e.g. for an ephemeral CI container)")
    parser.add_argument("--baseline", type=Path, default=None, help="Path to a previous run's experiment JSON to compare against")
    parser.add_argument("--out", type=Path, required=True, help="Where to write this run's full experiment JSON (for next time's --baseline)")
    parser.add_argument("--out-md", type=Path, required=True, help="Where to write the human-readable gate result (for a PR comment)")
    args = parser.parse_args()

    config = ExperimentConfig.from_yaml(args.config)
    if args.base_url:
        config.adapter["base_url"] = args.base_url

    adapter = get_adapter(config.system, config.adapter)
    evaluators = build_evaluators(config.evaluators, config.llm_judge)
    runner = ExperimentRunner(adapter, evaluators)

    print(f"Running '{args.name}' ({config.system}, dataset={config.dataset}, {len(evaluators)} evaluators)...")
    candidate = await runner.run(name=args.name, config=config)

    baseline = _load_baseline(args.baseline)
    thresholds: dict[str, MetricThreshold] = config.thresholds
    report = compare(baseline, candidate, thresholds)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(candidate.model_dump_json(indent=2), encoding="utf-8")

    markdown = _render_markdown(report, config, candidate)
    args.out_md.parent.mkdir(parents=True, exist_ok=True)
    args.out_md.write_text(markdown, encoding="utf-8")

    print(markdown)
    return 0 if report.overall_pass else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
