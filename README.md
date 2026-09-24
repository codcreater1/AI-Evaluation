# AI Evaluation Platform

Reusable evaluation infrastructure for AI-powered applications, built on
Langfuse. Wired up against two real, deployed systems: the **Internship
Coordinator** (github.com/codcreater1/Internship-report-reviewer,
pomelo-2) and the **ATA RAG Chatbot** (github.com/codcreater1/ata-rag,
pomelo-8).

Read **`PROJECT_PLAN.md`** first — it maps this repo's structure to the real
project deadlines and documents every gap found (and fixed) along the way,
including real baseline numbers from both live deployments.
Read **`docs/architecture.md`** for how to add a new AI system or evaluator.

This README is the "I just got a fresh machine, how do I get this running"
guide. Every command below has been run end-to-end from a clean `git clone`
before being written down here — if something doesn't match what you see,
that's a bug in this doc, not something to work around.

## 1. Prerequisites

- **Python 3.12+.** Check with `python --version` (Windows: also try
  `py -3.12 --version` — some machines have multiple Pythons installed and
  the bare `python`/`pip`/`uvicorn` commands silently resolve to the wrong
  one). If in doubt, find the real interpreter path first and use it
  explicitly for the venv step below, e.g.
  `C:\Python312\python.exe -m venv .venv`.
- **Git access to `codcreater1/AI-Evaluation`** (and, only if you also want
  to run the Internship Coordinator locally — section 5 — access to
  `codcreater1/Internship-report-reviewer` too). Make sure `git clone`/`git
  push` already work with your credentials before following the rest of
  this guide.
- Internet access. The ATA RAG dataset runs against the real live
  deployment (pomelo-8.codewithpeter.com) — no local ATA RAG setup is ever
  needed.

## 2. Clone and install

```bash
git clone https://github.com/codcreater1/AI-Evaluation.git
cd AI-Evaluation

python3.12 -m venv .venv
# Windows:      .venv\Scripts\activate
# macOS/Linux:  source .venv/bin/activate

pip install -e ".[dev]"
```

Verify the install before doing anything else — this runs fully offline,
no keys or live systems required:

```bash
pytest -q
```

You should see something like `108 passed`. If you see collection errors
instead, you're almost certainly running the wrong Python (see the
prerequisites note above) or forgot to activate the venv.

## 3. Configure Langfuse (optional but recommended)

```bash
cp .env.example .env
```

