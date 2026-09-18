"""Simple HTML report/dashboard. Spec: "A simple report - not a SPA ... a
static HTML report or one FastAPI-rendered page showing system overview +
experiment history + failed-case list with links to Langfuse traces is
enough."

Deliberately plain server-rendered f-string HTML (no Jinja2, no JS
framework) - this endpoint exists to satisfy that one sentence in the spec,
not to become a product. GET /report renders everything; GET /report/{id}
drills into one experiment's failed cases in full.

NOTE: f-string expressions below never contain a backslash (e.g. no \" inside
{...}) - that syntax needs Python 3.12+ (PEP 701) and breaks on 3.11, which
is what actually runs this project on Windows. Any escaped quote is built in
a plain variable first, then interpolated as a bare name.
"""

from __future__ import annotations

import html
import os
from datetime import datetime

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from app.core.experiment import CaseRecord, Experiment, ExperimentStore

router = APIRouter(prefix="/report", tags=["report"])
_store = ExperimentStore()

_NA_SPAN = '<span class="muted">n/a</span>'
_NONE_SPAN = '<span class="muted">No experiments recorded yet.</span>'

_STYLE = """
<style>
  body { font-family: -apple-system, Segoe UI, Arial, sans-serif; margin: 2rem;
         color: #1a1a1a; background: #fafafa; }
  h1 { margin-bottom: 0.2rem; }
  h2 { margin-top: 2.5rem; border-bottom: 1px solid #ddd; padding-bottom: 0.3rem; }
  .subtitle { color: #666; margin-top: 0; }
  table { border-collapse: collapse; width: 100%; margin-top: 0.75rem; background: white; }
  th, td { border: 1px solid #ddd; padding: 0.5rem 0.75rem; text-align: left; font-size: 0.9rem; }
  th { background: #f0f0f0; }
  .pass { color: #0a7d2c; font-weight: 600; }
  .fail { color: #b3261e; font-weight: 600; }
  .neutral { color: #666; }
  .badge { display: inline-block; padding: 0.1rem 0.5rem; border-radius: 4px; font-size: 0.8rem; }
  .badge.pass { background: #e3f8e8; }
  .badge.fail { background: #fce8e6; }
  a { color: #1a56db; text-decoration: none; }
  a:hover { text-decoration: underline; }
  .card { background: white; border: 1px solid #ddd; border-radius: 6px;
           padding: 1rem 1.25rem; margin-bottom: 1rem; }
  .muted { color: #888; font-size: 0.85rem; }
  code { background: #f0f0f0; padding: 0.1rem 0.3rem; border-radius: 3px; font-size: 0.85em; }
</style>
"""


def _trace_url(trace_id: str | None) -> str | None:
    """Spec §13: every run must let you deep-link to its Langfuse trace.
    Suppressed when there's no trace id at all, or for the "disabled-<uuid>"
    ids langfuse_client.py yields when Langfuse isn't configured - those
    aren't real trace ids."""
    if not trace_id or trace_id.startswith("disabled-"):
        return None
    host = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
    return f"{host.rstrip('/')}/trace/{trace_id}"


