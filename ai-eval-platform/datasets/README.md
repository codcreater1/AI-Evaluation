# Golden datasets

Each `<system>/<version>.jsonl` file is one immutable dataset version (spec §14).
Both need expanding to reach the spec's minimums before the 21.09 demo:

- `ata-rag/`: **26 real cases, ported from the target system's own golden set**
  (see below) — minimum 100 (target 200-500)
- `internship-coordinator/`: **9 real, verified cases** — generated and captured
  from an actual run of the real system (see below) — minimum 50 (target 100+)

## ata-rag/v1.jsonl is ported from the real repo's own golden set

These 26 cases are not hand-written — they're `scripts/convert_ata_rag_dataset.py`
reshaping `backend/eval/cases.json` from the actual `codcreater1/ata-rag` repo
(its own maintainers' golden set) into this platform's `EvaluationCase`
schema, one field mapping (`checks` → `expected_output`), no invented content.
See PROJECT_PLAN.md §8 for why: that repo already has a well-designed,
real-world-tested set covering tuition figures, admissions, programme info,
all four reply languages, the scope guardrail, and prompt-injection
resistance — reinventing it from the spec's generic description would have
produced something worse. `app/evaluators/deterministic/ata_rag_checks.py`
ports the same repo's own checking logic (`backend/eval/run_eval.py`) to
evaluate these cases.

To grow past 26 toward the 100-minimum, either add more cases upstream in
`codcreater1/ata-rag`'s own `cases.json` and re-run the conversion script, or
append platform-native cases directly to a new draft version via
`DatasetManager.append_draft_case` — the two are equivalent once converted,
so there's no need to keep growing them separately.

Unlike Internship Coordinator (below), ATA RAG is stateless per request, so
there's no case-ordering or shared-corpus concern here — see PROJECT_PLAN.md
§8. The one operational constraint is a 20-requests/60-second per-IP rate
limit on the real API, which is why `config/example.yaml` keeps
`concurrency: 1` for now.

## internship-coordinator/v1.jsonl is real data, not fixtures

These 9 cases were produced by `scripts/build_internship_coordinator_dataset.py`,
which drives the *actual* Internship Coordinator repo's own synthetic-document
generator (`testdocs/tool/completion_docs.py`, 9 named scenarios with the
repo's own documented expected outcomes) and records what a real, running
instance of the service actually returned. Re-run that script (see its
docstring) to regenerate or extend this file — that's also how to add more
cases toward the 50-minimum: vary the generator's parameters (day counts,
which field is perturbed, combinations) rather than hand-writing new JSON.

**Read this before running an experiment against internship-coordinator:**
the target system keeps mutable shared state across submissions (a SQLite
database and an in-memory TF-IDF "originality" corpus used to catch copied
reports). Two cases in the same run can affect each other's results
depending on submission order and on how similar their report text is —
this is *not* a bug in either system, it's what the originality check is
for, but it means naive concurrent evaluation against one long-lived
instance produces non-reproducible results. See PROJECT_PLAN.md §7 for the
full explanation and `config/internship-coordinator.yaml`'s `concurrency: 1`
setting. Each case in this dataset carries `metadata.requires_fresh_instance`
(`true` for the 7 single-issue cases — run each alone against an empty
corpus) and `metadata.corpus_group` (`"originality-pair"` for `ic-clean` and
`ic-copied`, which must run together, clean first, for `copied` to mean
anything).

Cover the case categories the spec calls out (§9 for ATA RAG, §11 for
Internship Coordinator) — don't just write more of the easy kind:

**ATA RAG:** straightforward factual, multi-document, ambiguous, no-answer-in-KB,
misleading-assumption, requires-source-attribution.

**Internship Coordinator:** valid, invalid, missing documents, ambiguous,
incomplete info, conflicting info, edge cases.

Use **synthetic or anonymized data only** (spec §28) — no real candidate names,
real documents, or real personal information.

Once a version has been used by a released experiment it is locked
(`DatasetManager.lock`) and a `.locked` marker file appears next to it — add
new cases through `DatasetManager.append_draft_case`, which starts a new
version automatically rather than editing a locked file.
