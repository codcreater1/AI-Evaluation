"""Simple HTML report/dashboard. Spec: "A simple report - not a SPA ... a
static HTML report or one FastAPI-rendered page showing system overview +
experiment history + failed-case list with links to Langfuse traces is
enough."

Deliberately plain server-rendered f-string HTML (no Jinja2, no JS
framework, no build step) - this endpoint exists to satisfy that one
sentence in the spec, not to become a product. It's still worth making it
genuinely pleasant to read, since this is the page a reviewer / teammate
actually opens: stat cards with per-metric meters (fill vs. configured
threshold, with a tick mark at the minimum) and a small trend sparkline
per metric, an overall pass/fail hero figure, and a styled run history.
Dark mode follows the OS setting (prefers-color-scheme) - there's no
toggle, since a toggle needs JS state and this page deliberately has none.

GET /report renders everything; GET /report/{id} drills into one
experiment's failed cases in full - and visually separates a genuine
evaluator failure from a request that never got a response at all
(execution.error set), per human-eval-spotcheck.md finding #2: a 504
timeout was previously indistinguishable from a wrong AI decision in this
report, which is exactly the failure mode that finding flagged.

NOTE: f-string expressions below never contain a backslash or a quote
character matching the string's own delimiter (e.g. no \" inside {...} of
an f"...") - that combination needs Python 3.12+ (PEP 701) and breaks on
3.11, which is what actually runs this project on Windows. Anything that
needs escaping or quoting is built in a plain variable first, then
interpolated as a bare name.
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

# Palette + spacing per the team's data-viz method (dataviz skill,
# references/palette.md): light/dark chart-chrome tokens, and the fixed
# status triad (good/warning/critical) - never themed, always paired with
# an icon + label so status is never color-alone.
_STYLE = """
<style>
  :root {
    --page-bg: #f9f9f7;
    --surface: #fcfcfb;
    --text-primary: #0b0b0b;
    --text-secondary: #52514e;
    --text-muted: #898781;
    --border: rgba(11,11,11,0.10);
    --gridline: #e1e0d9;
    --accent: #2a78d6;
    --good: #0ca30c;
    --good-bg: #e3f8e8;
    --critical: #d03b3b;
    --critical-bg: #fce8e6;
    --warning: #9a6b00;
    --warning-bg: #fff2d6;
    color-scheme: light;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --page-bg: #0d0d0d;
      --surface: #1a1a19;
      --text-primary: #ffffff;
      --text-secondary: #c3c2b7;
      --text-muted: #898781;
      --border: rgba(255,255,255,0.14);
      --gridline: #2c2c2a;
      --accent: #3987e5;
      --good: #0ca30c;
      --good-bg: rgba(12,163,12,0.16);
      --critical: #e66767;
      --critical-bg: rgba(214,90,90,0.18);
      --warning: #e0ac2f;
      --warning-bg: rgba(224,172,47,0.16);
      color-scheme: dark;
    }
  }
  * { box-sizing: border-box; }
  body {
    font-family: system-ui, -apple-system, "Segoe UI", Arial, sans-serif;
    margin: 0; background: var(--page-bg); color: var(--text-primary);
  }
  .wrap { max-width: 1120px; margin: 0 auto; padding: 2.25rem 1.5rem 4rem; }
  .topbar { margin-bottom: 1.75rem; }
  h1 { margin: 0 0 .3rem; font-size: 1.65rem; letter-spacing: -0.01em; }
  .subtitle { color: var(--text-secondary); margin: 0; font-size: .92rem; }
  .back-link { display: inline-block; margin-bottom: 1.25rem; font-size: .85rem; }
  h2 {
    margin: 2.75rem 0 1rem; font-size: .78rem; color: var(--text-secondary);
    text-transform: uppercase; letter-spacing: .06em; font-weight: 700;
    border-bottom: 1px solid var(--gridline); padding-bottom: .6rem;
  }
  .hero { display: flex; align-items: baseline; gap: .85rem; flex-wrap: wrap; }
  .hero .figure { font-size: 2.6rem; font-weight: 700; line-height: 1; font-variant-numeric: proportional-nums; }
  .hero .figure.good { color: var(--good); }
  .hero .figure.critical { color: var(--critical); }
  .hero .label { color: var(--text-secondary); font-size: .95rem; max-width: 34rem; }
  .cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(340px, 1fr)); gap: 1rem; margin-top: 1.25rem; }
  .card {
    background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
    padding: 1.35rem 1.5rem 1.5rem;
  }
  .card-head { display: flex; justify-content: space-between; align-items: flex-start; gap: .75rem; margin-bottom: .15rem; }
  .card-head h3 { margin: 0; font-size: 1.08rem; }
  .card .meta { color: var(--text-muted); font-size: .78rem; margin: .2rem 0 1.1rem; }
  .metric-row { display: flex; align-items: flex-start; gap: .9rem; margin-bottom: 1rem; }
  .metric-row:last-child { margin-bottom: 0; }
  .metric-main { flex: 1; min-width: 0; }
  .metric-head { display: flex; justify-content: space-between; font-size: .82rem; margin-bottom: .35rem; }
  .metric-name { color: var(--text-secondary); }
  .metric-value { font-variant-numeric: tabular-nums; font-weight: 600; }
  .meter-track { position: relative; height: 7px; border-radius: 4px; background: var(--gridline); }
  .meter-fill { height: 100%; border-radius: 4px; }
  .meter-fill.good { background: var(--good); }
  .meter-fill.critical { background: var(--critical); }
  .meter-fill.neutral { background: var(--accent); }
  .meter-tick { position: absolute; top: -3px; width: 2px; height: 13px; background: var(--text-primary); opacity: .32; }
  .metric-sub { margin-top: .35rem; font-size: .74rem; color: var(--text-muted); display: flex; align-items: center; gap: .4rem; flex-wrap: wrap; }
  .spark-wrap { flex-shrink: 0; padding-top: 1.05rem; }
  .status {
    display: inline-flex; align-items: center; gap: .3rem; font-size: .74rem;
    font-weight: 700; padding: .15rem .5rem; border-radius: 5px; white-space: nowrap;
  }
  .status.good { color: var(--good); background: var(--good-bg); }
  .status.critical { color: var(--critical); background: var(--critical-bg); }
  .status.warning { color: var(--warning); background: var(--warning-bg); }
  table { border-collapse: collapse; width: 100%; margin-top: .75rem; background: var(--surface);
          border: 1px solid var(--border); border-radius: 10px; overflow: hidden; }
  th, td { border-bottom: 1px solid var(--gridline); padding: .65rem .85rem; text-align: left; font-size: .86rem; }
  tr:last-child td { border-bottom: none; }
  th { background: var(--page-bg); color: var(--text-secondary); font-weight: 700;
       text-transform: uppercase; font-size: .68rem; letter-spacing: .04em; }
  a { color: var(--accent); text-decoration: none; }
  a:hover { text-decoration: underline; }
  .muted { color: var(--text-muted); font-size: .85rem; }
  code { background: var(--page-bg); border: 1px solid var(--border); padding: .1rem .35rem;
         border-radius: 4px; font-size: .85em; word-break: break-word; }
  .note { margin: .45rem 0 0; font-size: .82rem; color: var(--text-secondary); }
  @media (max-width: 640px) {
    table { display: block; overflow-x: auto; }
  }
  @media (max-width: 520px) {
    .metric-row { flex-wrap: wrap; }
    .metric-main { flex-basis: 100%; }
    .spark-wrap { padding-top: .4rem; flex-basis: 100%; }
    .spark { width: 100%; height: 22px; display: block; }
  }