def _fmt_time(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M UTC")


def _score_badge(evaluator: str, score: float, experiment: Experiment) -> str:
    threshold = experiment.config.get("thresholds", {}).get(evaluator, {})
    minimum = threshold.get("minimum") if isinstance(threshold, dict) else None
    if minimum is None:
        return f'<span class="neutral">{score:.3f}</span>'
    css = "pass" if score >= minimum else "fail"
    return f'<span class="badge {css}">{score:.3f} (min {minimum:.2f})</span>'


def _latest_per_system(experiments: list[Experiment]) -> dict[str, Experiment]:
    latest: dict[str, Experiment] = {}
    for exp in experiments:  # experiments is ascending by created_at
        latest[exp.system] = exp
    return latest


def _render_overview(latest: dict[str, Experiment]) -> str:
    if not latest:
        return _NONE_SPAN
    rows = []
    for system, exp in sorted(latest.items()):
        scores = ", ".join(
            f"{html.escape(name)}: {_score_badge(name, val, exp)}"
            for name, val in exp.aggregate_scores.items()
        )
        scores_cell = scores or _NA_SPAN
        rows.append(
            "<tr>"
            f"<td>{html.escape(system)}</td>"
            f'<td><a href="/report/{exp.id}">{html.escape(exp.name)}</a></td>'
            f"<td>{html.escape(exp.dataset_version)}</td>"
            f"<td>{exp.case_count}</td>"
            f"<td>{scores_cell}</td>"
            f"<td>{_fmt_time(exp.created_at)}</td>"
            "</tr>"
        )
    header = (
        "<tr><th>System</th><th>Latest run</th><th>Dataset</th><th>Cases</th>"
        "<th>Scores vs. threshold</th><th>When</th></tr>"
    )
    return f"""
    <table>
      {header}
      {''.join(rows)}
    </table>
    """


def _render_history(experiments: list[Experiment]) -> str:
    if not experiments:
        return _NONE_SPAN
    rows = []
    for exp in reversed(experiments):  # newest first
        pass_rates = ", ".join(f"{k}: {v:.0%}" for k, v in exp.pass_rate.items())
        pass_rates_cell = pass_rates or "-"
        model_cell = exp.model or "-"
        rows.append(
            "<tr>"
            f'<td><a href="/report/{exp.id}">{html.escape(exp.name)}</a></td>'
            f"<td>{html.escape(exp.system)}</td>"
            f"<td>{html.escape(exp.dataset_version)}</td>"
            f"<td>{html.escape(model_cell)}</td>"
            f"<td>{exp.case_count}</td>"
            f"<td>{pass_rates_cell}</td>"
            f"<td>{_fmt_time(exp.created_at)}</td>"
            "</tr>"
        )
    header = (
        "<tr><th>Run</th><th>System</th><th>Dataset</th><th>Model</th><th>Cases</th>"
        "<th>Pass rates</th><th>Created</th></tr>"
    )
    return f"""
    <table>
      {header}
      {''.join(rows)}
    </table>
    """


def _render_failed_cases(record: CaseRecord) -> str:
    trace_url = _trace_url(record.execution.trace_id)
    if trace_url:
        safe_url = html.escape(trace_url)
        trace_link = f'<a href="{safe_url}" target="_blank">view trace</a>'
    else:
        trace_link = '<span class="muted">no trace</span>'
    failed_results = [r for r in record.results if r.passed is False]
    reason_lines = []
    for r in failed_results:
        evaluator_name = html.escape(r.evaluator)
        reason_text = html.escape(r.reason or "no reason given")
        reason_lines.append(f"<strong>{evaluator_name}</strong>: {reason_text}")
    reasons = "<br>".join(reason_lines) or '<span class="muted">(no pass/fail reason given)</span>'
    case_id = html.escape(record.case_id)
    return f"<tr><td><code>{case_id}</code></td><td>{reasons}</td><td>{trace_link}</td></tr>"


def _render_experiment_detail(experiment: Experiment) -> str:
    failed = experiment.failed_cases()
    if failed:
        failed_rows = "".join(_render_failed_cases(r) for r in failed)
        failed_html = f"""
        <table>
          <tr><th>Case</th><th>Failed evaluators / reasons</th>
          <th>Langfuse trace</th></tr>
          {failed_rows}
        </table>
        """
    else:
        failed_html = '<p class="muted">All cases passed.</p>'
    scores_html = "<br>".join(
        f"{html.escape(name)}: {_score_badge(name, val, experiment)}"
        for name, val in experiment.aggregate_scores.items()
    )
    scores_block = scores_html or _NA_SPAN
    title = f"{html.escape(experiment.name)} - AI Evaluation Report"
    subtitle = (
        f"{html.escape(experiment.system)} &middot; "
        f"dataset {html.escape(experiment.dataset_version)} &middot; "
        f"{_fmt_time(experiment.created_at)}"
    )
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>{title}</title>{_STYLE}</head>
<body>
  <p><a href="/report">&larr; back to overview</a></p>
  <h1>{html.escape(experiment.name)}</h1>
  <p class="subtitle">{subtitle}</p>

  <div class="card">
    <strong>Aggregate scores</strong><br>
    {scores_block}
    <p class="muted">{experiment.case_count} cases &middot; {len(failed)} failed</p>
  </div>

  <h2>Failed cases</h2>
  {failed_html}
</body>
</html>"""


@router.get("", response_class=HTMLResponse)
def report_overview() -> str:
    experiments = _store.list_experiments()
    latest = _latest_per_system(experiments)
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>AI Evaluation Report</title>{_STYLE}</head>
<body>
  <h1>AI Evaluation Platform</h1>
  <p class="subtitle">System overview, experiment history, and failed cases
  with Langfuse trace links.</p>

  <h2>System overview (latest run per system)</h2>
  {_render_overview(latest)}

  <h2>Experiment history</h2>
  {_render_history(experiments)}
</body>
</html>"""


@router.get("/{experiment_id}", response_class=HTMLResponse)
def report_experiment_detail(experiment_id: str) -> str:
    try:
        experiment = _store.load(experiment_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Experiment not found") from exc
    return _render_experiment_detail(experiment)