Fill in `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` (and `LANGFUSE_HOST`
if you're not on Langfuse Cloud). **This file is gitignored on purpose —
it holds real secrets and has to be recreated by hand on every machine you
work from.** Without it, nothing crashes: `app/integrations/langfuse_client.py`
detects the missing keys and every tracing call becomes an inert no-op, so
experiments still run and still score correctly — you just won't get
traces to inspect in the Langfuse UI.

## 4. Run a real experiment against ATA RAG (no local setup needed)

Start the platform's own API server:

```bash
# Windows, full venv path so it can't resolve to the wrong Python:
.venv\Scripts\python.exe -m uvicorn app.api.main:app --reload --port 8080

# macOS/Linux:
.venv/bin/python -m uvicorn app.api.main:app --reload --port 8080
```

In another terminal, trigger a real run against the live pomelo-8 deployment:

```bash
curl -X POST "http://localhost:8080/experiments?config_path=config/example.yaml&name=my-ata-rag-run"
```

This runs all 102 cases in `datasets/ata-rag/v3.jsonl` (meets
PROJECT_PLAN.md's 100-case minimum) through `answered_correctness`,
`language_correctness` and `keyword_requirements`, and returns something
like:

```json
{"id": "...", "aggregate_scores": {"answered_correctness": 1.0, "language_correctness": 1.0, "keyword_requirements": 1.0}}
```

Thresholds (`config/example.yaml`): `answered_correctness ≥ 0.90`,
`language_correctness ≥ 0.90`, `keyword_requirements ≥ 0.85`. Takes ~6
minutes — ATA RAG rate-limits at 20 requests/60s, so `concurrency: 1` plus
the adapter's built-in request pacing (`app/adapters/ata_rag.py`) is
deliberate; raising concurrency will just get you 429s.

## 5. Run against the Internship Coordinator

**Against the shared team deployment (read-only checks, no policy
changes):**

```bash
curl -X POST "http://localhost:8080/experiments?config_path=config/internship-coordinator.yaml&name=my-ic-run"
```

Runs the 50 cases in `datasets/internship-coordinator/v4.jsonl` against
pomelo-2. Because pomelo-2 is a shared, long-lived instance with mutable
state (a SQLite-backed originality corpus that persists across
submissions — see PROJECT_PLAN.md section 9), **don't run this
interleaved with someone else's manual testing**, and don't expect to
reproduce an exact regression demo against it — for that, run locally
instead:

**Locally, to demo a real change (baseline → modify a policy → see the
effect):**

1. Clone and start a local instance:
   ```bash
   git clone https://github.com/codcreater1/Internship-report-reviewer.git
   cd Internship-report-reviewer/backend
   python3.12 -m venv .venv
   .venv\Scripts\pip install -r requirements.txt   # or the repo's documented install step
   ```
2. Copy its rules file somewhere outside the repo, so you can edit policy
   values without touching git-tracked files:
   ```bash
   copy rules\university-rules.json C:\path\to\demo-rules.json
   ```
3. Start it with an isolated DB/storage/rules, and no LLM key (disables the
   advisory-reading path entirely — fine for a deterministic-checks demo):
   ```bash
   set REVIEW_DB_PATH=C:\path\to\demo.db
   set REVIEW_STORAGE_ROOT=C:\path\to\demo_storage
   set REVIEW_RULES_PATH=C:\path\to\demo-rules.json
   set LLM_API_KEY=
   .venv\Scripts\python.exe -m uvicorn app.main:app --port 8010
   ```
4. Run a baseline experiment from the AI-Evaluation repo, in another
   terminal:
   ```bash
   curl -X POST "http://localhost:8080/experiments?config_path=config/internship-coordinator-local-demo.yaml&name=baseline"
   ```
5. Edit a value in `demo-rules.json` (e.g. `attendance.min_working_days`),
   **then**:
   ```bash
   del demo.db & rmdir /S /Q demo_storage
   ```
   before restarting the server in step 3 — skipping this is the one
   mistake that will actually break the demo: the originality corpus is
   not reset by a restart on its own, and re-submitting the same dataset
   into an already-populated corpus produces false `REPORT_NOT_ORIGINAL`
   findings on every case.
6. Run a second experiment (`name=modified`), then compare the two — see
   section 6.

## 6. Compare experiments / detect regressions

```bash
curl "http://localhost:8080/experiments/compare?baseline_id=<baseline experiment id>&candidate_id=<modified experiment id>"
```

Returns a per-metric delta table (`improved`/`regressed`/`unchanged`),
`newly_failing_case_ids`/`newly_passing_case_ids`, and an `overall_pass`
gate evaluated against the thresholds the *candidate* run actually used —
this is what backs Definition of Done items #7/#8. Every case's Langfuse
trace (deep-linkable via the case's `trace_id`) now carries real
input/output, not just metadata — fixed in commit `2aba77b` after tracing
showed `input: null`/`output: undefined` for every case.

## 7. CI/CD regression gate

`.github/workflows/evaluate.yml` runs on every PR touching `app/**`,
`config/**` or `datasets/**`:

- **ATA RAG**: runs the real 102-case dataset against the live pomelo-8
  deployment directly from CI — safe, because the system is stateless per
  request.
- **Internship Coordinator**: CI builds and runs
  `Internship-report-reviewer`'s own `backend/Dockerfile` as a disposable
  container, fresh per run, and evaluates against that instead of the
  shared pomelo-2 deployment. Never point a CI job at pomelo-2 — see the
  shared-corpus finding in section 5 above; a fresh container per run is
  the actual fix (`config/internship-coordinator-ci.yaml`).

Both jobs compare their run against the last known-good baseline (the most
recent successful run on `main`, passed between workflow runs as a GitHub
Actions artifact — experiment result JSONs still aren't committed to the
repo, same as running them locally) using the same `compare()` logic behind
`/experiments/compare`, via `scripts/ci_run_and_gate.py`. No baseline yet
(first run, or nothing's merged since this workflow was added) still gates
on each metric's configured `minimum` — a PR can't merge below the floor
either way. Results post as a PR comment, updated in place on re-runs.

**To actually block merges on this**, mark `test`, `evaluate-ata-rag` and
`evaluate-internship-coordinator` as required status checks in the `main`
branch protection rule (Settings → Branches) — a workflow file can't set
that on its own.

## 8. Quick tour

```
app/core/         schemas, Evaluator interface, dataset manager, experiment runner, regression logic
app/adapters/      one class per AI system under test — both wired to the real deployments, not stubs
app/evaluators/    deterministic/ (no LLM) and llm_judge/ (LLM-as-judge) evaluators
app/integrations/  Langfuse wrapper (traces + scores; degrades to no-ops without .env keys)
app/api/           FastAPI app (uvicorn app.api.main:app --reload)
config/            YAML experiment configs — this is what you edit to add an evaluation, not app/core
datasets/          versioned, immutable-once-used golden datasets (JSONL), one folder per system
tests/             pytest suite; runs standalone, no live systems or LLM calls needed
```

## 9. Troubleshooting

- **`curl: (7) Failed to connect`** — the platform's own API server (step 4)
  isn't running, or was closed in whichever terminal window had it. Start
  it again; `--reload` mode means editing a file under `app/` restarts it
  automatically, but closing the window does not restart it for you.
- **A rerun scores *worse* than expected right after "fixing" something**
  (Internship Coordinator only) — you almost certainly forgot to clear
  `demo.db`/`demo_storage` before restarting the local instance (step 5.5
  above). Check the failing cases' report pages for `REPORT_NOT_ORIGINAL`
  findings on cases that should be clean — that's the signature of this
  exact bug.
- **ATA RAG scores worse on a retry right after a run that hit 429s** —
  don't retry immediately; wait ~60s. Retrying immediately compounds the
  rate-limit window instead of clearing it.
- **`pip install -e ".[dev]"` succeeds but `python`/`uvicorn` behave
  strangely afterwards** — you're not actually inside the venv, or a
  different Python is shadowing it on PATH. Always invoke the venv's own
  executable by full path (`.venv\Scripts\python.exe`, not bare `python`)
  if this happens instead of debugging PATH order.

## 10. Status

Both system adapters (`app/adapters/ata_rag.py`,
`internship_coordinator.py`) are wired to their real deployments and have
run real experiments meeting every configured threshold — see
PROJECT_PLAN.md section 9 for the actual baseline numbers. Everything else
(schemas, evaluator registry, dataset versioning, experiment runner,
regression detection via `/experiments/compare`, Langfuse tracing with real
input/output, API) runs today; `pytest -q` is the fast confirmation, the
walkthroughs above are the real-system confirmation.

The 30-case human evaluation spot-check (spec §20-21, PROJECT_PLAN.md §2)
is done — see `human-eval-spotcheck.md`: 90% agreement with the automated
evaluators, and the 3 disagreements are genuine, fixable findings (not
sampling noise) — see PROJECT_PLAN.md §9.7 for how they change how the
real v4 baseline numbers should be read.

Still open, by design, not by omission — see PROJECT_PLAN.md for why it's
scoped where it is: ATA RAG's `groundedness`/`citation_accuracy` LLM-judge
evaluators (registered but not enabled by default — the public `/chat/ask`
API returns cited sources but not the retrieved passage text, so there's
nothing to judge groundedness against without the adapter change documented
in `ata_rag.py`'s docstring).