</style>
"""

_FAVICON = (
    '<link rel="icon" href="data:image/svg+xml,'
    "%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E"
    "%3Ctext y='.9em' font-size='90'%3E%F0%9F%93%8A%3C/text%3E%3C/svg%3E\">"
)

_SYSTEM_LABELS = {"ata-rag": "ATA RAG", "internship-coordinator": "Internship Coordinator"}


def _humanize_system(system: str) -> str:
    return _SYSTEM_LABELS.get(system, system.replace("-", " ").title())


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


def _threshold_minimum(experiment: Experiment, metric: str) -> float | None:
    thresholds = experiment.config.get("thresholds", {}) if isinstance(experiment.config, dict) else {}
    threshold = thresholds.get(metric, {}) if isinstance(thresholds, dict) else {}
    return threshold.get("minimum") if isinstance(threshold, dict) else None


def _sparkline(values: list[float], *, width: int = 92, height: int = 28) -> str:
    """A 1-series trend line - no legend needed (a single series' identity
    is the metric name already shown beside it, per the data-viz method's
    single-series rule). Native <title> gives a hover tooltip with the raw
    values without needing any JS on a page that deliberately has none."""
    if not values:
        return ""
    if len(values) == 1:
        value_text = f"{values[0]:.3f}"
        title = f"1 run so far: {value_text}"
        title_safe = html.escape(title)
        cx, cy = width / 2, height / 2
        return (
            f'<svg class="spark" width="{width}" height="{height}" preserveAspectRatio="none" '
            f'viewBox="0 0 {width} {height}" role="img"><title>{title_safe}</title>'
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="3" fill="var(--accent)" '
            f'stroke="var(--surface)" stroke-width="2"/></svg>'
        )
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1.0
    pad = 4
    n = len(values)

    def _x(i: int) -> float:
        return pad + (width - 2 * pad) * i / (n - 1)

    def _y(v: float) -> float:
        return pad + (height - 2 * pad) * (1 - (v - lo) / span)

    points = " ".join(f"{_x(i):.1f},{_y(v):.1f}" for i, v in enumerate(values))
    last_x, last_y = _x(n - 1), _y(values[-1])
    value_list = ", ".join(f"{v:.3f}" for v in values)
    title = f"Last {n} runs: {value_list}"
    title_safe = html.escape(title)
    return f"""<svg class="spark" width="{width}" height="{height}" preserveAspectRatio="none" viewBox="0 0 {width} {height}" role="img">
      <title>{title_safe}</title>
      <polyline points="{points}" fill="none" stroke="var(--text-muted)" stroke-width="2"
                stroke-linejoin="round" stroke-linecap="round"/>
      <circle cx="{last_x:.1f}" cy="{last_y:.1f}" r="3" fill="var(--accent)"
              stroke="var(--surface)" stroke-width="2"/>
    </svg>"""


def _meter(name: str, score: float, minimum: float | None, spark_svg: str = "") -> str:
    pct = max(0.0, min(score, 1.0)) * 100
    metric_name = html.escape(name)
    if minimum is None:
        fill_class = "neutral"
        sub = '<span class="muted">no threshold configured</span>'
        tick_html = ""
    else:
        ok = score >= minimum
        fill_class = "good" if ok else "critical"
        status_class = "good" if ok else "critical"
        icon = "✓" if ok else "✗"
        label = "Pass" if ok else "Below min"
        sub = (
            f'<span class="status {status_class}">{icon} {label}</span>'
            f'<span class="muted">min {minimum:.2f}</span>'
        )
        tick_pct = max(0.0, min(minimum, 1.0)) * 100
        tick_html = f'<div class="meter-tick" style="left:{tick_pct:.1f}%"></div>'
    spark_block = f'<div class="spark-wrap">{spark_svg}</div>' if spark_svg else ""
    return f"""
    <div class="metric-row">
      <div class="metric-main">
        <div class="metric-head">
          <span class="metric-name">{metric_name}</span>
          <span class="metric-value">{score:.3f}</span>
        </div>
        <div class="meter-track">
          <div class="meter-fill {fill_class}" style="width:{pct:.1f}%"></div>
          {tick_html}
        </div>
        <div class="metric-sub">{sub}</div>
      </div>
      {spark_block}
    </div>
    """


def _render_hero(system_status: dict[str, bool | None]) -> str:
    gated = [ok for ok in system_status.values() if ok is not None]
    if not gated:
        return ""
    total = len(gated)
    passing = sum(1 for ok in gated if ok)
    cls = "good" if passing == total else "critical"
    return f"""
    <div class="hero">
      <span class="figure {cls}">{passing}/{total}</span>
      <span class="label">systems meeting every configured threshold on their latest run</span>
    </div>
    """


def _render_system_card(system: str, latest: Experiment, history: list[Experiment]) -> str:
    metric_rows = []
    gate_results: list[bool] = []
    for name in sorted(latest.aggregate_scores):
        score = latest.aggregate_scores[name]
        minimum = _threshold_minimum(latest, name)
        if minimum is not None:
            gate_results.append(score >= minimum)
        values = [e.aggregate_scores[name] for e in history if name in e.aggregate_scores][-12:]
        metric_rows.append(_meter(name, score, minimum, _sparkline(values)))
    if gate_results:
        badge_class = "good" if all(gate_results) else "critical"
        icon = "✓" if all(gate_results) else "✗"
        badge_text = "All thresholds met" if all(gate_results) else "Regression"
        card_status = f'<span class="status {badge_class}">{icon} {badge_text}</span>'
        overall_ok: bool | None = all(gate_results)
    else:
        card_status = '<span class="muted">no thresholds configured</span>'
        overall_ok = None
    system_label = html.escape(_humanize_system(system))
    run_name = html.escape(latest.name)
    dataset = html.escape(latest.dataset_version)
    when = _fmt_time(latest.created_at)
    return (
        f"""
    <div class="card">
      <div class="card-head">
        <h3>{system_label}</h3>
        {card_status}
      </div>
      <p class="meta">
        <a href="/report/{latest.id}">{run_name}</a> &middot; dataset {dataset}
        &middot; {latest.case_count} cases &middot; {when}
      </p>
      {''.join(metric_rows)}
    </div>
    """,
        overall_ok,
    )


def _render_history(experiments: list[Experiment]) -> str:
    if not experiments:
        return _NONE_SPAN
    rows = []
    for exp in reversed(experiments):  # newest first
        pass_rates = ", ".join(f"{k}: {v:.0%}" for k, v in exp.pass_rate.items())
        pass_rates_cell = pass_rates or "-"
        model_cell = html.escape(exp.model or "-")
        run_name = html.escape(exp.name)
        system_label = html.escape(_humanize_system(exp.system))
        dataset = html.escape(exp.dataset_version)
        when = _fmt_time(exp.created_at)
        rows.append(
            f"<tr><td><a href=\"/report/{exp.id}\">{run_name}</a></td>"
            f"<td>{system_label}</td><td>{dataset}</td><td>{model_cell}</td>"
            f"<td>{exp.case_count}</td><td>{pass_rates_cell}</td><td>{when}</td></tr>"
        )
    header = (
        "<tr><th>Run</th><th>System</th><th>Dataset</th><th>Model</th><th>Cases</th>"
        "<th>Pass rates</th><th>Created</th></tr>"
    )
    rows_html = "".join(rows)
    return f"<table>{header}{rows_html}</table>"


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
    reasons_html = "<br>".join(reason_lines) or '<span class="muted">(no pass/fail reason given)</span>'

    if record.execution.error:
        # human-eval-spotcheck.md finding #2: a 504/timeout previously scored
        # identically to a genuinely wrong AI decision. Flag it distinctly
        # here rather than folding it into the same "fail" bucket silently.
        error_text = html.escape(record.execution.error)
        body = (
            '<span class="status warning">⚠ Execution error</span>'
            f'<p class="note"><code>{error_text}</code></p>'
            '<p class="note">No response was returned - the verdicts below '
            "reflect that absence, not a wrong decision (see "
            "human-eval-spotcheck.md finding #2).</p>"
            f'<p class="muted" style="margin-top:.5rem;">{reasons_html}</p>'
        )
    else:
        body = reasons_html

    case_id = html.escape(record.case_id)
    return f"<tr><td><code>{case_id}</code></td><td>{body}</td><td>{trace_link}</td></tr>"


def _render_experiment_detail(experiment: Experiment) -> str:
    failed = experiment.failed_cases()
    error_count = sum(1 for c in failed if c.execution.error)
    if failed:
        failed_rows = "".join(_render_failed_cases(r) for r in failed)
        header = (
            "<tr><th>Case</th><th>Failed evaluators / reasons</th>"
            "<th>Langfuse trace</th></tr>"
        )
        failed_html = f"<table>{header}{failed_rows}</table>"
    else:
        failed_html = '<p class="muted">All cases passed.</p>'

    meters = "".join(
        _meter(name, experiment.aggregate_scores[name], _threshold_minimum(experiment, name))
        for name in sorted(experiment.aggregate_scores)
    )
    meters_block = meters or _NA_SPAN

    failed_summary = f"{experiment.case_count} cases &middot; {len(failed)} failed"
    if error_count:
        failed_summary += f" ({error_count} of which are execution errors, not decision errors)"

    run_name = html.escape(experiment.name)
    title = f"{run_name} - AI Evaluation Report"
    system_label = html.escape(_humanize_system(experiment.system))
    dataset = html.escape(experiment.dataset_version)
    when = _fmt_time(experiment.created_at)
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
{_FAVICON}<title>{title}</title>{_STYLE}</head>
<body>
  <div class="wrap">
    <a class="back-link" href="/report">&larr; back to overview</a>
    <h1>{run_name}</h1>
    <p class="subtitle">{system_label} &middot; dataset {dataset} &middot; {when}</p>

    <div class="card" style="margin-top:1.25rem;">
      {meters_block}
      <p class="muted" style="margin-top:1rem;">{failed_summary}</p>
    </div>

    <h2>Failed cases</h2>
    {failed_html}
  </div>
</body>
</html>"""


@router.get("", response_class=HTMLResponse)
def report_overview() -> str:
    experiments = _store.list_experiments()
    latest_by_system: dict[str, Experiment] = {}
    for exp in experiments:  # ascending by created_at
        latest_by_system[exp.system] = exp

    system_status: dict[str, bool | None] = {}
    cards = []
    for system, latest in sorted(latest_by_system.items()):
        history = [e for e in experiments if e.system == system]
        card_html, overall_ok = _render_system_card(system, latest, history)
        cards.append(card_html)
        system_status[system] = overall_ok
    cards_html = "".join(cards) if cards else _NONE_SPAN
    hero_html = _render_hero(system_status)

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
{_FAVICON}<title>AI Evaluation Report</title>{_STYLE}</head>
<body>
  <div class="wrap">
    <div class="topbar">
      <h1>AI Evaluation Platform</h1>
      <p class="subtitle">System overview, experiment history, and failed cases
      with Langfuse trace links.</p>
    </div>

    {hero_html}

    <h2>System overview</h2>
    <div class="cards">{cards_html}</div>

    <h2>Experiment history</h2>
    {_render_history(experiments)}
  </div>
</body>
</html>"""


@router.get("/{experiment_id}", response_class=HTMLResponse)
def report_experiment_detail(experiment_id: str) -> str:
    try:
        experiment = _store.load(experiment_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Experiment not found") from exc
    return _render_experiment_detail(experiment)
